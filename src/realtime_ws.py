import asyncio
import json
import websockets
from typing import Optional, Dict, Any
from . import config
from .dynamo_utils import write_call_log
from .tools_impl import TOOLS_SCHEMA, TOOLS_IMPL
import pprint

async def websocket_task(call_id: str, phone_number: Optional[str], response_create: Dict[str, Any], twilio_call_sid: Optional[str] = None) -> None:
    try:
        async with websockets.connect(
            "wss://api.openai.com/v1/realtime?call_id=" + call_id,
            extra_headers=config.AUTH_HEADER,
        ) as websocket:
            # Enable server-side transcription via session.update
            try:
                await websocket.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "tools": TOOLS_SCHEMA,
                        "audio": {
                            "input": {
                                "transcription": {
                                    "model": "whisper-1",
                                    "language": "ja"
                                }
                            }
                        }
                    }
                }))
            except Exception as _e:
                print("session.update (enable transcription) failed:", _e)

            # Send initial greeting response and log it
            await websocket.send(json.dumps(response_create))
            try:
                greeting = response_create.get("response", {}).get("instructions")
                if greeting:
                    write_call_log(phone_number=phone_number, assistant_text=greeting, call_sid=(twilio_call_sid or call_id))
            except Exception as _e:
                print("Greeting log failed:", _e)

            assistant_text_chunks = []
            # Accumulate tool call arguments by call_id
            tool_args_buf: Dict[str, str] = {}
            # Remember tool name by call_id (some done events may omit name)
            tool_name_by_id: Dict[str, str] = {}

            while True:
                raw_message = await websocket.recv()
                try:
                    evt = json.loads(raw_message)
                    evt_type = evt.get("type")
                    if evt_type == "error":
                        print("[WS ERROR]", json.dumps(evt, ensure_ascii=False))
                    if isinstance(evt_type, str) and "input_audio_transcription" in evt_type:
                        print("[WS TRANSCRIPTION EVT]", evt_type, json.dumps(evt, ensure_ascii=False))
                    if evt_type == "input_audio_buffer.committed":
                        print("input_audio_buffer committed; waiting for transcription events...")

                    # Assistant outputs
                    if evt_type == "response.output_text.delta":
                        delta = evt.get("delta") or {}
                        for c in delta.get("content", []):
                            if c.get("type") == "output_text":
                                txt = c.get("text") or ""
                                if txt:
                                    assistant_text_chunks.append(txt)
                    elif evt_type == "response.output_audio_transcript.delta":
                        delta_txt = evt.get("delta")
                        if isinstance(delta_txt, str) and delta_txt:
                            assistant_text_chunks.append(delta_txt)
                    elif evt_type == "response.output_audio_transcript.done":
                        transcript = evt.get("transcript")
                        if isinstance(transcript, str) and transcript.strip():
                            write_call_log(phone_number=phone_number, assistant_text=transcript.strip(), call_sid=(twilio_call_sid or call_id))
                        assistant_text_chunks = []
                    elif evt_type in ("response.output_text.done", "response.completed"):
                        if assistant_text_chunks:
                            full_text = "".join(assistant_text_chunks).strip()
                            if full_text:
                                write_call_log(phone_number=phone_number, assistant_text=full_text, call_sid=(twilio_call_sid or call_id))
                            assistant_text_chunks = []
                    # Tool calling (function calling) - arguments streaming
                    elif evt_type in ("response.function_call_arguments.delta", "response.tool_call.delta"):
                        tool_call_id = evt.get("call_id")
                        tool_name = evt.get("name")
                        delta = evt.get("arguments_delta") or ""
                        if not isinstance(delta, str):
                            delta = ""
                        if tool_call_id:
                            tool_args_buf[tool_call_id] = tool_args_buf.get(tool_call_id, "") + delta
                            if tool_name:
                                tool_name_by_id[tool_call_id] = tool_name
                    elif evt_type in ("response.function_call_arguments.done", "response.tool_call.done"):
                        print("response.function_call_arguments.done or response.tool_call.done")
                        pprint.pprint(evt)
                        tool_call_id = evt.get("call_id")
                        tool_name = evt.get("name") or (tool_call_id and tool_name_by_id.get(tool_call_id))
                        # args_json = tool_call_id and tool_args_buf.get(tool_call_id, "") or ""
                        args_json = evt.get("arguments") or ""
                        # Parse args
                        args = {}
                        try:
                            if args_json:
                                args = json.loads(args_json)
                        except Exception:
                            args = {}
                        print("[tool call]", tool_name, "args=", args)
                        # Execute tool
                        result: Any = {"error": "unknown tool"}
                        impl = TOOLS_IMPL.get(tool_name or "")
                        if impl:
                            try:
                                result = impl(args)
                            except Exception as e:
                                result = {"error": str(e)}
                        if not tool_call_id:
                            print("[WS ERROR] function_call_arguments.done without call_id")
                        else:
                            # Send function_call_output back to Realtime
                            try:
                                await websocket.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": tool_call_id,
                                        "output": json.dumps(result, ensure_ascii=False)
                                    }
                                }))
                            except Exception as _e:
                                print("[WS ERROR] send function_call_output failed:", _e)
                        # Clear buffer for this call id
                        if tool_call_id and tool_call_id in tool_args_buf:
                            del tool_args_buf[tool_call_id]
                        if tool_call_id and tool_call_id in tool_name_by_id:
                            del tool_name_by_id[tool_call_id]
                        # Ask the model to continue the response
                        await websocket.send(json.dumps({"type": "response.create"}))
                    # User transcript (final)
                    elif evt_type in ("conversation.item.input_audio_transcription.completed", "input_audio_transcription.completed"):
                        transcript = evt.get("transcript")
                        if not transcript:
                            tr = evt.get("transcription") or {}
                            transcript = tr.get("text")
                        print("[user transcription]", evt_type, repr(transcript))
                        if isinstance(transcript, str) and transcript.strip():
                            write_call_log(phone_number=phone_number, user_text=transcript.strip(), call_sid=(twilio_call_sid or call_id))
                    # User transcript (delta)
                    elif evt_type == "conversation.item.input_audio_transcription.delta":
                        delta_txt = evt.get("delta")
                        print("[user transcription delta]", repr(delta_txt))
                    # Fallback user transcript
                    elif evt_type in ("conversation.item.added", "conversation.item.done"):
                        item = evt.get("item") or {}
                        if item.get("role") == "user":
                            for c in item.get("content", []):
                                if c.get("type") == "input_audio":
                                    tr = c.get("transcript")
                                    if isinstance(tr, str) and tr.strip():
                                        write_call_log(phone_number=phone_number, user_text=tr.strip(), call_sid=(twilio_call_sid or call_id))
                except Exception:
                    pass
    except Exception as e:
        print(f"WebSocket error: {e}")



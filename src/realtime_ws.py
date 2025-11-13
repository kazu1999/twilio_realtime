import asyncio
import json
import websockets
from typing import Optional, Dict, Any
from . import config
from .dynamo_utils import write_call_log

async def websocket_task(call_id: str, phone_number: Optional[str], response_create: Dict[str, Any]) -> None:
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
                    write_call_log(phone_number=phone_number, assistant_text=greeting, call_sid=call_id)
            except Exception as _e:
                print("Greeting log failed:", _e)

            assistant_text_chunks = []

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
                            write_call_log(phone_number=phone_number, assistant_text=transcript.strip(), call_sid=call_id)
                        assistant_text_chunks = []
                    elif evt_type in ("response.output_text.done", "response.completed"):
                        if assistant_text_chunks:
                            full_text = "".join(assistant_text_chunks).strip()
                            if full_text:
                                write_call_log(phone_number=phone_number, assistant_text=full_text, call_sid=call_id)
                            assistant_text_chunks = []
                    # User transcript (final)
                    elif evt_type in ("conversation.item.input_audio_transcription.completed", "input_audio_transcription.completed"):
                        transcript = evt.get("transcript")
                        if not transcript:
                            tr = evt.get("transcription") or {}
                            transcript = tr.get("text")
                        print("[user transcription]", evt_type, repr(transcript))
                        if isinstance(transcript, str) and transcript.strip():
                            write_call_log(phone_number=phone_number, user_text=transcript.strip(), call_sid=call_id)
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
                                        write_call_log(phone_number=phone_number, user_text=tr.strip(), call_sid=call_id)
                except Exception:
                    pass
    except Exception as e:
        print(f"WebSocket error: {e}")



from flask import Flask, request, Response
import threading
import requests
from openai import InvalidWebhookSignatureError

# Support both "python -m src.app_modular" and "python src/app_modular.py"
try:
    from . import config
    from .prompt_loader import build_system_prompt
    from .phone_utils import extract_phone_from_event_or_request
    from .realtime_ws import websocket_task
except Exception:
    import os as _os, sys as _sys
    _sys.path.append(_os.path.dirname(_os.path.dirname(__file__)))
    from src import config  # type: ignore
    from src.prompt_loader import build_system_prompt  # type: ignore
    from src.phone_utils import extract_phone_from_event_or_request  # type: ignore
    from src.realtime_ws import websocket_task  # type: ignore

app = Flask(__name__)

system_prompt = build_system_prompt()

call_accept = {
    "type": "realtime",
    "instructions": system_prompt,
    "model": "gpt-4o-realtime-preview-2024-12-17",
}

response_create = {
    "type": "response.create",
    "response": {
        "instructions": "お電話ありがとうございます。ご予約ですか？それともご質問でしょうか？"
    },
}

@app.get("/")
def healthz():
    # Simple health endpoint for HTTP health checks
    return Response("ok", status=200)

@app.route("/", methods=["POST"])
def webhook():
    try:
        event = config.openai_client.webhooks.unwrap(request.data, request.headers)
        print("[event] type:", getattr(event, "type", None))
        try:
            print("[event] raw data:", getattr(event, "data", None))
        except Exception:
            pass

        # Try to extract Twilio CallSid from SIP headers if present
        def _extract_twilio_call_sid(evt) -> str | None:
            try:
                data = getattr(evt, "data", None)
                sip_headers = None
                if data is not None:
                    if isinstance(data, dict):
                        sip_headers = data.get("sip_headers")
                    else:
                        sip_headers = getattr(data, "sip_headers", None)
                if sip_headers:
                    for h in sip_headers:
                        name = h.get("name") if isinstance(h, dict) else getattr(h, "name", None)
                        value = h.get("value") if isinstance(h, dict) else getattr(h, "value", None)
                        if name and name.lower() in ("x-twilio-callsid", "twilio-callsid"):
                            if value:
                                return str(value).strip()
            except Exception:
                pass
            return None

        phone_number = extract_phone_from_event_or_request(event, request)
        print("[phone] extracted:", phone_number)
        twilio_call_sid = _extract_twilio_call_sid(event)
        print("[twilio] CallSid:", twilio_call_sid)

        if event.type == "realtime.call.incoming":
            requests.post(
                "https://api.openai.com/v1/realtime/calls/" + event.data.call_id + "/accept",
                headers={**config.AUTH_HEADER, "Content-Type": "application/json"},
                json=call_accept,
            )
            threading.Thread(
                target=lambda: __import__("asyncio").run(
                    websocket_task(
                        event.data.call_id,
                        phone_number=phone_number,
                        response_create=response_create,
                        twilio_call_sid=twilio_call_sid,
                    )
                ),
                daemon=True,
            ).start()
            return Response(status=200)
    except InvalidWebhookSignatureError as e:
        print("Invalid signature", e)
        return Response("Invalid signature", status=400)

if __name__ == "__main__":
    app.run(port=8000)


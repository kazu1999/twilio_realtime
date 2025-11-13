import re
from typing import Optional
from flask import Request
from . import config

def normalize_phone(num: str) -> Optional[str]:
    if not isinstance(num, str):
        return None
    digits = "".join(ch for ch in num if ch.isdigit() or ch == "+")
    if digits.startswith("+81"):
        rest = digits[3:]
        if rest and rest[0] != "0":
            return "0" + rest
        return rest if rest else None
    return "".join(ch for ch in digits if ch.isdigit())

def extract_phone_from_event_or_request(event, request: Request) -> Optional[str]:
    # 1) HTTP headers
    for key in ["X-Phone-Number", "X-Caller-Number", "From", "x-phone-number", "x-caller-number"]:
        if key in request.headers and request.headers.get(key):
            return normalize_phone(request.headers.get(key))
    # 2) Query
    try:
        q = request.args or {}
        for key in ["phone", "phone_number", "from", "From"]:
            if key in q and q.get(key):
                return normalize_phone(q.get(key))
    except Exception:
        pass
    # 3) Form
    try:
        form = request.form or {}
        for key in ["From", "phone", "phone_number"]:
            if key in form and form.get(key):
                return normalize_phone(form.get(key))
    except Exception:
        pass
    # 4) JSON body
    try:
        body = request.get_json(silent=True) or {}
        for key in ["phone", "phone_number", "from", "From"]:
            if key in body and body.get(key):
                return normalize_phone(body.get(key))
    except Exception:
        pass
    # 5) SIP headers in event.data
    try:
        data = getattr(event, "data", None)
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
                if name and name.lower() == "from" and value:
                    m = re.search(r"\+?\d+", value)
                    if m:
                        return normalize_phone(m.group(0))
    except Exception as _e:
        print("Failed to extract phone from sip_headers:", _e)
    # 6) Other attributes
    try:
        data = getattr(event, "data", None)
        if data is not None:
            for attr in ["phone_number", "from_number", "caller", "from"]:
                if hasattr(data, attr):
                    return normalize_phone(getattr(data, attr))
    except Exception:
        pass
    # 7) Fallback from env
    if config.DEFAULT_PHONE_NUMBER:
        return normalize_phone(config.DEFAULT_PHONE_NUMBER)
    return None



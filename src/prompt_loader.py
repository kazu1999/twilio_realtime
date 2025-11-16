import json
from typing import Optional
from . import config
from .dynamo_utils import load_system_prompt_from_dynamo, load_faq_kb_from_dynamo

def _load_text_file(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def build_system_prompt() -> str:
    # Start with default (from file if provided) then override by Dynamo if available
    # 1) Dynamo (PROMPTS_TABLE_NAME)
    system_prompt = None
    if config.PROMPTS_TABLE_NAME:
        _p_dyn = load_system_prompt_from_dynamo(config.PROMPTS_TABLE_NAME)
        if _p_dyn:
            system_prompt = _p_dyn
    # 2) File path (SYSTEM_PROMPT_PATH)
    if not system_prompt and config.SYSTEM_PROMPT_PATH:
        _p = _load_text_file(config.SYSTEM_PROMPT_PATH)
        if _p:
            system_prompt = _p
    # 3) If still None, fallback to empty
    if not system_prompt:
        system_prompt = ""
    print("system_prompt: ", system_prompt)
    # Inject FAQ KB payload
    _faq_payload = None
    if config.FAQ_TABLE_NAME:
        _faq_payload = load_faq_kb_from_dynamo(config.FAQ_TABLE_NAME)
    if not _faq_payload and config.FAQ_KB_PATH:
        _kb = _load_text_file(config.FAQ_KB_PATH)
        print("faq_kb: ", _kb)
        if _kb:
            _faq_payload = _kb
    print("faq_payload: ", _faq_payload)
    if _faq_payload:
        system_prompt = system_prompt.replace("{FAQ_KB}", _faq_payload)
    return system_prompt



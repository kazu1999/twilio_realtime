import json
from typing import Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:
    boto3 = None

from datetime import datetime, timezone
from . import config
from .phone_utils import normalize_phone

_ddb = None

def dynamo_resource():
    global _ddb
    if _ddb is None:
        if boto3 is None:
            return None
        try:
            print("Init DynamoDB resource, region:", config.AWS_REGION)
            _ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        except Exception as _e:
            print("DynamoDB resource init failed:", _e)
            _ddb = None
    return _ddb

def to_iso8601_utc_micro() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")

def write_call_log(phone_number: Optional[str] = None, user_text: Optional[str] = None,
                   assistant_text: Optional[str] = None, call_sid: Optional[str] = None,
                   ts: Optional[str] = None) -> None:
    ddb = dynamo_resource()
    if not ddb:
        print("[log] no ddb")
        return
    try:
        table = ddb.Table(config.CALL_LOGS_TABLE_NAME)
        normalized = normalize_phone(phone_number) if phone_number else None
        item = {
            "phone_number": normalized or (phone_number or "unknown"),
            "ts": ts or to_iso8601_utc_micro(),
        }
        if user_text is not None:
            print("[log] user_text:", user_text)
            item["user_text"] = user_text
        if assistant_text is not None:
            print("[log] assistant_text:", assistant_text)
            item["assistant_text"] = assistant_text
        if call_sid:
            item["call_sid"] = call_sid
        print("[log] put_item:", item)
        table.put_item(Item=item)
    except Exception as _e:
        print("Call log write failed:", _e)

def load_system_prompt_from_dynamo(table_name: str) -> Optional[str]:
    ddb = dynamo_resource()
    if not ddb:
        return None
    try:
        table = ddb.Table(table_name)
        res = table.get_item(Key={"id": "system"})
        item = res.get("Item")
        if not item:
            return None
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content
        return None
    except (BotoCoreError, ClientError, Exception) as _e:
        print("load_system_prompt_from_dynamo failed:", _e)
        return None

def load_faq_kb_from_dynamo(table_name: str, limit: int = 200) -> Optional[str]:
    ddb = dynamo_resource()
    if not ddb:
        return None
    try:
        table = ddb.Table(table_name)
        scan_kwargs = {}
        items = []
        while True:
            res = table.scan(**scan_kwargs)
            items.extend(res.get("Items", []))
            if "LastEvaluatedKey" in res and len(items) < limit:
                scan_kwargs["ExclusiveStartKey"] = res["LastEvaluatedKey"]
            else:
                break
            if len(items) >= limit:
                items = items[:limit]
                break
        kb = []
        for it in items:
            q = it.get("question")
            a = it.get("answer")
            if isinstance(q, str) and isinstance(a, str):
                kb.append({"question": q, "answer": a})
        if not kb:
            return None
        return json.dumps(kb, ensure_ascii=False)
    except (BotoCoreError, ClientError, Exception) as _e:
        print("load_faq_kb_from_dynamo failed:", _e)
        return None



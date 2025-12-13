import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key
from . import config

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:
    boto3 = None

TASKS_TABLE_NAME = os.getenv("TASKS_TABLE_NAME", "app-tasks")
TOOLS_DEBUG = os.getenv("TOOLS_DEBUG", "1") not in ("0", "false", "False", "")

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _log(*args, **kwargs):
    if TOOLS_DEBUG:
        print("[tools_impl]", *args, **kwargs)

def _ddb_table():
    if boto3 is None:
        raise RuntimeError("boto3 not available")
    region = config.AWS_REGION
    _log("ddb.init", {"region": region, "table": TASKS_TABLE_NAME})
    ddb = boto3.resource("dynamodb", region_name=region)
    return ddb.Table(TASKS_TABLE_NAME)

def list_tasks(args: Dict[str, Any]) -> Dict[str, Any]:
    _log("list_tasks.args", args)
    try:
        table = _ddb_table()
        # Use Query instead of Scan for tenant isolation
        r = table.query(
            KeyConditionExpression=Key("client_id").eq(config.CLIENT_ID),
            Limit=int(args.get("limit") or 200)
        )
        out = {"items": r.get("Items", [])}
        _log("list_tasks.count", len(out.get("items", [])))
        return out
    except Exception as e:
        _log("list_tasks.error", repr(e))
        return {"error": str(e)}

def create_task(args: Dict[str, Any]) -> Dict[str, Any]:
    _log("create_task.args", args)
    table = _ddb_table()
    name = args.get("name")
    request = args.get("request") or args.get("requirement") or ""
    start_datetime = args.get("start_datetime") or args.get("start_date") or ""
    phone_number = args.get("phone_number") or args.get("phone") or ""
    address = args.get("address") or ""
    if not name:
        return {"error": "name is required"}
    item = {
        "client_id": config.CLIENT_ID,
        "name": str(name),
        "request": str(request),
        "start_datetime": str(start_datetime),
        "phone_number": str(phone_number),
        "address": str(address),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    try:
        table.put_item(Item=item)
        _log("create_task.ok", item)
        return {"item": item}
    except Exception as e:
        _log("create_task.error", repr(e))
        return {"error": str(e)}

def get_task(args: Dict[str, Any]) -> Dict[str, Any]:
    _log("get_task.args", args)
    table = _ddb_table()
    name = args.get("name")
    if not name:
        return {"error": "name is required"}
    try:
        r = table.get_item(Key={"client_id": config.CLIENT_ID, "name": str(name)})
        it = r.get("Item")
        if not it:
            _log("get_task.not_found", name)
            return {"error": "not found"}
        _log("get_task.ok", it)
        return {"item": it}
    except Exception as e:
        _log("get_task.error", repr(e))
        return {"error": str(e)}

def update_task(args: Dict[str, Any]) -> Dict[str, Any]:
    _log("update_task.args", args)
    table = _ddb_table()
    name = args.get("name")
    if not name:
        return {"error": "name is required"}
    expr = []
    values: Dict[str, Any] = {":u": _now_iso()}
    names: Dict[str, str] = {"#updated_at": "updated_at"}
    updates = {
        "request": args.get("request"),
        "start_datetime": args.get("start_datetime"),
        "phone_number": args.get("phone_number"),
        "address": args.get("address"),
    }
    for k, v in updates.items():
        if v is None:
            continue
        expr.append(f"#{k} = :{k}")
        values[f":{k}"] = str(v)
        names[f"#{k}"] = k
    if not expr:
        return {"error": "nothing to update"}
    try:
        r = table.update_item(
            Key={"client_id": config.CLIENT_ID, "name": str(name)},
            UpdateExpression="SET " + ", ".join(expr) + ", #updated_at = :u",
            ExpressionAttributeValues=values,
            ExpressionAttributeNames=names,
            ReturnValues="ALL_NEW",
        )
        out = {"item": r.get("Attributes")}
        _log("update_task.ok", out)
        return out
    except Exception as e:
        _log("update_task.error", repr(e))
        return {"error": str(e)}

def delete_task(args: Dict[str, Any]) -> Dict[str, Any]:
    _log("delete_task.args", args)
    table = _ddb_table()
    name = args.get("name")
    if not name:
        return {"error": "name is required"}
    try:
        table.delete_item(Key={"client_id": config.CLIENT_ID, "name": str(name)})
        _log("delete_task.ok", {"name": name})
        return {"ok": True}
    except Exception as e:
        _log("delete_task.error", repr(e))
        return {"error": str(e)}

TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "list_tasks",
        "type": "function",
        "description": "List existing reservation tasks",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200}
            }
        }
    },
    {
        "name": "create_task",
        "type": "function",
        "description": "Create reservation with basic details",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "customer name"},
                "request": {"type": "string", "description": "requirements/notes"},
                "start_datetime": {"type": "string", "description": "start datetime (YYYY-MM-DD HH:MM)"},
                "phone_number": {"type": "string"},
                "address": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_task",
        "type": "function",
        "description": "Get reservation by name",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_task",
        "type": "function",
        "description": "Update reservation fields by name",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "request": {"type": "string"},
                "start_datetime": {"type": "string"},
                "phone_number": {"type": "string"},
                "address": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "delete_task",
        "type": "function",
        "description": "Delete reservation by name",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
    },
]

TOOLS_IMPL = {
    "list_tasks": list_tasks,
    "create_task": create_task,
    "get_task": get_task,
    "update_task": update_task,
    "delete_task": delete_task,
}

if __name__ == "__main__":
    # Simplified CLI for testing (Requires CLIENT_ID in env or config)
    import argparse
    import json as _json
    import sys as _sys
    import time as _time

    def _print(obj):
        try:
            print(_json.dumps(obj, ensure_ascii=False, indent=2))
        except Exception:
            print(obj)

    parser = argparse.ArgumentParser(description="Reservation tools CLI (DynamoDB-backed)")
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--limit", type=int, default=20)

    p_create = sub.add_parser("create", help="Create task")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--request", default="")
    p_create.add_argument("--start-datetime", dest="start_datetime", default="")
    p_create.add_argument("--phone-number", dest="phone_number", default="")
    p_create.add_argument("--address", default="")

    p_get = sub.add_parser("get", help="Get task")
    p_get.add_argument("--name", required=True)

    p_update = sub.add_parser("update", help="Update task")
    p_update.add_argument("--name", required=True)
    p_update.add_argument("--request")
    p_update.add_argument("--start-datetime", dest="start_datetime")
    p_update.add_argument("--phone-number", dest="phone_number")
    p_update.add_argument("--address")

    p_delete = sub.add_parser("delete", help="Delete task")
    p_delete.add_argument("--name", required=True)

    parser.add_argument("--selftest", action="store_true", help="Run self test flow (create->get->list->update->delete)")

    args = parser.parse_args()

    if args.selftest and not args.cmd:
        test_name = f"TEST-{int(_time.time())}"
        _print({"step": "create", "name": test_name})
        _print(create_task({
            "name": test_name,
            "request": "table for two",
            "start_datetime": "2025-12-24 19:00",
            "phone_number": "09012345678",
            "address": "Tokyo",
        }))
        _print({"step": "get"})
        _print(get_task({"name": test_name}))
        _print({"step": "list"})
        _print(list_tasks({"limit": 5}))
        _print({"step": "update"})
        _print(update_task({"name": test_name, "request": "window seat"}))
        _print({"step": "delete"})
        _print(delete_task({"name": test_name}))
        _sys.exit(0)

    if args.cmd == "list":
        _print(list_tasks({"limit": args.limit}))
    elif args.cmd == "create":
        _print(create_task({
            "name": args.name,
            "request": args.request,
            "start_datetime": args.start_datetime,
            "phone_number": args.phone_number,
            "address": args.address,
        }))
    elif args.cmd == "get":
        _print(get_task({"name": args.name}))
    elif args.cmd == "update":
        payload = {"name": args.name}
        if args.request is not None:
            payload["request"] = args.request
        if args.start_datetime is not None:
            payload["start_datetime"] = args.start_datetime
        if args.phone_number is not None:
            payload["phone_number"] = args.phone_number
        if args.address is not None:
            payload["address"] = args.address
        _print(update_task(payload))
    elif args.cmd == "delete":
        _print(delete_task({"name": args.name}))
    else:
        parser.print_help()
        _sys.exit(1)

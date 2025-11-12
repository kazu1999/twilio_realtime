from flask import Flask, request, Response, jsonify, make_response
from openai import OpenAI, InvalidWebhookSignatureError
import asyncio
import json
import os
import requests
import time
import threading
import websockets
from dotenv import load_dotenv
import re
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:
    boto3 = None

# Load environment variables from .env file
load_dotenv()

# Core configuration (all overridable via environment variables)
OPENAI_WEBHOOK_SECRET = os.getenv('OPENAI_WEBHOOK_SECRET')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SYSTEM_PROMPT_PATH = os.getenv('SYSTEM_PROMPT_PATH', 'system_prompt.txt')
FAQ_KB_PATH = os.getenv('FAQ_KB_PATH', 'faq.txt')
CALL_LOGS_TABLE_NAME = os.getenv('CALL_LOGS_TABLE_NAME', 'ueki-chatbot')
AWS_REGION = os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') or 'ap-northeast-1'

FAQ_TABLE_NAME = os.getenv("FAQ_TABLE_NAME", "ueki-faq")
PROMPTS_TABLE_NAME = os.getenv("PROMPTS_TABLE_NAME", "ueki-prompts")
DEFAULT_PHONE_NUMBER = os.getenv('DEFAULT_PHONE_NUMBER')  # Optional fallback used when caller number cannot be extracted

app = Flask(__name__)
client = OpenAI(
    webhook_secret=OPENAI_WEBHOOK_SECRET
)

# HTTP Authorization header used for Realtime REST and WS calls
AUTH_HEADER = {
    "Authorization": "Bearer " + OPENAI_API_KEY
}

def _load_text_file(path: str):
    # Safe file loader used for system prompt and FAQ KB files
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def _to_iso8601_utc():
    from datetime import datetime, timezone
    # Include microseconds to ensure unique sort keys in DynamoDB
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")

def _normalize_phone(num: str):
    # Normalizes E.164 (+81...) to domestic 0-leading (e.g., 080...) and strips non-digits
    if not isinstance(num, str):
        return None
    digits = "".join(ch for ch in num if ch.isdigit() or ch == '+')
    if digits.startswith('+81'):
        rest = digits[3:]
        if rest and rest[0] != '0':
            return '0' + rest
        return rest if rest else None
    return "".join(ch for ch in digits if ch.isdigit())

def _dynamo_resource():
    # Lazy-initialize DynamoDB resource if boto3 is available
    if boto3 is None:
        return None
    try:
        print("Init DynamoDB resource, region:", AWS_REGION)
        return boto3.resource('dynamodb', region_name=AWS_REGION)
    except Exception as _e:
        print("DynamoDB resource init failed:", _e)
        return None

def _write_call_log(phone_number=None, user_text=None, assistant_text=None, call_sid=None, ts=None):
    # Writes a single conversation turn to DynamoDB.
    # Item schema:
    # - phone_number (PK)
    # - ts (SK, ISO8601 with microseconds, UTC)
    # - user_text | assistant_text (one or both present)
    # - call_sid (optional)
    ddb = _dynamo_resource()
    if not ddb:
        print("[log] no ddb")
        return
    try:
        table = ddb.Table(CALL_LOGS_TABLE_NAME)
        normalized = _normalize_phone(phone_number) if phone_number else None
        item = {
            "phone_number": normalized or (phone_number or "unknown"),
            "ts": ts or _to_iso8601_utc()
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
        # Best-effort logging; do not raise
        print("Call log write failed:", _e)

def _load_system_prompt_from_dynamo(table_name: str):
    # Reads system prompt from DynamoDB by id='system' and returns 'content' string
    ddb = _dynamo_resource()
    if not ddb:
        return None
    try:
        table = ddb.Table(table_name)
        res = table.get_item(Key={'id': 'system'})
        item = res.get('Item')
        if not item:
            return None
        content = item.get('content')
        if isinstance(content, str) and content.strip():
            return content
        return None
    except (BotoCoreError, ClientError, Exception) as _e:
        print('load_system_prompt_from_dynamo failed:', _e)
        return None

def _load_faq_kb_from_dynamo(table_name: str, limit: int = 200):
    # Scans FAQ table and returns a JSON array string: [{question, answer}, ...]
    ddb = _dynamo_resource()
    if not ddb:
        return None
    try:
        table = ddb.Table(table_name)
        scan_kwargs = {}
        items = []
        while True:
            res = table.scan(**scan_kwargs)
            items.extend(res.get('Items', []))
            if 'LastEvaluatedKey' in res and len(items) < limit:
                scan_kwargs['ExclusiveStartKey'] = res['LastEvaluatedKey']
            else:
                break
            if len(items) >= limit:
                items = items[:limit]
                break
        kb = []
        for it in items:
            q = it.get('question')
            a = it.get('answer')
            if isinstance(q, str) and isinstance(a, str):
                kb.append({'question': q, 'answer': a})
        if not kb:
            return None
        return json.dumps(kb, ensure_ascii=False)
    except (BotoCoreError, ClientError, Exception) as _e:
        print('load_faq_kb_from_dynamo failed:', _e)
        return None

default_system_prompt = (
    "## 電話AIボット 用 SYSTEMプロンプト（予約＋FAQ）\n\n"
    "あなたは電話窓口のAIオペレーターです。目的は「予約の受付」と「よくある質問（FAQ）への回答」です。必ず丁寧で簡潔、1ターン1質問、確認重視で案内します。\n\n"
    "通話相手は日本語話者を想定。英語が来たら英語で対応してOKです。\n\n"
    "### 役割・口調\n\n"
    "役割：電話受付AI。「予約の新規受付」と「事前定義FAQの回答」を行う。\n\n"
    "口調：丁寧・親切・はっきり・1文は短く。専門用語を避け、要点→次の行動の順で案内。\n\n"
    "ペース：ゆっくり、語尾は明瞭に。「はい／いいえ」で答えやすい質問を優先。\n\n"
    "### インテント\n\n"
    "予約: 以下5項目を聞き取り（スロット取得）\n\n"
    "名前（フルネーム／カタカナ可）\n\n"
    "住所（都道府県から・建物名任意）\n\n"
    "電話番号（ハイフン有無OK、数字だけに正規化）\n\n"
    "日時（第1希望必須・あれば第2希望も）\n\n"
    "要望（自由記述：例）人数、メニュー、配慮事項 など）\n\n"
    "FAQ: 事前に用意されたFAQナレッジから最も近い回答を返す（雑談は簡潔に切り上げ、FAQ or 予約に誘導）。\n\n"
    "その他/エスカレーション: 要求が不明・規約外・判断不能な場合は人間につなぐ。\n\n"
    "### ステート管理（予約の基本フロー）\n\n"
    "目的確認：「本日は予約のご希望ですか？それともご質問でしょうか？」\n\n"
    "予約ならスロットを順に収集：\n\n"
    "名前 → 電話番号 → 日時 → 住所 → 要望（※在庫/枠の有無が必要なら日時で一度確認）\n\n"
    "バリデーション＆復唱確定：全項目を短く復唱し、「これでお間違いないですか？」\n\n"
    "最終確定：OKなら予約を確定して予約番号（仮）を発行（RES-YYYYMMDD-XXXX 形式など）。\n\n"
    "完了通知：SMS送信可否を確認（送るなら要配慮）。\n\n"
    "FAQの場合：要点→具体回答→補足（必要ならWeb/SMSでリンク案内）→「他にありますか？」。\n\n"
    "迷子時：2回以上噛み合わなければ、要点を言い換え、最後は人間へ引き継ぎ提案。\n\n"
    "### 入力の確認・言い換え\n\n"
    "聞き取り不安な語は言い換え＆分割で確認。\n"
    "例：「お名前は、山田 太郎様でよろしいですか？カタカナだと、ヤマダ タロウ様です。」\n\n"
    "電話番号は数字だけで復唱（例：「09012345678」）。\n\n"
    "日時は「年月日(曜日)・開始時刻」を必ず復唱。タイムゾーンは日本時間（JST）。\n\n"
    "住所は都道府県から。長ければ「郵便番号または建物名はSMSで伺います」と簡略可。\n\n"
    "要望は自由記述。機微情報（健康・宗教等）が含まれる場合は配慮し、必要最低限のみ取得。\n\n"
    "### エラー/聞き取り対策\n\n"
    "無音/雑音：最長3回までリトライ。「お電話が遠いようです。もう一度ゆっくりお願いします。」\n\n"
    "長文：要点を要約して確認。「つまり○○ということですね、合っていますか？」\n\n"
    "日付の曖昧さ：「来週の金曜」は必ず日付に変換して確認（例：「10月3日(金)でよろしいですか？」）。\n\n"
    "収集打ち切り：3回以上合意がとれない項目はSMS/折り返し提案 or オペレーターへ。\n\n"
    "### FAQの使い方\n\n"
    "システムはFAQナレッジ {FAQ_KB} を参照できる前提。\n\n"
    "運用上、FAQナレッジは別の system メッセージとして提供されます。形式:\n"
    "「FAQ_KB\\n[ {\"question\":\"...\",\"answer\":\"...\"}, ... ]」\n"
    "（JSON 配列: 各要素に question/answer）\n\n"
    "手順:\n\n"
    "1. ユーザー質問を1文で要約（内部）\n"
    "2. FAQ_KB 内の質問と照合（意味が最も近いものを採用。複数候補が拮抗する場合は、短く確認質問）\n"
    "3. 採用したエントリの answer をベースに、端的に返答（必要最小限の補足のみ）\n"
    "4. KBに無い/曖昧な場合は、不明と伝え「確認のうえ折り返し」または人間へ引き継ぎを提案\n\n"
    "### 注意:\n\n"
    "- FAQに書かれていない断定は避ける\n"
    "- 在庫・料金・アクセスなど“最新性が重要”な項目は、「最新情報をご確認ください」等の一言を添える\n\n"
    "### 厳守事項（回答スタイル・出力）\n\n"
    "- FAQの回答は FAQ_KB に記載の内容のみを根拠とする。推測や補完で断定しない。\n"
    "- 返答は最短で分かりやすく。原則2文以内。「結論→必要なら注意1文→最後に促し（質問の有無）」。\n"
    "- 出力は通話用の短い文1つのみ。タグやJSONは不要。余計な前置きや補足文も避ける。\n\n"
    "### プライバシー・注意\n\n"
    "個人情報は予約に必要な最小限のみ取得。\n\n"
    "収集の目的と利用範囲を一言で告げる（例：「予約管理のためお名前とご連絡先をお預かりします」）。\n\n"
    "クレジットカード情報などのセンシティブ情報は電話で収集しない。\n\n"
    "未成年・代理予約は続柄と連絡可能な保護者情報を確認。\n\n"
    "### 終了\n\n"
    "用件完了後は、要点の最終確認→お礼→切断前の一言（「ご不明点があればいつでもお電話ください」）。\n\n"
    "### 出力フォーマット（毎ターン）\n\n"
    "各ターンで、音声にする「発話文」だけを出力してください。JSONは出力しないでください。\n\n"
    "例：\n\n"
    "「お電話ありがとうございます。ご予約ですか？それともご質問でしょうか？」\n\n"
    "### 具体ガイダンス（短縮テンプレ）\n\n"
    "目的確認：「本日は予約のご希望ですか？それともご質問でしょうか？」\n\n"
    "予約 – 名前：「ご予約のため、お名前をフルネームでお願いします。」\n\n"
    "予約 – 電話：「折り返し用にお電話番号をお願いします。ゆっくり、数字でお伝えください。」\n\n"
    "予約 – 日時：「第一希望の日時をお願いします。可能なら第二希望もお願いします。」\n\n"
    "予約 – 住所：「ご住所は都道府県からお願いします。建物名は任意です。」\n\n"
    "予約 – 要望：「人数やご希望などがあればお知らせください。」\n\n"
    "予約 – 確認：「では確認します。お名前：◯◯様。電話：◯◯。日時：◯月◯日◯時。住所：◯◯。要望：◯◯。こちらでよろしいですか？」\n\n"
    "FAQ導入：「ご質問ありがとうございます。要点を確認しますと、◯◯についてですね。」\n\n"
    "FAQ返答：要点→回答→注意/条件→「他にございますか？」\n\n"
    "エスカレ：「担当者におつなぎします。少々お待ちください。」\n\n"
    "### ミニ対話サンプル（出力例）\n\n"
    "1. 目的確認\n\n"
    "発話\n\n"
    "「お電話ありがとうございます。ご予約ですか？それともご質問でしょうか？」\n\n"
    "1. 予約フロー開始（名前）\n\n"
    "発話\n\n"
    "「ご予約ですね。ありがとうございます。お名前をフルネームでお願いします。」\n\n"
    "1. FAQ例\n\n"
    "発話\n\n"
    "「◯◯の料金についてのご質問ですね。通常コースはお一人様◯◯円です。直近の価格は変動する場合があるため、ご来店前日にもご確認ください。他にございますか？」\n\n"
    "### 実装ヒント\n\n"
    "音声認識（ASR）誤認に備え、重要項目は必ず復唱確認。\n\n"
    "電話番号は正規化（数字抽出）。日付は自然言語 → YYYY-MM-DD HH:MM へ正規化。\n\n"
    "3回噛み合わない場合はSMSフォームや人間エスカレーションを提案。\n\n"
    "FAQ検索は「要約→キーワード抽出→スコア上位から採用→足りない注意点を1文追加」。"
)

system_prompt = default_system_prompt
# Build final system prompt, precedence:
# 1) DynamoDB (PROMPTS_TABLE_NAME) → 2) File (SYSTEM_PROMPT_PATH) → 3) Default
if PROMPTS_TABLE_NAME:
    _p_dyn = _load_system_prompt_from_dynamo(PROMPTS_TABLE_NAME)
    if _p_dyn:
        system_prompt = _p_dyn
if SYSTEM_PROMPT_PATH:
    _p = _load_text_file(SYSTEM_PROMPT_PATH)
    print('system_prompt: ', _p)
    if _p:
        system_prompt = _p
# Replace FAQ_KB placeholder with KB from DynamoDB (preferred) or file
_faq_payload = None
if FAQ_TABLE_NAME:
    _faq_payload = _load_faq_kb_from_dynamo(FAQ_TABLE_NAME)
if not _faq_payload and FAQ_KB_PATH:
    _kb = _load_text_file(FAQ_KB_PATH)
    print('faq_kb: ', _kb)
    if _kb:
        _faq_payload = _kb
print('faq_payload: ', _faq_payload)
if _faq_payload:
    system_prompt = system_prompt.replace("{FAQ_KB}", _faq_payload)


call_accept = {
    # Payload used to accept an incoming SIP call on Realtime
    "type": "realtime",
    "instructions": system_prompt,
    "model": "gpt-4o-realtime-preview-2024-12-17",
}

response_create = {
    # Initial greeting response sent after WS connection is established
    "type": "response.create",
    "response": {
        "instructions": (
            "お電話ありがとうございます。ご予約ですか？それともご質問でしょうか？"
        )
    },
}


async def websocket_task(call_id, phone_number=None):
    # Handles the Realtime WS lifecycle for a single call
    try:
        async with websockets.connect(
            "wss://api.openai.com/v1/realtime?call_id=" + call_id,
            extra_headers=AUTH_HEADER,
        ) as websocket:
            # Enable server-side transcription via session.update
            # Note: SIP + Realtime currently expects session.type="realtime" and
            # audio.input.transcription.model to be set for ASR events to emit.
            try:
                await websocket.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "type": "realtime",  # Required in some SIP integrations
                        "audio": {
                            "input": {
                                "transcription": {
                                    "model": "whisper-1",  # Or gpt-4o-transcribe
                                    "language": "ja"
                                }
                            }
                        }
                    }
                }))
            except Exception as _e:
                print("session.update (enable transcription) failed:", _e)

            # Send initial greeting response and log it as assistant_text
            await websocket.send(json.dumps(response_create))
            try:
                greeting = response_create.get("response", {}).get("instructions")
                if greeting:
                    _write_call_log(phone_number=phone_number, assistant_text=greeting, call_sid=call_id)
            except Exception as _e:
                print("Greeting log failed:", _e)

            assistant_text_chunks = []
            user_text_chunks = []

            while True:
                raw_message = await websocket.recv()
                # Parse and route key Realtime events for logging
                try:
                    evt = json.loads(raw_message)
                    evt_type = evt.get("type")
                    # Show any errors prominently
                    if evt_type == "error":
                        try:
                            print("[WS ERROR]", json.dumps(evt, ensure_ascii=False))
                        except Exception:
                            print("[WS ERROR]", evt_type)
                    # Show all transcription-related events for debugging
                    if isinstance(evt_type, str) and "input_audio_transcription" in evt_type:
                        try:
                            print("[WS TRANSCRIPTION EVT]", evt_type, json.dumps(evt, ensure_ascii=False))
                        except Exception:
                            print("[WS TRANSCRIPTION EVT]", evt_type)
                    # Boundary of a user utterance detected by server-side VAD
                    if evt_type == "input_audio_buffer.committed":
                        print("input_audio_buffer committed; waiting for transcription events...")

                    # Assistant output (text modality)
                    if evt_type == "response.output_text.delta":
                        delta = evt.get("delta") or {}
                        for c in delta.get("content", []):
                            if c.get("type") == "output_text":
                                txt = c.get("text") or ""
                                if txt:
                                    assistant_text_chunks.append(txt)
                    # Assistant output (audio transcript modality)
                    elif evt_type == "response.output_audio_transcript.delta":
                        # Audio transcript delta arrives as a plain string under "delta"
                        delta_txt = evt.get("delta")
                        if isinstance(delta_txt, str) and delta_txt:
                            assistant_text_chunks.append(delta_txt)
                    elif evt_type == "response.output_audio_transcript.done":
                        # Final assistant transcript string is provided in "transcript"
                        transcript = evt.get("transcript")
                        if isinstance(transcript, str) and transcript.strip():
                            _write_call_log(phone_number=phone_number, assistant_text=transcript.strip(), call_sid=call_id)
                        # Clear any accumulated deltas
                        assistant_text_chunks = []
                    elif evt_type in ("response.output_text.done", "response.completed"):
                        if assistant_text_chunks:
                            full_text = "".join(assistant_text_chunks).strip()
                            if full_text:
                                _write_call_log(phone_number=phone_number, assistant_text=full_text, call_sid=call_id)
                            assistant_text_chunks = []
                    # User transcript (Realtime ASR). Modern payload:
                    # type: conversation.item.input_audio_transcription.completed
                    # body: { transcript: "..." }
                    elif evt_type in ("conversation.item.input_audio_transcription.completed", "input_audio_transcription.completed"):
                        # Current payloads provide top-level "transcript"
                        transcript = evt.get("transcript")
                        # Backward compatibility fallback
                        if not transcript:
                            tr = evt.get("transcription") or {}
                            transcript = tr.get("text")
                        print("[user transcription]", evt_type, repr(transcript))
                        if isinstance(transcript, str) and transcript.strip():
                            _write_call_log(phone_number=phone_number, user_text=transcript.strip(), call_sid=call_id)
                    
                    # Optional: user transcription delta stream (debug visibility)
                    elif evt_type == "conversation.item.input_audio_transcription.delta":
                        delta_txt = evt.get("delta")
                        print("[user transcription delta]", repr(delta_txt))
                    
                    # Fallback: some backends attach transcript to the user item directly
                    elif evt_type in ("conversation.item.added", "conversation.item.done"):
                        item = evt.get("item") or {}
                        if item.get("role") == "user":
                            for c in item.get("content", []):
                                if c.get("type") == "input_audio":
                                    tr = c.get("transcript")
                                    if isinstance(tr, str) and tr.strip():
                                        _write_call_log(phone_number=phone_number, user_text=tr.strip(), call_sid=call_id)
                except Exception:
                    # Ignore malformed or non-JSON events
                    pass
    except Exception as e:
        print(f"WebSocket error: {e}")

@app.route("/", methods=["POST"])
def webhook():
    # Webhook entrypoint: verifies signature, extracts phone number, accepts call, launches WS task
    try:
        event = client.webhooks.unwrap(request.data, request.headers)
        print("[event] type:", getattr(event, "type", None))
        try:
            print("[event] raw data:", getattr(event, "data", None))
        except Exception:
            pass

        # Try to extract caller phone number from headers or event
        def _extract_phone():
            # 1) Common HTTP headers (if a proxy or gateway injects them)
            for key in ["X-Phone-Number", "X-Caller-Number", "From", "x-phone-number", "x-caller-number"]:
                if key in request.headers and request.headers.get(key):
                    return _normalize_phone(request.headers.get(key))
            # 2) Query string (e.g., .../?phone=09012345678)
            try:
                q = request.args or {}
                for key in ["phone", "phone_number", "from", "From"]:
                    if key in q and q.get(key):
                        return _normalize_phone(q.get(key))
            except Exception:
                pass
            # 3) Form-encoded (Twilio-style webhooks)
            try:
                form = request.form or {}
                for key in ["From", "phone", "phone_number"]:
                    if key in form and form.get(key):
                        return _normalize_phone(form.get(key))
            except Exception:
                pass
            # 4) JSON body (custom integrations)
            try:
                body = request.get_json(silent=True) or {}
                for key in ["phone", "phone_number", "from", "From"]:
                    if key in body and body.get(key):
                        return _normalize_phone(body.get(key))
            except Exception:
                pass
            # 5) Parse SIP headers from event.data (official Realtime SIP payload)
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
                                return _normalize_phone(m.group(0))
            except Exception as _e:
                print("Failed to extract phone from sip_headers:", _e)
            # 6) Attempt to read from other event data attributes if available
            try:
                data = getattr(event, "data", None)
                if data is not None:
                    for attr in ["phone_number", "from_number", "caller", "from"]:
                        if hasattr(data, attr):
                            return _normalize_phone(getattr(data, attr))
            except Exception:
                pass
            # 7) Fallback: environment-provided default (useful during local tests)
            if DEFAULT_PHONE_NUMBER:
                return _normalize_phone(DEFAULT_PHONE_NUMBER)
            return None

        phone_number = _extract_phone()
        print("[phone] extracted:", phone_number)

        if event.type == "realtime.call.incoming":
            # Accept incoming call, then start the bidirectional WS task in a background thread
            requests.post(
                "https://api.openai.com/v1/realtime/calls/"
                + event.data.call_id
                + "/accept",
                headers={**AUTH_HEADER, "Content-Type": "application/json"},
                json=call_accept,
            )
            threading.Thread(
                target=lambda: asyncio.run(
                    websocket_task(event.data.call_id, phone_number=phone_number)
                ),
                daemon=True,
            ).start()
            return Response(status=200)
    except InvalidWebhookSignatureError as e:
        print("Invalid signature", e)
        return Response("Invalid signature", status=400)


if __name__ == "__main__":
    app.run(port=8000)
# OpenAI Realtime Webhook Server

OpenAI Realtime APIのWebhookリクエストを受信し、音声通話を処理するFlaskアプリケーションです。日本語対応のサポートエージェントとして動作します。

参考：https://qiita.com/halapolo/items/76081368155760f4a245

## 機能

- OpenAI Realtime APIからのWebhookリクエストを受信
- 着信通話の自動受付
- WebSocket接続による双方向通信
- 日本語での音声応答（「もしもし、本日のご要件はなんですか？」）
- カスタマイズ可能な音声応答メッセージ
- Function Calling（予約タスクの作成/参照/更新/削除）をRealtimeで実行（DynamoDB連携）

## 必要要件

- Python 3.8以上
- OpenAI APIキー
- OpenAI Webhook Secret

## セットアップ

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd realtimeapi-sip-webhook-server
```

### 2. 仮想環境の作成とアクティベート

```bash
# 仮想環境を作成
python3 -m venv venv

# 仮想環境をアクティベート（macOS/Linux）
source venv/bin/activate

# 仮想環境をアクティベート（Windows）
# venv\Scripts\activate
```

### 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

## 設定方法

### 環境変数を使用（.env）

`.env`ファイルを使用して認証情報・設定を管理します。

1. `.env`に以下を設定してください（例）：

```env
OPENAI_API_KEY=sk-xxxx
OPENAI_WEBHOOK_SECRET=whsec_xxxx
AWS_REGION=ap-northeast-1

# DynamoDB（任意）
PROMPTS_TABLE_NAME=ueki-prompts        # id=system の content を読み込み
FAQ_TABLE_NAME=ueki-faq                # question/answer をスキャンしてFAQ_KBに注入
CALL_LOGS_TABLE_NAME=ueki-chatbot      # 会話ログ（user/assistant）を書き込み
TASKS_TABLE_NAME=ueki-tasks            # 予約タスクの保存先（Function Calling）
TOOLS_DEBUG=1                          # ツール実行の詳細ログ（不要なら 0）

# プロンプト/FAQの外部ファイル（任意）
SYSTEM_PROMPT_PATH=system_prompt.txt
FAQ_KB_PATH=faq.txt

# 電話番号フォールバック（任意・デバッグ用）
DEFAULT_PHONE_NUMBER=08012345678

# AWS認証
AWS_ACCESS_KEY_ID=あなたのアクセスキーID
AWS_SECRET_ACCESS_KEY=あなたのシークレットアクセスキー
AWS_SESSION_TOKEN=yyyyyyyy    # SSO/一時認証のときのみ有効化
```

2. アプリを起動します（ローカルPython または Docker）

## 実行方法

### 開発サーバーの起動（ローカルPython）

```bash

# パッケージ実行（推奨）
python -m src.app_modular

# またはモジュール分割版（src/）を使う場合
python -m src.app_modular
```

サーバーはデフォルトでポート8000で起動します。

### Webhookエンドポイント

```
POST http://localhost:8000/
```

## プロジェクト構成

```
SIP-Webhook/
├── README.md           # このファイル
├── .env               # 環境変数ファイル（gitignoreに追加）
├── .gitignore         # Git除外設定ファイル
├── requirements.txt   # 依存パッケージリスト
├── src/               # モジュール分割構成（推奨）
│   ├── __init__.py
│   ├── app_modular.py     # 分割版のFlaskエントリ（/ webhook）
│   ├── config.py          # 環境変数/クライアント設定
│   ├── dynamo_utils.py    # DynamoDB 読み書き（会話ログ、プロンプト/FAQ）
│   ├── phone_utils.py     # 電話番号の抽出/正規化
│   ├── prompt_loader.py   # システムプロンプトの組み立て
│   ├── realtime_ws.py     # Realtime WebSocket 処理
│   └── tools_impl.py      # Function Calling用ツール実装（予約タスク）
└── venv/               # 仮想環境ディレクトリ（gitignoreに追加）
```

## システムプロンプト／FAQナレッジの外部化

- 環境変数 `SYSTEM_PROMPT_PATH` を設定すると、そのテキストファイル内容が `call_accept["instructions"]` に適用されます。
- 環境変数 `FAQ_KB_PATH` を設定すると、システムプロンプト内の `{FAQ_KB}` プレースホルダがそのファイル内容で置換されます（JSON配列など）。

例：

```bash
export SYSTEM_PROMPT_PATH=system_prompt.txt
export FAQ_KB_PATH=faq.txt
python -m src.app_modular
```

デフォルトでは `system_prompt.txt` に近い内容が組み込み済みです。そのままでも動作します。

### DynamoDB からの読み込み（任意）

- 環境変数 `PROMPTS_TABLE_NAME` を設定すると、DynamoDB テーブル（例: `ueki-prompts`）の `id=system` の `content` をシステムプロンプトとして読み込みます。
- 環境変数 `FAQ_TABLE_NAME` を設定すると、DynamoDB テーブル（例: `ueki-faq`）をスキャンし、`[{\"question\",\"answer\"}, ...]` の配列を構築して `{FAQ_KB}` を置換します（最大200件, PAY_PER_REQUEST前提）。

例:
```bash
export PROMPTS_TABLE_NAME=ueki-prompts
export FAQ_TABLE_NAME=ueki-faq
python -m src.app_modular
```

## 主要な依存パッケージ

- **Flask** (3.0.0): Webフレームワーク
- **OpenAI** (1.102.0): OpenAI APIクライアント
- **websockets** (13.1): WebSocket通信（additional_headers対応）
- **requests** (2.31.0): HTTPリクエスト処理
- **python-dotenv** (1.0.0): 環境変数管理
- **boto3**: AWS SDK（DynamoDB読み書き）

## 動作フロー

1. OpenAI Realtime APIからWebhookリクエストを受信
2. `realtime.call.incoming`イベントを検知
3. 通話を自動的に受付（accept）
4. WebSocket接続を確立
5. 日本語で応答（「もしもし、本日のご要件はなんですか？」）
6. WebSocket経由でリアルタイム通信を継続
7. 必要に応じて Function Calling（ツール呼び出し）を実施し、予約をDynamoDBに保存/更新

<!-- Function Calling 機能は現在無効化しています。 -->

## 実装詳細と注意点

### 電話番号の抽出（SIPヘッダ）
- `realtime.call.incoming` イベントの `data.sip_headers` 内の `From` から番号を抽出します。
- 例: `<sip:+818012345678@pstn.twilio.com;...>` → `+818012345678` を取り出し、`080...` に正規化します。
- 追加の代替: HTTPヘッダ `X-Phone-Number`/`From`、クエリ `?phone=...`、フォーム `From=...`、JSONボディ `phone` に対応。
- 環境変数 `DEFAULT_PHONE_NUMBER` を設定しておくと、抽出失敗時のフォールバックとして使用されます。

### ユーザー音声の文字起こし（Realtime ASR）
- WebSocket接続直後に `session.update` で ASR を有効化しています。
- 設定例（コード反映済み）:
  - `session.type = "realtime"`
  - `session.audio.input.transcription.model = "whisper-1"`（日本語なら `language: "ja"` 推奨）
- 受信するイベント:
  - ユーザー最終文字起こし: `conversation.item.input_audio_transcription.completed`（payloadの `transcript` を保存）
  - フォールバック: `conversation.item.added/done` の `role=user` 内 `content[].input_audio.transcript`
- よくある症状:
  - transcriptionイベントが来ない場合、`session.update` の指定不足/誤りが原因のことがあります。エラーログ（`[WS ERROR]`）を確認してください。

### DynamoDBへの会話ログ書き込み
- `CALL_LOGS_TABLE_NAME` に対して `put_item`。
- 保存項目の例:
  - `phone_number`（正規化済み）
  - `ts`（UTC ISO8601, マイクロ秒まで含む）
  - `user_text` / `assistant_text`
  - `call_sid`
- 重要: `ts` はマイクロ秒を含めています（例: `2025-11-11T14:20:08.123456+00:00`）。同一秒内の連続ログでも上書きされないようにするためです。

### Realtime 予約（Function Calling）
- モデルにツールを公開し、予約CRUDをDynamoDBで実施します。
- 定義箇所: `src/tools_impl.py`
  - 提供ツール: `list_tasks`, `create_task`, `get_task`, `update_task`, `delete_task`
  - 保存テーブル: `TASKS_TABLE_NAME`（既定 `ueki-tasks`）
- WebSocket側の処理: `src/realtime_ws.py`
  - `session.update` で `tools` を渡し、ツール呼び出しイベントを処理
  - イベントは Realtime 仕様に従ってパースします:
    - 逐次: `response.function_call_arguments.delta` → `call_id`, `arguments_delta` を使用
    - 完了: `response.function_call_arguments.done` → `call_id`, `name`（必要に応じて直前の name を補完）
    - 実装では一部バックエンドで `evt.arguments` が渡る場合も考慮（存在すれば優先）
  - 引数をJSONに組み立て、`TOOLS_IMPL` を実行
  - 結果を `conversation.item.create` で返却（`item.type: function_call_output`, `call_id: <必須>`, `output: "<json>"`）
  - その後 `response.create` を送信して応答を継続
  - デバッグログ（有効時）: `[tool call] <name> args= {...}` / `[WS ERROR] ...`

注意点（ハマりどころ）:
- `session.tools` スキーマは name がトップレベルに必須（例: `{"name":"create_task","type":"function","parameters":{...}}`）
- 戻りのアイテムは `tool_result` ではなく `function_call_output`
- `function_call_output.call_id` は空で送れない（必ずイベントの `call_id` を使用）

## コンテナ/クラウドデプロイ（AWS App Runner 推奨）

### ローカルDocker実行
```bash
docker build -t realtime-sip-bot .
docker run --rm -p 8000:8000 \
  --env-file .env \
  realtime-sip-bot
# → http://localhost:8000 に / をPOST でWebhook受信
```

### ECRにpush
```bash
AWS_REGION=ap-northeast-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO=realtime-sip-bot

aws ecr create-repository --repository-name $REPO --region $AWS_REGION || true
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build -t $REPO .
docker tag $REPO:latest $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:latest
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:latest
```

### App Runner作成（コンソール推奨・ポイント）
- イメージ: 上記ECRの最新イメージ
- ポート: 8000
- 起動コマンド: 既定（DockerfileのCMD: gunicorn ...）
- 環境変数（Secrets推奨）:
  - `OPENAI_API_KEY`, `OPENAI_WEBHOOK_SECRET`, `AWS_REGION`
  - `PROMPTS_TABLE_NAME`, `FAQ_TABLE_NAME`, `CALL_LOGS_TABLE_NAME`, `TASKS_TABLE_NAME`
  - `DEFAULT_PHONE_NUMBER`（任意）, `TOOLS_DEBUG`（任意）
- ヘルスチェック: HTTP GET `/`（200 OK）
- スケール: 最小 1 インスタンス（通話受けのため常時起動）
- カスタムドメイン（任意）: Route53 + ACM

### OpenAI側設定
- Realtime（SIP）の Webhook URL に App Runner のURLを登録
- Webhook Secret を `OPENAI_WEBHOOK_SECRET` と一致させる

トラブルシュート:
- 401/署名不正 → `OPENAI_WEBHOOK_SECRET` の一致確認
- ASRが出ない → `session.update` の設定、ログの `[WS TRANSCRIPTION EVT]` を確認
- Function Calling失敗 → README「Realtime 予約（Function Calling）」の注意点（call_id/name/arguments）を確認

## カスタマイズ

### 応答メッセージの変更

`response_create`オブジェクト内の`instructions`を編集：

```python
response_create = {
    "type": "response.create",
    "response": {
        "instructions": "カスタムメッセージをここに記載"
    },
}
```

### サポートエージェントの設定変更

`call_accept`オブジェクト内の`instructions`を編集（現在は日本語専用エージェントとして設定）：

```python
call_accept = {
    "type": "realtime",
    "instructions": "You are a support agent for Japanese. Please speak Japanese only.",
    "model": "gpt-4o-realtime-preview-2024-12-17",
}
```

## トラブルシューティング

### WebSocketエラー: additional_headers

websocketsライブラリのバージョンが古い場合に発生します。バージョン13.1を使用してください：

```bash
pip install websockets==13.1
```

### ASRイベントが来ない / unknown_parameter エラー
- `session.update` のキーが誤っていると `unknown_parameter` が返ります。
- 本実装は `session.audio.input.transcription.model` を使用しています（`session.input_audio_transcription` ではありません）。
- ログに `[WS ERROR]` を出すようにしているので、エラー内容を確認してください。

### ポート8000が既に使用中
- ローカルPython実行の場合は環境変数 `PORT` を使うか、`src/app_modular.py` の `app.run(port=8000)` を手元で変更
- Docker実行の場合は `-p <host_port>:8000` でホスト側ポートを変える（例: `-p 8001:8000`）

### 仮想環境の終了

作業が終わったら、仮想環境を終了：

```bash
deactivate
```

## セキュリティに関する注意

- 本番環境では必ず環境変数または安全な秘密管理システムを使用してください
- APIキーやWebhook Secretをコードに直接記載しないでください
- `.env`ファイルは`.gitignore`に追加してください
- HTTPSを使用してWebhookエンドポイントを保護してください


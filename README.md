# OpenAI Realtime Webhook Server

OpenAI Realtime APIのWebhookリクエストを受信し、音声通話を処理するFlaskアプリケーションです。日本語対応のサポートエージェントとして動作します。

参考：https://qiita.com/halapolo/items/76081368155760f4a245

## 機能

- OpenAI Realtime APIからのWebhookリクエストを受信
- 着信通話の自動受付
- WebSocket接続による双方向通信
- 日本語での音声応答（「もしもし、本日のご要件はなんですか？」）
- カスタマイズ可能な音声応答メッセージ

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

### 環境変数を使用（main_with_env.py）

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

# プロンプト/FAQの外部ファイル（任意）
SYSTEM_PROMPT_PATH=system_prompt.txt
FAQ_KB_PATH=faq.txt

# 電話番号フォールバック（任意・デバッグ用）
DEFAULT_PHONE_NUMBER=08012345678
```

2. `main_with_env.py`を使用して起動します。

## 実行方法

### 開発サーバーの起動

```bash

# 方法: 環境変数を使用（推奨）
python main_with_env.py
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
├── main_with_env.py   # 環境変数版のアプリケーション（日本語対応）
├── .env               # 環境変数ファイル（gitignoreに追加）
├── .gitignore         # Git除外設定ファイル
├── requirements.txt   # 依存パッケージリスト
└── venv/             # 仮想環境ディレクトリ（gitignoreに追加）
```

## システムプロンプト／FAQナレッジの外部化

- 環境変数 `SYSTEM_PROMPT_PATH` を設定すると、そのテキストファイル内容が `call_accept["instructions"]` に適用されます。
- 環境変数 `FAQ_KB_PATH` を設定すると、システムプロンプト内の `{FAQ_KB}` プレースホルダがそのファイル内容で置換されます（JSON配列など）。

例：

```bash
export SYSTEM_PROMPT_PATH=system_prompt.txt
export FAQ_KB_PATH=faq.txt
python main_with_env.py
```

デフォルトでは `system_prompt.txt` に近い内容が組み込み済みです。そのままでも動作します。

### DynamoDB からの読み込み（任意）

- 環境変数 `PROMPTS_TABLE_NAME` を設定すると、DynamoDB テーブル（例: `ueki-prompts`）の `id=system` の `content` をシステムプロンプトとして読み込みます。
- 環境変数 `FAQ_TABLE_NAME` を設定すると、DynamoDB テーブル（例: `ueki-faq`）をスキャンし、`[{\"question\",\"answer\"}, ...]` の配列を構築して `{FAQ_KB}` を置換します（最大200件, PAY_PER_REQUEST前提）。

例:
```bash
export PROMPTS_TABLE_NAME=ueki-prompts
export FAQ_TABLE_NAME=ueki-faq
python main_with_env.py
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

`main.py`または`main_with_env.py`の最終行でポート番号を変更：

```python
app.run(port=8001)  # 別のポート番号に変更
```

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


import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

# Core configuration
OPENAI_WEBHOOK_SECRET = os.getenv("OPENAI_WEBHOOK_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-northeast-1"

SYSTEM_PROMPT_PATH = os.getenv("SYSTEM_PROMPT_PATH", "system_prompt.txt")
FAQ_KB_PATH = os.getenv("FAQ_KB_PATH", "faq.txt")
PROMPTS_TABLE_NAME = os.getenv("PROMPTS_TABLE_NAME", "ueki-prompts")
FAQ_TABLE_NAME = os.getenv("FAQ_TABLE_NAME", "ueki-faq")
CALL_LOGS_TABLE_NAME = os.getenv("CALL_LOGS_TABLE_NAME", "ueki-chatbot")
DEFAULT_PHONE_NUMBER = os.getenv("DEFAULT_PHONE_NUMBER")

# OpenAI client and headers
openai_client = OpenAI(webhook_secret=OPENAI_WEBHOOK_SECRET)
AUTH_HEADER = {"Authorization": "Bearer " + (OPENAI_API_KEY or "")}



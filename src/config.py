import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

# Client Identity (Tenant ID)
CLIENT_ID = os.getenv("CLIENT_ID", "ueki")

# Core configuration
OPENAI_WEBHOOK_SECRET = os.getenv("OPENAI_WEBHOOK_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-northeast-1"

SYSTEM_PROMPT_PATH = os.getenv("SYSTEM_PROMPT_PATH", "system_prompt.txt")
FAQ_KB_PATH = os.getenv("FAQ_KB_PATH", "faq.txt")

# Multi-tenant tables (default to app-*)
PROMPTS_TABLE_NAME = os.getenv("PROMPTS_TABLE_NAME", "app-prompts")
FAQ_TABLE_NAME = os.getenv("FAQ_TABLE_NAME", "app-faq")
CALL_LOGS_TABLE_NAME = os.getenv("CALL_LOGS_TABLE_NAME", "app-logs")
TASKS_TABLE_NAME = os.getenv("TASKS_TABLE_NAME", "app-tasks")

DEFAULT_PHONE_NUMBER = os.getenv("DEFAULT_PHONE_NUMBER")

# OpenAI client and headers
openai_client = OpenAI(webhook_secret=OPENAI_WEBHOOK_SECRET)
AUTH_HEADER = {"Authorization": "Bearer " + (OPENAI_API_KEY or "")}

import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
class Settings:
    ai_provider = os.getenv("AI_PROVIDER", "none")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    paypal_id = os.getenv("PAYPAL_CLIENT_ID", "")
    paypal_secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
    paypal_base = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
    channel3_key = os.getenv("CHANNEL3_API_KEY", "")
    currency = os.getenv("CURRENCY", "USD")
    db_path = os.getenv("DB_PATH", str(Path(__file__).parent / "paypilot.db"))
settings = Settings()

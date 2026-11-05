"""Provider-agnostic LLM helper. Returns None when no provider/key, so callers use rule-based fallback."""
import json, re, httpx
from backend.config import settings

async def complete(prompt: str, json_mode=False):
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            if settings.ai_provider == "gemini" and settings.gemini_key:
                url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
                body = {"contents": [{"parts": [{"text": prompt}]}]}
                if json_mode: body["generationConfig"] = {"responseMimeType": "application/json"}
                r = await c.post(url, params={"key": settings.gemini_key}, json=body)
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            if settings.ai_provider == "openai" and settings.openai_key:
                body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]}
                if json_mode: body["response_format"] = {"type": "json_object"}
                r = await c.post("https://api.openai.com/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {settings.openai_key}"}, json=body)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None
    return None

def parse_json(text):
    if not text: return None
    try: return json.loads(re.sub(r"```json|```", "", text).strip())
    except Exception: return None

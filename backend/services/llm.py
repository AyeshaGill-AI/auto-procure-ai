import os, json, requests, logging
from services.db import decrypt as _decrypt
logger = logging.getLogger(__name__)

# Groq is the default provider; override the endpoint/model only if you use another
# OpenAI-compatible service (OpenRouter, OpenAI, ...).
GROQ_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("AI_MODEL", "llama-3.3-70b-versatile")

def _ai_key():
    """Key resolution: Settings DB entry first, then GROQ_API_KEY env var."""
    try:
        from services.gates import get_settings
        from services.db import conn
        c = conn()
        s = get_settings(c)
        c.close()
        raw = s.get("ai_key") or s.get("groq_key")  # groq_key kept for legacy databases
        return _decrypt(raw) if raw else None
    except Exception as e:
        logger.warning("Failed to load AI key from DB: %s", e)
        return None

def summarize(pr, gr, dec):
    key = _ai_key() or os.environ.get("GROQ_API_KEY")
    prompt = (f"Purchase request {pr['code']}: {pr['raw_text']}. Qty {pr['qty']}. "
              f"Gate results: {json.dumps(gr)}. Decision: {dec['recommendation']}, "
              f"score {dec['score']}. Write a 2-sentence procurement analyst summary.")
    if key:
        try:
            r = requests.post(f"{GROQ_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": GROQ_MODEL,
                      "messages": [{"role": "system", "content": "You are a senior FMCG procurement analyst. Be terse."},
                                  {"role": "user", "content": prompt}]}, timeout=8)
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning("Generative AI call failed, using fallback: %s", e)
    return (f"Analyst read: {dec['recommendation']} protocol on {pr['code']}. "
            f"Internal coverage and usage caps remove {dec['savings']:,.0f} USD of unnecessary external spend "
            f"while keeping {dec['buy_qty']} units on order to protect the production schedule.")
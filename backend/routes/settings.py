from flask import Blueprint, request, jsonify, session
from services.db import conn, init, DBPATH, encrypt, decrypt
from services.llm import _ai_key, GROQ_BASE_URL, GROQ_MODEL
import requests as _rq
import os
bp = Blueprint("settings", __name__, url_prefix="/api")

def _role():
    c = conn()
    u = c.execute("SELECT role FROM users WHERE id=?", (session["uid"],)).fetchone()
    c.close()
    return u["role"] if u else None

@bp.get("/settings")
def get():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    c = conn(); s = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close()
    # surface any legacy groq_key under the generic ai_key name
    if not s.get("ai_key") and s.get("groq_key"):
        s["ai_key"] = s["groq_key"]
    raw = s.get("ai_key")
    if raw:
        try:
            raw = decrypt(raw)
        except Exception:
            pass
        s["ai_key_masked"] = "****" + raw[-4:]
    s.pop("groq_key", None); s.pop("groq_key_masked", None)
    return jsonify(s)

@bp.post("/settings")
def save():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    if _role() != "Procurement Manager": return jsonify(error="manager role required"), 403
    d = request.get_json(silent=True) or {}
    c = conn()
    for k in ("usage_cap_months", "dup_window_days", "essential_categories", "ai_key"):
        if k in d and d[k] != "":
            val = encrypt(str(d[k])) if k == "ai_key" else str(d[k])
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, val))
    c.commit(); c.close(); return jsonify(ok=True)

@bp.post("/ai/test")
def ai_test():
    """Verify the configured generative-AI key with a minimal completion request."""
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    key = _ai_key() or os.environ.get("GROQ_API_KEY")
    if not key: return jsonify(ok=False, error="no key on file")
    try:
        r = _rq.post(f"{GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": GROQ_MODEL,
                  "messages": [{"role": "user", "content": "Reply with the single word: READY"}]},
            timeout=10)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return jsonify(ok=True, model=GROQ_MODEL, reply=text)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 502

@bp.post("/admin/reset")
def reset():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    if _role() != "Procurement Manager": return jsonify(error="forbidden"), 403
    if os.path.exists(DBPATH): os.remove(DBPATH)
    init(); return jsonify(ok=True)
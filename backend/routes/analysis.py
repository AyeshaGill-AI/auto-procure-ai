import json
from flask import Blueprint, jsonify, session
from services.db import conn
from services.gates import run_gate
from services.scoring import decide
from services.llm import summarize
from routes.requests import current_role

bp = Blueprint("analysis", __name__, url_prefix="/api")

def _allowed(pid):
    """Per-account isolation: owners and Procurement Managers only."""
    c = conn()
    r = c.execute("SELECT created_by FROM purchase_requests WHERE id=?", (pid,)).fetchone()
    c.close()
    if not r: return "not found"
    if r["created_by"] not in (None, session["uid"]) and current_role() != "Procurement Manager":
        return "forbidden"
    return None

@bp.post("/requests/<int:pid>/gates/<int:n>")
def gate(pid, n):
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    denied = _allowed(pid)
    if denied == "not found": return jsonify(error="not found"), 404
    if denied == "forbidden": return jsonify(error="forbidden - this request belongs to another operator"), 403
    c = conn()
    if not c.execute("SELECT 1 FROM purchase_requests WHERE id=?", (pid,)).fetchone():
        c.close(); return jsonify(error="not found"), 404
    gr = run_gate(c, pid, min(max(n, 1), 5)); c.close()
    return jsonify(gate=n, result=gr[str(n)], gates=gr)

@bp.get("/requests/<int:pid>/decision")
def decision(pid):
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    denied = _allowed(pid)
    if denied == "not found": return jsonify(error="not found"), 404
    if denied == "forbidden": return jsonify(error="forbidden - this request belongs to another operator"), 403
    c = conn()
    r = c.execute("SELECT * FROM purchase_requests WHERE id=?", (pid,)).fetchone()
    if not r:
        c.close(); return jsonify(error="not found"), 404
    gr = json.loads(r["gate_results"] or "null")
    dec = json.loads(r["decision"] or "null")
    if not gr:
        gr = run_gate(c, pid, 5)
        r = c.execute("SELECT * FROM purchase_requests WHERE id=?", (pid,)).fetchone()
    if not dec:
        dec = decide(c, r, gr); dec["llm_summary"] = summarize(r, gr, dec)
        c.execute("UPDATE purchase_requests SET decision=? WHERE id=?", (json.dumps(dec), pid)); c.commit()
    c.close()
    return jsonify(gates=gr, decision=dec)

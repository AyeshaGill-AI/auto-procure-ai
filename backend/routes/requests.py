from uuid import uuid4
import json, random
from datetime import datetime
from flask import Blueprint, request, session, jsonify
from services.db import conn
from services.scoring import decide
from services.gates import run_gate
bp = Blueprint("requests", __name__, url_prefix="/api/requests")

def authed(): return "uid" in session

def current_role():
    c = conn()
    u = c.execute("SELECT role FROM users WHERE id=?", (session["uid"],)).fetchone()
    c.close()
    return u["role"] if u else None

def load_request(c, pid):
    """Fetch a request, enforcing per-account isolation.
    Owners see their own requests; Procurement Managers see everything."""
    r = c.execute("""SELECT p.*, d.name dept FROM purchase_requests p
                     JOIN departments d ON d.id=p.department_id WHERE p.id=?""", (pid,)).fetchone()
    if not r: return None, (jsonify(error="not found"), 404)
    if r["created_by"] not in (None, session["uid"]) and current_role() != "Procurement Manager":
        return None, (jsonify(error="forbidden - this request belongs to another operator"), 403)
    return r, None

@bp.get("")
def list_requests():
    if not authed(): return jsonify(error="unauthenticated"), 401
    q = request.args.get("q", "").strip().lower()
    st = request.args.get("status", ""); dp = request.args.get("dept", "")
    c = conn()
    if current_role() == "Procurement Manager":
        rows = c.execute("""SELECT p.*, d.name dept FROM purchase_requests p
                            JOIN departments d ON d.id=p.department_id
                            ORDER BY p.created_at DESC""").fetchall()
    else:
        rows = c.execute("""SELECT p.*, d.name dept FROM purchase_requests p
                            JOIN departments d ON d.id=p.department_id
                            WHERE p.created_by IS NULL OR p.created_by=?
                            ORDER BY p.created_at DESC""", (session["uid"],)).fetchall()
    out = []
    for r in rows:
        dec = json.loads(r["decision"] or "null")
        if q and q not in (r["raw_text"] or "").lower() and q not in (r["cleaned_name"] or "").lower() and q not in (r["sku"] or "").lower() and q not in r["code"].lower(): continue
        if st and r["status"] != st: continue
        if dp and r["dept"] != dp: continue
        out.append({"id": r["id"], "code": r["code"], "item": r["cleaned_name"] or r["raw_text"],
                    "dept": r["dept"], "status": r["status"], "date": (r["created_at"] or "")[:10],
                    "score": dec["score"] if dec else None,
                    "priority": dec["priority"] if dec else None, "qty": r["qty"]})
    c.close(); return jsonify(out)

def _validate_payload(d):
    """Validate and normalize a create-request payload. Returns (data, error)."""
    if not isinstance(d, dict): return None, "JSON object required"
    raw = (d.get("raw_text") or "").strip()
    if not raw: return None, "raw_text is required"
    if len(raw) > 500: return None, "raw_text exceeds 500 characters"
    qty = d.get("qty")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1 or qty > 1_000_000:
        return None, "qty must be a positive integer"
    price = d.get("unit_price")
    if price is None: price = 0
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0:
        return None, "unit_price must be a non-negative number"
    if not d.get("department_id"): return None, "department_id is required"
    try:
        dept_id = int(d["department_id"])
    except (TypeError, ValueError):
        return None, "department_id must be an integer"
    req_date = (d.get("required_date") or "").strip()
    if req_date:
        try:
            datetime.strptime(req_date, "%Y-%m-%d")
        except ValueError:
            return None, "required_date must be YYYY-MM-DD"
    notes = (d.get("notes") or "").strip()
    if len(notes) > 1000: return None, "notes exceed 1000 characters"
    return {"raw_text": raw, "qty": qty, "unit_price": float(price), "department_id": dept_id,
            "required_date": req_date, "notes": notes}, None

@bp.post("")
def create():
    if not authed(): return jsonify(error="unauthenticated"), 401
    d, err = _validate_payload(request.get_json(silent=True))
    if err: return jsonify(error=err), 400
    c = conn()
    if not c.execute("SELECT 1 FROM departments WHERE id=?", (d["department_id"],)).fetchone():
        c.close(); return jsonify(error="unknown department"), 400
    code = f"PR-{uuid4().hex[:6].upper()}"
    try:
        created_at = datetime.now().isoformat(timespec="seconds")
        cur = c.execute("""INSERT INTO purchase_requests(code,raw_text,department_id,qty,unit_cost,
            required_date,notes,status,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (code, d["raw_text"], d["department_id"], d["qty"], d["unit_price"],
             d["required_date"], d["notes"], "PENDING", created_at, session["uid"]))
        c.commit(); pid = cur.lastrowid
    finally:
        c.close()
    return jsonify(id=pid, code=code), 201

@bp.get("/<int:pid>")
def detail(pid):
    if not authed(): return jsonify(error="unauthenticated"), 401
    c = conn()
    r, err = load_request(c, pid)
    if err: c.close(); return err
    c.close()
    o = dict(r); o["gate_results"] = json.loads(r["gate_results"] or "null")
    o["decision"] = json.loads(r["decision"] or "null"); return jsonify(o)

def ensure_decision(pid):
    """Run all gates and the decision engine once, persisting both."""
    c = conn()
    r = c.execute("SELECT * FROM purchase_requests WHERE id=?", (pid,)).fetchone()
    if not r:
        c.close(); return None, None, None
    dec = json.loads(r["decision"] or "null")
    gr = json.loads(r["gate_results"] or "null")
    if not gr or not dec:
        gr = run_gate(c, pid, 5)
        dec = decide(c, r, gr)
        from services.llm import summarize
        dec["llm_summary"] = summarize(r, gr, dec)
        c.execute("UPDATE purchase_requests SET decision=? WHERE id=?", (json.dumps(dec), pid)); c.commit()
        r = c.execute("SELECT * FROM purchase_requests WHERE id=?", (pid,)).fetchone()
    c.close(); return r, gr, dec

@bp.post("/<int:pid>/action")
def action(pid):
    if not authed(): return jsonify(error="unauthenticated"), 401
    act = (request.get_json(silent=True) or {}).get("action")
    c = conn()
    r, err = load_request(c, pid)
    c.close()
    if err: return err
    r, gr, dec = ensure_decision(pid)
    if not r: return jsonify(error="not found"), 404
    if r["status"] not in ("PENDING", "REDUCE", "INVESTIGATE", "ON_HOLD", "EXPEDITE", "APPROVED"):
        return jsonify(error="request is closed"), 409
    if act == "REJECT":
        c = conn()
        c.execute("UPDATE purchase_requests SET status='REJECTED' WHERE id=?", (pid,))
        c.commit(); c.close()
        return jsonify(status="REJECTED")
    mapping = {"APPROVE": "APPROVED", "HOLD": "ON_HOLD", "INVESTIGATE": "INVESTIGATE", "EXPEDITE": "EXPEDITE"}
    if act not in mapping: return jsonify(error="invalid action"), 400
    status = mapping[act]
    if status == "APPROVED" and r["status"] == "APPROVED":
        return jsonify(error="request already approved"), 409
    po_number = None
    if act in ("APPROVE", "EXPEDITE") and r["status"] not in ("APPROVED", "EXPEDITE"):
        # side effects run once; re-approval of an EXPEDITE'd request never double-spends
        c = conn()
        need = dec["transfer_qty"]
        if need:
            rows = c.execute("SELECT * FROM inventory WHERE sku=? AND qty>0 ORDER BY qty DESC", (r["sku"],)).fetchall()
            for row in rows:
                if need <= 0: break
                take = min(need, row["qty"])
                c.execute("UPDATE inventory SET qty=qty-? WHERE id=?", (take, row["id"])); need -= take
        c.execute("UPDATE departments SET budget_spent=budget_spent+? WHERE id=?", (dec["external_cost"], r["department_id"]))
        if dec["buy_qty"] > 0:
            existing = c.execute("SELECT 1 FROM open_pos WHERE sku=? AND status='ORDERED'", (r["sku"],)).fetchone()
            if not existing:
                po_number = f"PO-{random.randint(4600, 9999)}"
                c.execute("INSERT INTO open_pos(po_number,sku,qty,status) VALUES(?,?,?,'ORDERED')",
                          (po_number, r["sku"], dec["buy_qty"]))
        c.execute("UPDATE purchase_requests SET status=? WHERE id=?", (status, pid)); c.commit(); c.close()
    else:
        c = conn()
        c.execute("UPDATE purchase_requests SET status=? WHERE id=?", (status, pid)); c.commit(); c.close()
    return jsonify(status=status, po_number=po_number, external_cost=dec["external_cost"])
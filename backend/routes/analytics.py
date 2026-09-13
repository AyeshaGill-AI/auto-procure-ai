import json
from flask import Blueprint, jsonify, session
from services.db import conn
bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")

@bp.get("/summary")
def summary():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    c = conn()
    rows = c.execute("SELECT status, decision FROM purchase_requests").fetchall()
    counts = {}
    savings = 0.0; scores = []
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        d = json.loads(r["decision"] or "null")
        if d:
            scores.append(d["score"])
            if r["status"] in ("APPROVED", "EXPEDITE"): savings += d["savings"]
    c.close()
    return jsonify(total=len(rows), counts=counts, savings=round(savings, 2),
                   avg_score=round(sum(scores) / len(scores), 1) if scores else 0)

@bp.get("/budget")
def budget():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    c = conn()
    rows = c.execute("""SELECT d.name, d.budget_total, d.budget_spent,
        ROUND(CASE WHEN d.budget_total > 0 THEN 100.0*d.budget_spent/d.budget_total ELSE 0 END, 1) pct,
        ROUND(d.budget_total - d.budget_spent, 2) remaining
        FROM departments d ORDER BY pct DESC""").fetchall()
    result = []
    for r in rows:
        if r["pct"] >= 90:
            status = "OVER_BUDGET"
        elif r["pct"] >= 70:
            status = "WARNING"
        else:
            status = "ON_TRACK"
        result.append({"name": r["name"], "budget_total": r["budget_total"],
                       "budget_spent": r["budget_spent"], "remaining": r["remaining"],
                       "pct": r["pct"], "status": status})
    c.close()
    return jsonify(depts=result)

@bp.get("/charts")
def charts():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    c = conn()
    dept = [dict(r) for r in c.execute("""SELECT name, budget_total, budget_spent,
        ROUND(CASE WHEN budget_total > 0 THEN 100.0*budget_spent/budget_total ELSE 0 END) pct FROM departments""")]
    uv = [dict(r) for r in c.execute("""SELECT i.name label, u.avg_monthly a, MAX(p.qty) b
        FROM usage_hist u JOIN item_master i ON i.sku=u.sku
        JOIN purchase_requests p ON p.sku=u.sku GROUP BY u.sku ORDER BY b DESC LIMIT 6""")]
    mo = [dict(r) for r in c.execute("""SELECT strftime('%Y-%m', created_at) m, COUNT(*) n
        FROM purchase_requests GROUP BY m ORDER BY m DESC LIMIT 6""")][::-1]
    st = [dict(r) for r in c.execute("SELECT status label, COUNT(*) n FROM purchase_requests GROUP BY status")]
    c.close()
    return jsonify(dept=dept, usage_vs_request=uv, monthly=mo, status=st)
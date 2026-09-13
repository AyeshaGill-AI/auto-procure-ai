from flask import Blueprint, request, jsonify, session
from services.db import conn

bp = Blueprint("meta", __name__, url_prefix="/api")

def _role():
    c = conn()
    u = c.execute("SELECT role FROM users WHERE id=?", (session["uid"],)).fetchone()
    c.close()
    return u["role"] if u else None

def _validated_body(d):
    """Validate a department payload. Returns (data, error)."""
    if not isinstance(d, dict): return None, "JSON object required"
    name = (d.get("name") or "").strip()
    if not name: return None, "name is required"
    if len(name) > 80: return None, "name exceeds 80 characters"
    for f in ("budget_total", "budget_spent"):
        v = d.get(f, 0 if f == "budget_spent" else None)
        if v is None: return None, f"{f} is required"
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            return None, f"{f} must be a non-negative number"
    return {"name": name, "budget_total": float(d["budget_total"]),
            "budget_spent": float(d.get("budget_spent", 0))}, None

@bp.get("/departments")
def departments():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    c = conn()
    rows = c.execute("""SELECT id, name, budget_total, budget_spent,
        ROUND(CASE WHEN budget_total > 0 THEN 100.0*budget_spent/budget_total ELSE 0 END, 1) pct,
        ROUND(budget_total - budget_spent, 2) remaining
        FROM departments ORDER BY name""").fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])

@bp.post("/departments")
def create_department():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    if _role() != "Procurement Manager": return jsonify(error="manager role required"), 403
    d, err = _validated_body(request.get_json(silent=True))
    if err: return jsonify(error=err), 400
    c = conn()
    if c.execute("SELECT 1 FROM departments WHERE name=?", (d["name"],)).fetchone():
        c.close(); return jsonify(error="department name already exists"), 409
    cur = c.execute("INSERT INTO departments(name,budget_total,budget_spent) VALUES(?,?,?)",
                    (d["name"], d["budget_total"], d["budget_spent"]))
    c.commit(); did = cur.lastrowid; c.close()
    return jsonify(id=did, name=d["name"], budget_total=d["budget_total"],
                   budget_spent=d["budget_spent"], remaining=d["budget_total"] - d["budget_spent"]), 201

@bp.put("/departments/<int:did>")
def update_department(did):
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    if _role() != "Procurement Manager": return jsonify(error="manager role required"), 403
    d, err = _validated_body(request.get_json(silent=True))
    if err: return jsonify(error=err), 400
    c = conn()
    if not c.execute("SELECT 1 FROM departments WHERE id=?", (did,)).fetchone():
        c.close(); return jsonify(error="not found"), 404
    clash = c.execute("SELECT 1 FROM departments WHERE name=? AND id<>?", (d["name"], did)).fetchone()
    if clash:
        c.close(); return jsonify(error="department name already exists"), 409
    c.execute("UPDATE departments SET name=?, budget_total=?, budget_spent=? WHERE id=?",
              (d["name"], d["budget_total"], d["budget_spent"], did))
    c.commit(); c.close()
    return jsonify(id=did, name=d["name"], budget_total=d["budget_total"],
                   budget_spent=d["budget_spent"], remaining=d["budget_total"] - d["budget_spent"])

@bp.delete("/departments/<int:did>")
def delete_department(did):
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    if _role() != "Procurement Manager": return jsonify(error="manager role required"), 403
    c = conn()
    if not c.execute("SELECT 1 FROM departments WHERE id=?", (did,)).fetchone():
        c.close(); return jsonify(error="not found"), 404
    n = c.execute("SELECT COUNT(*) c FROM purchase_requests WHERE department_id=?", (did,)).fetchone()["c"]
    if n:
        c.close()
        return jsonify(error=f"department has {n} purchase request(s) and cannot be deleted — set its budget to 0 instead"), 409
    c.execute("DELETE FROM departments WHERE id=?", (did,))
    c.commit(); c.close()
    return jsonify(ok=True)

@bp.get("/items")
def items():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    c = conn()
    rows = c.execute("SELECT sku, name, category, gl_code, unit_cost FROM item_master ORDER BY name").fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])

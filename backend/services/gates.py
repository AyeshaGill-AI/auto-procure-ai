import re, difflib, json
from datetime import datetime, timedelta

TYPOS = {"saftey":"safety","helms":"helmets","steele":"steel","pip":"pipe","chager":"charger",
         "laptap":"laptop","chrgr":"charger","unform":"uniform",
         "maintainance":"maintenance"}

def clean_text(raw):
    t = raw.lower()
    t = re.sub(r"[^a-z0-9 .-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return " ".join(TYPOS.get(w, w) for w in t.split())

def match_item(c, cleaned):
    rows = c.execute("SELECT * FROM item_master").fetchall()
    pool = {f"{r['name']} {r['keywords']}": r for r in rows}
    hit = difflib.get_close_matches(cleaned, list(pool.keys()), 1, 0.30)
    if hit: return pool[hit[0]]
    return None

def get_settings(c):
    return {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}

def gate1(c, pr, gr=None):
    cleaned = clean_text(pr["raw_text"])
    item = match_item(c, cleaned)
    if not item:
        return {"status":"NEEDS_REVIEW","original":pr["raw_text"],"cleaned":cleaned,
                "sku":None,"category":None,"gl":None,"unit_cost":pr["unit_cost"] or 0,
                "note":"No confident item-master match. Routed to human review."}
    return {"status":"PASSED","original":pr["raw_text"],"cleaned":item["name"],
            "sku":item["sku"],"category":item["category"],"gl":item["gl_code"],
            "unit_cost":item["unit_cost"]}

def gate2(c, pr, gr):
    unit = gr["1"]["unit_cost"]; est = pr["qty"] * unit
    d = c.execute("SELECT * FROM departments WHERE id=?", (pr["department_id"],)).fetchone()
    rem = d["budget_total"] - d["budget_spent"]
    st = "PASSED" if est <= rem else "FAILED"
    return {"status":st,"estimated_cost":est,"remaining_budget":rem,
            "delta":round(rem - est,2),"department":d["name"]}

def gate3(c, pr, gr):
    rows = c.execute("SELECT warehouse,qty FROM inventory WHERE sku=? AND qty>0",
                     (gr["1"]["sku"],)).fetchall()
    total = sum(r["qty"] for r in rows)
    st = "FOUND" if total >= pr["qty"] else ("PARTIAL" if total > 0 else "NONE")
    return {"status":st,"total":total,
            "breakdown":[{"warehouse":r["warehouse"],"stock":r["qty"]} for r in rows]}

def gate4(c, pr, gr):
    s = get_settings(c); win = int(s.get("dup_window_days", 30))
    cutoff = (datetime.now() - timedelta(days=win)).isoformat()
    dup = None
    if gr["1"]["sku"]:
        row = c.execute("""SELECT code,raw_text FROM purchase_requests
            WHERE id<>? AND sku=? AND created_at>=? AND status<>'REJECTED'
            ORDER BY created_at DESC LIMIT 1""",
            (pr["id"], gr["1"]["sku"], cutoff)).fetchone()
        if row: dup = {"code":row["code"],"text":row["raw_text"]}
    if not dup:
        others = c.execute("""SELECT code,raw_text FROM purchase_requests
            WHERE id<>? AND created_at>=? AND status<>'REJECTED'""", (pr["id"], cutoff)).fetchall()
        for o in others:
            if difflib.SequenceMatcher(None, pr["raw_text"].lower(), o["raw_text"].lower()).ratio() > 0.85:
                dup = {"code":o["code"],"text":o["raw_text"]}; break
    po = c.execute("SELECT po_number,qty FROM open_pos WHERE sku=? AND status='OPEN'",
                   (gr["1"]["sku"],)).fetchone()
    st = "DUPLICATE" if dup else ("PO_OVERLAP" if po else "CLEAR")
    return {"status":st,"duplicate_pr":dup,
            "open_po":{"number":po["po_number"],"qty":po["qty"]} if po else None}

def gate5(c, pr, gr):
    s = get_settings(c); cap = float(s.get("usage_cap_months", 3))
    u = c.execute("SELECT * FROM usage_hist WHERE sku=?", (gr["1"]["sku"],)).fetchone()
    avg = u["avg_monthly"] if u else 0
    months = round(pr["qty"] / avg, 1) if avg else None
    if months is None: st = "OPTIMAL"; note = "No consumption baseline on file."
    elif months > cap: st = "OVER"; note = f"Request equals {months} months of usage (cap {cap})."
    elif months < 0.5: st = "UNDER"; note = f"Request covers only {months} months — stockout risk."
    else: st = "OPTIMAL"; note = f"Request equals {months} months of usage."
    return {"status":st,"avg_monthly":avg,"peak_monthly":u["peak_monthly"] if u else 0,
            "months":months,"cap_months":cap,"note":note}

FUNCS = {1:gate1, 2:gate2, 3:gate3, 4:gate4, 5:gate5}

def run_gate(c, pr_id, n):
    pr = c.execute("SELECT * FROM purchase_requests WHERE id=?", (pr_id,)).fetchone()
    gr = json.loads(pr["gate_results"] or "{}")
    for i in range(1, n + 1):
        gr[str(i)] = FUNCS[i](c, pr, gr)
    c.execute("UPDATE purchase_requests SET gate_results=?, cleaned_name=?, sku=?, category=?, gl_code=?, unit_cost=? WHERE id=?",
              (json.dumps(gr), gr["1"].get("cleaned"), gr["1"].get("sku"), gr["1"].get("category"),
               gr["1"].get("gl"), gr["1"].get("unit_cost"), pr_id))
    c.commit()
    return gr
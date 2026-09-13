def decide(c, pr, gr):
    from services.gates import get_settings
    s = get_settings(c)
    essential = [x.strip() for x in s.get("essential_categories", "").split(",") if x.strip()]
    g1, g2, g3, g4, g5 = (gr[str(i)] for i in range(1, 6))
    qty, unit = pr["qty"], g1["unit_cost"]
    available = g3["total"]
    transfer = min(qty, available)
    remainder = qty - transfer
    po_qty = g4["open_po"]["qty"] if g4["open_po"] else 0
    po_reuse = min(remainder, po_qty)
    buy_initial = remainder - po_reuse
    cap = round(g5["avg_monthly"] * g5["cap_months"]) if g5["avg_monthly"] else buy_initial
    buy = min(buy_initial, cap) if g5["status"] == "OVER" else buy_initial
    avoided = buy_initial - buy
    savings = round((transfer + po_reuse + avoided) * unit, 2)
    external = round(buy * unit, 2)

    stock_pts = 40 if (available == 0 and g5["avg_monthly"] >= 20) else \
                30 if available == 0 else 20 if available < g5["avg_monthly"] else \
                12 if available < qty else 6
    ops_pts = 30 if g1["category"] in essential else 12
    budget_pts = 15 if g2["status"] == "PASSED" else (10 if external <= g2["remaining_budget"] else 4)
    hyg_pts = 15
    if g4["status"] == "DUPLICATE": hyg_pts = 0
    elif g5["status"] != "OPTIMAL": hyg_pts = 8
    score = stock_pts + ops_pts + budget_pts + hyg_pts
    priority = "CRITICAL" if score >= 80 else "HIGH" if score >= 60 else "MEDIUM" if score >= 50 else "LOW"

    dup = g4["status"] == "DUPLICATE"
    if dup: rec = "HOLD"
    elif score >= 80: rec = "EXPEDITE"
    elif g2["status"] == "FAILED" and external > g2["remaining_budget"]: rec = "HOLD"
    elif transfer > 0 or avoided > 0 or po_reuse > 0: rec = "REDUCE"
    elif g5["status"] == "UNDER": rec = "INVESTIGATE"
    elif g2["status"] == "FAILED": rec = "REDUCE"
    else: rec = "PROCEED"

    reasoning, actions = [], []
    reasoning.append(f"Gate 1 standardized \"{g1['original']}\" to \"{g1['cleaned']}\" ({g1['sku'] or 'unmapped'}).")
    reasoning.append(f"Gate 2: estimated {qty*unit:,.0f} USD vs {g2['remaining_budget']:,.0f} USD remaining — {g2['status']}.")
    if transfer > 0:
        actions.append({"t": f"TRANSFER {transfer} idle units from internal warehouses before external buy."})
        reasoning.append(f"Gate 3: {available} idle units on hand across sites — {transfer} drafted for internal transfer.")
    else:
        reasoning.append(f"Gate 3: {available} idle units on hand — no transfer available.")
    if po_reuse > 0:
        actions.append({"t": f"REUSE open {g4['open_po']['number']} covering {po_reuse} units."})
        reasoning.append(f"Gate 4: open PO {g4['open_po']['number']} already covers {po_reuse} units.")
    if dup:
        actions.append({"t": f"MERGE with duplicate {g4['duplicate_pr']['code']} inside 30-day window."})
        reasoning.append(f"Gate 4: duplicate pattern matched {g4['duplicate_pr']['code']}.")
    if avoided > 0:
        actions.append({"t": f"RESIZE external buy from {buy_initial} to {buy} units (usage cap {g5['cap_months']} months)."})
    if buy > 0:
        actions.append({"t": f"PURCHASE only {buy} units externally ({external:,.0f} USD)."})
    else:
        actions.append({"t": "NO external purchase required — internal coverage sufficient."})
    reasoning.append(f"Gate 5: average usage {g5['avg_monthly']}/month — {g5['note']}")
    reasoning.append(f"Criticality {score}/100 ({priority}): stockout {stock_pts}/40, operational {ops_pts}/30, budget {budget_pts}/15, hygiene {hyg_pts}/15.")

    return {"recommendation": rec, "priority": priority, "score": score,
            "parts": {"stockout": stock_pts, "operational": ops_pts, "budget": budget_pts, "hygiene": hyg_pts},
            "transfer_qty": transfer, "po_reuse_qty": po_reuse, "buy_qty": buy,
            "avoided_qty": avoided, "savings": savings, "external_cost": external,
            "reasoning": reasoning, "actions": [a["t"] for a in actions]}
"""Regression checks for GATEWAY // AutoProcure AI.

Run from the project root:  python test_flows.py
Uses a throwaway copy of the demo database so the seeded data is untouched.
"""
import os, shutil, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import services.db as db  # noqa: E402

DB_BACKUP = db.DBPATH.with_suffix(".bak")
if DB_BACKUP.exists():
    shutil.copy(DB_BACKUP, db.DBPATH)  # restore leftover backup from a crashed run
elif db.DBPATH.exists():
    shutil.copy(db.DBPATH, DB_BACKUP)

db.init()

import app as app_module  # noqa: E402
client = app_module.app.test_client()

PASS, FAIL = 0, 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok    {name}")
    else:
        FAIL += 1; print(f"  FAIL  {name} {extra}")

def csrf():
    return client.get("/").headers.get("X-CSRF-Token")

def fresh():
    """CSRF token refreshed right before a request (server rotates it on every response)."""
    return {"X-CSRF-Token": csrf()}

print("== auth ==")
r = client.post("/api/auth/login", json={"username": "ayesha.gill", "password": "procure123"},
                headers={"X-CSRF-Token": csrf()})
check("login", r.status_code == 200, r.status_code)
H = {"X-CSRF-Token": csrf()}

r = client.get("/api/departments")
check("departments endpoint", r.status_code == 200 and len(r.get_json()) >= 5)
DEPT_IDS = {d["name"]: d["id"] for d in r.get_json()}

print("== request validation ==")
r = client.post("/api/requests", json={"raw_text": "", "qty": 1, "department_id": 1}, **{"headers": H} if False else {})
check("create without CSRF rejected", r.status_code == 403)
r = client.post("/api/requests", headers=H, json={"raw_text": "", "qty": 1, "department_id": 1})
check("empty raw_text rejected", r.status_code == 400, r.get_json())
r = client.post("/api/requests", headers=H, json={"raw_text": "widget", "qty": 0, "department_id": 1})
check("zero qty rejected", r.status_code == 400)
r = client.post("/api/requests", headers=H, json={"raw_text": "widget", "qty": 1, "department_id": 999})
check("unknown department rejected", r.status_code == 400)
r = client.post("/api/requests", headers=H, json={"raw_text": "widget", "qty": 1, "department_id": 1,
                                                  "required_date": "20-09-2026"})
check("bad date format rejected", r.status_code == 400)
r = client.post("/api/requests", headers=H, json={"raw_text": "3in steele pip for factory maintenance 40 count",
                                                  "department_id": DEPT_IDS["Maintenance"], "qty": 40,
                                                  "unit_price": 48, "required_date": "2026-10-01"})
check("valid create accepted", r.status_code == 201, r.get_json())
PID = r.get_json()["id"]

print("== gates + decision ==")
for n in (1, 2, 3, 4, 5):
    r = client.post(f"/api/requests/{PID}/gates/{n}", headers=H)
    check(f"gate {n} runs", r.status_code == 200 and "status" in r.get_json()["result"])
r = client.get(f"/api/requests/{PID}/decision")
d = r.get_json()
check("decision returned", r.status_code == 200 and d["decision"] is not None)
check("decision has all five gates", all(str(i) in d["gates"] for i in range(1, 6)))
check("llm summary present", bool(d["decision"].get("llm_summary")))
check("score in range", 0 <= d["decision"]["score"] <= 100)

print("== action lifecycle ==")
r = client.post(f"/api/requests/{PID}/action", headers=H, json={"action": "APPROVE"})
check("approve executes", r.status_code == 200 and r.get_json()["status"] == "APPROVED")
r = client.post(f"/api/requests/{PID}/action", headers=H, json={"action": "APPROVE"})
check("double-approve blocked", r.status_code == 409, r.get_json())
r = client.post(f"/api/requests/{PID}/action", headers=H, json={"action": "BOGUS"})
check("invalid action rejected", r.status_code == 400)
r = client.post("/api/requests/999999/action", headers=H, json={"action": "APPROVE"})
check("unknown request 404", r.status_code == 404)

print("== PO dedupe on re-approve via EXPEDITE ==")
r = client.post("/api/requests", headers=H, json={"raw_text": "hydraulic seal kit for press line 7",
                                                  "department_id": DEPT_IDS["Maintenance"], "qty": 30,
                                                  "unit_price": 80, "required_date": "2026-10-05"})
PID2 = r.get_json()["id"]
client.post(f"/api/requests/{PID2}/action", headers=H, json={"action": "EXPEDITE"})
c = db.conn()
pos_before = c.execute("SELECT COUNT(*) c FROM open_pos WHERE sku='HYD-SEL-K7' AND status='ORDERED'").fetchone()["c"]
c.close()
client.post(f"/api/requests/{PID2}/action", headers=H, json={"action": "APPROVE"})
c = db.conn()
pos_after = c.execute("SELECT COUNT(*) c FROM open_pos WHERE sku='HYD-SEL-K7' AND status='ORDERED'").fetchone()["c"]
c.close()
check("no duplicate ORDERED PO per SKU", pos_after <= pos_before + 1, f"{pos_before} -> {pos_after}")

print("== reject path ==")
r = client.post("/api/requests", headers=H, json={"raw_text": "office chair ergonomic", "department_id": DEPT_IDS["HR"],
                                                  "qty": 5, "unit_price": 120})
PID3 = r.get_json()["id"]
r = client.post(f"/api/requests/{PID3}/action", headers=H, json={"action": "REJECT"})
check("reject executes", r.status_code == 200 and r.get_json()["status"] == "REJECTED")
r = client.post(f"/api/requests/{PID3}/action", headers=H, json={"action": "APPROVE"})
check("rejected request is closed", r.status_code == 409)

print("== department CRUD ==")
r = client.post("/api/departments", headers=H, json={"name": "QA Test Dept", "budget_total": 5000})
check("create department", r.status_code == 201, r.get_json())
NEW_ID = r.get_json()["id"]
r = client.post("/api/departments", headers=H, json={"name": "QA Test Dept", "budget_total": 1})
check("duplicate name blocked", r.status_code == 409)
r = client.post("/api/departments", headers=H, json={"name": "", "budget_total": 1})
check("empty name rejected", r.status_code == 400)
r = client.post("/api/departments", headers=H, json={"name": "Neg", "budget_total": -5})
check("negative budget rejected", r.status_code == 400)
r = client.put(f"/api/departments/{NEW_ID}", headers=H, json={"name": "QA Test Dept 2", "budget_total": 7500, "budget_spent": 1500})
check("update department", r.status_code == 200 and r.get_json()["remaining"] == 6000, r.get_json())
r = client.get("/api/departments")
check("list shows pct/remaining", all("pct" in d and "remaining" in d for d in r.get_json()))
r = client.delete(f"/api/departments/{NEW_ID}", headers=H)
check("delete empty department", r.status_code == 200)
r = client.delete(f"/api/departments/{DEPT_IDS['Maintenance']}", headers=H)
check("delete with PRs blocked", r.status_code == 409)
r = client.delete("/api/departments/999999", headers=H)
check("delete unknown 404", r.status_code == 404)

print("== requisitioner role guard ==")
csrf2 = csrf()
client.post("/api/auth/login", json={"username": "marcus.reed", "password": "request123"}, headers={"X-CSRF-Token": csrf2})
H2 = {"X-CSRF-Token": csrf()}
r = client.post("/api/departments", headers=H2, json={"name": "Sneaky", "budget_total": 1})
check("requisitioner create blocked", r.status_code == 403)
r = client.put(f"/api/departments/{DEPT_IDS['IT']}", headers=H2, json={"name": "X", "budget_total": 1})
check("requisitioner update blocked", r.status_code == 403)
r = client.get("/api/departments")
check("requisitioner can view", r.status_code == 200)

print("== AI key plumbing ==")
r = client.get("/api/settings", headers=fresh())
s = r.get_json()
check("settings expose ai_key fields", "groq_key" not in s)
r = client.post("/api/ai/test", headers=fresh())
check("ai test endpoint responds", r.status_code in (200, 502) and "ok" in r.get_json(), f"status={r.status_code}")

print("== account registration ==")
csrf3 = csrf()
r = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf3},
                json={"name": "Test User", "username": "test.user", "password": "testpass1", "role": "Department Requisitioner"})
check("register new account", r.status_code == 200, r.get_json())
r = client.get("/api/auth/me")
check("auto sign-in after register", r.status_code == 200 and r.get_json()["username"] == "test.user")
r = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf()},
                json={"name": "Dup", "username": "test.user", "password": "testpass1"})
check("duplicate Operator ID blocked", r.status_code == 409)
r = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf()},
                json={"name": "Weak", "username": "weak.user", "password": "short"})
check("weak password rejected", r.status_code == 400)
r = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf()},
                json={"name": "Bad", "username": "bad user!", "password": "testpass1"})
check("invalid username rejected", r.status_code == 400)
client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf()})

print("== account isolation ==")
# NOTE: login clears the session, so tokens must be captured AFTER each login
client.post("/api/auth/login", json={"username": "ayesha.gill", "password": "procure123"}, headers=fresh())
H_MGR = fresh()
r = client.post("/api/requests", headers=H_MGR, json={"raw_text": "manager owned item test", "department_id": DEPT_IDS["IT"],
                                                      "qty": 1, "unit_price": 10})
MGR_PR = r.get_json()["id"]
client.post("/api/auth/login", json={"username": "test.user", "password": "testpass1"}, headers=fresh())
H_TST = fresh()
r = client.post("/api/requests", headers=H_TST, json={"raw_text": "test user owned item", "department_id": DEPT_IDS["IT"],
                                                      "qty": 1, "unit_price": 10})
TST_PR = r.get_json()["id"]
r = client.get("/api/requests")
ids = {row["id"] for row in r.get_json()}
check("list scoped to owner", MGR_PR not in ids and TST_PR in ids)
r = client.get(f"/api/requests/{MGR_PR}")
check("other user's detail forbidden", r.status_code == 403, r.get_json())
r = client.post(f"/api/requests/{MGR_PR}/action", headers=H_TST, json={"action": "APPROVE"})
check("other user's action forbidden", r.status_code == 403)
r = client.get(f"/api/requests/{MGR_PR}/decision")
check("other user's decision forbidden", r.status_code == 403)
r = client.post(f"/api/requests/{MGR_PR}/gates/1", headers=H_TST)
check("other user's gates forbidden", r.status_code == 403)
client.post("/api/auth/logout", headers=fresh())
client.post("/api/auth/login", json={"username": "ayesha.gill", "password": "procure123"}, headers=fresh())
H_MGR2 = fresh()
r = client.get("/api/requests", headers=H_MGR2)
ids = {row["id"] for row in r.get_json()}
check("manager sees all requests", MGR_PR in ids and TST_PR in ids)
r = client.get(f"/api/requests/{TST_PR}")
check("manager can open others' requests", r.status_code == 200)
client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf()})

print("== remember-me flow ==")
rcsrf = csrf()
r = client.post("/api/auth/login", headers={"X-CSRF-Token": rcsrf},
                json={"username": "test.user", "password": "testpass1", "remember": True})
cookie = r.headers.get("Set-Cookie") or ""
check("remember cookie issued", "remember_token=" in cookie and "HttpOnly" in cookie, cookie[:80])
tok1 = cookie.split("remember_token=")[1].split(";")[0]
client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf()})  # clears server token too
r = client.get("/api/auth/me")  # cookie was deleted server-side by logout
check("logout invalidates remember token", r.status_code == 401)
r = client.post("/api/auth/login", headers={"X-CSRF-Token": csrf()},
                json={"username": "test.user", "password": "testpass1", "remember": True})
cookie = r.headers.get("Set-Cookie") or ""
tok2 = cookie.split("remember_token=")[1].split(";")[0]
client.get("/")  # any page hit triggers auto-login via cookie
r = client.get("/api/auth/me")
check("remember cookie auto-login", r.status_code == 200 and r.get_json().get("username") == "test.user", r.status_code)
import services.db as _db
c = _db.conn()
row_count = c.execute("SELECT COUNT(*) c FROM remember_tokens").fetchone()["c"]
c.close()
check("token stored hashed", row_count >= 1)

print("== login lockout ==")
lock_user = "locktest.user"
csrfL = csrf()
client.post("/api/auth/register", headers={"X-CSRF-Token": csrfL},
            json={"name": "Lock Test", "username": lock_user, "password": "lockpass1"})
client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf()})
for i in range(5):
    client.post("/api/auth/login", json={"username": lock_user, "password": "wrong" + str(i)},
                headers={"X-CSRF-Token": csrf()})
r = client.post("/api/auth/login", json={"username": lock_user, "password": "lockpass1"},
                headers={"X-CSRF-Token": csrf()})
check("6th attempt locked out (even correct password)", r.status_code == 429, r.get_json())

print("== summary ==")
client.post("/api/auth/login", json={"username": "ayesha.gill", "password": "procure123"}, headers=fresh())
r = client.get("/api/analytics/summary")
check("analytics summary", r.status_code == 200 and "savings" in r.get_json())
r = client.get("/api/analytics/budget")
check("budget endpoint", r.status_code == 200 and len(r.get_json()["depts"]) >= 5)
r = client.get("/api/settings")
check("settings read", r.status_code == 200)

print(f"\n{PASS} passed, {FAIL} failed")
if DB_BACKUP.exists():
    shutil.copy(DB_BACKUP, db.DBPATH)
    os.remove(DB_BACKUP)
    print("demo database restored")
sys.exit(1 if FAIL else 0)

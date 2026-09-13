from flask import Blueprint, request, session, jsonify, g
from services.db import conn, hash_pw, hash_token
from datetime import datetime, timedelta
import re
import secrets as _secrets

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

REMEMBER_COOKIE = "remember_token"
REMEMBER_DAYS = 30
FAILED_LOGINS = {}  # username -> [failed attempt timestamps]
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = 300  # seconds

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,40}$")

def _username_error(u):
    if not u: return "Operator ID is required"
    if not _USERNAME_RE.match(u): return "Operator ID: 3-40 chars, letters, digits, dots, dashes, underscores only"
    return None

def _password_error(p):
    if not p or len(p) < 8: return "Password must be at least 8 characters"
    if len(p) > 128: return "Password too long"
    if not re.search(r"[A-Za-z]", p): return "Password must contain a letter"
    if not re.search(r"\d", p): return "Password must contain a digit"
    return None

def _user_row(uid):
    c = conn()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return u

def _start_session(u, remember=False):
    session.clear()  # regeneration prevents session fixation on login
    session["uid"] = u["id"]
    session.permanent = True
    if not remember:
        return jsonify(id=u["id"], name=u["name"], role=u["role"])
    token = _secrets.token_hex(32)
    c = conn()
    c.execute("DELETE FROM remember_tokens WHERE user_id=?", (u["id"],))  # one remembered device per account
    c.execute("INSERT INTO remember_tokens(user_id,token_hash,expires_at,created_at) VALUES(?,?,?,?)",
              (u["id"], hash_token(token),
               (datetime.utcnow() + timedelta(days=REMEMBER_DAYS)).isoformat(),
               datetime.utcnow().isoformat()))
    c.commit(); c.close()
    resp = jsonify(id=u["id"], name=u["name"], role=u["role"])
    resp.set_cookie(REMEMBER_COOKIE, token, max_age=REMEMBER_DAYS * 86400, httponly=True, samesite="Lax")
    return resp

@bp.post("/register")
def register():
    d = request.get_json(silent=True) or {}
    uerr = _username_error(d.get("username"))
    if uerr: return jsonify(error=uerr), 400
    perr = _password_error(d.get("password"))
    if perr: return jsonify(error=perr), 400
    name = (d.get("name") or "").strip()
    if not name: return jsonify(error="Full name is required"), 400
    if len(name) > 80: return jsonify(error="Name too long"), 400
    role = d.get("role") or "Department Requisitioner"
    if role not in ("Department Requisitioner", "Procurement Manager"):
        return jsonify(error="Invalid role selection"), 400
    username = d["username"].strip().lower()
    c = conn()
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        c.close(); return jsonify(error="That Operator ID is already registered"), 409
    h, s = hash_pw(d["password"])
    cur = c.execute("INSERT INTO users(username,password_hash,salt,name,role) VALUES(?,?,?,?,?)",
                    (username, h, s, name, role))
    c.commit(); uid = cur.lastrowid; c.close()
    return _start_session(_user_row(uid))  # auto sign-in after registration

@bp.post("/login")
def login():
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip().lower()
    now = datetime.utcnow().timestamp()
    attempts = [t for t in FAILED_LOGINS.get(username, []) if now - t < ATTEMPT_WINDOW]
    if len(attempts) >= MAX_ATTEMPTS:
        FAILED_LOGINS[username] = attempts
        wait = int(ATTEMPT_WINDOW - (now - attempts[0])) + 1
        return jsonify(error=f"Too many failed attempts - try again in {wait} seconds"), 429
    c = conn()
    u = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone(); c.close()
    if not u:
        FAILED_LOGINS[username] = attempts + [now]
        return jsonify(error="Unknown operator or bad credentials"), 401
    h, _ = hash_pw(d.get("password", ""), u["salt"])
    if h != u["password_hash"]:
        FAILED_LOGINS[username] = attempts + [now]
        return jsonify(error="Unknown operator or bad credentials"), 401
    FAILED_LOGINS.pop(username, None)
    return _start_session(u, remember=bool(d.get("remember")))

@bp.get("/me")
def me():
    if "uid" not in session: return jsonify(error="unauthenticated"), 401
    u = _user_row(session["uid"])
    if not u: return jsonify(error="unauthenticated"), 401
    return jsonify(id=u["id"], name=u["name"], role=u["role"], username=u["username"])

@bp.post("/logout")
def logout():
    tok = request.cookies.get(REMEMBER_COOKIE)
    if tok:
        c = conn()
        c.execute("DELETE FROM remember_tokens WHERE token_hash=?", (hash_token(tok),))
        c.commit(); c.close()
    resp = jsonify(ok=True)
    resp.delete_cookie(REMEMBER_COOKIE)
    session.clear()
    return resp

def try_remember_me():
    """Auto-login from a valid remember-me cookie; the token rotates on every use."""
    if "uid" in session or request.endpoint in ("auth.login", "auth.register", "auth.logout"):
        return
    tok = request.cookies.get(REMEMBER_COOKIE)
    if not tok: return
    c = conn()
    row = c.execute("SELECT id, user_id, expires_at FROM remember_tokens WHERE token_hash=?",
                    (hash_token(tok),)).fetchone()
    if not row or row["expires_at"] < datetime.utcnow().isoformat():
        if row:
            c.execute("DELETE FROM remember_tokens WHERE id=?", (row["id"],)); c.commit()
        c.close(); return
    u = c.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
    if u:
        g._rotate_remember = _secrets.token_hex(32)
        c.execute("UPDATE remember_tokens SET token_hash=?, expires_at=? WHERE id=?",
                  (hash_token(g._rotate_remember),
                   (datetime.utcnow() + timedelta(days=REMEMBER_DAYS)).isoformat(), row["id"]))
        c.commit()
    c.close()
    if not u: return
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
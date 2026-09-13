from flask import Flask, send_from_directory, jsonify, session, request
import pathlib, secrets
from datetime import timedelta
from dotenv import load_dotenv
from services.db import init, get_secret
from routes import auth, requests, analysis, analytics, settings, meta

load_dotenv()
FRONTEND = pathlib.Path(__file__).resolve().parents[1] / "frontend"
app = Flask(__name__)
app.secret_key = get_secret()  # app-managed; no env setup required
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # reject oversized request bodies
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

from routes.auth import try_remember_me, REMEMBER_COOKIE, REMEMBER_DAYS

@app.before_request
def auto_login():
    """Restore a session from the remember-me cookie before anything else."""
    try_remember_me()

@app.after_request
def rotate_remember_cookie(response):
    """Remember-me tokens rotate on every use; the new value is set here."""
    from flask import g
    new_tok = g.pop("_rotate_remember", None)
    if new_tok:
        response.set_cookie(REMEMBER_COOKIE, new_tok, max_age=REMEMBER_DAYS * 86400,
                            httponly=True, samesite="Lax")
    return response

@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.endpoint not in ("auth.login", "auth.register"):
        token = session.get("_csrf_token")
        if not token or token != request.headers.get("X-CSRF-Token"):
            return jsonify(error="CSRF token missing or invalid"), 403

@app.after_request
def set_csrf_header(response):
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    response.headers["X-CSRF-Token"] = session["_csrf_token"]
    return response

for b in (auth.bp, requests.bp, analysis.bp, analytics.bp, settings.bp, meta.bp):
    app.register_blueprint(b)

@app.get("/")
def home():
    token = session.get("_csrf_token") or secrets.token_hex(32)
    session["_csrf_token"] = token
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    html = html.replace("</head>", f'<meta name="csrf-token" content="{token}"></head>')
    return (html, 200, {'Content-Type': 'text/html; charset=utf-8', 'X-CSRF-Token': token})

@app.get("/<path:p>")
def static_files(p):
    if p.startswith("api/"): return jsonify(error="not found"), 404
    target = (FRONTEND / p)
    if target.is_file():
        token = session.get("_csrf_token", secrets.token_hex(32))
        if "_csrf_token" not in session:
            session["_csrf_token"] = token
        ext = target.suffix.lower()
        if ext == ".html":
            content = target.read_text(encoding="utf-8")
            content = content.replace("</head>", f'<meta name="csrf-token" content="{token}"></head>')
            return (content, 200, {'Content-Type': 'text/html; charset=utf-8', 'X-CSRF-Token': token})
        return send_from_directory(FRONTEND, p)
    return send_from_directory(FRONTEND, "index.html")

@app.errorhandler(404)
def nf(e): return jsonify(error="not found"), 404

@app.errorhandler(500)
def err(e): return jsonify(error="internal fault"), 500

if __name__ == "__main__":
    init()
    app.run(debug=True, port=5000)
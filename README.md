# GATEWAY // AutoProcure AI
AI-powered purchase-request checking system. Flask + SQLite backend, vanilla HTML/CSS/JS frontend.
Palette: #727D73 #AAB99A #D0DDD0 #F0F0D7 · Type: Bebas Neue / Barlow Condensed / IBM Plex Mono.

## RUN
pip install -r requirements.txt
cp .env.example .env           # add your GROQ_API_KEY (optional)
python backend/app.py          # seeds SQLite on first boot, self-generates its secret
open http://localhost:5000     # login: ayesha.gill / procure123

## PAGE MAP
index → dashboard → submit → analysis (live gates) → checks → decision → history / analytics / settings.
Every sidebar item, table row arrow, flow arrow and button is wired to a live endpoint.

## KEY ENDPOINTS
POST /api/auth/login · GET /api/auth/me
GET/POST /api/requests · GET /api/requests/<id> · POST /api/requests/<id>/action
POST /api/requests/<id>/gates/<1-5> · GET /api/requests/<id>/decision
GET/POST /api/departments · PUT/DELETE /api/departments/<id>  (writes require the Procurement Manager role)
GET /api/items · POST /api/ai/test
GET /api/analytics/summary · GET /api/analytics/charts · GET /api/analytics/budget
GET/POST /api/settings · POST /api/admin/reset

## ACCOUNTS & SECURITY
- Create an account from the login page (SIGN IN / CREATE ACCOUNT tabs); new users sign in automatically.
- Passwords: min 8 chars with a letter + digit, stored salted + hashed. Operator IDs are unique.
- Wrong Operator ID/password cannot reach another account. Requests are stamped to their creator:
  users see only their own, managers see all. Others' gates/decisions/actions return 403.
- "Remember me" keeps a device signed in for 30 days via an HttpOnly cookie; tokens are stored
  hashed, rotate on every use, and are revoked on logout.
- 5 failed logins per Operator ID lock attempts for 5 minutes.

## TESTS
python test_flows.py        # end-to-end regression suite (restores demo DB after)
PYTHONPATH=backend python test_budget.py

## GENERATIVE AI (GROQ)
Set your key in the `.env` file (`GROQ_API_KEY=gsk_...`) or have a manager save it in Settings
(Settings wins). Groq is the default provider; reroute to another OpenAI-compatible service with
`AI_BASE_URL` / `AI_MODEL` env vars. Without a key the deterministic analyst fallback is used.

## SECRETS
No `FLASK_SECRET_KEY` setup is required — on first boot the app generates a strong random secret
and stores it in `backend/data/secret.key` (gitignored). Deployments that prefer their own secret
can still set `FLASK_SECRET_KEY`, which takes priority.
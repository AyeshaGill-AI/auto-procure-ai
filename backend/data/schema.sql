CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, salt TEXT,
  name TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS remember_tokens(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS departments(
  id INTEGER PRIMARY KEY, name TEXT, budget_total REAL, budget_spent REAL);
CREATE TABLE IF NOT EXISTS item_master(
  id INTEGER PRIMARY KEY, sku TEXT UNIQUE, name TEXT, keywords TEXT,
  category TEXT, gl_code TEXT, unit_cost REAL);
CREATE TABLE IF NOT EXISTS inventory(
  id INTEGER PRIMARY KEY, sku TEXT REFERENCES item_master(sku), warehouse TEXT, qty INTEGER);
CREATE TABLE IF NOT EXISTS open_pos(
  id INTEGER PRIMARY KEY, po_number TEXT, sku TEXT REFERENCES item_master(sku), qty INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS usage_hist(
  id INTEGER PRIMARY KEY, sku TEXT REFERENCES item_master(sku), avg_monthly REAL, peak_monthly REAL);
CREATE TABLE IF NOT EXISTS purchase_requests(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, raw_text TEXT, cleaned_name TEXT,
  sku TEXT REFERENCES item_master(sku), category TEXT, gl_code TEXT, department_id INTEGER REFERENCES departments(id), qty INTEGER,
  unit_cost REAL, required_date TEXT, notes TEXT, status TEXT,
  created_at TEXT, gate_results TEXT, decision TEXT, created_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
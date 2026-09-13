import sqlite3, pathlib, hashlib, os, base64, secrets
from cryptography.fernet import Fernet

BASE = pathlib.Path(__file__).resolve().parents[1]
VERCEL = os.environ.get("VERCEL") == "1"
if VERCEL:
    DBPATH = pathlib.Path("/tmp/autoprocure.db")
    SECRET_FILE = pathlib.Path("/tmp/secret.key")
else:
    DBPATH = BASE / "data" / "autoprocure.db"
    SECRET_FILE = BASE / "data" / "secret.key"

def get_secret():
    """App-managed secret: generated once, persisted next to the database.
    FLASK_SECRET_KEY env var still wins if a deployment explicitly sets it."""
    env = os.environ.get("FLASK_SECRET_KEY")
    if env:
        return env
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    SECRET_FILE.parent.mkdir(exist_ok=True)
    tok = secrets.token_urlsafe(48)
    SECRET_FILE.write_text(tok, encoding="utf-8")
    if os.name != "nt":
        os.chmod(SECRET_FILE, 0o600)
    return tok

def _get_cipher():
    key = base64.urlsafe_b64encode(hashlib.pbkdf2_hmac("sha256", get_secret().encode(),
                                                       b"auto-procure-encryption", 100000)[:32])
    return Fernet(key)

def encrypt(value):
    return _get_cipher().encrypt(value.encode()).decode()

def decrypt(value):
    try:
        return _get_cipher().decrypt(value.encode()).decode()
    except Exception:
        return value

def hash_pw(pw, salt=None):
    salt = salt or os.urandom(8).hex()
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 120000).hex(), salt

def hash_token(token):
    """Hash for remember-me cookie tokens (fast hash is fine for 256-bit random values)."""
    return hashlib.sha256(token.encode()).hexdigest()

def conn():
    c = sqlite3.connect(DBPATH); c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON"); return c

def _migrate(c):
    """Lightweight column migrations for databases created before these features."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(purchase_requests)")}
    if "created_by" not in cols:
        c.execute("ALTER TABLE purchase_requests ADD COLUMN created_by INTEGER REFERENCES users(id)")

def init():
    if not VERCEL:
        (BASE / "data").mkdir(exist_ok=True)
    c = conn(); c.executescript((BASE / "data" / "schema.sql").read_text(encoding="utf-8"))
    _migrate(c); c.commit()
    if c.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        seed(c); c.commit()
    c.close()

def seed(c):
    for u, p, n, r in [("ayesha.gill","procure123","Ayesha Gill","Procurement Manager"),
                       ("marcus.reed","request123","Marcus Reed","Department Requisitioner")]:
        h, s = hash_pw(p)
        c.execute("INSERT INTO users(username,password_hash,salt,name,role) VALUES(?,?,?,?,?)",(u,h,s,n,r))
    for n, t, s in [("Maintenance",20000,16000),("IT",5000,4850),("HR",6000,3000),
                    ("Operations",30000,18000),("Admin",4000,2000)]:
        c.execute("INSERT INTO departments(name,budget_total,budget_spent) VALUES(?,?,?)",(n,t,s))
    items = [
      ("HS-9912","Helmet, Protective Industrial","helmet safety head protective hard hat saftey helms","Safety Equipment","GL-5510",25),
      ("IT-CHR-065W","Laptop Charger 65W","laptop charger adapter power 65w usb-c chager","IT Accessories","GL-5120",25),
      ("402-STEEL-P3","3-inch Carbon-Steel Pipe","pipe steel carbon 3 inch piping tube steele pip","MRO Supplies","GL-5120",48),
      ("OFC-CHR-101","Office Chair, Ergonomic","office chair ergonomic seat furniture","Furniture","GL-6200",120),
      ("PRN-TRC-220","Printer Toner, Black","toner printer cartridge ink black","Office Supplies","GL-5130",60),
      ("UNI-SFT-009","High-Vis Uniform Set","uniform hi-vis visibility jacket safety wear","Safety Equipment","GL-5510",45),
      ("HYD-SEL-K7","Hydraulic Seal Kit","hydraulic seal kit press cylinder gasket","Production Parts","GL-5300",80)]
    for i in items: c.execute("INSERT INTO item_master(sku,name,keywords,category,gl_code,unit_cost) VALUES(?,?,?,?,?,?)", i)
    for s, w, q in [("HS-9912","Site B",350),("IT-CHR-065W","Warehouse A",15),("OFC-CHR-101","Site C",12),
                    ("PRN-TRC-220","Warehouse A",4),("HS-9912","Warehouse A",0),("HYD-SEL-K7","Warehouse A",0)]:
        c.execute("INSERT INTO inventory(sku,warehouse,qty) VALUES(?,?,?)",(s,w,q))
    c.execute("INSERT INTO open_pos(po_number,sku,qty,status) VALUES('PO-4587','HS-9912',100,'OPEN')")
    for s, a, p in [("HS-9912",30,55),("IT-CHR-065W",2,4),("402-STEEL-P3",12,20),("OFC-CHR-101",1,2),
                    ("PRN-TRC-220",6,9),("UNI-SFT-009",25,40),("HYD-SEL-K7",40,60)]:
        c.execute("INSERT INTO usage_hist(sku,avg_monthly,peak_monthly) VALUES(?,?,?)",(s,a,p))
    reqs = [
      ("PR-007","hydraulic seal kit for press line 2",1,"HYD-SEL-K7",60,80,"2026-09-12","PENDING","Line 2 press leaking"),
      ("PR-001","500 saftey helms for site refit project",1,"HS-9912",500,25,"2026-09-10","REDUCE","Site refit project"),
      ("PR-002","laptop charger 65w x10 for it pool",2,"IT-CHR-065W",10,25,"2026-09-09","APPROVED",""),
      ("PR-003","office chair ergonomic",3,"OFC-CHR-101",8,120,"2026-09-08","ON_HOLD",""),
      ("PR-004","3in steele pip for factory maintenance 50 count",4,"402-STEEL-P3",50,48,"2026-09-07","INVESTIGATE",""),
      ("PR-005","printer toner cartridge black",5,"PRN-TRC-220",12,60,"2026-09-06","APPROVED",""),
      ("PR-006","hi-vis uniform set winter 40",1,"UNI-SFT-009",40,45,"2026-09-04","EXPEDITE","")]
    for code, raw, d, sku, q, p, dt, st, nt in reqs:
        c.execute("""INSERT INTO purchase_requests(code,raw_text,department_id,sku,qty,unit_cost,
                   required_date,status,created_at,notes) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (code,raw,d,sku,q,p,dt,st,dt+"T09:00:00",nt))
    for k, v in [("usage_cap_months","3"),("dup_window_days","30"),
                 ("essential_categories","Safety Equipment,Production Parts,MRO Supplies"),("groq_key","")]:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?)",(k,v))

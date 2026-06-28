"""SQLite — lekka baza w pliku. Tabele: ogloszenia, cv_wygenerowane, konfiguracja."""
import sqlite3, json, datetime
from . import config

def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS ogloszenia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT,
        tytul TEXT, firma TEXT, opis TEXT, link TEXT, kraj TEXT, zrodlo TEXT,
        status TEXT DEFAULT 'nowa',          -- nowa | zaakceptowana | odrzucona | wyeksportowana
        score INTEGER,
        summary TEXT, gaps TEXT,
        eval_model TEXT                      -- którym modelem oceniono
    );
    CREATE TABLE IF NOT EXISTS cv_wygenerowane (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogloszenie_id INTEGER,
        created_at TEXT,
        content_json TEXT,                   -- dopasowane CV (schemat jak cv.json)
        justification TEXT,
        warnings TEXT,                       -- ostrzeżenia guardraila (JSON list)
        pdf_path TEXT,
        edited INTEGER DEFAULT 0,
        UNIQUE(ogloszenie_id)
    );
    CREATE TABLE IF NOT EXISTS konfiguracja (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS dokumenty (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT, orig TEXT, fname TEXT
    );
    """)
    c.execute("INSERT OR IGNORE INTO konfiguracja(key,value) VALUES('threshold',?)",
              (str(config.DEFAULT_THRESHOLD),))
    try: c.execute("ALTER TABLE ogloszenia ADD COLUMN eval_model TEXT")   # migracja istniejącej bazy
    except Exception: pass
    try: c.execute("ALTER TABLE ogloszenia ADD COLUMN ord INTEGER")       # ręczna kolejność w poczekalni
    except Exception: pass
    c.execute("UPDATE ogloszenia SET ord = -id WHERE ord IS NULL")        # domyślnie najnowsze u góry
    c.commit(); c.close()

def now(): return datetime.datetime.now().isoformat(timespec="seconds")

def get_config(key, default=None):
    c = conn(); r = c.execute("SELECT value FROM konfiguracja WHERE key=?", (key,)).fetchone(); c.close()
    return r["value"] if r else default

def set_config(key, value):
    c = conn(); c.execute("INSERT OR REPLACE INTO konfiguracja(key,value) VALUES(?,?)", (key, str(value)))
    c.commit(); c.close()

def add_ad(d):
    c = conn()
    cur = c.execute("""INSERT INTO ogloszenia(created_at,tytul,firma,opis,link,kraj,zrodlo,status)
                       VALUES(?,?,?,?,?,?,?, 'nowa')""",
                    (now(), d.get("tytul",""), d.get("firma",""), d.get("opis",""),
                     d.get("link",""), d.get("kraj",""), d.get("zrodlo","manual")))
    rid = cur.lastrowid
    c.execute("UPDATE ogloszenia SET ord=? WHERE id=?", (-rid, rid))   # nowe na górze
    c.commit(); c.close(); return rid

def reorder(ids):
    """Zapisuje ręczną kolejność: ids w kolejności od góry listy."""
    c = conn()
    for i, aid in enumerate(ids):
        c.execute("UPDATE ogloszenia SET ord=? WHERE id=?", (i, int(aid)))
    c.commit(); c.close()

def update_ad_eval(ad_id, score, summary, gaps, model=None):
    c = conn(); c.execute("UPDATE ogloszenia SET score=?, summary=?, gaps=?, eval_model=? WHERE id=?",
                          (score, summary, gaps, model, ad_id)); c.commit(); c.close()

def update_ad_meta(ad_id, tytul, firma, kraj, link):
    c = conn(); c.execute("UPDATE ogloszenia SET tytul=?, firma=?, kraj=?, link=? WHERE id=?",
                          (tytul, firma, kraj, link, ad_id)); c.commit(); c.close()

def set_status(ad_id, status):
    c = conn(); c.execute("UPDATE ogloszenia SET status=? WHERE id=?", (status, ad_id)); c.commit(); c.close()

def save_cv(ad_id, content, justification, warnings, pdf_path, edited=0):
    c = conn()
    c.execute("""INSERT INTO cv_wygenerowane(ogloszenie_id,created_at,content_json,justification,warnings,pdf_path,edited)
                 VALUES(?,?,?,?,?,?,?)
                 ON CONFLICT(ogloszenie_id) DO UPDATE SET
                   content_json=excluded.content_json, justification=excluded.justification,
                   warnings=excluded.warnings, pdf_path=excluded.pdf_path, edited=excluded.edited,
                   created_at=excluded.created_at""",
              (ad_id, now(), json.dumps(content, ensure_ascii=False), justification,
               json.dumps(warnings, ensure_ascii=False), pdf_path, edited))
    c.commit(); c.close()

def get_ad(ad_id):
    c = conn(); r = c.execute("SELECT * FROM ogloszenia WHERE id=?", (ad_id,)).fetchone(); c.close()
    return dict(r) if r else None

def get_cv(ad_id):
    c = conn(); r = c.execute("SELECT * FROM cv_wygenerowane WHERE ogloszenie_id=?", (ad_id,)).fetchone(); c.close()
    return dict(r) if r else None

def delete_ad(ad_id):
    c = conn()
    c.execute("DELETE FROM ogloszenia WHERE id=?", (ad_id,))
    c.execute("DELETE FROM cv_wygenerowane WHERE ogloszenie_id=?", (ad_id,))
    c.commit(); c.close()

# --- dodatkowe dokumenty kandydata ---
def add_doc(orig, fname):
    c = conn(); cur = c.execute("INSERT INTO dokumenty(created_at,orig,fname) VALUES(?,?,?)",
                                (now(), orig, fname)); c.commit(); rid = cur.lastrowid; c.close(); return rid

def list_docs():
    c = conn(); rows = c.execute("SELECT * FROM dokumenty ORDER BY id ASC").fetchall(); c.close()
    return [dict(r) for r in rows]

def get_doc(doc_id):
    c = conn(); r = c.execute("SELECT * FROM dokumenty WHERE id=?", (doc_id,)).fetchone(); c.close()
    return dict(r) if r else None

def del_doc(doc_id):
    c = conn(); c.execute("DELETE FROM dokumenty WHERE id=?", (doc_id,)); c.commit(); c.close()

def list_ads():
    c = conn()
    rows = c.execute("""SELECT o.*, (SELECT 1 FROM cv_wygenerowane v WHERE v.ogloszenie_id=o.id) AS has_cv
                        FROM ogloszenia o ORDER BY o.ord ASC, o.id DESC""").fetchall()
    c.close(); return [dict(r) for r in rows]

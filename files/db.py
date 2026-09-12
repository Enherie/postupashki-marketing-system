"""
db.py — единственный слой работы с БД. Никакой зависимости от telegram
здесь нет специально: это позволяет тестировать всю бизнес-логику
(в т.ч. в CI) без реального бота.

Схема — это и есть marketing data model кейса, только не на диаграмме,
а в виде рабочих таблиц:

    users        — ститчинг-ключ = telegram user_id (реальный, надёжный)
    ad_links     — рекламные размещения (campaign/placement/creative + cost)
    promocodes   — промокоды, опционально привязаны к ad_link
    touches      — касания: клик по deep-link ИЛИ активация промокода
    orders       — заказы (и живые из бота, и импортированные исторические)
"""
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    joined_at   TEXT NOT NULL,
    promo_code  TEXT
);

CREATE TABLE IF NOT EXISTS ad_links (
    code        TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,
    placement   TEXT,
    creative    TEXT,
    cost        REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    comment     TEXT
);

CREATE TABLE IF NOT EXISTS promocodes (
    code             TEXT PRIMARY KEY,
    discount_percent REAL NOT NULL DEFAULT 0,
    ad_link_code     TEXT,
    created_at       TEXT NOT NULL,
    FOREIGN KEY (ad_link_code) REFERENCES ad_links(code)
);

CREATE TABLE IF NOT EXISTS touches (
    touch_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    ad_link_code TEXT NOT NULL,
    source       TEXT NOT NULL,          -- 'deeplink' | 'promo'
    touch_time   TEXT NOT NULL,
    FOREIGN KEY (ad_link_code) REFERENCES ad_links(code)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    course      TEXT NOT NULL,
    amount      REAL NOT NULL,
    promo_code  TEXT,
    order_time  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'bot'   -- 'bot' (живой) | 'import' (исторический)
);
"""


@contextmanager
def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path):
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)


def now_iso():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------- users ----------

def upsert_user(db_path, user_id, username, first_name):
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (user_id, username, first_name, joined_at) VALUES (?,?,?,?)",
                (user_id, username, first_name, now_iso()),
            )
            return True  # новый пользователь
        return False


def set_user_promo(db_path, user_id, promo_code):
    with get_conn(db_path) as conn:
        conn.execute("UPDATE users SET promo_code=? WHERE user_id=?", (promo_code, user_id))


# ---------- ad_links ----------

def create_ad_link(db_path, code, channel, placement, creative, cost, comment=""):
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO ad_links (code, channel, placement, creative, cost, created_at, comment) "
            "VALUES (?,?,?,?,?,?,?)",
            (code, channel, placement, creative, cost, now_iso(), comment),
        )


def get_ad_link(db_path, code):
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM ad_links WHERE code=?", (code,)).fetchone()
        return dict(row) if row else None


def list_ad_links(db_path):
    with get_conn(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM ad_links ORDER BY created_at DESC")]


# ---------- promocodes ----------

def create_promocode(db_path, code, discount_percent, ad_link_code=None):
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO promocodes (code, discount_percent, ad_link_code, created_at) VALUES (?,?,?,?)",
            (code, discount_percent, ad_link_code, now_iso()),
        )


def get_promocode(db_path, code):
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM promocodes WHERE code=?", (code,)).fetchone()
        return dict(row) if row else None


# ---------- touches ----------

def add_touch(db_path, user_id, ad_link_code, source, dedupe=False):
    """dedupe=True — не плодить повторные touch с одним и тем же источником
    для одного пользователя (используется для промо, чтобы не заспамить
    таблицу при повторном вводе того же кода)."""
    with get_conn(db_path) as conn:
        if dedupe:
            existing = conn.execute(
                "SELECT 1 FROM touches WHERE user_id=? AND ad_link_code=? AND source=?",
                (user_id, ad_link_code, source),
            ).fetchone()
            if existing:
                return
        conn.execute(
            "INSERT INTO touches (user_id, ad_link_code, source, touch_time) VALUES (?,?,?,?)",
            (user_id, ad_link_code, source, now_iso()),
        )


# ---------- orders ----------

def add_order(db_path, user_id, course, amount, promo_code=None, source="bot"):
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO orders (user_id, course, amount, promo_code, order_time, source) VALUES (?,?,?,?,?,?)",
            (user_id, course, amount, promo_code, now_iso(), source),
        )


def counts(db_path):
    with get_conn(db_path) as conn:
        def one(q):
            return conn.execute(q).fetchone()[0]
        return dict(
            users=one("SELECT COUNT(*) FROM users"),
            touches=one("SELECT COUNT(*) FROM touches"),
            orders=one("SELECT COUNT(*) FROM orders"),
            revenue=conn.execute("SELECT COALESCE(SUM(amount),0) FROM orders").fetchone()[0],
        )

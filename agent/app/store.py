"""发布任务存储（SQLite）。状态：pending_review → approved → published / failed；rejected。"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from .config import settings

STATUSES = ("pending_review", "approved", "published", "drafted", "failed", "rejected")


@contextmanager
def conn():
    os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    c = sqlite3.connect(settings.db_path)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL, topic TEXT, title TEXT, digest TEXT,
            body TEXT, tags TEXT, status TEXT, issues TEXT, draft_id TEXT, publish_id TEXT, error TEXT)""")
        c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
        c.execute("""CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, title TEXT, body TEXT, ref TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS metrics(
            date TEXT PRIMARY KEY, visitors REAL, orders REAL, gmv REAL, ad_cost REAL, repeat_orders REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS schedules(
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, platform TEXT, run_at REAL,
            status TEXT, result TEXT, error TEXT, created_at REAL)""")
        if "mode" not in [r[1] for r in c.execute("PRAGMA table_info(schedules)").fetchall()]:
            c.execute("ALTER TABLE schedules ADD COLUMN mode TEXT")


def _row(r):
    d = dict(r)
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["issues"] = json.loads(d.get("issues") or "[]")
    return d


def add_task(topic, title, digest, body, tags, issues, status="pending_review") -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO tasks(created_at,topic,title,digest,body,tags,status,issues) VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), topic, title, digest, body, json.dumps(tags, ensure_ascii=False), status,
             json.dumps(issues, ensure_ascii=False)))
        return cur.lastrowid


def get(task_id):
    with conn() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _row(r) if r else None


def list_tasks(status=None, limit=50):
    with conn() as c:
        if status:
            rows = c.execute("SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row(r) for r in rows]


def update(task_id, **fields):
    if not fields:
        return
    for k in ("tags", "issues"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    sets = ",".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*fields.values(), task_id))


def kv_get(k, default=None):
    with conn() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default


def kv_set(k, v):
    with conn() as c:
        c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


# ---------- 发布计划 ----------
def _srow(r):
    d = dict(r)
    d["result"] = json.loads(d.get("result") or "null")
    return d


def add_schedule(task_id, platform, run_at, mode=None) -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO schedules(task_id,platform,run_at,status,created_at,mode) VALUES(?,?,?,?,?,?)",
                        (task_id, platform, run_at, "scheduled", time.time(), mode))
        return cur.lastrowid


def get_schedule(sid):
    with conn() as c:
        r = c.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
        return _srow(r) if r else None


def list_schedules(task_id=None, status=None, limit=200):
    q, args = "SELECT * FROM schedules", []
    cond = []
    if task_id is not None:
        cond.append("task_id=?"); args.append(task_id)
    if status:
        cond.append("status=?"); args.append(status)
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY run_at ASC, id ASC LIMIT ?"
    with conn() as c:
        return [_srow(r) for r in c.execute(q, (*args, limit)).fetchall()]


def claim_schedule(sid) -> bool:
    """原子地把 scheduled → running，避免同一计划被执行两次。"""
    with conn() as c:
        cur = c.execute("UPDATE schedules SET status='running' WHERE id=? AND status='scheduled'", (sid,))
        return cur.rowcount == 1


def update_schedule(sid, **fields):
    if "result" in fields and not isinstance(fields["result"], str):
        fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
    sets = ",".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE schedules SET {sets} WHERE id=?", (*fields.values(), sid))


# ---------- 服务端事件（前端轮询后显示为消息红点）----------
def add_event(kind, title, body="", ref=""):
    with conn() as c:
        cur = c.execute("INSERT INTO events(ts,kind,title,body,ref) VALUES(?,?,?,?,?)", (time.time(), kind, title, body, ref))
        return cur.lastrowid


def list_events(after=0, limit=50):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM events WHERE id>? ORDER BY id ASC LIMIT ?", (after, limit)).fetchall()]


# ---------- 经营数据（导入的店铺每日数据）----------
METRIC_COLS = ("visitors", "orders", "gmv", "ad_cost", "repeat_orders")


def upsert_metrics(rows, replace=False):
    with conn() as c:
        if replace:
            c.execute("DELETE FROM metrics")
        for r in rows:
            c.execute("""INSERT INTO metrics(date,visitors,orders,gmv,ad_cost,repeat_orders) VALUES(?,?,?,?,?,?)
                         ON CONFLICT(date) DO UPDATE SET
                           visitors=COALESCE(excluded.visitors,visitors), orders=COALESCE(excluded.orders,orders),
                           gmv=COALESCE(excluded.gmv,gmv), ad_cost=COALESCE(excluded.ad_cost,ad_cost),
                           repeat_orders=COALESCE(excluded.repeat_orders,repeat_orders)""",
                      (r["date"], *(r.get(k) for k in METRIC_COLS)))


def list_metrics():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM metrics ORDER BY date ASC").fetchall()]


def clear_metrics():
    with conn() as c:
        c.execute("DELETE FROM metrics")

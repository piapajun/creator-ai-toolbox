"""
Creator AI Toolbox - 用户系统 & 付费模块
SQLite 数据库：用户表、激活码表、使用记录表
"""
import sqlite3
import uuid
import hashlib
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "toolbox.db")


def get_db():
    """获取数据库连接（自动建表）"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_tables(conn)
    return conn


def _init_tables(conn):
    """初始化表结构"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT 'free',
            activation_code TEXT,
            activated_at TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS activation_codes (
            code TEXT PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT 'pro',
            duration_days INTEGER NOT NULL DEFAULT 365,
            batch_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            used_by TEXT,
            used_at TEXT
        );

        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_usage_user_date
            ON usage_logs(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_usage_ip_date
            ON usage_logs(ip, created_at);
        CREATE INDEX IF NOT EXISTS idx_codes_batch
            ON activation_codes(batch_id);
    """)


# ========== 用户操作 ==========

def get_or_create_user(user_id=None):
    """获取或创建用户（基于 IP 匿名用户，激活后绑定）"""
    db = get_db()
    if user_id:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user:
            db.execute("UPDATE users SET last_seen = datetime('now') WHERE id = ?", (user_id,))
            db.commit()
            return dict(user)

    # 创建新匿名用户
    new_id = f"anon_{uuid.uuid4().hex[:12]}"
    db.execute("INSERT INTO users (id, plan) VALUES (?, 'free')", (new_id,))
    db.commit()
    return dict(db.execute("SELECT * FROM users WHERE id = ?", (new_id,)).fetchone())


def activate_user(user_id, activation_code):
    """激活用户会员"""
    db = get_db()

    # 检查激活码
    code = db.execute(
        "SELECT * FROM activation_codes WHERE code = ? AND used_by IS NULL",
        (activation_code,)
    ).fetchone()

    if not code:
        return False, "激活码无效或已被使用"

    # 激活
    now = datetime.now()
    expires = now + timedelta(days=code["duration_days"])

    db.execute(
        "UPDATE users SET plan = ?, activation_code = ?, activated_at = ?, expires_at = ? WHERE id = ?",
        (code["plan"], activation_code, now.isoformat(), expires.isoformat(), user_id)
    )
    db.execute(
        "UPDATE activation_codes SET used_by = ?, used_at = ? WHERE code = ?",
        (user_id, now.isoformat(), activation_code)
    )
    db.commit()

    return True, {
        "plan": code["plan"],
        "expires_at": expires.strftime("%Y-%m-%d"),
        "duration_days": code["duration_days"]
    }


def get_user_status(user_id):
    """获取用户状态（含是否过期）"""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return None

    user = dict(user)
    # 检查是否过期
    if user.get("expires_at"):
        try:
            expires = datetime.fromisoformat(user["expires_at"])
            if expires < datetime.now():
                user["plan"] = "free"
                user["expired"] = True
            else:
                user["expired"] = False
        except:
            pass

    return user


# ========== 用量统计 & 限流 ==========

# 免费用户每日限额
FREE_LIMITS = {
    "rewrite": 3,
    "image_search": 3,
    "hotboard_analyze": 3,
}

ADMIN_KEY = os.environ.get("ADMIN_KEY", "creator2026")


def get_today_usage(user_id, action=None):
    """获取今日用量"""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    if action:
        count = db.execute(
            "SELECT COUNT(*) as cnt FROM usage_logs WHERE user_id = ? AND action = ? AND created_at >= ?",
            (user_id, action, today)
        ).fetchone()["cnt"]
        return count
    else:
        rows = db.execute(
            "SELECT action, COUNT(*) as cnt FROM usage_logs WHERE user_id = ? AND created_at >= ? GROUP BY action",
            (user_id, today)
        ).fetchall()
        return {r["action"]: r["cnt"] for r in rows}


def check_and_record(user_id, action, ip="unknown"):
    """检查用量并记录。返回 (allowed, remaining, limit)"""
    db = get_db()
    user = dict(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    # 付费用户不限
    if user.get("plan") == "pro" and not _is_expired(user):
        db.execute(
            "INSERT INTO usage_logs (user_id, action, ip) VALUES (?, ?, ?)",
            (user_id, action, ip)
        )
        db.commit()
        return True, float("inf"), float("inf")

    # 免费用户检查限额
    limit = FREE_LIMITS.get(action, 3)
    today = datetime.now().strftime("%Y-%m-%d")
    used = db.execute(
        "SELECT COUNT(*) as cnt FROM usage_logs WHERE user_id = ? AND action = ? AND created_at >= ?",
        (user_id, action, today)
    ).fetchone()["cnt"]

    if used >= limit:
        return False, 0, limit

    # 记录使用
    db.execute(
        "INSERT INTO usage_logs (user_id, action, ip) VALUES (?, ?, ?)",
        (user_id, action, ip)
    )
    db.commit()
    return True, limit - used - 1, limit


def _is_expired(user):
    """检查用户是否过期"""
    if not user.get("expires_at"):
        return False
    try:
        return datetime.fromisoformat(user["expires_at"]) < datetime.now()
    except:
        return False


# ========== 激活码管理 ==========

def generate_codes(count=10, plan="pro", duration_days=365, batch_id=None):
    """生成激活码"""
    db = get_db()
    if not batch_id:
        batch_id = datetime.now().strftime("%Y%m%d%H%M")

    codes = []
    for _ in range(count):
        # 生成 16 位字母数字码，排除易混淆字符
        raw = hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()[:12].upper()
        code = "CTB-" + raw[:4] + "-" + raw[4:8] + "-" + raw[8:12]
        db.execute(
            "INSERT INTO activation_codes (code, plan, duration_days, batch_id) VALUES (?, ?, ?, ?)",
            (code, plan, duration_days, batch_id)
        )
        codes.append(code)

    db.commit()
    return {"batch_id": batch_id, "count": len(codes), "codes": codes}


def list_codes(batch_id=None):
    """列出激活码"""
    db = get_db()
    if batch_id:
        rows = db.execute(
            "SELECT * FROM activation_codes WHERE batch_id = ? ORDER BY created_at DESC",
            (batch_id,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM activation_codes ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]


def get_code_stats():
    """激活码统计"""
    db = get_db()
    total = db.execute("SELECT COUNT(*) as cnt FROM activation_codes").fetchone()["cnt"]
    used = db.execute("SELECT COUNT(*) as cnt FROM activation_codes WHERE used_by IS NOT NULL").fetchone()["cnt"]
    return {"total": total, "used": used, "available": total - used}

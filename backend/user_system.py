"""
Creator AI Toolbox - 用户系统 & 付费模块 v3
- 账号密码注册/登录
- 多级付费：free / trial(首月免费) / pro_monthly / pro_yearly / pro_lifetime / credits
- SQLite 数据库
"""
import sqlite3
import uuid
import hashlib
import os
import requests
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "toolbox.db")

ADMIN_KEY = os.environ.get("ADMIN_KEY", "creator2026")

# ========== 套餐定义 ==========
PLANS = {
    "free": {
        "name": "免费版",
        "price": "¥0",
        "price_num": 0,
        "duration_days": 0,
        "limits": {"rewrite": 3, "image_search": 3, "hotboard_analyze": 3},
        "description": "游客模式，无需登录",
        "badge": "basic",
    },
    "trial": {
        "name": "新用户体验",
        "price": "¥0",
        "price_num": 0,
        "duration_days": 30,
        "limits": {"rewrite": 5, "image_search": 5, "hotboard_analyze": 5},
        "description": "注册登录即享30天免费试用，每天5次AI功能",
        "badge": "trial",
    },
    "pro_monthly": {
        "name": "Pro月付",
        "price": "¥29.9/月",
        "price_num": 29.9,
        "duration_days": 30,
        "limits": {"rewrite": float("inf"), "image_search": float("inf"), "hotboard_analyze": 10},
        "description": "无限AI改写、无限搜图",
        "badge": "pro",
    },
    "pro_yearly": {
        "name": "Pro年付",
        "price": "¥199/年",
        "price_num": 199,
        "duration_days": 365,
        "limits": {"rewrite": float("inf"), "image_search": float("inf"), "hotboard_analyze": 10},
        "description": "年付省45%，相当于¥16.6/月",
        "badge": "pro",
    },
    "pro_lifetime": {
        "name": "永久版",
        "price": "¥99",
        "price_num": 99,
        "duration_days": 36500,
        "limits": {"rewrite": float("inf"), "image_search": float("inf"), "hotboard_analyze": 10},
        "description": "一次购买，永久使用",
        "badge": "pro",
    },
    "credits_50": {
        "name": "50次点数包",
        "price": "¥9.9",
        "price_num": 9.9,
        "duration_days": 0,
        "limits": {},
        "credits": 50,
        "description": "适合轻度使用，用完即止",
        "badge": "credits",
    },
    "credits_200": {
        "name": "200次点数包",
        "price": "¥29.9",
        "price_num": 29.9,
        "duration_days": 0,
        "limits": {},
        "credits": 200,
        "description": "最受欢迎，每次仅¥0.15",
        "badge": "credits",
    },
}


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
    """初始化表结构 v3 — 支持账号密码登录 + 试用 + 点数"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            plan TEXT NOT NULL DEFAULT 'free',
            activation_code TEXT,
            activated_at TEXT,
            expires_at TEXT,
            trial_started_at TEXT,
            wechat_openid TEXT,
            wechat_nickname TEXT,
            wechat_avatar TEXT,
            credits_balance INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS activation_codes (
            code TEXT PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT 'pro_monthly',
            duration_days INTEGER NOT NULL DEFAULT 30,
            credits INTEGER NOT NULL DEFAULT 0,
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

    # 兼容老数据库：逐个补齐新字段
    _safe_add_column(conn, "users", "username", "TEXT")
    _safe_add_column(conn, "users", "password_hash", "TEXT")
    _safe_add_column(conn, "users", "trial_started_at", "TEXT")
    _safe_add_column(conn, "users", "wechat_openid", "TEXT")
    _safe_add_column(conn, "users", "wechat_nickname", "TEXT")
    _safe_add_column(conn, "users", "wechat_avatar", "TEXT")
    _safe_add_column(conn, "users", "credits_balance", "INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "activation_codes", "credits", "INTEGER NOT NULL DEFAULT 0")

    # 安全创建索引
    _safe_create_index(conn, "idx_users_username", "users", "username")


def _safe_add_column(conn, table, column, typedef):
    """安全添加列 — 忽略已存在的列"""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


def _safe_create_index(conn, idx_name, table, column):
    """安全创建索引"""
    try:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})")
    except sqlite3.OperationalError:
        pass  # 列不存在时跳过


# ========== 账号密码注册/登录 ==========

def hash_password(password: str) -> str:
    """PBKDF2-SHA256 密码哈希"""
    import hashlib as _hl
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + ':' + dk.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码"""
    if not stored_hash or ':' not in stored_hash:
        return False
    salt_hex, dk_hex = stored_hash.split(':', 1)
    salt = bytes.fromhex(salt_hex)
    import hashlib as _hl
    dk = _hl.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return dk.hex() == dk_hex


def register_user(username: str, password: str):
    """注册新用户。返回 (user_dict, error)"""
    db = get_db()
    username = username.strip().lower()
    if not username or len(username) < 2:
        return None, "用户名至少2个字符"
    if not password or len(password) < 4:
        return None, "密码至少4个字符"

    # 检查用户名是否已存在
    existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        return None, "该用户名已被注册"

    # 创建用户（新用户自动进入试用期）
    new_id = f"u_{uuid.uuid4().hex[:10]}"
    now = datetime.now().isoformat()
    trial_ends = (datetime.now() + timedelta(days=30)).isoformat()
    pwd_hash = hash_password(password)

    db.execute(
        """INSERT INTO users (id, username, password_hash, plan, trial_started_at, expires_at, created_at, last_seen)
           VALUES (?, ?, ?, 'trial', ?, ?, ?, ?)""",
        (new_id, username, pwd_hash, now, trial_ends, now, now)
    )
    db.commit()
    user = dict(db.execute("SELECT * FROM users WHERE id = ?", (new_id,)).fetchone())
    # 不返回密码哈希
    user.pop("password_hash", None)
    return user, None


def login_user(username: str, password: str):
    """登录。返回 (user_dict, error)"""
    db = get_db()
    username = username.strip().lower()
    if not username or not password:
        return None, "请输入用户名和密码"

    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        return None, "用户名不存在"
    user = dict(user)

    if not verify_password(password, user.get("password_hash", "")):
        return None, "密码错误"

    # 更新最后登录时间
    db.execute("UPDATE users SET last_seen = datetime('now') WHERE id = ?", (user["id"],))
    db.commit()

    # 不返回密码哈希
    user.pop("password_hash", None)
    return user, None


# ========== 用户操作 ==========

def get_or_create_user(user_id=None):
    """获取或创建匿名用户"""
    db = get_db()
    if user_id:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user:
            db.execute("UPDATE users SET last_seen = datetime('now') WHERE id = ?", (user_id,))
            db.commit()
            return dict(user)

    new_id = f"anon_{uuid.uuid4().hex[:12]}"
    db.execute("INSERT INTO users (id, plan) VALUES (?, 'free')", (new_id,))
    db.commit()
    return dict(db.execute("SELECT * FROM users WHERE id = ?", (new_id,)).fetchone())


def activate_user(user_id, activation_code):
    """激活用户会员（支持多种套餐 + 点数包）"""
    db = get_db()

    code = dict(db.execute(
        "SELECT * FROM activation_codes WHERE code = ? AND used_by IS NULL",
        (activation_code,)
    ).fetchone())

    if not code:
        return False, "激活码无效或已被使用"

    now = datetime.now()
    plan = code["plan"]
    duration = code["duration_days"]
    extra_credits = code.get("credits", 0)

    # 计算到期时间
    if duration > 0:
        expires = now + timedelta(days=duration)
    else:
        expires = None  # 永久/点数包不过期

    # 更新用户
    if extra_credits > 0:
        # 点数包：累加点数
        db.execute(
            "UPDATE users SET credits_balance = credits_balance + ?, activation_code = ?, activated_at = ? WHERE id = ?",
            (extra_credits, activation_code, now.isoformat(), user_id)
        )
    elif plan.startswith("pro_"):
        # Pro套餐：设置新计划 + 到期日
        db.execute(
            "UPDATE users SET plan = ?, activation_code = ?, activated_at = ?, expires_at = ? WHERE id = ?",
            (plan, activation_code, now.isoformat(),
             expires.isoformat() if expires else None, user_id)
        )
        # 若从试用升级，保留原有到期再叠加
        if expires:
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            old_expires = user["expires_at"] if user else None
            if old_expires:
                try:
                    old_dt = datetime.fromisoformat(old_expires)
                    if old_dt > now:
                        expires = old_dt + timedelta(days=duration)
                        db.execute("UPDATE users SET expires_at = ? WHERE id = ?",
                                   (expires.isoformat(), user_id))
                except:
                    pass

    db.execute(
        "UPDATE activation_codes SET used_by = ?, used_at = ? WHERE code = ?",
        (user_id, now.isoformat(), activation_code)
    )
    db.commit()

    plan_info = PLANS.get(plan, {})
    result = {
        "plan": plan,
        "plan_name": plan_info.get("name", plan),
        "expires_at": expires.strftime("%Y-%m-%d") if expires else "永久",
        "duration_days": duration,
        "credits_added": extra_credits,
    }
    return True, result


def upgrade_user(user_id, plan_key):
    """直接升级用户（用于测试/管理）"""
    db = get_db()
    plan = PLANS.get(plan_key)
    if not plan:
        return False, "无效套餐"

    now = datetime.now()
    days = plan.get("duration_days", 0)
    expires = (now + timedelta(days=days)).isoformat() if days > 0 else None
    credits = plan.get("credits", 0)

    if credits > 0:
        db.execute(
            "UPDATE users SET credits_balance = credits_balance + ? WHERE id = ?",
            (credits, user_id)
        )
    else:
        db.execute(
            "UPDATE users SET plan = ?, expires_at = ? WHERE id = ?",
            (plan_key, expires, user_id)
        )
    db.commit()
    return True, {"plan": plan_key, "expires_at": expires}


def get_user_status(user_id):
    """获取用户状态（含试用到期检测、过期检测）"""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return None

    user = dict(user)
    now = datetime.now()

    # 检查试用过期
    if user.get("plan") == "trial" and user.get("expires_at"):
        try:
            if datetime.fromisoformat(user["expires_at"]) < now:
                user["plan"] = "free"
                user["expired"] = True
                user["trial_ended"] = True
                # 更新数据库
                db.execute(
                    "UPDATE users SET plan = 'free' WHERE id = ?", (user_id,)
                )
                db.commit()
            else:
                days_left = (datetime.fromisoformat(user["expires_at"]) - now).days
                user["trial_days_left"] = max(0, days_left)
        except:
            pass

    # 检查Pro过期
    if user.get("plan", "").startswith("pro_") and user.get("expires_at"):
        try:
            if datetime.fromisoformat(user["expires_at"]) < now:
                user["plan"] = "free"
                user["expired"] = True
                db.execute(
                    "UPDATE users SET plan = 'free', expires_at = NULL WHERE id = ?",
                    (user_id,)
                )
                db.commit()
        except:
            pass

    return user


# ========== 用量统计 & 限流 v2 ==========

def get_user_limits(user):
    """根据用户套餐返回限额"""
    plan = user.get("plan", "free")
    plan_def = PLANS.get(plan, PLANS["free"])
    limits = plan_def.get("limits", {})

    # 试用期满5次/天
    result = {}
    for action in ["rewrite", "image_search", "hotboard_analyze"]:
        result[action] = limits.get(action, PLANS["free"]["limits"].get(action, 3))
    return result


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


def get_credits_balance(user_id):
    """获取点数余额"""
    db = get_db()
    user = db.execute("SELECT credits_balance FROM users WHERE id = ?", (user_id,)).fetchone()
    return user["credits_balance"] if user else 0


def consume_credit(user_id, amount=1):
    """消费点数"""
    db = get_db()
    db.execute(
        "UPDATE users SET credits_balance = MAX(0, credits_balance - ?) WHERE id = ?",
        (amount, user_id)
    )
    db.commit()


def check_and_record(user_id, action, ip="unknown"):
    """检查用量并记录。返回 (allowed, remaining, limit)"""
    db = get_db()
    user = dict(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    plan = user.get("plan", "free")

    # Pro套餐：无限
    if plan.startswith("pro_"):
        db.execute(
            "INSERT INTO usage_logs (user_id, action, ip) VALUES (?, ?, ?)",
            (user_id, action, ip)
        )
        db.commit()
        return True, float("inf"), float("inf")

    # 试用/免费：按日限额
    limits = get_user_limits(user)
    limit = limits.get(action, 3)
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


# ========== 激活码管理 ==========

def generate_codes(count=10, plan="trial", duration_days=30, credits=0, batch_id=None):
    """生成激活码（支持点数包）"""
    db = get_db()
    if not batch_id:
        batch_id = datetime.now().strftime("%Y%m%d%H%M")

    codes = []
    for _ in range(count):
        raw = hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()[:12].upper()
        code = "CTB-" + raw[:4] + "-" + raw[4:8] + "-" + raw[8:12]
        db.execute(
            "INSERT INTO activation_codes (code, plan, duration_days, credits, batch_id) VALUES (?, ?, ?, ?, ?)",
            (code, plan, duration_days, credits, batch_id)
        )
        codes.append({
            "code": code,
            "plan": PLANS.get(plan, {}).get("name", plan),
            "duration_days": duration_days,
            "credits": credits,
        })

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

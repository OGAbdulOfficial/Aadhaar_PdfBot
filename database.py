import os
import json
import logging
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", os.getenv("MONGODB_URI", "")).strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "AdharPDFBot").strip()
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_database.db")
LEGACY_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

# Database client instance
mongo_client = None
mongo_db = None
use_mongo = False

def get_sqlite():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    global mongo_client, mongo_db, use_mongo
    
    # 1. Try connecting to MongoDB if MONGO_URI is set
    if MONGO_URI:
        try:
            from pymongo import MongoClient
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=4000)
            client.admin.command('ping')
            mongo_client = client
            mongo_db = client[MONGO_DB_NAME]
            use_mongo = True
            logger.info("Connected to MongoDB successfully")
            
            mongo_db.claimed_utrs.create_index("utr", unique=True)
            mongo_db.users.create_index("user_id", unique=True)
            
            # Migrate legacy users.json to MongoDB if empty
            if mongo_db.users.count_documents({}) == 0 and os.path.exists(LEGACY_JSON):
                try:
                    with open(LEGACY_JSON, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for uid, udata in data.items():
                        mongo_db.users.update_one(
                            {"_id": str(uid)},
                            {"$setOnInsert": {
                                "user_id": str(uid),
                                "credits": float('inf') if udata.get('lifetime') else float(udata.get('credits', 1)),
                                "lifetime": bool(udata.get('lifetime')),
                                "referred_by": str(udata.get('referred_by')) if udata.get('referred_by') else None,
                                "referral_count": int(udata.get('referral_count', 0)),
                                "joined_at": udata.get('joined', datetime.now().isoformat()),
                                "banned": bool(udata.get('banned'))
                            }},
                            upsert=True
                        )
                    logger.info("Migrated legacy users.json to MongoDB")
                except Exception as e:
                    logger.error(f"Error migrating to MongoDB: {e}")
            return
        except Exception as e:
            logger.warning(f"MongoDB connection failed: {e}. Falling back to SQLite.")
            use_mongo = False
            
    # 2. SQLite Database
    logger.info("Using SQLite database for local persistence")
    conn = get_sqlite()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    credits REAL DEFAULT 1,
                    lifetime INTEGER DEFAULT 0,
                    referred_by TEXT DEFAULT NULL,
                    referral_count INTEGER DEFAULT 0,
                    joined_at TEXT,
                    banned INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS claimed_utrs (
                    utr TEXT PRIMARY KEY,
                    user_id TEXT,
                    amount REAL,
                    credits_added REAL,
                    claimed_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    utr TEXT,
                    amount REAL,
                    credits REAL,
                    status TEXT,
                    created_at TEXT
                )
            """)
            
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt FROM users")
            if cur.fetchone()[0] == 0 and os.path.exists(LEGACY_JSON):
                try:
                    with open(LEGACY_JSON, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for uid, udata in data.items():
                        cur.execute("""
                            INSERT OR IGNORE INTO users (user_id, credits, lifetime, referred_by, referral_count, joined_at, banned)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            str(uid),
                            float('inf') if udata.get('lifetime') else float(udata.get('credits', 1)),
                            1 if udata.get('lifetime') else 0,
                            str(udata.get('referred_by')) if udata.get('referred_by') else None,
                            int(udata.get('referral_count', 0)),
                            udata.get('joined', datetime.now().isoformat()),
                            1 if udata.get('banned') else 0
                        ))
                    logger.info("Migrated legacy users.json to SQLite")
                except Exception as e:
                    logger.error(f"Error migrating to SQLite: {e}")
    finally:
        conn.close()

def ensure_user(user_id, referrer_id=None):
    uid = str(user_id)
    ref_id = str(referrer_id) if referrer_id and str(referrer_id) != uid else None
    now_str = datetime.now().isoformat()
    
    if use_mongo and mongo_db is not None:
        existing = mongo_db.users.find_one({"_id": uid})
        if existing:
            return False
        user_doc = {
            "_id": uid,
            "user_id": uid,
            "credits": 1.0,
            "lifetime": False,
            "referred_by": ref_id,
            "referral_count": 0,
            "joined_at": now_str,
            "banned": False
        }
        mongo_db.users.insert_one(user_doc)
        if ref_id:
            mongo_db.users.update_one(
                {"_id": ref_id},
                {"$inc": {"credits": 1.0, "referral_count": 1}}
            )
        return True
    else:
        conn = get_sqlite()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,))
                if cur.fetchone():
                    return False
                cur.execute("""
                    INSERT INTO users (user_id, credits, lifetime, referred_by, referral_count, joined_at, banned)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (uid, 1.0, 0, ref_id, 0, now_str, 0))
                if ref_id:
                    cur.execute("""
                        UPDATE users SET credits = credits + 1.0, referral_count = referral_count + 1
                        WHERE user_id = ?
                    """, (ref_id,))
            return True
        finally:
            conn.close()

def get_user(user_id):
    uid = str(user_id)
    if use_mongo and mongo_db is not None:
        doc = mongo_db.users.find_one({"_id": uid})
        if doc:
            doc.pop("_id", None)
            return doc
        return None
    else:
        conn = get_sqlite()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

def get_credits(user_id):
    u = get_user(user_id)
    if not u:
        return 0
    if u.get('lifetime'):
        return float('inf')
    return float(u.get('credits', 0))

def is_lifetime(user_id):
    u = get_user(user_id)
    return bool(u.get('lifetime')) if u else False

def has_credits(user_id):
    return get_credits(user_id) > 0

def add_credits(user_id, amount, make_lifetime=False):
    uid = str(user_id)
    ensure_user(uid)
    if use_mongo and mongo_db is not None:
        if make_lifetime:
            mongo_db.users.update_one({"_id": uid}, {"$set": {"lifetime": True}})
        else:
            mongo_db.users.update_one({"_id": uid}, {"$inc": {"credits": float(amount)}})
    else:
        conn = get_sqlite()
        try:
            with conn:
                if make_lifetime:
                    conn.execute("UPDATE users SET lifetime = 1 WHERE user_id = ?", (uid,))
                else:
                    conn.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (float(amount), uid))
        finally:
            conn.close()

def deduct_credit(user_id):
    uid = str(user_id)
    if use_mongo and mongo_db is not None:
        u = mongo_db.users.find_one({"_id": uid})
        if u and not u.get('lifetime'):
            new_credits = max(0.0, float(u.get('credits', 0)) - 1.0)
            mongo_db.users.update_one({"_id": uid}, {"$set": {"credits": new_credits}})
    else:
        conn = get_sqlite()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("SELECT lifetime, credits FROM users WHERE user_id = ?", (uid,))
                row = cur.fetchone()
                if row and not row['lifetime']:
                    new_credits = max(0.0, float(row['credits']) - 1.0)
                    cur.execute("UPDATE users SET credits = ? WHERE user_id = ?", (new_credits, uid))
        finally:
            conn.close()

def ban_user(user_id):
    uid = str(user_id)
    ensure_user(uid)
    if use_mongo and mongo_db is not None:
        mongo_db.users.update_one({"_id": uid}, {"$set": {"banned": True}})
    else:
        conn = get_sqlite()
        try:
            with conn:
                conn.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (uid,))
        finally:
            conn.close()

def unban_user(user_id):
    uid = str(user_id)
    if use_mongo and mongo_db is not None:
        mongo_db.users.update_one({"_id": uid}, {"$set": {"banned": False}})
    else:
        conn = get_sqlite()
        try:
            with conn:
                conn.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (uid,))
        finally:
            conn.close()

def is_banned(user_id):
    u = get_user(user_id)
    return bool(u.get('banned')) if u else False

def all_users():
    if use_mongo and mongo_db is not None:
        users = {}
        for doc in mongo_db.users.find():
            uid = doc.get("user_id", str(doc.get("_id")))
            doc.pop("_id", None)
            users[uid] = doc
        return users
    else:
        conn = get_sqlite()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users")
            rows = cur.fetchall()
            return {r['user_id']: dict(r) for r in rows}
        finally:
            conn.close()

# ─── UPI TRANSACTION & UTR REPLAY PROTECTION ───────────────

def is_utr_claimed(utr: str) -> bool:
    clean_utr = utr.strip()
    if use_mongo and mongo_db is not None:
        return mongo_db.claimed_utrs.find_one({"_id": clean_utr}) is not None
    else:
        conn = get_sqlite()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM claimed_utrs WHERE utr = ?", (clean_utr,))
            return cur.fetchone() is not None
        finally:
            conn.close()

def record_successful_payment(user_id: str, utr: str, amount: float, credits_added: float, is_lifetime_tier: bool = False) -> bool:
    clean_utr = utr.strip()
    uid = str(user_id)
    ensure_user(uid)
    now_str = datetime.now().isoformat()
    
    if use_mongo and mongo_db is not None:
        if mongo_db.claimed_utrs.find_one({"_id": clean_utr}):
            return False
        try:
            mongo_db.claimed_utrs.insert_one({
                "_id": clean_utr,
                "utr": clean_utr,
                "user_id": uid,
                "amount": float(amount),
                "credits_added": float(credits_added),
                "claimed_at": now_str
            })
            mongo_db.transactions.insert_one({
                "user_id": uid,
                "utr": clean_utr,
                "amount": float(amount),
                "credits": float(credits_added),
                "status": "SUCCESS",
                "created_at": now_str
            })
            if is_lifetime_tier:
                mongo_db.users.update_one({"_id": uid}, {"$set": {"lifetime": True}})
            else:
                mongo_db.users.update_one({"_id": uid}, {"$inc": {"credits": float(credits_added)}})
            return True
        except Exception as e:
            logger.error(f"Error recording payment in MongoDB: {e}")
            return False
    else:
        conn = get_sqlite()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM claimed_utrs WHERE utr = ?", (clean_utr,))
                if cur.fetchone():
                    return False
                cur.execute("""
                    INSERT INTO claimed_utrs (utr, user_id, amount, credits_added, claimed_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (clean_utr, uid, float(amount), float(credits_added), now_str))
                cur.execute("""
                    INSERT INTO transactions (user_id, utr, amount, credits, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (uid, clean_utr, float(amount), float(credits_added), "SUCCESS", now_str))
                if is_lifetime_tier:
                    cur.execute("UPDATE users SET lifetime = 1 WHERE user_id = ?", (uid,))
                else:
                    cur.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (float(credits_added), uid))
            return True
        finally:
            conn.close()

# Auto-initialize
init_db()

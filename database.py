import os
import json
import logging
import time
import threading
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", os.getenv("MONGODB_URI", "")).strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "AdharPDFBot").strip()
LEGACY_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

# Database client instance
mongo_client: MongoClient = None
mongo_db = None

# ─── IN-MEMORY USER CACHE (ULTRA-FAST LATENCY) ───────────────
_user_cache = {}
_cache_lock = threading.Lock()
USER_CACHE_TTL = 30.0  # Cache duration: 30 seconds

def _cache_get(uid: str):
    with _cache_lock:
        item = _user_cache.get(uid)
        if item and (time.time() - item['t']) < USER_CACHE_TTL:
            return dict(item['doc'])
    return None

def _cache_set(uid: str, doc: dict):
    with _cache_lock:
        if doc is not None:
            _user_cache[uid] = {'t': time.time(), 'doc': dict(doc)}
        else:
            _user_cache.pop(uid, None)

def _cache_invalidate(uid: str):
    with _cache_lock:
        _user_cache.pop(uid, None)

def init_db():
    global mongo_client, mongo_db
    
    if not MONGO_URI:
        err = "FATAL: MONGO_URI environment variable is missing. MongoDB is mandatory."
        logger.error(err)
        raise RuntimeError(err)

    try:
        logger.info(f"Connecting to MongoDB Atlas (DB: {MONGO_DB_NAME})...")
        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=10000,
            socketTimeoutMS=15000,
            retryWrites=True
        )
        client.admin.command('ping')
        mongo_client = client
        mongo_db = client[MONGO_DB_NAME]
        logger.info(f"Successfully connected to MongoDB database '{MONGO_DB_NAME}'")
        
        # Ensure collections & unique indexes
        mongo_db.users.create_index("user_id", unique=True)
        
        # Migrate legacy users.json if database users collection is completely empty
        if mongo_db.users.count_documents({}) == 0 and os.path.exists(LEGACY_JSON):
            try:
                with open(LEGACY_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for uid, udata in data.items():
                    mongo_db.users.update_one(
                        {"_id": str(uid)},
                        {"$setOnInsert": {
                            "user_id": str(uid),
                            "joined_at": udata.get('joined', datetime.now().isoformat()),
                            "banned": bool(udata.get('banned'))
                        }},
                        upsert=True
                    )
                logger.info("Migrated legacy users.json to MongoDB")
            except Exception as e:
                logger.error(f"Error migrating users.json to MongoDB: {e}")
                
    except Exception as e:
        logger.critical(f"FATAL: Failed to connect to MongoDB: {e}")
        raise

# Ensure MongoDB is initialized
init_db()

# ─── USER MANAGEMENT (100% MONGODB) ────────────────────────

def ensure_user(user_id, first_name=None, last_name=None, username=None):
    uid = str(user_id)
    now_str = datetime.now().isoformat()
    
    update_data = {}
    if first_name is not None:
        update_data["first_name"] = first_name
    if last_name is not None:
        update_data["last_name"] = last_name
    if username is not None:
        update_data["username"] = username
        
    cached = _cache_get(uid)
    if cached:
        needs_update = False
        for k, v in update_data.items():
            if cached.get(k) != v:
                needs_update = True
                cached[k] = v
        if needs_update:
            try:
                mongo_db.users.update_one({"_id": uid}, {"$set": update_data})
                _cache_set(uid, cached)
            except Exception as e:
                logger.error(f"Error updating user in mongo: {e}")
        return False

    existing = mongo_db.users.find_one({"_id": uid})
    if existing:
        existing.pop("_id", None)
        if update_data:
            existing.update(update_data)
            try:
                mongo_db.users.update_one({"_id": uid}, {"$set": update_data})
            except Exception as e:
                logger.error(f"Error updating user in mongo: {e}")
        _cache_set(uid, existing)
        return False
        
    user_doc = {
        "_id": uid,
        "user_id": uid,
        "first_name": first_name or "",
        "last_name": last_name or "",
        "username": username or "",
        "joined_at": now_str,
        "banned": False,
        "channel_verified": False,
        "downloads_count": 0
    }
    try:
        mongo_db.users.insert_one(user_doc)
        doc_copy = dict(user_doc)
        doc_copy.pop("_id", None)
        _cache_set(uid, doc_copy)
        return True
    except Exception as e:
        logger.debug(f"User {uid} already exists or insert error: {e}")
        return False

def mark_channel_verified(user_id) -> bool:
    uid = str(user_id)
    u = _cache_get(uid) or mongo_db.users.find_one({"_id": uid})
    if u and not u.get("channel_verified"):
        mongo_db.users.update_one({"_id": uid}, {"$set": {"channel_verified": True}})
        mongo_db.bot_settings.update_one({"_id": "channel_stats"}, {"$inc": {"verified_joins": 1}}, upsert=True)
        if u:
            u["channel_verified"] = True
            _cache_set(uid, u)
        return True
    return False

def get_channel_verified_count() -> int:
    doc = mongo_db.bot_settings.find_one({"_id": "channel_stats"})
    return int(doc.get("verified_joins", 0)) if doc else 0

def get_channel_config(default_id="-1002894475319", default_link="https://t.me/+Vq7Ha3AVq4JjNTNl"):
    try:
        doc = mongo_db.bot_settings.find_one({"_id": "channel_config"})
        if doc:
            return {
                "channel_id": str(doc.get("channel_id") or default_id),
                "channel_link": str(doc.get("channel_link") or default_link),
                "force_check": bool(doc.get("force_check", True))
            }
    except Exception as e:
        logger.error(f"Error getting channel config: {e}")
    return {
        "channel_id": default_id,
        "channel_link": default_link,
        "force_check": True
    }

def set_channel_config(channel_id: str, channel_link: str, force_check: bool = None):
    try:
        update_data = {
            "channel_id": str(channel_id).strip(),
            "channel_link": str(channel_link).strip(),
            "updated_at": datetime.now().isoformat()
        }
        if force_check is not None:
            update_data["force_check"] = bool(force_check)
        mongo_db.bot_settings.update_one(
            {"_id": "channel_config"},
            {"$set": update_data},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error setting channel config: {e}")
        return False

def get_user(user_id):
    uid = str(user_id)
    cached = _cache_get(uid)
    if cached is not None:
        return cached
    doc = mongo_db.users.find_one({"_id": uid})
    if doc:
        doc.pop("_id", None)
        _cache_set(uid, doc)
        return dict(doc)
    return None

def ban_user(user_id):
    uid = str(user_id)
    ensure_user(uid)
    mongo_db.users.update_one({"_id": uid}, {"$set": {"banned": True}})
    _cache_invalidate(uid)

def unban_user(user_id):
    uid = str(user_id)
    mongo_db.users.update_one({"_id": uid}, {"$set": {"banned": False}})
    _cache_invalidate(uid)

def is_banned(user_id):
    u = get_user(user_id)
    return bool(u.get('banned')) if u else False

def all_users():
    users = {}
    for doc in mongo_db.users.find():
        uid = doc.get("user_id", str(doc.get("_id")))
        doc.pop("_id", None)
        users[uid] = doc
    return users

# ─── PDF DOWNLOAD AUDIT & STATS ────────────────────────────

def record_pdf_download(user_id: str, name: str, is_admin_user: bool, is_owner_user: bool, method: str = "mobile", password: str = None) -> bool:
    """Logs each PDF downloaded: whether owner, admin, or regular user."""
    try:
        uid = str(user_id)
        now_str = datetime.now().isoformat()
        role = "owner" if is_owner_user else ("admin" if is_admin_user else "user")
        
        mongo_db.pdf_downloads.insert_one({
            "user_id": uid,
            "name": name,
            "role": role,
            "method": method,
            "password": password,
            "downloaded_at": now_str
        })
        mongo_db.users.update_one({"_id": uid}, {"$inc": {"downloads_count": 1}}, upsert=True)
        _cache_invalidate(uid)
        return True
    except Exception as e:
        logger.error(f"Error recording pdf download: {e}")
        return False

def get_download_stats() -> dict:
    """Returns total downloads broken down by owner, admin, users, and overall."""
    try:
        total = mongo_db.pdf_downloads.count_documents({})
        owner_dl = mongo_db.pdf_downloads.count_documents({"role": "owner"})
        admin_dl = mongo_db.pdf_downloads.count_documents({"role": "admin"})
        user_dl = mongo_db.pdf_downloads.count_documents({"role": "user"})
        return {
            "total": total,
            "owner": owner_dl,
            "admin": admin_dl,
            "user": user_dl
        }
    except Exception as e:
        logger.error(f"Error getting download stats: {e}")
        return {"total": 0, "owner": 0, "admin": 0, "user": 0}

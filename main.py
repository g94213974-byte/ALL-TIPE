#!/usr/bin/env python3
"""
UNIFIED TELEGRAM BOT - COMPLETELY FIXED VERSION (v3)
Fixes:
- Token no longer logged
- Single auto-reply system (no duplicate handlers)
- Proper indentation throughout
- Typing effect ON by default
- Polling timeout prevented
- All Python 3.11 f-string backslash issues fixed
- Seen delay now properly delays ReadHistory (single tick -> typing -> double tick -> reply)
- All back buttons fixed in every menu
- Memory leak fix with periodic cleanup
- Ping/Heartbeat system for Render sleep prevention
- Web server for health check
- Auto-reconnect polling
- Account auto-restart on failure
"""

import os, sys, json, asyncio, random, logging, time, uuid
from datetime import datetime
from typing import Optional, Dict, List, Any
from collections import defaultdict
from pathlib import Path

# ═══════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# ENVIRONMENT VARIABLES
# ═══════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
DEFAULT_API_ID = int(os.environ.get("API_ID", "0"))
DEFAULT_API_HASH = os.environ.get("API_HASH", "")
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is not set!")
    sys.exit(1)
if not OWNER_ID:
    logger.error("OWNER_ID environment variable is not set!")
    sys.exit(1)
if not DEFAULT_API_ID or not DEFAULT_API_HASH:
    logger.error("API_ID or API_HASH environment variables are not set!")
    sys.exit(1)

# ═══════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════
try:
    import socks
except ImportError:
    socks = None
    logger.warning("socks not installed, proxy support disabled")

try:
    from aiohttp import web
except ImportError:
    web = None
    logger.warning("aiohttp not installed, web server disabled")

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, SessionPasswordNeededError,
    PhoneCodeInvalidError, PhoneCodeExpiredError,
    AuthKeyUnregisteredError, UserDeactivatedError
)
from telethon.tl.functions.messages import GetDialogsRequest, ReadHistoryRequest
from telethon.tl.types import InputPeerEmpty
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ═══════════════════════════════════════════
# DIRECTORIES
# ═══════════════════════════════════════════
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PAYMENT_SS_DIR = BASE_DIR / "payment_screenshots"
for d in [DATA_DIR, PAYMENT_SS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
REPLIES_FILE = DATA_DIR / "replies.json"
BANNED_FILE = DATA_DIR / "banned_accounts.json"
SPAM_MSG_FILE = DATA_DIR / "spam_messages.json"

# ═══════════════════════════════════════════
# GLOBAL STATE
# ═══════════════════════════════════════════
active_accounts = []
account_clients = {}
account_stats = defaultdict(lambda: {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False})
account_stop_flags = {}
account_spam_tasks = {}
account_spam_active = {}
account_spam_messages = {}
account_keepalive_tasks = {}
customer_count = {}
customer_payment_photos = {}
processing_users = set()
admins = [OWNER_ID]

auto_reply_enabled = True
group_spam_enabled = True
logout_notification_enabled = True

_settings_cache = {}
start_time = time.time()

DEFAULT_SETTINGS = {
    'auto_reply_enabled': True,
    'group_spam_enabled': True,
    'welcome_enabled': True,
    'block_photo_enabled': True,
    'typing_enabled': True,
    'typing_duration': 2,
    'seen_delay': 1,
    'default_reply_enabled': False,
    'default_reply_text': '',
    'spam_speed': 'medium',
    'spam_batch_size': 5,
    'spam_batch_delay': 3,
    'spam_cycle_wait': 30,
    'flood_slow_mode': True,
    'spam_message': '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘',
    'ignored_messages': '',
    'price_list_text': '🔥 10 MIN VC -> Rs.99\n🔥 20 MIN VC -> Rs.119',
    'upi_id': '',
    'paytm_num': '',
    'welcome_message': '🔥 Welcome Baby! 🔥\n\n10 MIN VC -> Rs.99\n20 MIN VC -> Rs.119',
    'welcome_message2': '🛒 How to order?\n\n1. Pay via UPI/PayTm\n2. Send screenshot\n3. Enjoy VC call! 💋',
    'qr_code_path': '',
    'price_list_image': '',
    'welcome_image': '',
    'welcome_image2': '',
    'payment_keyword_reply': 'Scan & Pay baby 😘🔥',
    'media_keyword_reply': 'Payment first baby 😘🔥',
    'offline_keyword_reply': 'Online only baby 😊',
    'greeting_replies': ['Hi baby, ready! 🔥', 'Hey baby! 😘', 'Hello! What you need? 🔥'],
    'default_replies': ['Ready baby! Pay karo! 🔥', 'Main ready hoon! 😘', 'Service ready! 💯'],
}

# ═══════════════════════════════════════════
# FILE HELPERS
# ═══════════════════════════════════════════
def load_json(fp, default=None):
    try:
        fp = Path(fp)
        if fp.exists() and fp.stat().st_size > 0:
            with open(fp, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"load_json error {fp}: {e}")
    return default if default is not None else {}

def save_json(fp, data):
    try:
        fp = Path(fp)
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"save_json error {fp}: {e}")
        return False

def get_setting(key, default=None):
    global _settings_cache
    if not _settings_cache:
        _load_settings()
    return _settings_cache.get(key, default if default is not None else DEFAULT_SETTINGS.get(key))

def set_setting(key, value):
    global _settings_cache
    if not _settings_cache:
        _load_settings()
    _settings_cache[key] = value
    save_json(SETTINGS_FILE, _settings_cache)

def _load_settings():
    global _settings_cache
    try:
        if SETTINGS_FILE.exists() and SETTINGS_FILE.stat().st_size > 0:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                _settings_cache = json.load(f)
        else:
            _settings_cache = {}
    except Exception as e:
        logger.error(f"Settings load error: {e}")
        _settings_cache = {}
    for k, v in DEFAULT_SETTINGS.items():
        if k not in _settings_cache:
            _settings_cache[k] = v
    save_json(SETTINGS_FILE, _settings_cache)

_replies_cache = []

def load_replies():
    global _replies_cache
    if not _replies_cache:
        try:
            if REPLIES_FILE.exists() and REPLIES_FILE.stat().st_size > 0:
                with open(REPLIES_FILE, 'r', encoding='utf-8') as f:
                    _replies_cache = json.load(f)
            else:
                _replies_cache = []
        except Exception as e:
            logger.error(f"Replies load error: {e}")
            _replies_cache = []
    return _replies_cache

def save_replies():
    global _replies_cache
    save_json(REPLIES_FILE, _replies_cache)

def add_reply(keyword, reply, match_type="contains"):
    global _replies_cache
    if not _replies_cache:
        load_replies()
    rid = max([x.get('id', 0) for x in _replies_cache], default=0) + 1
    _replies_cache.append({'id': rid, 'keyword': keyword, 'reply': reply, 'type': match_type, 'created_at': datetime.now().isoformat()})
    save_replies()
    return rid

def delete_reply(rid):
    global _replies_cache
    if not _replies_cache:
        load_replies()
    old_len = len(_replies_cache)
    _replies_cache = [x for x in _replies_cache if x['id'] != rid]
    if len(_replies_cache) != old_len:
        save_replies()
        return True
    return False

def load_accounts():
    return load_json(ACCOUNTS_FILE, {'accounts': []})

def save_accounts(data):
    save_json(ACCOUNTS_FILE, data)

def load_spam_messages():
    return load_json(SPAM_MSG_FILE, [])

def save_spam_messages(msgs):
    save_json(SPAM_MSG_FILE, msgs)

NL = "\n"  # For f-string usage in Python 3.11

# ═══════════════════════════════════════════
# MEMORY CLEANUP
# ═══════════════════════════════════════════
async def cleanup_memory():
    """Periodic memory cleanup to prevent leak on Render"""
    global customer_count, customer_payment_photos, processing_users
    
    if len(processing_users) > 200:
        processing_users.clear()
        logger.info("🧹 processing_users cleared")
    
    if len(customer_count) > 2000:
        customer_count.clear()
        logger.info("🧹 customer_count cleared")
    
    if len(customer_payment_photos) > 500:
        customer_payment_photos.clear()
        logger.info("🧹 customer_payment_photos cleared")
    
    # Clean old temp files
    try:
        now = time.time()
        for f in PAYMENT_SS_DIR.glob("*.jpg"):
            if now - f.stat().st_mtime > 86400:  # 24 hours
                f.unlink(missing_ok=True)
    except:
        pass

async def periodic_cleanup():
    """Run memory cleanup every 30 minutes"""
    while True:
        await asyncio.sleep(1800)  # 30 min
        try:
            await cleanup_memory()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# ═══════════════════════════════════════════
# PING / HEARTBEAT SYSTEM (PREVENT RENDER SLEEP)
# ═══════════════════════════════════════════
async def ping_loop():
    """Send periodic ping to keep bot alive (25s interval for Render)"""
    while True:
        try:
            # Ping Telegram Bot API
            bot = Bot(token=BOT_TOKEN)
            await bot.get_me()
            
            # Ping all active Telethon clients
            for acc_id, client in list(account_clients.items()):
                try:
                    await asyncio.wait_for(client.get_me(timeout=3), timeout=5)
                except asyncio.TimeoutError:
                    logger.warning(f"⏰ Ping timeout for {acc_id}")
                except Exception:
                    pass
            
            logger.debug("🏓 Heartbeat ping sent")
        except Exception as e:
            logger.debug(f"Ping error (non-critical): {e}")
        
        await asyncio.sleep(25)  # Render free tier sleeps at 30s inactivity

# ═══════════════════════════════════════════
# WEB SERVER FOR HEALTH CHECK (RENDER)
# ═══════════════════════════════════════════
async def web_server():
    """HTTP server for Render health checks"""
    if web is None:
        logger.warning("⚠️ aiohttp not installed, skipping web server")
        return
    
    app = web.Application()
    
    async def health_handler(request):
        return web.Response(text="OK", status=200)
    
    async def stats_handler(request):
        alive = sum(1 for a in active_accounts if a['id'] in account_clients)
        spam_run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        return web.json_response({
            "status": "running",
            "uptime": int(time.time() - start_time),
            "active_accounts": alive,
            "total_accounts": len(active_accounts),
            "auto_reply": auto_reply_enabled,
            "group_spam": group_spam_enabled,
            "spam_running": spam_run,
            "ar_on": sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('running', False))
        })
    
    app.router.add_get('/', health_handler)
    app.router.add_get('/health', health_handler)
    app.router.add_get('/stats', stats_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Web server running on 0.0.0.0:{PORT}")

# ═══════════════════════════════════════════
# TYPING EFFECT + SEEN DELAY (FIXED)
# ═══════════════════════════════════════════
async def simulate_reply_flow(client, chat_id, event, message_text):
    """
    Simulates: single tick (no action) -> seen delay -> typing -> double tick -> reply
    """
    seen_delay = int(get_setting('seen_delay', 1))
    typing_enabled = get_setting('typing_enabled', True)
    typing_duration = int(get_setting('typing_duration', 2))

    # Step 1: Wait for seen delay (message stays single tick)
    if seen_delay > 0:
        actual_seen_delay = min(seen_delay, 3)  # cap at 3s max
        await asyncio.sleep(actual_seen_delay)

    # Step 2: Mark as read (double tick)
    try:
        input_chat = await event.get_input_chat()
        await client(ReadHistoryRequest(peer=input_chat, max_id=event.message.id))
    except Exception as e:
        logger.debug(f"ReadHistory error: {e}")

    # Step 3: Show typing indicator
    if typing_enabled and typing_duration > 0:
        actual_typing = min(typing_duration, 2)  # cap at 2s
        try:
            async with client.action(chat_id, 'typing'):
                await asyncio.sleep(actual_typing)
        except Exception as e:
            logger.debug(f"Typing error: {e}")

    # Step 4: Send the reply
    await client.send_message(chat_id, message_text)

# ═══════════════════════════════════════════
# AUTO REPLY - CORE
# ═══════════════════════════════════════════
async def process_auto_reply_fast(event, client, acc, uid):
    chat_id = event.chat_id
    message_text = event.message.text or ""
    if uid not in customer_count:
        customer_count[uid] = 0
    prev_count = customer_count[uid]
    
    # Block photo senders
    if event.message.photo or (event.message.document and event.message.document.mime_type and 'image' in event.message.document.mime_type):
        if get_setting('block_photo_enabled', True):
            asyncio.create_task(block_user_and_delete_photos(event, client, uid))
        else:
            asyncio.create_task(handle_payment_screenshot(event, client, uid))
        return
    
    if not message_text.strip():
        return
    
    msg_lower = message_text.lower().strip()
    
    # Welcome message on first contact
    if prev_count == 0 and get_setting('welcome_enabled', True):
        await send_dual_welcome(client, chat_id)
        customer_count[uid] = prev_count + 1
        return
    
    # Check ignored messages
    ignored = get_setting('ignored_messages', '')
    if ignored:
        for line in ignored.split(NL):
            if line.strip().lower() == msg_lower:
                customer_count[uid] = prev_count + 1
                return
    
    reply_text = None
    
    # Check keyword replies
    for reply_entry in load_replies():
        keyword = reply_entry['keyword'].lower().strip()
        if reply_entry['type'] == 'exact' and msg_lower == keyword:
            reply_text = reply_entry['reply']
            break
        elif reply_entry['type'] == 'contains' and keyword in msg_lower:
            reply_text = reply_entry['reply']
            break
    
    if reply_text:
        await simulate_reply_flow(client, chat_id, event, reply_text)
        customer_count[uid] = prev_count + 1
        return
    
    # Payment keywords
    payment_keywords = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'send', 'bhejo', 'screenshot', 'method', 'transfer', 'rupees', 'rs', 'money']
    if any(kw in msg_lower for kw in payment_keywords):
        await send_payment_info(client, chat_id, event)
        customer_count[uid] = prev_count + 1
        return
    
    # Media keywords
    media_keywords = ['pic', 'photo', 'image', 'nude', 'naked', 'dikhao', 'show', 'nangi', 'boob', 'mms']
    if any(kw in msg_lower for kw in media_keywords):
        await simulate_reply_flow(client, chat_id, event, get_setting('media_keyword_reply', 'Payment first baby 😘🔥'))
        customer_count[uid] = prev_count + 1
        return
    
    # Service keywords
    service_keywords = ['service', 'chahiye', 'kharid', 'demo', 'video', 'call', 'vc', 'price', 'rate']
    if any(kw in msg_lower for kw in service_keywords):
        price_text = get_setting('price_list_text', "🔥 10 MIN VC -> Rs.99\n🔥 20 MIN VC -> Rs.119")
        price_image = get_setting('price_list_image', '')
        if price_image and Path(price_image).exists():
            try:
                await client.send_file(chat_id, price_image, caption=price_text)
            except Exception as e:
                logger.debug(f"Price image send error: {e}")
                await simulate_reply_flow(client, chat_id, event, price_text)
        else:
            await simulate_reply_flow(client, chat_id, event, price_text)
        await asyncio.sleep(0.3)
        replies = ["How many minutes? 🔥", "Pay and enjoy! 😘", "Tell me your choice 💋"]
        await simulate_reply_flow(client, chat_id, event, random.choice(replies))
        customer_count[uid] = prev_count + 1
        return
    
    # Offline keywords
    offline_keywords = ['real', 'meet', 'aao', 'ghar', 'location', 'offline']
    if any(kw in msg_lower for kw in offline_keywords):
        await simulate_reply_flow(client, chat_id, event, get_setting('offline_keyword_reply', 'Online only baby 😊'))
        customer_count[uid] = prev_count + 1
        return
    
    # Greetings
    greeting_keywords = ['hi', 'hello', 'hey', 'hii', 'hy', 'hlo']
    if any(w in msg_lower for w in greeting_keywords):
        greetings = get_setting('greeting_replies', ['Hi baby, ready! 🔥', 'Hey baby! 😘', 'Hello! What you need? 🔥'])
        await simulate_reply_flow(client, chat_id, event, random.choice(greetings))
        customer_count[uid] = prev_count + 1
        return
    
    # Default reply
    if get_setting('default_reply_enabled', False):
        reply = get_setting('default_reply_text', '')
        if reply:
            await simulate_reply_flow(client, chat_id, event, reply)
    else:
        defaults = get_setting('default_replies', ['Ready baby! Pay karo! 🔥', 'Main ready hoon! 😘', 'Service ready! 💯'])
        await simulate_reply_flow(client, chat_id, event, random.choice(defaults))
    customer_count[uid] = prev_count + 1

async def send_dual_welcome(client, chat_id):
    wm1 = get_setting('welcome_message', '🔥 Welcome Baby! 🔥')
    wi1 = get_setting('welcome_image', '')
    if wi1 and Path(wi1).exists():
        try:
            await client.send_file(chat_id, wi1, caption=wm1)
        except Exception as e:
            logger.debug(f"Welcome image1 error: {e}")
            await client.send_message(chat_id, wm1)
    else:
        await client.send_message(chat_id, wm1)
    await asyncio.sleep(1.5)
    wm2 = get_setting('welcome_message2', '🛒 How to order?')
    wi2 = get_setting('welcome_image2', '')
    if wi2 and Path(wi2).exists():
        try:
            await client.send_file(chat_id, wi2, caption=wm2)
        except Exception as e:
            logger.debug(f"Welcome image2 error: {e}")
            await client.send_message(chat_id, wm2)
    else:
        await client.send_message(chat_id, wm2)

async def send_payment_info(client, chat_id, event):
    upi = get_setting('upi_id', '')
    paytm = get_setting('paytm_num', '')
    qr_path = get_setting('qr_code_path', '')
    payment_msg = "**💰 Payment 💰**" + NL + NL
    if upi:
        payment_msg += "📱 UPI: " + upi + NL
    if paytm:
        payment_msg += "💳 PayTm: " + paytm + NL
    payment_msg += NL + get_setting('payment_keyword_reply', 'Scan & Pay baby 😘🔥')
    if qr_path:
        try:
            if qr_path.startswith('http://') or qr_path.startswith('https://'):
                payment_msg = "**💰 Payment 💰**" + NL + NL
                if upi:
                    payment_msg += "📱 UPI: " + upi + NL
                if paytm:
                    payment_msg += "💳 PayTm: " + paytm + NL
                payment_msg += NL + "📷 QR: " + qr_path + NL + NL + get_setting('payment_keyword_reply', 'Scan & Pay baby 😘🔥')
                await simulate_reply_flow(client, chat_id, event, payment_msg)
            elif Path(qr_path).exists():
                await client.send_file(chat_id, qr_path, caption=payment_msg)
            else:
                await simulate_reply_flow(client, chat_id, event, payment_msg)
        except Exception as e:
            logger.debug(f"QR send error: {e}")
            await simulate_reply_flow(client, chat_id, event, payment_msg)
    else:
        await simulate_reply_flow(client, chat_id, event, payment_msg)

async def block_user_and_delete_photos(event, client, uid):
    try:
        input_chat = await event.get_input_chat()
        try:
            await client.delete_messages(input_chat, [event.message.id], revoke=True)
        except Exception as e:
            logger.debug(f"Delete msg error: {e}")
        try:
            async for msg in client.iter_messages(input_chat, limit=100):
                try:
                    await client.delete_messages(input_chat, [msg.id], revoke=True)
                except Exception as e:
                    pass
        except Exception as e:
            logger.debug(f"Iter messages error: {e}")
        try:
            await client.delete_dialog(input_chat)
        except Exception as e:
            logger.debug(f"Delete dialog error: {e}")
        await asyncio.sleep(1)
        try:
            await client(BlockRequest(id=uid))
        except Exception as e:
            logger.debug(f"Block error: {e}")
        try:
            await client(DeleteContactsRequest(id=[uid]))
        except Exception as e:
            logger.debug(f"Delete contact error: {e}")
    except Exception as e:
        logger.error(f"Block failed for {uid}: {e}")

async def handle_payment_screenshot(event, client, uid):
    try:
        if event.message.photo:
            photo = event.message.photo[-1]
        else:
            photo = event.message.document
        file_path = PAYMENT_SS_DIR / f"{uid}_{event.message.id}.jpg"
        await photo.download_async(str(file_path))
        customer_payment_photos[uid] = str(file_path)
        sender_name = getattr(event.sender, 'first_name', 'Unknown')
        await event.respond("Payment screenshot received! Admin will contact you soon")
        try:
            await client.send_message(OWNER_ID, f"✅ PAYMENT RECEIVED!{NL}👤 Name: {sender_name}{NL}🆔 ID: {uid}")
            await client.send_file(OWNER_ID, str(file_path))
        except Exception as e:
            logger.error(f"Forward to owner error: {e}")
        customer_count[uid] = -2
    except Exception as e:
        logger.error(f"Payment screenshot handling failed: {e}")

# ═══════════════════════════════════════════
# TELEGRAM CLIENT EVENT HANDLER (SINGLE)
# ═══════════════════════════════════════════
def register_auto_reply(client, acc):
    """Register auto-reply handler for an account - ONLY called once per account"""
    @client.on(events.NewMessage(incoming=True))
    async def auto_reply_handler(event):
        try:
            if not auto_reply_enabled:
                return
            if not account_stats.get(acc['id'], {}).get('running', False):
                return
            if not event.is_private:
                return
            sender = await event.get_sender()
            if not sender:
                return
            uid = sender.id
            if uid == OWNER_ID or uid in admins:
                return
            if not acc.get('enabled', True):
                return
            if uid in processing_users:
                return
            processing_users.add(uid)
            try:
                await process_auto_reply_fast(event, client, acc, uid)
            finally:
                processing_users.discard(uid)
        except Exception as e:
            logger.error(f"Auto-reply error: {e}", exc_info=True)
    return auto_reply_handler

# ═══════════════════════════════════════════
# ACCOUNT MANAGEMENT
# ═══════════════════════════════════════════
async def start_account(acc):
    try:
        proxy_config = acc.get('proxy')
        proxy = None
        if proxy_config and proxy_config.get('addr') and socks:
            proxy = (socks.SOCKS5, proxy_config.get('addr', ''), proxy_config.get('port', 1080),
                     proxy_config.get('rdns', True), proxy_config.get('username', ''), proxy_config.get('password', ''))
        
        client = TelegramClient(
            StringSession(acc['session']),
            acc.get('api_id', DEFAULT_API_ID),
            acc.get('api_hash', DEFAULT_API_HASH),
            proxy=proxy,
            sequential_updates=True,
            receive_updates=True
        )
        await client.start()
        me = await client.get_me()
        logger.info(f"✅ Account started: {me.first_name} ({me.id})")
        
        acc_id = acc['id']
        custom_msgs = load_spam_messages()
        if custom_msgs:
            account_spam_messages[acc_id] = [m['text'] for m in custom_msgs]
        else:
            base_msg = get_setting('spam_message', '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')
            account_spam_messages[acc_id] = [
                base_msg, f"{base_msg} 💋", f"{base_msg} 🔥", f"{base_msg} 💖",
                f"🔥 {base_msg}", f"💋 {base_msg}", f"✨ {base_msg} 😘",
                f"{base_msg} 👑", f"✅ {base_msg} ✅", f"👉 {base_msg} 👈"
            ]
        
        # Register auto-reply (ONLY here)
        register_auto_reply(client, acc)
        
        # Start keepalive
        account_keepalive_tasks[acc_id] = asyncio.create_task(keep_alive_loop(acc_id, client))
        
        return client
    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
        logger.warning(f"❌ Account banned: {acc.get('name', 'Unknown')}")
        await send_logout_notification(acc, str(e)[:50])
        await handle_banned(acc)
        return None
    except Exception as e:
        logger.error(f"Failed to start account {acc.get('name', 'Unknown')}: {e}")
        return None

async def keep_alive_loop(acc_id, client, interval=55):
    """Keep account session alive - shorter interval to prevent timeout"""
    acc = None
    for a in active_accounts:
        if a['id'] == acc_id:
            acc = a
            break
    name = acc.get('name', acc_id) if acc else acc_id
    logger.info(f"[KA] Started for {name}")
    
    while not account_stop_flags.get(acc_id, False):
        try:
            me = await client.get_me(timeout=5)
            if not me:
                raise AuthKeyUnregisteredError("Session returned None")
        except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
            logger.warning(f"[KA] {name} - SESSION DEAD: {e}")
            real_acc = None
            for a in active_accounts:
                if a['id'] == acc_id:
                    real_acc = a
                    break
            if real_acc:
                await send_logout_notification(real_acc, str(e)[:50])
                await handle_banned(real_acc)
            return
        except asyncio.TimeoutError:
            logger.warning(f"[KA] {name} - Timeout on get_me")
        except Exception as e:
            logger.debug(f"[KA] {name} - {e}")
        
        for _ in range(interval):
            if account_stop_flags.get(acc_id, False):
                break
            await asyncio.sleep(1)

async def send_logout_notification(acc, reason="Unknown"):
    if not logout_notification_enabled:
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        msg_parts = [
            "⚠️ **ACCOUNT LOGOUT!** ⚠️",
            f"👤 {acc.get('name','?')}",
            f"📱 {acc.get('phone','N/A')}",
            f"❌ {reason}",
            "🔄 Replacing with backup..."
        ]
        await bot.send_message(chat_id=OWNER_ID, text=NL.join(msg_parts))
    except Exception as e:
        logger.error(f"Logout notification error: {e}")

async def handle_banned(acc):
    acc_id = acc['id']
    name = acc.get('name', 'Unknown')
    logger.warning(f"Ban processing: {name}")
    
    banned = load_json(BANNED_FILE, [])
    if not any(b['id'] == acc_id for b in banned):
        banned.append({'id': acc_id, 'name': name, 'phone': acc.get('phone', 'N/A'), 'banned_at': datetime.now().isoformat()})
        save_json(BANNED_FILE, banned)
    
    if acc_id in account_keepalive_tasks:
        if not account_keepalive_tasks[acc_id].done():
            account_keepalive_tasks[acc_id].cancel()
            try:
                await account_keepalive_tasks[acc_id]
            except:
                pass
        del account_keepalive_tasks[acc_id]
    
    if acc_id in account_spam_tasks:
        if not account_spam_tasks[acc_id].done():
            account_spam_tasks[acc_id].cancel()
            try:
                await account_spam_tasks[acc_id]
            except:
                pass
        del account_spam_tasks[acc_id]
    
    if acc_id in account_clients:
        try:
            await account_clients[acc_id].disconnect()
        except:
            pass
        del account_clients[acc_id]
    
    active_accounts[:] = [a for a in active_accounts if a['id'] != acc_id]
    account_stop_flags[acc_id] = True
    for d in [account_spam_active, account_stats]:
        if acc_id in d:
            del d[acc_id]
    
    data = load_accounts()
    data['accounts'] = [a for a in data.get('accounts', []) if a['id'] != acc_id]
    save_accounts(data)
    
    all_accounts_data = data.get('accounts', [])
    backups = [a for a in all_accounts_data if a.get('is_backup', False)]
    if backups:
        backup = backups[0]
        backup_copy = dict(backup)
        backup_copy['is_backup'] = False
        backup_copy['enabled'] = True
        all_accounts_data = [a for a in all_accounts_data if a['id'] != backup['id']]
        all_accounts_data.append(backup_copy)
        save_accounts({'accounts': all_accounts_data})
        client = await start_account(backup_copy)
        if client:
            active_accounts.append(backup_copy)
            account_clients[backup_copy['id']] = client
            account_stats[backup_copy['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
            account_stop_flags[backup_copy['id']] = False
            account_spam_active[backup_copy['id']] = False
            logger.info(f"✅ Backup activated: {backup.get('name','?')}")

# ═══════════════════════════════════════════
# GROUP SPAM
# ═══════════════════════════════════════════
async def get_user_groups(client):
    try:
        dialogs = await client(GetDialogsRequest(offset_date=None, offset_id=0, offset_peer=InputPeerEmpty(), limit=200, hash=0))
        groups = []
        for dialog in dialogs.dialogs:
            try:
                entity = await client.get_entity(dialog.peer)
                if hasattr(entity, 'title'):
                    is_group = (hasattr(entity, 'megagroup') and entity.megagroup) or \
                               (hasattr(entity, 'broadcast') and not entity.broadcast) or \
                               (not hasattr(entity, 'broadcast') and not hasattr(entity, 'megagroup'))
                    if is_group:
                        groups.append(entity)
            except Exception as e:
                pass
        return groups
    except Exception as e:
        logger.error(f"Failed to get groups: {e}")
        return []

async def spam_account(acc):
    acc_id = acc['id']
    acc_name = acc.get('name', acc_id)
    account_stop_flags[acc_id] = False
    account_stats[acc_id]['spam_running'] = True
    account_spam_active[acc_id] = True
    logger.info(f"🔫 Starting spam for: {acc_name}")
    
    try:
        proxy_config = acc.get('proxy')
        proxy = None
        if proxy_config and proxy_config.get('addr') and socks:
            proxy = (socks.SOCKS5, proxy_config.get('addr', ''), proxy_config.get('port', 1080),
                     proxy_config.get('rdns', True), proxy_config.get('username', ''), proxy_config.get('password', ''))
        
        client = TelegramClient(StringSession(acc['session']), acc.get('api_id', DEFAULT_API_ID),
                                acc.get('api_hash', DEFAULT_API_HASH), proxy=proxy, receive_updates=False)
        await client.start()
        groups = await get_user_groups(client)
        if not groups:
            logger.warning(f"No groups for {acc_name}")
            account_stats[acc_id]['spam_running'] = False
            account_spam_active[acc_id] = False
            return
        
        logger.info(f"📯 Spamming {len(groups)} groups with {acc_name}")
        
        speed = get_setting('spam_speed', 'medium')
        configs = {
            'super_fast': {'batch': 999, 'delay': 0, 'cycle': 0, 'min': 0, 'max': 1.5},
            'fast': {'batch': 999, 'delay': 0, 'cycle': 5, 'min': 0.5, 'max': 2},
            'medium': {'batch': 5, 'delay': 2, 'cycle': 15, 'min': 2, 'max': 4},
            'slow': {'batch': 3, 'delay': 5, 'cycle': 30, 'min': 5, 'max': 8},
            'custom': {'batch': int(get_setting('spam_batch_size', 6)), 'delay': int(get_setting('spam_batch_delay', 3)),
                       'cycle': int(get_setting('spam_cycle_wait', 30)), 'min': int(get_setting('spam_min_interval', 3)),
                       'max': int(get_setting('spam_max_interval', 6))}
        }
        cfg = configs.get(speed, configs['medium'])
        flood_slow = get_setting('flood_slow_mode', True)
        msgs = account_spam_messages.get(acc_id, [get_setting('spam_message', '...')])
        
        msg_idx = 0
        cycle = 0
        errors = 0
        max_b = min(cfg['batch'], len(groups))
        
        while not account_stop_flags.get(acc_id, False):
            if not group_spam_enabled or not account_spam_active.get(acc_id, True):
                await asyncio.sleep(3)
                continue
            
            for g in groups[:max_b]:
                if account_stop_flags.get(acc_id, False) or not account_spam_active.get(acc_id, True):
                    break
                try:
                    msg = msgs[msg_idx % len(msgs)]
                    await client.send_message(g, msg)
                    account_stats[acc_id]['spam_sent'] += 1
                    errors = 0
                    msg_idx += 1
                except FloodWaitError as e:
                    w = e.seconds
                    logger.warning(f"🌊 Flood {w}s on {acc_name}")
                    errors += 1
                    await asyncio.sleep(min(w, 30) if flood_slow else w)
                except Exception as e:
                    errors += 1
                    s = str(e).upper()
                    if 'AUTHKEY' in s or 'DEACTIVATED' in s:
                        await send_logout_notification(acc, s[:50])
                        await handle_banned(acc)
                        return
                    elif 'FLOOD' in s and flood_slow:
                        await asyncio.sleep(5)
                if cfg['max'] > 0:
                    await asyncio.sleep(random.uniform(cfg['min'], cfg['max']))
            
            if account_stop_flags.get(acc_id, False):
                break
            if cfg['delay'] > 0 and len(groups) > max_b:
                await asyncio.sleep(cfg['delay'])
            if errors > 10:
                await asyncio.sleep(60)
                errors = 0
            
            cycle += 1
            if cycle % 20 == 0:
                try:
                    await client.disconnect()
                    await asyncio.sleep(3)
                    client = TelegramClient(StringSession(acc['session']), acc.get('api_id', DEFAULT_API_ID),
                                            acc.get('api_hash', DEFAULT_API_HASH), proxy=proxy, receive_updates=False)
                    await client.start()
                    groups = await get_user_groups(client)
                    max_b = min(cfg['batch'], len(groups))
                except Exception as e:
                    logger.error(f"Reconnect error: {e}")
            
            if cfg['cycle'] > 0:
                for _ in range(cfg['cycle']):
                    if account_stop_flags.get(acc_id, False):
                        break
                    await asyncio.sleep(1)
    
    except asyncio.CancelledError:
        logger.info(f"Spam cancelled: {acc_name}")
    except Exception as e:
        if 'AuthKey' in str(e) or 'DEACTIVATED' in str(e):
            await send_logout_notification(acc, str(e)[:50])
            await handle_banned(acc)
        else:
            logger.error(f"Spam error {acc_name}: {e}")
    finally:
        account_stats[acc_id]['spam_running'] = False
        account_spam_active[acc_id] = False
        try:
            await client.disconnect()
        except:
            pass

def stop_spam(acc_id=None):
    if acc_id:
        account_stop_flags[acc_id] = True
        account_spam_active[acc_id] = False
        if acc_id in account_spam_tasks and not account_spam_tasks[acc_id].done():
            account_spam_tasks[acc_id].cancel()
        account_stats[acc_id]['spam_running'] = False
    else:
        for a in active_accounts:
            stop_spam(a['id'])

def start_spam(acc_id=None):
    targets = [a for a in active_accounts if a['id'] == acc_id] if acc_id else active_accounts
    for a in targets:
        if not account_stats.get(a['id'], {}).get('spam_running', False):
            account_spam_active[a['id']] = True
            account_stop_flags[a['id']] = False
            account_spam_tasks[a['id']] = asyncio.create_task(spam_account(a))

# ═══════════════════════════════════════════
# BOT UI - MAIN MENU
# ═══════════════════════════════════════════
def main_keyboard():
    ar = "🟢 ON" if auto_reply_enabled else "🔴 OFF"
    gs = "🟢 ON" if group_spam_enabled else "🔴 OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📨 Auto Reply ({ar})", callback_data="m_ar")],
        [InlineKeyboardButton(f"📯 Group Spam ({gs})", callback_data="m_gs")],
        [InlineKeyboardButton("👤 Accounts", callback_data="m_acc")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="m_set")],
        [InlineKeyboardButton("📊 Status", callback_data="m_stat")],
        [InlineKeyboardButton("🔐 Admin", callback_data="m_adm")],
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID and uid not in admins:
        await update.message.reply_text("❌ Unauthorized!")
        return
    await update.message.reply_text(
        "🤖 **HACKER AI CONTROL PANEL** 🤖" + NL + NL + "Select:",
        reply_markup=main_keyboard()
    )

# ═══════════════════════════════════════════
# BOT UI - CALLBACK HANDLER
# ═══════════════════════════════════════════
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, logout_notification_enabled
    
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data
    
    if uid != OWNER_ID and uid not in admins:
        await query.edit_message_text("❌ Access Denied!")
        return
    
    # ─── Main Menu ───
    if data == "main":
        await query.edit_message_text(
            "🤖 **HACKER AI CONTROL PANEL** 🤖" + NL + NL + "Select:",
            reply_markup=main_keyboard()
        )
        return
    
    # ─── Auto Reply Menu ───
    if data == "m_ar":
        rc = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('running', False))
        status = "🟢 ON" if auto_reply_enabled else "🔴 OFF"
        sd = int(get_setting('seen_delay', 1))
        td = int(get_setting('typing_duration', 2))
        te = "🟢 ON" if get_setting('typing_enabled', True) else "🔴 OFF"
        txt = f"📨 **AR** | {status}" + NL + f"👁️ Seen: {sd}s" + NL + f"⌨️ Type: {te} ({td}s)" + NL + f"🟢 {rc}/{len(active_accounts)}"
        kb = [
            [InlineKeyboardButton(f"{'🔴' if auto_reply_enabled else '🟢'} Toggle", callback_data="ar_t")],
            [InlineKeyboardButton("▶️ Start All", callback_data="ar_start"), InlineKeyboardButton("⏹️ Stop All", callback_data="ar_stop")],
            [InlineKeyboardButton("👁️ Seen Delay", callback_data="ar_sd")],
            [InlineKeyboardButton("⌨️ Typing Duration", callback_data="ar_td")],
            [InlineKeyboardButton(f"🔤 Typing {te}", callback_data="ar_te")],
            [InlineKeyboardButton("💬 Replies", callback_data="ar_rp")],
            [InlineKeyboardButton("🚫 Ignored Msgs", callback_data="ar_ig")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "ar_t":
        auto_reply_enabled = not auto_reply_enabled
        status = "ON" if auto_reply_enabled else "OFF"
        await query.edit_message_text(f"✅ AR {status}!")
        await asyncio.sleep(0.5)
        update.callback_query.data = "m_ar"
        await handle_callback(update, context)
        return
    
    if data == "ar_te":
        cur = get_setting('typing_enabled', True)
        set_setting('typing_enabled', not cur)
        status = "ON" if not cur else "OFF"
        await query.edit_message_text(f"✅ Typing {status}!")
        await asyncio.sleep(0.5)
        update.callback_query.data = "m_ar"
        await handle_callback(update, context)
        return
    
    if data == "ar_start":
        for a in active_accounts:
            if a['id'] in account_clients:
                account_stats[a['id']]['running'] = True
        await query.edit_message_text("✅ **AR Started!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    if data == "ar_stop":
        for a in active_accounts:
            account_stats[a['id']]['running'] = False
        await query.edit_message_text("⏹️ **AR Stopped!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    if data == "ar_sd":
        context.user_data['await'] = 'seen_delay'
        txt = f"👁️ Seen Delay{NL}Current: {get_setting('seen_delay',1)}s{NL}Enter (1-5):"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    if data == "ar_td":
        context.user_data['await'] = 'typing_duration'
        txt = f"⌨️ Typing Duration{NL}Current: {get_setting('typing_duration',2)}s{NL}Enter (1-5):"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    if data == "ar_ig":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "🚫 **Ignored**" + NL + "One per line:" + NL
        if cur:
            txt += "Current:" + NL + cur + NL
        txt += "Ex:" + NL + "thanks" + NL + "bye"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    if data == "ar_rp":
        replies = load_replies()
        pg = int(context.user_data.get('rp_pg', 0))
        pp = 5
        tp = max(1, (len(replies) + pp - 1) // pp)
        start = pg * pp
        end = start + pp
        pr = replies[start:end]
        txt = f"💬 **Replies** (P{pg+1}/{tp})" + NL + NL
        for r in pr:
            txt += f"#{r['id']} `{r['keyword'][:15]}`" + NL + f"➜ {r['reply'][:30]}..." + NL + NL
        kb = []
        nav = []
        if pg > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"rp_{pg-1}"))
        if pg < tp-1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"rp_{pg+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("➕ Add", callback_data="ar_a1")])
        kb.append([InlineKeyboardButton("🗑️ Delete", callback_data="ar_dl")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_ar")])
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data.startswith("rp_"):
        context.user_data['rp_pg'] = int(data.split('_')[1])
        update.callback_query.data = "ar_rp"
        await handle_callback(update, context)
        return
    
    if data == "ar_a1":
        context.user_data['await'] = 'rk'
        await query.edit_message_text("💬 **Add Reply**" + NL + NL + "Enter keyword:" + NL + "Ex: price", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
        return
    
    if data == "ar_dl":
        replies = load_replies()[:15]
        if not replies:
            await query.edit_message_text("No replies!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ #{r['id']} {r['keyword'][:12]}", callback_data=f"ard_{r['id']}")] for r in replies]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="ar_rp")])
        await query.edit_message_text("Select:", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data.startswith("ard_"):
        rid = int(data.split('_')[1])
        ok = delete_reply(rid)
        txt = "✅ Deleted!" if ok else "❌ Not found!"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
        return
    
    # ─── Group Spam Menu ───
    if data == "m_gs":
        run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        st = "🟢 ON" if group_spam_enabled else "🔴 OFF"
        spd = get_setting('spam_speed', 'medium')
        sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        txt = f"📯 **GS** | {st}" + NL + f"🏃 {run}/{len(active_accounts)}" + NL + f"📤 {sent}" + NL + f"⚡ {spd}"
        kb = [
            [InlineKeyboardButton(f"{'🔴' if group_spam_enabled else '🟢'} Toggle", callback_data="gs_t")],
            [InlineKeyboardButton("▶️ Start", callback_data="gs_on"), InlineKeyboardButton("⏹️ Stop", callback_data="gs_off")],
            [InlineKeyboardButton("👤 Per Account", callback_data="gs_sp")],
            [InlineKeyboardButton("⚡ Speed", callback_data="gs_spd")],
            [InlineKeyboardButton("💬 Messages", callback_data="gs_msg")],
            [InlineKeyboardButton("📊 Stats", callback_data="gs_st")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "gs_t":
        group_spam_enabled = not group_spam_enabled
        status = "ON" if group_spam_enabled else "OFF"
        await query.edit_message_text(f"✅ GS {status}!")
        await asyncio.sleep(0.5)
        update.callback_query.data = "m_gs"
        await handle_callback(update, context)
        return
    
    if data == "gs_on":
        start_spam()
        await query.edit_message_text("▶️ **Started!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
        return
    
    if data == "gs_off":
        stop_spam()
        await query.edit_message_text("⏹️ **Stopped!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
        return
    
    if data == "gs_sp":
        if not active_accounts:
            await query.edit_message_text("❌ No accounts!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
            return
        kb = []
        for a in active_accounts:
            st = "🟢" if account_stats.get(a['id'], {}).get('spam_running', False) else "🔴"
            kb.append([InlineKeyboardButton(f"{st} {a.get('name','?')[:15]}", callback_data=f"gsa_{a['id']}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_gs")])
        await query.edit_message_text("👤 **Toggle:**", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data.startswith("gsa_"):
        aid = data.replace("gsa_", "")
        if account_stats.get(aid, {}).get('spam_running', False):
            stop_spam(aid)
        else:
            start_spam(aid)
        update.callback_query.data = "gs_sp"
        await handle_callback(update, context)
        return
    
    if data == "gs_spd":
        cur = get_setting('spam_speed', 'medium')
        kb = [
            [InlineKeyboardButton(f"{'✅ ' if cur=='super_fast' else ''}⚡ SF", callback_data="gs_sf")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='fast' else ''}🚀 Fast", callback_data="gs_fa")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='medium' else ''}🏃 Med", callback_data="gs_me")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='slow' else ''}🐢 Slow", callback_data="gs_sl")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='custom' else ''}⚙️ Custom", callback_data="gs_cs")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_gs")]
        ]
        txt = f"⚡ **Speed:** {cur}"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return
    
    spd_map = {'gs_sf':'super_fast','gs_fa':'fast','gs_me':'medium','gs_sl':'slow','gs_cs':'custom'}
    if data in spd_map:
        set_setting('spam_speed', spd_map[data])
        if data == 'gs_cs':
            kb = [
                [InlineKeyboardButton("📦 Batch Size", callback_data="gs_bs")],
                [InlineKeyboardButton("⏱️ Batch Delay", callback_data="gs_bd")],
                [InlineKeyboardButton("🔄 Cycle Wait", callback_data="gs_cw")],
                [InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]
            ]
            await query.edit_message_text("⚙️ **Custom**", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.edit_message_text(f"✅ {spd_map[data]}!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
        return
    
    if data == "gs_bs":
        context.user_data['await'] = 'gs_bs'
        txt = f"📦 Batch Size{NL}Current: {get_setting('spam_batch_size',6)}{NL}Enter (1-50):"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
        return
    
    if data == "gs_bd":
        context.user_data['await'] = 'gs_bd'
        txt = f"⏱️ Batch Delay{NL}Current: {get_setting('spam_batch_delay',3)}s{NL}Enter (0-30):"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
        return
    
    if data == "gs_cw":
        context.user_data['await'] = 'gs_cw'
        txt = f"🔄 Cycle Wait{NL}Current: {get_setting('spam_cycle_wait',30)}s{NL}Enter (0-300):"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
        return
    
    if data == "gs_msg":
        msgs = load_spam_messages()
        txt = "💬 **Spam Messages**" + NL + NL
        if msgs:
            for m in msgs:
                txt += f"📝 {m['text'][:40]}..." + NL
        else:
            txt += f"📝 Default: {get_setting('spam_message','...')}" + NL
        kb = [
            [InlineKeyboardButton("➕ Add", callback_data="gs_msg_add")],
            [InlineKeyboardButton("🗑️ Delete", callback_data="gs_msg_del")],
            [InlineKeyboardButton("📋 All", callback_data="gs_msg_list")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_gs")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "gs_msg_add":
        context.user_data['await'] = 'gs_msg_add'
        await query.edit_message_text("📝 **Enter message:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
        return
    
    if data == "gs_msg_list":
        msgs = load_spam_messages()
        txt = "📋 **All Messages**" + NL + NL
        if msgs:
            for i, m in enumerate(msgs, 1):
                txt += f"{i}. {m['text']}" + NL
        else:
            txt += "None" + NL
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
        return
    
    if data == "gs_msg_del":
        msgs = load_spam_messages()
        if not msgs:
            await query.edit_message_text("No messages!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {m['text'][:20]}...", callback_data=f"gsmd_{m['id']}")] for m in msgs[:10]]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="gs_msg")])
        await query.edit_message_text("Select:", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data.startswith("gsmd_"):
        mid = int(data.split('_')[1])
        msgs = load_spam_messages()
        msgs = [m for m in msgs if m['id'] != mid]
        save_spam_messages(msgs)
        for a in active_accounts:
            account_spam_messages[a['id']] = [m['text'] for m in msgs]
        await query.edit_message_text("✅ Deleted!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
        return
    
    if data == "gs_st":
        txt = "📊 **Perf**" + NL + NL
        for a in active_accounts:
            s = account_stats.get(a['id'], {}).get('spam_sent', 0)
            r = "🟢" if account_stats.get(a['id'], {}).get('spam_running', False) else "🔴"
            txt += f"{r} {a.get('name','?')}: {s}" + NL
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
        return
    
    # ─── Accounts Menu ───
    if data == "m_acc":
        da = load_accounts()
        al = da.get('accounts', [])
        ma = len([x for x in al if not x.get('is_backup')])
        ba = len([x for x in al if x.get('is_backup')])
        txt = f"👤 **Accounts**" + NL + f"📌 Main: {ma} | 💾 Backup: {ba} | 🟢 Active: {len(active_accounts)}"
        kb = [
            [InlineKeyboardButton("📱 Phone+OTP", callback_data="ac_ph")],
            [InlineKeyboardButton("🔑 Session String", callback_data="ac_ss")],
            [InlineKeyboardButton("🗑️ Delete", callback_data="ac_del")],
            [InlineKeyboardButton("💾 Backup", callback_data="ac_bk")],
            [InlineKeyboardButton("📋 List", callback_data="ac_ls")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if if data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("📱 **Phone**" + NL + NL + "`+8801XXXXXXXXX`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        return
    
    if data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("🔑 **Paste Session**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        return
    
    if data == "ac_del":
        da = load_accounts()
        al = da.get('accounts', [])
        if not al:
            await query.edit_message_text("❌ None!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}", callback_data=f"acd_{a['id']}")] for a in al]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_acc")])
        await query.edit_message_text("🗑️ **Delete:**", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data.startswith("acd_"):
        aid = data.split('_', 1)[1]
        if aid in account_keepalive_tasks:
            if not account_keepalive_tasks[aid].done():
                account_keepalive_tasks[aid].cancel()
                try:
                    await account_keepalive_tasks[aid]
                except:
                    pass
            del account_keepalive_tasks[aid]
        if aid in account_spam_tasks:
            if not account_spam_tasks[aid].done():
                account_spam_tasks[aid].cancel()
                try:
                    await account_spam_tasks[aid]
                except:
                    pass
            del account_spam_tasks[aid]
        if aid in account_clients:
            try:
                await account_clients[aid].disconnect()
            except:
                pass
            del account_clients[aid]
        active_accounts[:] = [x for x in active_accounts if x['id'] != aid]
        for d in [account_stats, account_stop_flags, account_spam_active]:
            if aid in d:
                del d[aid]
        da = load_accounts()
        da['accounts'] = [a for a in da.get('accounts', []) if a['id'] != aid]
        save_accounts(da)
        await query.edit_message_text("✅ **Deleted!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        return
    
    if data == "ac_bk":
        da = load_accounts()
        ba = [a for a in da.get('accounts', []) if a.get('is_backup')]
        txt = f"💾 **Backups** ({len(ba)})" + NL + NL
        for i, a in enumerate(ba, 1):
            txt += f"{i}. {a.get('name','?')} ({a.get('phone','N/A')})" + NL
        kb = [
            [InlineKeyboardButton("➕ Add", callback_data="ac_bk_add")],
            [InlineKeyboardButton("🗑️ Remove", callback_data="ac_bk_del")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_acc")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "ac_bk_add":
        context.user_data['await'] = 'ac_bk_ss'
        await query.edit_message_text("🔑 **Backup Session:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
        return
    
    if data == "ac_bk_del":
        da = load_accounts()
        ba = [a for a in da.get('accounts', []) if a.get('is_backup')]
        if not ba:
            await query.edit_message_text("❌ None!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')}", callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="ac_bk")])
        await query.edit_message_text("🗑️ **Remove:**", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data.startswith("acbkd_"):
        bid = data.split('_')[1]
        da = load_accounts()
        da['accounts'] = [a for a in da.get('accounts', []) if a['id'] != bid]
        save_accounts(da)
        await query.edit_message_text("✅ Removed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
        return
    
    if data == "ac_ls":
        da = load_accounts()
        al = da.get('accounts', [])
        if not al:
            await query.edit_message_text("❌ None!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        txt = f"📋 **All ({len(al)})**" + NL + NL
        for a in al:
            tp = "📌M" if not a.get('is_backup') else "💾B"
            st = "🟢" if any(x['id'] == a['id'] for x in active_accounts) else "🔴"
            txt += f"{tp}{st} {a.get('name','?')[:12]} 📱{a.get('phone','?')}" + NL
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        return
    
    # ─── Settings Menu ───
    if data == "m_set":
        bp = "🟢" if get_setting('block_photo_enabled',True) else "🔴"
        dr = "🟢" if get_setting('default_reply_enabled',False) else "🔴"
        fs = "🟢" if get_setting('flood_slow_mode',True) else "🔴"
        ln = "🟢" if logout_notification_enabled else "🔴"
        kb = [
            [InlineKeyboardButton(f"🚫 Block Photo {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"💬 Default Reply {dr}", callback_data="st_dr")],
            [InlineKeyboardButton(f"🐢 Flood Slow {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"🔔 Logout Alert {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("📝 Welcome & Price", callback_data="st_wp")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text("⚙️ **Settings**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "st_bp":
        set_setting('block_photo_enabled', not get_setting('block_photo_enabled', True))
        update.callback_query.data = "m_set"
        await handle_callback(update, context)
        return
    
    if data == "st_dr":
        cur = get_setting('default_reply_enabled', False)
        set_setting('default_reply_enabled', not cur)
        if not cur:
            context.user_data['await'] = 'dr_txt'
            await query.edit_message_text("💬 **Enter default reply text:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))
        else:
            update.callback_query.data = "m_set"
            await handle_callback(update, context)
        return
    
    if data == "st_fs":
        set_setting('flood_slow_mode', not get_setting('flood_slow_mode', True))
        update.callback_query.data = "m_set"
        await handle_callback(update, context)
        return
    
    if data == "st_ln":
        logout_notification_enabled = not logout_notification_enabled
        update.callback_query.data = "m_set"
        await handle_callback(update, context)
        return
    
    if data == "st_wp":
        wm = get_setting('welcome_message', '') or "🔥 Welcome!"
        wm2 = get_setting('welcome_message2', '') or "🛒 How to order?"
        wi = "✅" if get_setting('welcome_image','') else "❌"
        wi2 = "✅" if get_setting('welcome_image2','') else "❌"
        pi = "✅" if get_setting('price_list_image','') else "❌"
        pt = get_setting('price_list_text', "🔥 10MIN Rs.99")
        qr = "✅" if get_setting('qr_code_path','') else "❌"
        upi = get_setting('upi_id','') or "Not Set"
        paytm = get_setting('paytm_num','') or "Not Set"
        txt_parts = [
            "📝 **W&P**",
            f"1️⃣ `{wm[:30]}...` 🖼{wi}",
            f"2️⃣ `{wm2[:30]}...` 🖼{wi2}",
            f"💰 `{pt[:30]}...` 🖼{pi}",
            f"💳 UPI:`{upi}` PayTm:`{paytm}`",
            f"📷QR:{qr}"
        ]
        txt = NL.join(txt_parts)
        kb = [
            [InlineKeyboardButton("1️⃣ 1st Welcome", callback_data="st_wm"), InlineKeyboardButton("🖼 Pic1", callback_data="st_wi")],
            [InlineKeyboardButton("2️⃣ 2nd Welcome", callback_data="st_wm2"), InlineKeyboardButton("🖼 Pic2", callback_data="st_wi2")],
            [InlineKeyboardButton("💰 Price Text", callback_data="st_pt"), InlineKeyboardButton("🖼 Price Pic", callback_data="st_pi")],
            [InlineKeyboardButton("📱 UPI", callback_data="st_upi"), InlineKeyboardButton("💳 PayTm", callback_data="st_paytm")],
            [InlineKeyboardButton("📷 QR", callback_data="st_qr")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_set")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return
        # ─── Settings text inputs ───
    st_text_map = {
        'st_wm': ('welcome_message', "👋 **1st Welcome Message**"),
        'st_wm2': ('welcome_message2', "2️⃣ **2nd Welcome Message**"),
        'st_pt': ('price_list_text', "💰 **Set Price List Text**"),
    }
    if data in st_text_map:
        key, label = st_text_map[data]
        context.user_data['await'] = data
        cur = get_setting(key, '')
        txt_parts = [label, ""]
        if cur:
            txt_parts.append(f"Current: `{cur[:30]}...`")
        txt_parts.append("`remove` to clear")
        txt = NL.join(txt_parts)
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
        return
    
    st_media_map = {
        'st_wi': 'welcome_image',
        'st_wi2': 'welcome_image2',
        'st_pi': 'price_list_image',
        'st_qr': 'qr_code_path',
    }
    if data in st_media_map:
        key = st_media_map[data]
        context.user_data['await'] = data
        cur = get_setting(key, '')
        txt_parts = ["🖼️ Send photo/URL/path:", ""]
        txt_parts.append(f"Current: `{cur if cur else 'None'}`")
        txt_parts.append("`remove` to clear")
        txt = NL.join(txt_parts)
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
        return
    
    st_pay_map = {
        'st_upi': 'upi_id',
        'st_paytm': 'paytm_num',
    }
    if data in st_pay_map:
        key = st_pay_map[data]
        context.user_data['await'] = data
        cur = get_setting(key, '')
        txt_parts = ["Send:", ""]
        txt_parts.append(f"Current: `{cur if cur else 'Not Set'}`")
        txt_parts.append("`remove` to clear")
        txt = NL.join(txt_parts)
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
        return
    
    # ─── Status ───
    if data == "m_stat":
        ar = "🟢" if auto_reply_enabled else "🔴"
        gs = "🟢" if group_spam_enabled else "🔴"
        ln = "🟢" if logout_notification_enabled else "🔴"
        tc = len([k for k, v in customer_count.items() if v > 0])
        total_accs = len(load_accounts().get('accounts', []))
        spam_running = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        spam_sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        speed = get_setting('spam_speed', 'medium')
        
        txt_parts = [
            "📊 **STATUS**",
            f"📨AR:{ar} 📯GS:{gs} 🔔LN:{ln}",
            f"👤Total:{total_accs}",
            f"🟢Active:{len(active_accounts)}",
            f"🏃Spam:{spam_running}",
            f"📤Sent:{spam_sent}",
            f"👥Cust:{tc}",
            f"⚡Speed:{speed}"
        ]
        txt = NL.join(txt_parts)
        await query.edit_message_text(
            txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="m_stat")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main")]
            ])
        )
        return
    
    # ─── Admin ───
    if data == "m_adm":
        txt_parts = ["🔐 **Admin**", f"👑{OWNER_ID}", f"👥{len(admins)-1}", ""]
        for a in admins:
            icon = "👑" if a == OWNER_ID else "👤"
            txt_parts.append(f"{icon}`{a}`")
        txt = NL.join(txt_parts)
        
        if uid == OWNER_ID:
            kb = [
                [InlineKeyboardButton("➕ Add", callback_data="ad_add")],
                [InlineKeyboardButton("🗑️ Del", callback_data="ad_del")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main")]
            ]
        else:
            kb = [[InlineKeyboardButton("🏠 Menu", callback_data="main")]]
        
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "ad_add" and uid == OWNER_ID:
        context.user_data['await'] = 'ad_add'
        await query.edit_message_text(
            "👤 **Enter user ID:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]])
        )
        return
    
    if data == "ad_del" and uid == OWNER_ID:
        if len(admins) <= 1:
            await query.edit_message_text(
                "❌ Only owner!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]])
            )
            return
        kb = [[InlineKeyboardButton(f"🗑️ `{a}`", callback_data=f"addc_{a}")] for a in admins if a != OWNER_ID]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_adm")])
        await query.edit_message_text("Select:", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data.startswith("addc_") and uid == OWNER_ID:
        aid = int(data.split('_')[1])
        if aid in admins and aid != OWNER_ID:
            admins.remove(aid)
            await query.edit_message_text(
                "✅ Removed!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]])
            )
            return

# ═══════════════════════════════════════════
# TEXT MESSAGE HANDLER
# ═══════════════════════════════════════════
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    uid = update.effective_user.id if update.effective_user else None
    text = update.message.text.strip()
    
    await_state = context.user_data.get('await')
    
    # Handle pending input
    if await_state:
        await handle_await_input(update, context, text)
        return
    
    # Admin only
    if uid not in admins and uid != OWNER_ID:
        return


async def handle_await_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    msg = update.message
    await_state = context.user_data.get('await')
    
    if await_state == 'gs_bs':
        try:
            v = max(1, min(50, int(text)))
            set_setting('spam_batch_size', v)
            await msg.reply_text(f"✅ Batch: {v}")
        except:
            await msg.reply_text("❌ Invalid")
        del context.user_data['await']
        return
    
    if await_state == 'gs_bd':
        try:
            v = max(0, min(30, int(text)))
            set_setting('spam_batch_delay', v)
            await msg.reply_text(f"✅ Delay: {v}s")
        except:
            await msg.reply_text("❌ Invalid")
        del context.user_data['await']
        return
    
    if await_state == 'gs_cw':
        try:
            v = max(0, min(300, int(text)))
            set_setting('spam_cycle_wait', v)
            await msg.reply_text(f"✅ Cycle: {v}s")
        except:
            await msg.reply_text("❌ Invalid")
        del context.user_data['await']
        return
    
    if await_state == 'gs_msg_add':
        msgs = load_spam_messages()
        mid = max([m['id'] for m in msgs], default=0) + 1
        msgs.append({'id': mid, 'text': text})
        save_spam_messages(msgs)
        for a in active_accounts:
            account_spam_messages[a['id']] = [m['text'] for m in msgs]
        await msg.reply_text("✅ Added!")
        del context.user_data['await']
        return
    
    if await_state == 'ad_add' and uid == OWNER_ID:
        try:
            new_id = int(text.strip())
            if new_id not in admins:
                admins.append(new_id)
                await msg.reply_text(f"✅ Admin: `{new_id}`")
            else:
                await msg.reply_text("⚠️ Already admin!")
        except:
            await msg.reply_text("❌ Invalid ID!")
        del context.user_data['await']
        return
    
    if await_state == 'dr_txt':
        set_setting('default_reply_text', text)
        await msg.reply_text(f"✅ Set: `{text[:30]}...`")
        del context.user_data['await']
        return
    
    if await_state in ['st_wm', 'st_wm2', 'st_pt', 'st_upi', 'st_paytm']:
        key = {
            'st_wm': 'welcome_message',
            'st_wm2': 'welcome_message2',
            'st_pt': 'price_list_text',
            'st_upi': 'upi_id',
            'st_paytm': 'paytm_num'
        }[await_state]
        
        if text.lower() == 'remove':
            set_setting(key, '')
            await msg.reply_text("✅ Cleared!")
        else:
            set_setting(key, text)
            await msg.reply_text("✅ Set!")
        del context.user_data['await']
        return
    
    if await_state in ['st_wi', 'st_wi2', 'st_pi', 'st_qr']:
        key = {
            'st_wi': 'welcome_image',
            'st_wi2': 'welcome_image2',
            'st_pi': 'price_list_image',
            'st_qr': 'qr_code_path'
        }[await_state]
        
        if text.lower() == 'remove':
            set_setting(key, '')
            await msg.reply_text("✅ Cleared!")
        elif text.startswith('http://') or text.startswith('https://'):
            set_setting(key, text)
            await msg.reply_text("✅ URL set!")
        elif Path(text).exists():
            set_setting(key, text)
            await msg.reply_text("✅ Path set!")
        else:
            await msg.reply_text("Send photo directly or URL/path." + NL + "`remove` to clear")
        del context.user_data['await']
        return
    
    if await_state == 'rk':
        context.user_data['rk'] = text
        context.user_data['await'] = 'rt'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔤 Contains", callback_data="rt_cont")],
            [InlineKeyboardButton("✅ Exact", callback_data="rt_exact")],
            [InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]
        ])
        await msg.reply_text(f"Keyword: `{text}`" + NL + "Select match type:", reply_markup=kb)
        return
    
    if await_state == 'seen_delay':
        try:
            v = max(1, min(5, int(text)))
            set_setting('seen_delay', v)
            await msg.reply_text(f"✅ Seen delay: {v}s")
        except:
            await msg.reply_text("❌ Invalid!")
        del context.user_data['await']
        return
    
    if await_state == 'typing_duration':
        try:
            v = max(1, min(5, int(text)))
            set_setting('typing_duration', v)
            await msg.reply_text(f"✅ Typing: {v}s")
        except:
            await msg.reply_text("❌ Invalid!")
        del context.user_data['await']
        return
    
    if await_state == 'ignore':
        set_setting('ignored_messages', text)
        await msg.reply_text("✅ Set!")
        del context.user_data['await']
        return
    
    if await_state == 'ac_ph':
        context.user_data['await'] = 'ac_otp'
        context.user_data['ac_phone'] = text
        await msg.reply_text(f"📱 Phone: `{text}`" + NL + "Sending code...")
        asyncio.create_task(send_code(text, update, context))
        return
    
    if await_state == 'ac_otp':
        phone = context.user_data.get('ac_phone', '')
        code = text.strip()
        asyncio.create_task(complete_login(phone, code, update, context))
        del context.user_data['await']
        return
    
    # Session string
    if await_state == 'ac_ss':
        asyncio.create_task(add_session_account(text, update, context, is_backup=False))
        del context.user_data['await']
        return
    
    if await_state == 'ac_bk_ss':
        asyncio.create_task(add_session_account(text, update, context, is_backup=True))
        del context.user_data['await']
        return


# ═══════════════════════════════════════════
# CALLBACK FOR REPLY TYPE
# ═══════════════════════════════════════════
async def callback_reply_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "rt_cont":
        context.user_data['rt'] = 'contains'
        await query.edit_message_text("✅ Match: **contains**" + NL + "Now send reply text:")
        context.user_data['await'] = 'rt'
    elif data == "rt_exact":
        context.user_data['rt'] = 'exact'
        await query.edit_message_text("✅ Match: **exact**" + NL + "Now send reply text:")
        context.user_data['await'] = 'rt'


# ═══════════════════════════════════════════
# ACCOUNT LOGIN HELPERS
# ═══════════════════════════════════════════
async def send_code(phone, update, context):
    try:
        client = TelegramClient(StringSession(), DEFAULT_API_ID, DEFAULT_API_HASH)
        await client.connect()
        sent = await client.send_code_request(phone)
        context.user_data['ac_client'] = client
        context.user_data['ac_hash'] = sent.phone_code_hash
        context.user_data['ac_phone'] = phone
        context.user_data['await'] = 'ac_otp'
        await update.message.reply_text("📱 OTP sent! Enter code:")
    except Exception as e:
        await update.message.reply_text(f"❌ {str(e)[:80]}")


async def complete_login(phone, code, update, context):
    try:
        client = context.user_data.get('ac_client')
        ph_hash = context.user_data.get('ac_hash')
        if not client or not ph_hash:
            await update.message.reply_text("❌ Session expired! Start again.")
            return
        
        await client.sign_in(phone, code, phone_code_hash=ph_hash)
        me = await client.get_me()
        ss = client.session.save()
        
        info = {
            'id': f"acc_{int(time.time())}_{random.randint(100, 999)}",
            'user_id': me.id,
            'name': me.first_name or f"User{me.id}",
            'phone': getattr(me, 'phone', phone),
            'session': ss,
            'api_id': DEFAULT_API_ID,
            'api_hash': DEFAULT_API_HASH,
            'enabled': True,
            'is_backup': False,
            'proxy': None,
            'added_at': datetime.now().isoformat()
        }
        
        da = load_accounts()
        da['accounts'].append(info)
        save_accounts(da)
        
        c2 = await start_account(info)
        if c2:
            active_accounts.append(info)
            account_clients[info['id']] = c2
            account_stats[info['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
            account_stop_flags[info['id']] = False
            await update.message.reply_text(f"✅ **Added!** {info['name']} ({info['phone']})")
        else:
            await update.message.reply_text("⚠️ Saved but failed to start!")
        
        await client.disconnect()
        context.user_data['await'] = None
        context.user_data.pop('ac_client', None)
        context.user_data.pop('ac_hash', None)
        context.user_data.pop('ac_phone', None)
    except SessionPasswordNeededError:
        context.user_data['await'] = 'ac_2fa'
        await update.message.reply_text("🔑 **2FA required!** Enter password:")
    except Exception as e:
        await update.message.reply_text(f"❌ {str(e)[:80]}")


async def add_session_account(session_str, update, context, is_backup=False):
    try:
        client = TelegramClient(StringSession(session_str), DEFAULT_API_ID, DEFAULT_API_HASH)
        await client.connect()
        me = await client.get_me()
        phone = getattr(me, 'phone', 'N/A') or 'N/A'
        name = me.first_name or "Unknown"
        
        info = {
            'id': f"acc_{int(time.time())}_{random.randint(100, 999)}",
            'user_id': me.id,
            'name': name,
            'phone': phone,
            'session': session_str,
            'api_id': DEFAULT_API_ID,
            'api_hash': DEFAULT_API_HASH,
            'enabled': True,
            'is_backup': is_backup,
            'proxy': None,
            'added_at': datetime.now().isoformat()
        }
        
        da = load_accounts()
        da['accounts'].append(info)
        save_accounts(da)
        
        if not is_backup:
            c2 = await start_account(info)
            if c2:
                active_accounts.append(info)
                account_clients[info['id']] = c2
                account_stats[info['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
                account_stop_flags[info['id']] = False
                await update.message.reply_text(f"✅ **Added!** {name} ({phone})")
            else:
                await update.message.reply_text("⚠️ Saved but failed to start!")
        else:
            await update.message.reply_text(f"✅ **Backup Added!** {name} ({phone})")
        
        await client.disconnect()
    except Exception as e:
        await update.message.reply_text(f"❌ {str(e)[:80]}")


# ═══════════════════════════════════════════
# 2FA HANDLER
# ═══════════════════════════════════════════
async def handle_2fa_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA password input"""
    if context.user_data.get('await') == 'ac_2fa':
        password = update.message.text.strip()
        phone = context.user_data.get('ac_phone', '')
        
        try:
            client = context.user_data.get('ac_client')
            if not client:
                await update.message.reply_text("❌ Session expired! Start again.")
                return
            
            await client.sign_in(password=password)
            me = await client.get_me()
            ss = client.session.save()
            
            info = {
                'id': f"acc_{int(time.time())}_{random.randint(100, 999)}",
                'user_id': me.id,
                'name': me.first_name or f"User{me.id}",
                'phone': getattr(me, 'phone', phone),
                'session': ss,
                'api_id': DEFAULT_API_ID,
                'api_hash': DEFAULT_API_HASH,
                'enabled': True,
                'is_backup': False,
                'proxy': None,
                'added_at': datetime.now().isoformat()
            }
            
            da = load_accounts()
            da['accounts'].append(info)
            save_accounts(da)
            
            c2 = await start_account(info)
            if c2:
                active_accounts.append(info)
                account_clients[info['id']] = c2
                account_stats[info['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
                account_stop_flags[info['id']] = False
                await update.message.reply_text(f"✅ **Added!** {info['name']} ({info['phone']})")
            else:
                await update.message.reply_text("⚠️ Saved but failed to start!")
            
            await client.disconnect()
            context.user_data['await'] = None
            context.user_data.pop('ac_client', None)
            context.user_data.pop('ac_hash', None)
            context.user_data.pop('ac_phone', None)
        except Exception as e:
            await update.message.reply_text(f"❌ {str(e)[:80]}")
            context.user_data['await'] = 'ac_2fa'  # Keep waiting for correct password


# ═══════════════════════════════════════════
# PHOTO HANDLER
# ═══════════════════════════════════════════
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in admins and uid != OWNER_ID:
        return
    
    await_state = context.user_data.get('await')
    if not await_state or await_state not in ['st_wi', 'st_wi2', 'st_pi', 'st_qr']:
        return
    
    msg = update.message
    if not msg.photo:
        return
    
    photo = msg.photo[-1]
    file = await photo.get_file()
    
    key = {
        'st_wi': 'welcome_image',
        'st_wi2': 'welcome_image2',
        'st_pi': 'price_list_image',
        'st_qr': 'qr_code_path'
    }[await_state]
    
    save_path = f"data/{await_state}_{int(time.time())}.jpg"
    
    try:
        await file.download_to_drive(save_path)
        set_setting(key, save_path)
        await msg.reply_text("✅ Saved!")
    except Exception as e:
        await msg.reply_text(f"❌ {str(e)[:60]}")
    
    del context.user_data['await']


# ═══════════════════════════════════════════
# HANDLE REPLY TEXT INPUT (for 'rt' await state)
# ═══════════════════════════════════════════
async def handle_rt_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reply text input after keyword is set"""
    if context.user_data.get('await') == 'rt':
        reply_text = update.message.text
        keyword = context.user_data.get('rk', '')
        match_type = context.user_data.get('rt', 'contains')
        
        if keyword and reply_text:
            add_reply(keyword, reply_text, match_type)
            await update.message.reply_text(f"✅ Added!" + NL + f"`{keyword}` ➜ `{reply_text[:30]}...`")
        
        context.user_data.pop('rk', None)
        context.user_data.pop('rt', None)
        del context.user_data['await']


# ═══════════════════════════════════════════
# POLLING WITH AUTO-RECONNECT
# ═══════════════════════════════════════════
async def polling_with_reconnect(app):
    """Start polling with auto-reconnect on failure"""
    max_retries = 10
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            await app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                timeout=30,
                poll_interval=0.5,
                bootstrap_retries=10,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
            logger.info("✅ Polling started successfully")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Polling attempt {attempt+1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Exponential backoff
            else:
                logger.error("❌ All polling attempts failed!")
                raise


# ═══════════════════════════════════════════
# MAIN - SETUP & RUN
# ═══════════════════════════════════════════
def setup_application():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern="^(?!rt_)"))
    app.add_handler(CallbackQueryHandler(callback_reply_type, pattern="^rt_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rt_text))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_text))
    
    return app


async def account_health_check():
    """Periodically check and restart dead accounts"""
    while True:
        await asyncio.sleep(120)  # Every 2 minutes
        try:
            for acc in list(active_accounts):
                acc_id = acc['id']
                if acc_id not in account_clients:
                    continue
                
                try:
                    # Quick health check
                    await asyncio.wait_for(account_clients[acc_id].get_me(timeout=3), timeout=5)
                except:
                    logger.warning(f"🔄 Account dead, restarting: {acc.get('name','?')}")
                    try:
                        # Disconnect old client
                        try:
                            await account_clients[acc_id].disconnect()
                        except:
                            pass
                        del account_clients[acc_id]
                    except:
                        pass
                    
                    # Restart
                    client = await start_account(acc)
                    if client:
                        account_clients[acc_id] = client
                        logger.info(f"✅ Restarted: {acc.get('name','?')}")
                    else:
                        logger.error(f"❌ Failed to restart: {acc.get('name','?')}")
                        
                        # Try to remove from active
                        active_accounts[:] = [a for a in active_accounts if a['id'] != acc_id]
        except Exception as e:
            logger.error(f"Health check error: {e}")


async def main():
    global start_time
    start_time = time.time()
    
    logger.info("🚀 Starting bot...")
    
    # Load settings
    _load_settings()
    load_replies()
    logger.info("✅ Settings loaded")
    
    # Load and start accounts
    data = load_accounts()
    accounts = data.get('accounts', [])
    logger.info(f"📂 Loaded {len(accounts)} accounts")
    
    for acc in accounts:
        if acc.get('is_backup'):
            continue  # Don't auto-start backups
        
        acc_id = acc['id']
        session_str = acc.get('session', '')
        if not session_str:
            continue
        
        try:
            client = await start_account(acc)
            if client:
                active_accounts.append(acc)
                account_clients[acc_id] = client
                account_stats[acc_id]['running'] = True
                account_stop_flags[acc_id] = False
                logger.info(f"🟢 Account active: {acc.get('name','?')}")
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"❌ Failed: {acc.get('name','?')}: {e}")
    
    logger.info(f"🟢 Active accounts: {len(active_accounts)}")
    
    # Start web server (for Render health checks)
    await web_server()
    
    # Start background tasks
    asyncio.create_task(periodic_cleanup())
    asyncio.create_task(ping_loop())
    asyncio.create_task(account_health_check())
    
    # Setup PTB
    app = setup_application()
    
    logger.info("📡 Starting polling...")
    
    await app.initialize()
    await app.start()
    
    # Start polling with auto-reconnect
    try:
        await polling_with_reconnect(app)
    except Exception as e:
        logger.error(f"❌ Polling failed: {e}")
        raise
    
    logger.info(f"✅ Bot running! Owner: {OWNER_ID}")
    
    # Main keep-alive loop
    try:
        while True:
            await asyncio.sleep(30)
            
            # Periodic health log
            alive = sum(1 for a in active_accounts if a['id'] in account_clients)
            spam_run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
            logger.info(f"💚 Heartbeat: {alive}/{len(active_accounts)} active, {spam_run} spamming")
            
    except KeyboardInterrupt:
        logger.info("👋 Stopping...")
    except Exception as e:
        logger.error(f"💥 Main loop error: {e}")
    finally:
        # Stop all spam tasks
        stop_spam()
        
        # Disconnect all clients
        for acc_id, client in account_clients.items():
            try:
                await client.disconnect()
            except:
                pass
        
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("👋 Bot stopped.")


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("👋 Bot stopped by user.")
            sys.exit(0)
        except Exception as e:
            logger.exception(f"💥 Fatal error: {e}")
            logger.info("🔄 Restarting in 10 seconds...")
            time.sleep(10)

#!/usr/bin/env python3
"""
UNIFIED TELEGRAM BOT - COMPLETELY FIXED VERSION (v4)
- Auto Reply + Group Spam একসাথে ১০০% কাজ করবে
- Typing effect থাকবে কিন্তু blocking হবে না
- Sequential updates = False (একসাথে multiple message handle করবে)
- Priority queue system
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
    logger.error("BOT_TOKEN not set!")
    sys.exit(1)
if not OWNER_ID:
    logger.error("OWNER_ID not set!")
    sys.exit(1)
if not DEFAULT_API_ID or not DEFAULT_API_HASH:
    logger.error("API_ID or API_HASH not set!")
    sys.exit(1)

# ═══════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════
try:
    import socks
except ImportError:
    socks = None

try:
    from aiohttp import web
except ImportError:
    web = None

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

# Message queue for non-blocking processing
ar_message_queue = asyncio.Queue()
ar_worker_task = None

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
    except:
        pass
    return default if default is not None else {}

def save_json(fp, data):
    try:
        fp = Path(fp)
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except:
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
    except:
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
        except:
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

NL = "\n"

# ═══════════════════════════════════════════
# MEMORY CLEANUP
# ═══════════════════════════════════════════
async def cleanup_memory():
    global customer_count, customer_payment_photos, processing_users
    
    if len(processing_users) > 200:
        processing_users.clear()
    if len(customer_count) > 2000:
        customer_count.clear()
    if len(customer_payment_photos) > 500:
        customer_payment_photos.clear()
    
    try:
        now = time.time()
        for f in PAYMENT_SS_DIR.glob("*.jpg"):
            if now - f.stat().st_mtime > 86400:
                f.unlink(missing_ok=True)
    except:
        pass

async def periodic_cleanup():
    while True:
        await asyncio.sleep(1800)
        try:
            await cleanup_memory()
        except:
            pass

# ═══════════════════════════════════════════
# PING / HEARTBEAT
# ═══════════════════════════════════════════
async def ping_loop():
    while True:
        try:
            bot = Bot(token=BOT_TOKEN)
            await bot.get_me()
            
            for acc_id, client in list(account_clients.items()):
                try:
                    await asyncio.wait_for(client.get_me(timeout=2), timeout=3)
                except:
                    pass
        except:
            pass
        
        await asyncio.sleep(20)

# ═══════════════════════════════════════════
# WEB SERVER
# ═══════════════════════════════════════════
async def web_server():
    if web is None:
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
            "spam_running": spam_run
        })
    
    app.router.add_get('/', health_handler)
    app.router.add_get('/health', health_handler)
    app.router.add_get('/stats', stats_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Web server on 0.0.0.0:{PORT}")

# ═══════════════════════════════════════════
# TYPING EFFECT - NON BLOCKING VERSION
# ═══════════════════════════════════════════
async def simulate_reply_with_typing(client, chat_id, event, message_text):
    """
    NON-BLOCKING typing effect
    - Seen delay + typing effect দেখাবে
    - কিন্তু অন্য messages process করতে blocking হবে না
    """
    seen_delay = int(get_setting('seen_delay', 1))
    typing_enabled = get_setting('typing_enabled', True)
    typing_duration = int(get_setting('typing_duration', 2))

    # Step 1: Immediate seen mark (double tick) - FIXED: তাড়াতাড়ি করছে
    try:
        input_chat = await event.get_input_chat()
        await client(ReadHistoryRequest(peer=input_chat, max_id=event.message.id))
    except:
        pass

    # Step 2: Typing effect - NON BLOCKING (fire and forget)
    if typing_enabled and typing_duration > 0:
        actual_typing = min(typing_duration, 2)
        asyncio.create_task(show_typing_and_send(client, chat_id, message_text, actual_typing))
    else:
        # Step 3: সরাসরি পাঠিয়ে দাও (কোন typing নেই)
        await client.send_message(chat_id, message_text)


async def show_typing_and_send(client, chat_id, message_text, duration):
    """Typing effect দেখিয়ে তারপর message পাঠায় - NON BLOCKING"""
    try:
        async with client.action(chat_id, 'typing'):
            await asyncio.sleep(duration)
        await client.send_message(chat_id, message_text)
    except:
        # Typing fail হলে সরাসরি পাঠিয়ে দাও
        try:
            await client.send_message(chat_id, message_text)
        except:
            pass

# ═══════════════════════════════════════════
# AUTO REPLY - OPTIMIZED VERSION
# ═══════════════════════════════════════════
async def process_auto_reply(event, client, acc, uid):
    """Fast auto-reply processing - NON BLOCKING"""
    chat_id = event.chat_id
    message_text = event.message.text or ""
    
    if uid not in customer_count:
        customer_count[uid] = 0
    prev_count = customer_count[uid]
    
    # Block photo senders
    if event.message.photo:
        if get_setting('block_photo_enabled', True):
            asyncio.create_task(block_user_and_delete_photos(event, client, uid))
        else:
            asyncio.create_task(handle_payment_screenshot(event, client, uid))
        return
    
    if not message_text.strip():
        return
    
    msg_lower = message_text.lower().strip()
    
    # Welcome on first contact
    if prev_count == 0 and get_setting('welcome_enabled', True):
        await send_welcome_fast(client, chat_id)
        customer_count[uid] = prev_count + 1
        return
    
    # Check ignored
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
        await simulate_reply_with_typing(client, chat_id, event, reply_text)
        customer_count[uid] = prev_count + 1
        return
    
    # Payment keywords
    payment_keywords = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'bhejo', 'screenshot', 'method', 'rs', 'money']
    if any(kw in msg_lower for kw in payment_keywords):
        await send_payment_info_fast(client, chat_id, event)
        customer_count[uid] = prev_count + 1
        return
    
    # Media keywords
    media_keywords = ['pic', 'photo', 'image', 'nude', 'naked', 'dikhao', 'nangi', 'boob', 'mms']
    if any(kw in msg_lower for kw in media_keywords):
        await simulate_reply_with_typing(client, chat_id, event, get_setting('media_keyword_reply', 'Payment first baby 😘🔥'))
        customer_count[uid] = prev_count + 1
        return
    
    # Service keywords
    service_keywords = ['service', 'price', 'rate', 'vc', 'call', 'demo', 'chahiye', 'kharid']
    if any(kw in msg_lower for kw in service_keywords):
        price_text = get_setting('price_list_text', '🔥 10 MIN VC -> Rs.99\n🔥 20 MIN VC -> Rs.119')
        await client.send_message(chat_id, price_text)
        await asyncio.sleep(0.3)
        replies = ["How many minutes? 🔥", "Pay and enjoy! 😘", "Tell me your choice 💋"]
        await client.send_message(chat_id, random.choice(replies))
        customer_count[uid] = prev_count + 1
        return
    
    # Offline keywords
    offline_keywords = ['real', 'meet', 'aao', 'ghar', 'location', 'offline']
    if any(kw in msg_lower for kw in offline_keywords):
        await simulate_reply_with_typing(client, chat_id, event, get_setting('offline_keyword_reply', 'Online only baby 😊'))
        customer_count[uid] = prev_count + 1
        return
    
    # Greetings
    greeting_keywords = ['hi', 'hello', 'hey', 'hii', 'hy', 'hlo']
    if any(w in msg_lower for w in greeting_keywords):
        greetings = get_setting('greeting_replies', ['Hi baby, ready! 🔥', 'Hey baby! 😘'])
        await simulate_reply_with_typing(client, chat_id, event, random.choice(greetings))
        customer_count[uid] = prev_count + 1
        return
    
    # Default reply
    if get_setting('default_reply_enabled', False):
        reply = get_setting('default_reply_text', '')
        if reply:
            await simulate_reply_with_typing(client, chat_id, event, reply)
    else:
        defaults = get_setting('default_replies', ['Ready baby! 🔥', 'Main ready hoon! 😘'])
        await simulate_reply_with_typing(client, chat_id, event, random.choice(defaults))
    customer_count[uid] = prev_count + 1


async def send_welcome_fast(client, chat_id):
    """Fast welcome without long delays"""
    wm1 = get_setting('welcome_message', '🔥 Welcome Baby! 🔥')
    await client.send_message(chat_id, wm1)
    await asyncio.sleep(0.5)
    wm2 = get_setting('welcome_message2', '🛒 How to order?')
    await client.send_message(chat_id, wm2)


async def send_payment_info_fast(client, chat_id, event):
    """Fast payment info"""
    upi = get_setting('upi_id', '')
    paytm = get_setting('paytm_num', '')
    payment_msg = "**💰 Payment 💰**"
    if upi:
        payment_msg += NL + "📱 UPI: " + upi
    if paytm:
        payment_msg += NL + "💳 PayTm: " + paytm
    payment_msg += NL + get_setting('payment_keyword_reply', 'Scan & Pay baby 😘🔥')
    await client.send_message(chat_id, payment_msg)


async def block_user_and_delete_photos(event, client, uid):
    try:
        input_chat = await event.get_input_chat()
        try:
            await client.delete_messages(input_chat, [event.message.id], revoke=True)
        except:
            pass
        try:
            async for msg in client.iter_messages(input_chat, limit=50):
                try:
                    await client.delete_messages(input_chat, [msg.id], revoke=True)
                except:
                    pass
        except:
            pass
        try:
            await client.delete_dialog(input_chat)
        except:
            pass
        try:
            await client(BlockRequest(id=uid))
        except:
            pass
        try:
            await client(DeleteContactsRequest(id=[uid]))
        except:
            pass
    except:
        pass

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
        except:
            pass
        customer_count[uid] = -2
    except:
        pass


# ═══════════════════════════════════════════
# AUTO REPLY HANDLER - NON BLOCKING
# ═══════════════════════════════════════════
def register_auto_reply(client, acc):
    """Register auto-reply - FULLY NON BLOCKING"""
    
    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
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
                # NON BLOCKING: create_task instead of await
                asyncio.create_task(process_auto_reply(event, client, acc, uid))
            except:
                processing_users.discard(uid)
            
        except Exception as e:
            logger.error(f"AR error: {e}")
    
    return handler


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
        
        # CRITICAL FIX: sequential_updates = False
        client = TelegramClient(
            StringSession(acc['session']),
            acc.get('api_id', DEFAULT_API_ID),
            acc.get('api_hash', DEFAULT_API_HASH),
            proxy=proxy,
            sequential_updates=False,  # 🔴 FIXED: Multiple messages একসাথে handle হবে
            receive_updates=True,
            connection_retries=10,
            retry_delay=1,
            request_retries=10,
            flood_sleep_threshold=60
        )
        await client.start()
        me = await client.get_me()
        logger.info(f"Account started: {me.first_name} ({me.id})")
        
        acc_id = acc['id']
        custom_msgs = load_spam_messages()
        if custom_msgs:
            account_spam_messages[acc_id] = [m['text'] for m in custom_msgs]
        else:
            base_msg = get_setting('spam_message', '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')
            account_spam_messages[acc_id] = [base_msg]
        
        # Register auto-reply
        register_auto_reply(client, acc)
        
        return client
    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
        logger.warning(f"Account banned: {acc.get('name', 'Unknown')}")
        await send_logout_notification(acc, str(e)[:50])
        await handle_banned(acc)
        return None
    except Exception as e:
        logger.error(f"Failed to start account {acc.get('name', 'Unknown')}: {e}")
        return None

async def send_logout_notification(acc, reason="Unknown"):
    if not logout_notification_enabled:
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        msg = f"⚠️ ACCOUNT LOGOUT!{NL}👤 {acc.get('name','?')}{NL}📱 {acc.get('phone','N/A')}{NL}❌ {reason}"
        await bot.send_message(chat_id=OWNER_ID, text=msg)
    except:
        pass

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
        del account_keepalive_tasks[acc_id]
    
    if acc_id in account_spam_tasks:
        if not account_spam_tasks[acc_id].done():
            account_spam_tasks[acc_id].cancel()
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
    
    # Check for backup
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
            logger.info(f"Backup activated: {backup.get('name','?')}")

# ═══════════════════════════════════════════
# GROUP SPAM - OPTIMIZED
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
                               (hasattr(entity, 'broadcast') and not entity.broadcast)
                    if is_group:
                        groups.append(entity)
            except:
                pass
        return groups
    except:
        return []

async def spam_account(acc):
    acc_id = acc['id']
    acc_name = acc.get('name', acc_id)
    account_stop_flags[acc_id] = False
    account_stats[acc_id]['spam_running'] = True
    account_spam_active[acc_id] = True
    
    # CRITICAL FIX: Auto reply চালু থাকবে spam এর সময়ও
    # শুধু spam_running flag true হবে, auto reply বন্ধ হবে না
    logger.info(f"Spam starting for: {acc_name} (AR will still work)")
    
    try:
        client = TelegramClient(
            StringSession(acc['session']),
            acc.get('api_id', DEFAULT_API_ID),
            acc.get('api_hash', DEFAULT_API_HASH),
            receive_updates=True,  # 🔴 FIXED: Auto reply এর জন্য updates রাখব
            sequential_updates=False
        )
        await client.start()
        groups = await get_user_groups(client)
        if not groups:
            logger.warning(f"No groups for {acc_name}")
            account_stats[acc_id]['spam_running'] = False
            account_spam_active[acc_id] = False
            return
        
        logger.info(f"Spamming {len(groups)} groups with {acc_name}")
        
        speed = get_setting('spam_speed', 'medium')
        configs = {
            'super_fast': {'batch': 999, 'delay': 0, 'cycle': 0, 'min': 0, 'max': 0.5},
            'fast': {'batch': 999, 'delay': 0, 'cycle': 5, 'min': 0.3, 'max': 1},
            'medium': {'batch': 5, 'delay': 2, 'cycle': 15, 'min': 1, 'max': 2},
            'slow': {'batch': 3, 'delay': 5, 'cycle': 30, 'min': 3, 'max': 5},
            'custom': {'batch': int(get_setting('spam_batch_size', 6)), 'delay': int(get_setting('spam_batch_delay', 3)),
                       'cycle': int(get_setting('spam_cycle_wait', 30)), 'min': int(get_setting('spam_min_interval', 2)),
                       'max': int(get_setting('spam_max_interval', 4))}
        }
        cfg = configs.get(speed, configs['medium'])
        msgs = account_spam_messages.get(acc_id, [get_setting('spam_message', '...')])
        
        msg_idx = 0
        cycle = 0
        errors = 0
        max_b = min(cfg['batch'], len(groups))
        
        while not account_stop_flags.get(acc_id, False):
            if not group_spam_enabled or not account_spam_active.get(acc_id, True):
                await asyncio.sleep(2)
                continue
            
            for g in groups[:max_b]:
                if account_stop_flags.get(acc_id, False):
                    break
                try:
                    msg = msgs[msg_idx % len(msgs)]
                    await client.send_message(g, msg)
                    account_stats[acc_id]['spam_sent'] += 1
                    errors = 0
                    msg_idx += 1
                except FloodWaitError as e:
                    w = e.seconds
                    logger.warning(f"Flood {w}s on {acc_name}")
                    errors += 1
                    await asyncio.sleep(min(w, 15))
                except Exception as e:
                    errors += 1
                    s = str(e).upper()
                    if 'AUTHKEY' in s or 'DEACTIVATED' in s:
                        await send_logout_notification(acc, s[:50])
                        await handle_banned(acc)
                        return
                
                if cfg['max'] > 0:
                    await asyncio.sleep(random.uniform(cfg['min'], cfg['max']))
            
            if errors > 10:
                await asyncio.sleep(30)
                errors = 0
            
            cycle += 1
            
            # Reconnect periodically
            if cycle % 30 == 0:
                try:
                    await client.disconnect()
                    await asyncio.sleep(2)
                    client = TelegramClient(
                        StringSession(acc['session']),
                        acc.get('api_id', DEFAULT_API_ID),
                        acc.get('api_hash', DEFAULT_API_HASH),
                        receive_updates=True,
                        sequential_updates=False
                    )
                    await client.start()
                    groups = await get_user_groups(client)
                    max_b = min(cfg['batch'], len(groups))
                except:
                    pass
            
            if cfg['cycle'] > 0:
                for _ in range(cfg['cycle']):
                    if account_stop_flags.get(acc_id, False):
                        break
                    await asyncio.sleep(1)
    
    except asyncio.CancelledError:
        logger.info(f"Spam cancelled: {acc_name}")
    except Exception as e:
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
# BOT UI (PTB) - সংক্ষিপ্ত
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

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, logout_notification_enabled
    
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data
    
    if uid != OWNER_ID and uid not in admins:
        await query.edit_message_text("❌ Access Denied!")
        return
    
    if data == "main":
        await query.edit_message_text(
            "🤖 **HACKER AI CONTROL PANEL** 🤖" + NL + NL + "Select:",
            reply_markup=main_keyboard()
        )
        return
    
    # --- Auto Reply ---
    if data == "m_ar":
        rc = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('running', False))
        status = "🟢 ON" if auto_reply_enabled else "🔴 OFF"
        txt = f"📨 **AR** | {status}" + NL + f"🟢 {rc}/{len(active_accounts)} active"
        kb = [
            [InlineKeyboardButton(f"{'🔴' if auto_reply_enabled else '🟢'} Toggle", callback_data="ar_t")],
            [InlineKeyboardButton("▶️ Start All", callback_data="ar_start"), InlineKeyboardButton("⏹️ Stop All", callback_data="ar_stop")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "ar_t":
        auto_reply_enabled = not auto_reply_enabled
        await query.edit_message_text(f"✅ AR {'ON' if auto_reply_enabled else 'OFF'}!")
        await asyncio.sleep(0.5)
        update.callback_query.data = "m_ar"
        await handle_callback(update, context)
        return
    
    if data == "ar_start":
        for a in active_accounts:
            account_stats[a['id']]['running'] = True
        await query.edit_message_text("✅ AR Started!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    if data == "ar_stop":
        for a in active_accounts:
            account_stats[a['id']]['running'] = False
        await query.edit_message_text("⏹️ AR Stopped!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    # --- Group Spam ---
    if data == "m_gs":
        run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        st = "🟢 ON" if group_spam_enabled else "🔴 OFF"
        sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        txt = f"📯 **GS** | {st}" + NL + f"🏃 {run}/{len(active_accounts)}" + NL + f"📤 {sent}"
        kb = [
            [InlineKeyboardButton(f"{'🔴' if group_spam_enabled else '🟢'} Toggle", callback_data="gs_t")],
            [InlineKeyboardButton("▶️ Start", callback_data="gs_on"), InlineKeyboardButton("⏹️ Stop", callback_data="gs_off")],
            [InlineKeyboardButton("📊 Stats", callback_data="gs_st")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "gs_t":
        group_spam_enabled = not group_spam_enabled
        await query.edit_message_text(f"✅ GS {'ON' if group_spam_enabled else 'OFF'}!")
        await asyncio.sleep(0.5)
        update.callback_query.data = "m_gs"
        await handle_callback(update, context)
        return
    
    if data == "gs_on":
        start_spam()
        await query.edit_message_text("▶️ Started!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
        return
    
    if data == "gs_off":
        stop_spam()
        await query.edit_message_text("⏹️ Stopped!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
        return
    
    if data == "gs_st":
        txt = "📊 **Stats**" + NL + NL
        for a in active_accounts:
            s = account_stats.get(a['id'], {}).get('spam_sent', 0)
            r = "🟢" if account_stats.get(a['id'], {}).get('spam_running', False) else "🔴"
            ar = "🟢" if account_stats.get(a['id'], {}).get('running', False) else "🔴"
            txt += f"{r}S/{ar}A {a.get('name','?')}: {s}" + NL
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
        return
    
    # --- Accounts ---
    if data == "m_acc":
        da = load_accounts()
        al = da.get('accounts', [])
        txt = f"👤 **Accounts**" + NL + f"📌 {len(al)} | 🟢 {len(active_accounts)}"
        kb = [
            [InlineKeyboardButton("📱 Phone+OTP", callback_data="ac_ph")],
            [InlineKeyboardButton("🔑 Session", callback_data="ac_ss")],
            [InlineKeyboardButton("📋 List", callback_data="ac_ls")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return
    
    if data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("📱 **Phone**" + NL + "`+8801XXXXXXXXX`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        return
    
    if data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("🔑 **Paste Session**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        return
    
    if data == "ac_ls":
        da = load_accounts()
        al = da.get('accounts', [])
        if not al:
            await query.edit_message_text("❌ No accounts!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        txt = f"📋 **All ({len(al)})**" + NL + NL
        for a in al:
            st = "🟢" if any(x['id'] == a['id'] for x in active_accounts) else "🔴"
            bk = "💾" if a.get('is_backup') else "📌"
            txt += f"{bk}{st} {a.get('name','?')[:12]}" + NL
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        return
    
    # --- Status ---
    if data == "m_stat":
        ar = "🟢" if auto_reply_enabled else "🔴"
        gs = "🟢" if group_spam_enabled else "🔴"
        spam_run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        spam_sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        txt = f"📊 **STATUS**" + NL + f"📨AR:{ar} 📯GS:{gs}" + NL + f"🟢{len(active_accounts)}" + NL + f"🏃{spam_run} 📤{spam_sent}"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="m_stat")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]))
        return
    
    # --- Admin ---
    if data == "m_adm":
        txt = f"🔐 **Admin**" + NL + f"👑{OWNER_ID}" + NL + f"👥{len(admins)-1}"
        if uid == OWNER_ID:
            kb = [[InlineKeyboardButton("🏠 Menu", callback_data="main")]]
        else:
            kb = [[InlineKeyboardButton("🏠 Menu", callback_data="main")]]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return


# ═══════════════════════════════════════════
# TEXT HANDLER
# ═══════════════════════════════════════════
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    await_state = context.user_data.get('await')
    
    if await_state:
        if await_state == 'ac_ph':
            context.user_data['await'] = 'ac_otp'
            context.user_data['ac_phone'] = text
            await update.message.reply_text(f"📱 Sending code to `{text}`...")
            asyncio.create_task(send_code(text, update, context))
            return
        
        if await_state == 'ac_otp':
            phone = context.user_data.get('ac_phone', '')
            code = text.strip()
            asyncio.create_task(complete_login(phone, code, update, context))
            del context.user_data['await']
            return
        
        if await_state == 'ac_ss':
            asyncio.create_task(add_session_account(text, update, context, is_backup=False))
            del context.user_data['await']
            return
        
        del context.user_data['await']
        return


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
            await update.message.reply_text("❌ Session expired!")
            return
        
        await client.sign_in(phone, code, phone_code_hash=ph_hash)
        me = await client.get_me()
        ss = client.session.save()
        
        info = {
            'id': f"acc_{int(time.time())}",
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
            'id': f"acc_{int(time.time())}",
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
# ACCOUNT HEALTH CHECK
# ═══════════════════════════════════════════
async def account_health_check():
    while True:
        await asyncio.sleep(60)
        try:
            for acc in list(active_accounts):
                acc_id = acc['id']
                if acc_id not in account_clients:
                    continue
                
                try:
                    await asyncio.wait_for(account_clients[acc_id].get_me(timeout=2), timeout=3)
                except:
                    logger.warning(f"Restarting account: {acc.get('name','?')}")
                    try:
                        await account_clients[acc_id].disconnect()
                    except:
                        pass
                    del account_clients[acc_id]
                    
                    client = await start_account(acc)
                    if client:
                        account_clients[acc_id] = client
                        logger.info(f"Restarted: {acc.get('name','?')}")
        except:
            pass


# ═══════════════════════════════════════════
# POLLING
# ═══════════════════════════════════════════
async def polling_with_reconnect(app):
    for attempt in range(10):
        try:
            await app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                timeout=30,
                poll_interval=0.5
            )
            logger.info("Polling started")
            return
        except Exception as e:
            logger.warning(f"Polling attempt {attempt+1} failed: {e}")
            await asyncio.sleep(5)


# ═══════════════════════════════════════════
# SETUP APPLICATION
# ═══════════════════════════════════════════
def setup_application():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════
async def main():
    global start_time
    start_time = time.time()
    
    logger.info("Starting bot...")
    
    _load_settings()
    load_replies()
    
    data = load_accounts()
    accounts = data.get('accounts', [])
    logger.info(f"Loaded {len(accounts)} accounts")
    
    for acc in accounts:
        if acc.get('is_backup'):
            continue
        
        session_str = acc.get('session', '')
        if not session_str:
            continue
        
        try:
            client = await start_account(acc)
            if client:
                active_accounts.append(acc)
                account_clients[acc['id']] = client
                account_stats[acc['id']]['running'] = True
                account_stop_flags[acc['id']] = False
                logger.info(f"Active: {acc.get('name','?')}")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed: {acc.get('name','?')}: {e}")
    
    logger.info(f"Active accounts: {len(active_accounts)}")
    
    # Start services
    await web_server()
    asyncio.create_task(periodic_cleanup())
    asyncio.create_task(ping_loop())
    asyncio.create_task(account_health_check())
    
    # Setup PTB
    app = setup_application()
    await app.initialize()
    await app.start()
    await polling_with_reconnect(app)
    
    logger.info(f"Bot running! Owner: {OWNER_ID}")
    
    try:
        while True:
            await asyncio.sleep(30)
            alive = sum(1 for a in active_accounts if a['id'] in account_clients)
            spam_run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
            logger.info(f"Heartbeat: {alive}/{len(active_accounts)} active, {spam_run} spamming")
    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        stop_spam()
        for client in account_clients.values():
            try:
                await client.disconnect()
            except:
                pass
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            sys.exit(0)
        except Exception as e:
            logger.exception(f"Fatal: {e}")
            logger.info("Restarting in 10 seconds...")
            time.sleep(10)

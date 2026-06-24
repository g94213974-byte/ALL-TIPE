#!/usr/bin/env python3
"""
UNIFIED TELEGRAM BOT - COMPLETE FIXED VERSION
All problems solved:
1. Auto reply no longer takes 10-20 min 
2. Settings no longer auto-delete
3. Typing effect ON by default - you can OFF from menu
4. Polling mode - no webhook needed
5. Group spam + Auto reply runs together
"""

import os, sys, json, asyncio, random, logging, threading, time, uuid
from datetime import datetime
from typing import Optional, Dict, List, Any
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

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

import socks
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

from flask import Flask, jsonify, request

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PAYMENT_SS_DIR = BASE_DIR / "payment_screenshots"
PAYMENT_ASSETS_DIR = BASE_DIR / "payment_assets"
for d in [DATA_DIR, PAYMENT_SS_DIR, PAYMENT_ASSETS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
REPLIES_FILE = DATA_DIR / "replies.json"
BANNED_FILE = DATA_DIR / "banned_accounts.json"
SPAM_MSG_FILE = DATA_DIR / "spam_messages.json"

flask_app = Flask(__name__)
ptb_application = None
bot_event_loop = None

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
bot_ready = False
shutdown_event = asyncio.Event()
logout_notification_enabled = True

_settings_cache = {}
_settings_cache_dirty = False
_replies_cache = []
_replies_cache_dirty = False

DEFAULT_SETTINGS = {
    'auto_reply_enabled': True,
    'group_spam_enabled': True,
    'welcome_enabled': True,
    'block_photo_enabled': True,
    'typing_enabled': True,  # DEFAULT: ON - you can OFF from menu
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
    'price_list_text': '🔥 10 MIN VC → ₹99\n🔥 20 MIN VC → ₹119',
    'upi_id': '',
    'paytm_num': '',
    'welcome_message': '🔥 Welcome Baby! 🔥\n\n10 MIN VC → ₹99\n20 MIN VC → ₹119',
    'welcome_message2': '🛒 How to order?\n\n1️⃣ Pay via UPI/PayTm\n2️⃣ Send screenshot\n3️⃣ Enjoy VC call! 💋',
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

# ============ FIXED PERSISTENCE HELPERS ============

def _load_settings_to_cache():
    global _settings_cache
    try:
        if SETTINGS_FILE.exists() and SETTINGS_FILE.stat().st_size > 0:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    _settings_cache = json.loads(content)
                else:
                    _settings_cache = {}
        else:
            _settings_cache = {}
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Settings file corrupt, resetting: {e}")
        _settings_cache = {}
    
    for k, v in DEFAULT_SETTINGS.items():
        if k not in _settings_cache:
            _settings_cache[k] = v
    
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(_settings_cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Settings initial save failed: {e}")

def _load_replies_to_cache():
    global _replies_cache
    try:
        if REPLIES_FILE.exists() and REPLIES_FILE.stat().st_size > 0:
            with open(REPLIES_FILE, 'r', encoding='utf-8') as f:
                _replies_cache = json.load(f)
        else:
            _replies_cache = []
    except:
        _replies_cache = []

def get_setting(key, default=None):
    if not _settings_cache:
        _load_settings_to_cache()
    return _settings_cache.get(key, default if default is not None else DEFAULT_SETTINGS.get(key))

def set_setting(key, value):
    global _settings_cache, _settings_cache_dirty
    if not _settings_cache:
        _load_settings_to_cache()
    _settings_cache[key] = value
    # DIRECT WRITE - no tmp file swap
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(_settings_cache, f, indent=2, ensure_ascii=False)
        _settings_cache_dirty = False
    except Exception as e:
        logger.error(f"Settings save failed: {e}")
        _settings_cache_dirty = True

def load_replies():
    if not _replies_cache:
        _load_replies_to_cache()
    return _replies_cache

def add_reply(keyword, reply, match_type="contains"):
    global _replies_cache, _replies_cache_dirty
    if not _replies_cache:
        _load_replies_to_cache()
    rid = max([x.get('id', 0) for x in _replies_cache], default=0) + 1
    _replies_cache.append({'id': rid, 'keyword': keyword, 'reply': reply, 'type': match_type, 'created_at': datetime.now().isoformat()})
    _replies_cache_dirty = True
    save_json(REPLIES_FILE, _replies_cache)
    return rid

def add_replies_bulk(data_list):
    global _replies_cache, _replies_cache_dirty
    if not _replies_cache:
        _load_replies_to_cache()
    ids = []
    for kw, reply, mt in data_list:
        rid = max([x.get('id', 0) for x in _replies_cache], default=0) + 1
        _replies_cache.append({'id': rid, 'keyword': kw, 'reply': reply, 'type': mt, 'created_at': datetime.now().isoformat()})
        ids.append(rid)
    _replies_cache_dirty = True
    save_json(REPLIES_FILE, _replies_cache)
    return ids

def delete_reply(rid):
    global _replies_cache, _replies_cache_dirty
    if not _replies_cache:
        _load_replies_to_cache()
    old_len = len(_replies_cache)
    _replies_cache = [x for x in _replies_cache if x['id'] != rid]
    if len(_replies_cache) != old_len:
        _replies_cache_dirty = True
        save_json(REPLIES_FILE, _replies_cache)
        return True
    return False

def load_spam_messages():
    return load_json(SPAM_MSG_FILE, [])

def save_spam_messages(msgs):
    save_json(SPAM_MSG_FILE, msgs)

def add_spam_message(msg):
    msgs = load_spam_messages()
    msgs.append({'id': int(time.time()), 'text': msg, 'added_at': datetime.now().isoformat()})
    save_spam_messages(msgs)
    return True

def delete_spam_message(msg_id):
    msgs = load_spam_messages()
    msgs = [m for m in msgs if m['id'] != msg_id]
    save_spam_messages(msgs)
    return True

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

def load_accounts_data():
    return load_json(ACCOUNTS_FILE, {'main': [], 'backup': []})

def get_all_accounts():
    d = load_accounts_data()
    return d.get('main', []) + d.get('backup', [])

def get_main_accounts():
    return load_accounts_data().get('main', [])

def get_backup_accounts():
    return load_accounts_data().get('backup', [])

def add_account_data(acc, is_backup=False):
    d = load_accounts_data()
    key = 'backup' if is_backup else 'main'
    for existing in d[key]:
        if existing.get('user_id') == acc.get('user_id') or existing.get('session') == acc.get('session'):
            logger.warning(f"Duplicate account skipped: {acc.get('name', 'Unknown')}")
            return False
    d[key].append(acc)
    save_json(ACCOUNTS_FILE, d)
    return True

def remove_account_data(aid):
    d = load_accounts_data()
    found = False
    for key in ['main', 'backup']:
        original_len = len(d[key])
        d[key] = [a for a in d[key] if a.get('id') != aid]
        if len(d[key]) < original_len:
            found = True
    if found:
        save_json(ACCOUNTS_FILE, d)
        return True
    return False

def find_account(aid):
    for a in get_all_accounts():
        if a['id'] == aid:
            return a
    return None

def gen_acc_id():
    return f"acc_{int(time.time())}_{random.randint(100, 999)}"

# ============ TYPING EFFECT (CAPPED) ============

async def send_with_typing(client, chat_id, message_text):
    """Send message with typing effect - capped at 3 seconds max"""
    seen_delay = int(get_setting('seen_delay', 1))
    typing_duration = int(get_setting('typing_duration', 2))
    typing_enabled = get_setting('typing_enabled', True)
    
    # CAP total delay to max 3 seconds
    total_delay = seen_delay + (typing_duration if typing_enabled else 0)
    actual_delay = min(total_delay, 3)
    
    if actual_delay > 0:
        await asyncio.sleep(actual_delay)
    
    if typing_enabled and typing_duration > 0:
        try:
            async with client.action(chat_id, 'typing'):
                await asyncio.sleep(min(typing_duration, 3))
        except:
            pass
    
    await client.send_message(chat_id, message_text)

# ============ ACCOUNT MANAGEMENT ============

async def send_logout_notification(acc, reason="Unknown"):
    if not logout_notification_enabled:
        return
    try:
        name = acc.get('name', 'Unknown')
        phone = acc.get('phone', 'N/A')
        acc_id = acc.get('id', '?')
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"⚠️ **ACCOUNT LOGOUT DETECTED!** ⚠️\n\n"
                 f"👤 Name: {name}\n"
                 f"🆔 ID: {acc_id}\n"
                 f"📱 Phone: {phone}\n"
                 f"❌ Reason: {reason}\n"
                 f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                 f"🔄 Auto-replacing with backup..."
        )
    except Exception as e:
        logger.warning(f"Failed to send logout notification: {e}")

async def send_backup_activation_notification(backup):
    if not logout_notification_enabled:
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"✅ **BACKUP ACTIVATED!** ✅\n\n"
                 f"👤 New Active: {backup.get('name', 'Unknown')}\n"
                 f"📱 Phone: {backup.get('phone', 'N/A')}\n"
                 f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                 f"🟢 System is fully operational."
        )
    except:
        pass

async def keep_alive_loop(acc_id, client, interval=60):
    """Keep alive every 60 seconds with timeout"""
    acc = find_account(acc_id)
    name = acc.get('name', acc_id) if acc else acc_id
    logger.info(f"[KEEPALIVE] Started for {name} (every {interval}s)")
    
    while not account_stop_flags.get(acc_id, False):
        try:
            me = await client.get_me(timeout=5)
            if not me:
                raise AuthKeyUnregisteredError("Session returned None")
        except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
            logger.warning(f"[KEEPALIVE] {name} - SESSION DEAD: {e}")
            real_acc = find_account(acc_id)
            if real_acc:
                await send_logout_notification(real_acc, str(e)[:50])
                await handle_banned(real_acc)
            return
        except asyncio.TimeoutError:
            logger.warning(f"[KEEPALIVE] {name} - Timeout, retrying...")
        except Exception as e:
            logger.warning(f"[KEEPALIVE] {name} - Error: {e}")
        
        for _ in range(interval):
            if account_stop_flags.get(acc_id, False):
                break
            await asyncio.sleep(1)
# ============ MISSING ACCOUNT FUNCTIONS - ADD THESE ============

def load_accounts():
    """Load accounts from accounts.json"""
    try:
        if ACCOUNTS_FILE.exists() and ACCOUNTS_FILE.stat().st_size > 0:
            with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return {'accounts': data}
                    return data
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Accounts file corrupt: {e}")
    return {'accounts': []}


def save_accounts(data):
    """Save accounts to accounts.json"""
    try:
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save accounts: {e}")
        return False


def set_account_proxy(acc_id, proxy_config):
    """Set or remove proxy for an account"""
    data = load_accounts()
    for acc in data.get('accounts', []):
        if acc['id'] == acc_id:
            if proxy_config:
                acc['proxy'] = proxy_config
            else:
                acc['proxy'] = None
            save_accounts(data)
            for a in active_accounts:
                if a['id'] == acc_id:
                    a['proxy'] = proxy_config
            return True
    return False
    
async def check_account_status_periodically():
    logger.info("[CHECKER] Account status monitor started (every 10s)")
    while not shutdown_event.is_set():
        try:
            for acc in list(active_accounts):
                acc_id = acc['id']
                name = acc.get('name', 'Unknown')
                if acc_id in account_clients:
                    client = account_clients[acc_id]
                    try:
                        me = await client.get_me(timeout=5)
                        if not me:
                            raise AuthKeyUnregisteredError("No user returned")
                    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
                        logger.warning(f"[CHECKER] INSTANT LOGOUT: {name}")
                        await send_logout_notification(acc, str(e)[:50])
                        await handle_banned(acc)
                    except:
                        pass
        except:
            pass
        await asyncio.sleep(10)

async def start_account(acc):
    try:
        proxy_config = acc.get('proxy')
        proxy = None
        if proxy_config and proxy_config.get('addr'):
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
        logger.info(f"Account started: {me.first_name} ({me.id})")
        acc_id = acc['id']
        custom_msgs = load_spam_messages()
        if custom_msgs:
            account_spam_messages[acc_id] = [m['text'] for m in custom_msgs]
        else:
            base_msg = get_setting('spam_message', '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')
            account_spam_messages[acc_id] = [
                base_msg,
                f"{base_msg} 💋", f"{base_msg} 🔥", f"{base_msg} 💖",
                f"🔥 {base_msg}", f"💋 {base_msg}", f"✨ {base_msg} 😘",
                f"{base_msg} 👑", f"✅ {base_msg} ✅", f"👉 {base_msg} 👈"
            ]
        if acc_id in account_keepalive_tasks:
            account_keepalive_tasks[acc_id].cancel()
        account_keepalive_tasks[acc_id] = asyncio.create_task(keep_alive_loop(acc_id, client, interval=60))
        return client
    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
        logger.warning(f"Account banned/deactivated: {acc.get('name', 'Unknown')}")
        await send_logout_notification(acc, str(e)[:50])
        await handle_banned(acc)
        return None
    except Exception as e:
        logger.error(f"Failed to start account {acc.get('name', 'Unknown')}: {e}")
        return None

async def handle_banned(acc):
    acc_id = acc['id']
    name = acc.get('name', 'Unknown')
    logger.warning(f"Processing banned account: {name} ({acc_id})")
    banned = load_json(BANNED_FILE, [])
    if not any(b['id'] == acc_id for b in banned):
        banned.append({'id': acc_id, 'name': name, 'phone': acc.get('phone', 'N/A'), 'banned_at': datetime.now().isoformat()})
        save_json(BANNED_FILE, banned)
    if acc_id in account_keepalive_tasks and not account_keepalive_tasks[acc_id].done():
        account_keepalive_tasks[acc_id].cancel()
        try: await account_keepalive_tasks[acc_id]
        except: pass
        del account_keepalive_tasks[acc_id]
    active_accounts[:] = [a for a in active_accounts if a['id'] != acc_id]
    if acc_id in account_clients:
        try:
            await account_clients[acc_id].disconnect()
            await asyncio.sleep(0.3)
        except: pass
        del account_clients[acc_id]
    if acc_id in account_spam_tasks and not account_spam_tasks[acc_id].done():
        account_spam_tasks[acc_id].cancel()
        try: await account_spam_tasks[acc_id]
        except: pass
        del account_spam_tasks[acc_id]
    account_stop_flags[acc_id] = True
    for d in [account_spam_active, account_stats]:
        if acc_id in d: del d[acc_id]
    remove_account_data(acc_id)
    backups = get_backup_accounts()
    if backups:
        backup = backups[0]
        backup_copy = dict(backup)
        backup_copy['is_backup'] = False
        backup_copy['enabled'] = True
        remove_account_data(backup['id'])
        add_account_data(backup_copy, is_backup=False)
        await send_backup_activation_notification(backup_copy)
        client = await start_account(backup_copy)
        if client:
            active_accounts.append(backup_copy)
            account_clients[backup_copy['id']] = client
            account_stats[backup_copy['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
            account_stop_flags[backup_copy['id']] = False
            account_spam_active[backup_copy['id']] = False
            register_ar(client, backup_copy)

# ============ AUTO REPLY HANDLER ============

def register_ar(client, acc):
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

async def send_dual_welcome(client, chat_id):
    """Send 1st welcome (msg+pic), then 2nd welcome (msg only) with delay"""
    wm1 = get_setting('welcome_message', '🔥 Welcome Baby! 🔥\n\n10 MIN VC → ₹99\n20 MIN VC → ₹119')
    wi1 = get_setting('welcome_image', '')
    
    if wi1 and Path(wi1).exists():
        try:
            await client.send_file(chat_id, wi1, caption=wm1)
        except:
            await send_with_typing(client, chat_id, wm1)
    else:
        await send_with_typing(client, chat_id, wm1)
    
    await asyncio.sleep(1.5)
    
    wm2 = get_setting('welcome_message2', '🛒 How to order?\n\n1️⃣ Pay via UPI/PayTm\n2️⃣ Send screenshot\n3️⃣ Enjoy VC call! 💋')
    wi2 = get_setting('welcome_image2', '')
    
    if wi2 and Path(wi2).exists():
        try:
            await client.send_file(chat_id, wi2, caption=wm2)
        except:
            await send_with_typing(client, chat_id, wm2)
    else:
        await send_with_typing(client, chat_id, wm2)

async def process_auto_reply_fast(event, client, acc, uid):
    chat_id = event.chat_id
    message_text = event.message.text or ""
    if uid not in customer_count:
        customer_count[uid] = 0
    prev_count = customer_count[uid]
    
    if event.message.photo or (event.message.document and event.message.document.mime_type and 'image' in event.message.document.mime_type):
        if get_setting('block_photo_enabled', True):
            asyncio.create_task(block_user_and_delete_photos(event, client, uid))
        else:
            asyncio.create_task(handle_payment_screenshot(event, client, uid))
        return
    if not message_text.strip():
        return
    msg_lower = message_text.lower().strip()
    try:
        input_chat = await event.get_input_chat()
        await client(ReadHistoryRequest(peer=input_chat, max_id=event.message.id))
    except:
        pass
    if prev_count == 0 and get_setting('welcome_enabled', True):
        await send_dual_welcome(client, chat_id)
        customer_count[uid] = prev_count + 1
        return
    ignored = get_setting('ignored_messages', '')
    if ignored:
        for line in ignored.split('\n'):
            if line.strip().lower() == msg_lower:
                customer_count[uid] = prev_count + 1
                return
    for reply_entry in load_replies():
        keyword = reply_entry['keyword'].lower().strip()
        if reply_entry['type'] == 'exact' and msg_lower == keyword:
            await send_with_typing(client, chat_id, reply_entry['reply'])
            customer_count[uid] = prev_count + 1
            return
        elif reply_entry['type'] == 'contains' and keyword in msg_lower:
            await send_with_typing(client, chat_id, reply_entry['reply'])
            customer_count[uid] = prev_count + 1
            return
    payment_keywords = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'send', 'bhejo', 'screenshot', 'method', 'transfer', 'rupees', 'rs', 'money']
    if any(kw in msg_lower for kw in payment_keywords):
        await send_payment_info(client, chat_id, event)
        customer_count[uid] = prev_count + 1
        return
    media_keywords = ['pic', 'photo', 'image', 'nude', 'naked', 'dikhao', 'show', 'nangi', 'boob', 'mms']
    if any(kw in msg_lower for kw in media_keywords):
        await send_with_typing(client, chat_id, get_setting('media_keyword_reply', 'Payment first baby 😘🔥'))
        customer_count[uid] = prev_count + 1
        return
    service_keywords = ['service', 'chahiye', 'kharid', 'demo', 'video', 'call', 'vc', 'price', 'rate']
    if any(kw in msg_lower for kw in service_keywords):
        price_text = get_setting('price_list_text', "🔥 10 MIN VC → ₹99\n🔥 20 MIN VC → ₹119")
        price_image = get_setting('price_list_image', '')
        if price_image and Path(price_image).exists():
            try:
                await client.send_file(chat_id, price_image, caption=price_text)
            except:
                await send_with_typing(client, chat_id, price_text)
        else:
            await send_with_typing(client, chat_id, price_text)
        await asyncio.sleep(0.3)
        await send_with_typing(client, chat_id, random.choice(["How many minutes? 🔥", "Pay and enjoy! 😘", "Tell me your choice 💋"]))
        customer_count[uid] = prev_count + 1
        return
    offline_keywords = ['real', 'meet', 'aao', 'ghar', 'location', 'offline']
    if any(kw in msg_lower for kw in offline_keywords):
        await send_with_typing(client, chat_id, get_setting('offline_keyword_reply', 'Online only baby 😊'))
        customer_count[uid] = prev_count + 1
        return
    greeting_keywords = ['hi', 'hello', 'hey', 'hii', 'hy', 'hlo']
    if any(w in msg_lower for w in greeting_keywords):
        greetings = get_setting('greeting_replies', ['Hi baby, ready! 🔥', 'Hey baby! 😘', 'Hello! What you need? 🔥'])
        await send_with_typing(client, chat_id, random.choice(greetings))
        customer_count[uid] = prev_count + 1
        return
    if get_setting('default_reply_enabled', False):
        reply = get_setting('default_reply_text', '')
        if reply:
            await send_with_typing(client, chat_id, reply)
    else:
        defaults = get_setting('default_replies', ['Ready baby! Pay karo! 🔥', 'Main ready hoon! 😘', 'Service ready! 💯'])
        await send_with_typing(client, chat_id, random.choice(defaults))
    customer_count[uid] = prev_count + 1

async def send_payment_info(client, chat_id, event):
    upi = get_setting('upi_id', '')
    paytm = get_setting('paytm_num', '')
    qr_path = get_setting('qr_code_path', '')
    payment_msg = "**💰 Payment 💰**\n\n"
    if upi:
        payment_msg += f"📱 UPI: {upi}\n"
    if paytm:
        payment_msg += f"💳 PayTm: {paytm}\n"
    payment_msg += f"\n{get_setting('payment_keyword_reply', 'Scan & Pay baby 😘🔥')}"
    
    if qr_path:
        try:
            if qr_path.startswith('http://') or qr_path.startswith('https://'):
                payment_msg = f"**💰 Payment 💰**\n\n"
                if upi: payment_msg += f"📱 UPI: {upi}\n"
                if paytm: payment_msg += f"💳 PayTm: {paytm}\n"
                payment_msg += f"\n📷 QR: {qr_path}\n\n{get_setting('payment_keyword_reply', 'Scan & Pay baby 😘🔥')}"
                await send_with_typing(client, chat_id, payment_msg)
            elif Path(qr_path).exists():
                await client.send_file(chat_id, qr_path, caption=payment_msg)
            else:
                await send_with_typing(client, chat_id, payment_msg)
        except:
            await send_with_typing(client, chat_id, payment_msg)
    else:
        await send_with_typing(client, chat_id, payment_msg)

async def block_user_and_delete_photos(event, client, uid):
    try:
        input_chat = await event.get_input_chat()
        try: await client.delete_messages(input_chat, [event.message.id], revoke=True)
        except: pass
        try:
            async for msg in client.iter_messages(input_chat, limit=100):
                try: await client.delete_messages(input_chat, [msg.id], revoke=True)
                except: pass
        except: pass
        try: await client.delete_dialog(input_chat)
        except: pass
        await asyncio.sleep(1)
        try: await client(BlockRequest(id=uid))
        except: pass
        try: await client(DeleteContactsRequest(id=[uid]))
        except: pass
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
            await client.send_message(OWNER_ID, f"✅ PAYMENT RECEIVED!\n👤 Name: {sender_name}\n🆔 ID: {uid}")
            await client.send_file(OWNER_ID, str(file_path))
        except: pass
        customer_count[uid] = -2
    except Exception as e:
        logger.error(f"Payment screenshot handling failed: {e}")

async def setup_auto_reply():
    logger.info("Setting up auto-reply for main accounts...")
    _load_settings_to_cache()
    _load_replies_to_cache()
    for acc in get_main_accounts():
        if acc['id'] not in [a['id'] for a in active_accounts]:
            client = await start_account(acc)
            if client:
                active_accounts.append(acc)
                account_clients[acc['id']] = client
                account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
                account_stop_flags[acc['id']] = False
                register_ar(client, acc)
                logger.info(f"Auto-reply active for: {acc.get('name', 'Unknown')}")
            await asyncio.sleep(1)

# ============ GROUP SPAM ============

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
            except: pass
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
    logger.info(f"Starting spam for: {acc_name}")
    try:
        proxy_config = acc.get('proxy')
        proxy = None
        if proxy_config and proxy_config.get('addr'):
            proxy = (socks.SOCKS5, proxy_config.get('addr', ''), proxy_config.get('port', 1080),
                     proxy_config.get('rdns', True), proxy_config.get('username', ''), proxy_config.get('password', ''))
        client = TelegramClient(StringSession(acc['session']), acc.get('api_id', DEFAULT_API_ID),
                                acc.get('api_hash', DEFAULT_API_HASH), proxy=proxy, receive_updates=False)
        await client.start()
        groups = await get_user_groups(client)
        if not groups:
            logger.warning(f"No groups found for {acc_name}")
            account_stats[acc_id]['spam_running'] = False
            account_spam_active[acc_id] = False
            return
        logger.info(f"Spamming {len(groups)} groups with {acc_name}")
        speed = get_setting('spam_speed', 'medium')
        speed_configs = {
            'super_fast': {'batch_size': 999, 'batch_delay': 0, 'cycle_delay': 0, 'min_interval': 0, 'max_interval': 1.5},
            'fast': {'batch_size': 999, 'batch_delay': 0, 'cycle_delay': 5, 'min_interval': 0.5, 'max_interval': 2},
            'medium': {'batch_size': 5, 'batch_delay': 2, 'cycle_delay': 15, 'min_interval': 2, 'max_interval': 4},
            'slow': {'batch_size': 3, 'batch_delay': 5, 'cycle_delay': 30, 'min_interval': 5, 'max_interval': 8},
            'custom': {'batch_size': int(get_setting('spam_batch_size', 6)), 'batch_delay': int(get_setting('spam_batch_delay', 3)),
                       'cycle_delay': int(get_setting('spam_cycle_wait', 30)), 'min_interval': int(get_setting('spam_min_interval', 3)),
                       'max_interval': int(get_setting('spam_max_interval', 6))}
        }
        config = speed_configs.get(speed, speed_configs['medium'])
        flood_slow_mode = get_setting('flood_slow_mode', True)
        spam_messages = account_spam_messages.get(acc_id, [get_setting('spam_message', '...')])
        msg_index = 0
        cycle_count = 0
        error_count = 0
        max_batch = min(config['batch_size'], len(groups))
        while not account_stop_flags.get(acc_id, False):
            if not group_spam_enabled:
                await asyncio.sleep(3)
                continue
            if not account_spam_active.get(acc_id, True):
                await asyncio.sleep(5)
                continue
            for group in groups[:max_batch]:
                if account_stop_flags.get(acc_id, False) or not account_spam_active.get(acc_id, True):
                    break
                try:
                    message = spam_messages[msg_index % len(spam_messages)]
                    await client.send_message(group, message)
                    account_stats[acc_id]['spam_sent'] += 1
                    error_count = 0
                    msg_index += 1
                except FloodWaitError as e:
                    wait_time = e.seconds
                    logger.warning(f"Flood wait: {wait_time}s for {acc_name}")
                    error_count += 1
                    await asyncio.sleep(min(wait_time, 30) if flood_slow_mode else wait_time)
                except Exception as e:
                    error_count += 1
                    error_str = str(e).upper()
                    if 'FLOOD' in error_str and flood_slow_mode:
                        await asyncio.sleep(5)
                    elif 'AUTHKEY' in error_str or 'DEACTIVATED' in error_str:
                        await send_logout_notification(acc, error_str[:50])
                        await handle_banned(acc)
                        return
                if config['max_interval'] > 0:
                    await asyncio.sleep(random.uniform(config['min_interval'], config['max_interval']))
            if account_stop_flags.get(acc_id, False):
                break
            if config['batch_delay'] > 0 and len(groups) > max_batch:
                await asyncio.sleep(config['batch_delay'])
            if error_count > 10:
                await asyncio.sleep(60)
                error_count = 0
            cycle_count += 1
            if cycle_count % 20 == 0 and not account_stop_flags.get(acc_id, False):
                try:
                    await client.disconnect()
                    await asyncio.sleep(3)
                    client = TelegramClient(StringSession(acc['session']), acc.get('api_id', DEFAULT_API_ID),
                                            acc.get('api_hash', DEFAULT_API_HASH), proxy=proxy, receive_updates=False)
                    await client.start()
                    groups = await get_user_groups(client)
                    max_batch = min(config['batch_size'], len(groups))
                except: pass
            if config['cycle_delay'] > 0:
                for _ in range(config['cycle_delay']):
                    if account_stop_flags.get(acc_id, False): break
                    await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info(f"Spam cancelled for: {acc_name}")
    except Exception as e:
        if 'AuthKey' in str(e) or 'DEACTIVATED' in str(e):
            await send_logout_notification(acc, str(e)[:50])
            await handle_banned(acc)
        else:
            logger.error(f"Spam error for {acc_name}: {e}")
    finally:
        account_stats[acc_id]['spam_running'] = False
        account_spam_active[acc_id] = False
        try: await client.disconnect()
        except: pass
        logger.info(f"Spam stopped for: {acc_name}")

def stop_spam(acc_id=None):
    if acc_id:
        account_stop_flags[acc_id] = True
        account_spam_active[acc_id] = False
        if acc_id in account_spam_tasks and not account_spam_tasks[acc_id].done():
            account_spam_tasks[acc_id].cancel()
        account_stats[acc_id]['spam_running'] = False
    else:
        for acc in active_accounts:
            stop_spam(acc['id'])

def start_spam(acc_id=None):
    targets = [a for a in active_accounts if a['id'] == acc_id] if acc_id else active_accounts
    for acc in targets:
        if not account_stats.get(acc['id'], {}).get('spam_running', False):
            account_spam_active[acc['id']] = True
            account_stop_flags[acc['id']] = False
            task = asyncio.create_task(spam_account(acc))
            account_spam_tasks[acc['id']] = task

# ============ OTP SIGN IN ============

async def sign_in_with_code(phone, code, client, update, context):
    try:
        await client.sign_in(phone=phone, code=code)
        me = await client.get_me()
        ss = client.session.save()
        info = {
            'id': gen_acc_id(), 'user_id': me.id,
            'name': me.first_name or f"User{me.id}",
            'phone': getattr(me, 'phone', phone), 'session': ss,
            'api_id': DEFAULT_API_ID, 'api_hash': DEFAULT_API_HASH,
            'enabled': True, 'mode': 'ai', 'spam_active': False,
            'proxy': None, 'is_backup': False,
            'added_at': datetime.now().isoformat()
        }
        add_account_data(info)
        c2 = await start_account(info)
        if c2:
            active_accounts.append(info); account_clients[info['id']] = c2
            account_stats[info['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
            account_stop_flags[info['id']] = False; register_ar(c2, info)
        await update.message.reply_text(
            f"✅ **Added!**\n👤 {info['name']}\n📱 {info['phone']}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]])
        )
        await client.disconnect()
        context.user_data['await'] = None
        context.user_data.pop('ac_cl', None); context.user_data.pop('ac_ph', None); context.user_data.pop('ac_2fa', None)
        return True
    except SessionPasswordNeededError:
        context.user_data['ac_2fa'] = True
        context.user_data['await'] = 'ac_otp'
        await update.message.reply_text("🔑 2FA Password required:\n\nEnter your 2FA password:")
        return False
    except PhoneCodeInvalidError:
        await update.message.reply_text("❌ Invalid OTP! Try again:")
        return False
    except PhoneCodeExpiredError:
        await update.message.reply_text("⏰ OTP expired! Start again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        context.user_data['await'] = None
        return False
    except Exception as e:
        err_str = str(e)
        if "AuthKeyUnregistered" in err_str or "key is not registered" in err_str:
            try: await client.disconnect()
            except: pass
            new_client = TelegramClient(StringSession(), DEFAULT_API_ID, DEFAULT_API_HASH, receive_updates=False)
            await new_client.connect()
            await new_client.send_code_request(phone)
            context.user_data['ac_cl'] = new_client
            context.user_data['await'] = 'ac_otp'
            await update.message.reply_text("🔄 Session refreshed! Enter OTP again:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return False
        await update.message.reply_text(f"{err_str[:100]}")
        context.user_data['await'] = None
        return False

async def sign_in_with_2fa(password, client, update, context, phone):
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        ss = client.session.save()
        info = {
            'id': gen_acc_id(), 'user_id': me.id,
            'name': me.first_name or f"User{me.id}",
            'phone': getattr(me, 'phone', phone), 'session': ss,
            'api_id': DEFAULT_API_ID, 'api_hash': DEFAULT_API_HASH,
            'enabled': True, 'mode': 'ai', 'spam_active': False,
            'proxy': None, 'is_backup': False,
            'added_at': datetime.now().isoformat()
        }
        add_account_data(info)
        c2 = await start_account(info)
        if c2:
            active_accounts.append(info); account_clients[info['id']] = c2
            account_stats[info['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
            account_stop_flags[info['id']] = False; register_ar(c2, info)
        await update.message.reply_text(
            f"✅ **Added!**\n👤 {info['name']}\n📱 {info['phone']}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]])
        )
        await client.disconnect()
        context.user_data['await'] = None
        context.user_data.pop('ac_cl', None); context.user_data.pop('ac_ph', None); context.user_data.pop('ac_2fa', None)
    except Exception as e:
        await update.message.reply_text(f"❌ {str(e)[:80]}")
        context.user_data['await'] = None

async def test_session(session_string, api_id=None, api_hash=None):
    api_id = api_id or DEFAULT_API_ID
    api_hash = api_hash or DEFAULT_API_HASH
    if not api_id or not api_hash:
        return False, "API not configured", None, None
    try:
        client = TelegramClient(StringSession(session_string), api_id, api_hash, receive_updates=False)
        await client.connect()
        me = await client.get_me()
        phone = getattr(me, 'phone', None) or "N/A"
        await client.disconnect()
        return True, me.first_name or f"User{me.id}", me.id, phone
    except Exception as e:
        return False, str(e)[:100], None, None

# ============ BOT UI ============

def main_keyboard():
    ar_status = "🟢 ON" if auto_reply_enabled else "🔴 OFF"
    gs_status = "🟢 ON" if group_spam_enabled else "🔴 OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📨 Auto Reply ({ar_status})", callback_data="m_ar")],
        [InlineKeyboardButton(f"📯 Group Spam ({gs_status})", callback_data="m_gs")],
        [InlineKeyboardButton("👤 Accounts", callback_data="m_acc")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="m_set")],
        [InlineKeyboardButton("📊 Status", callback_data="m_stat")],
        [InlineKeyboardButton("🔐 Admin", callback_data="m_adm")],
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in admins:
        await update.message.reply_text("❌ Unauthorized!")
        return
    await update.message.reply_text(
        "🤖 **HACKER AI CONTROL PANEL** 🤖\n\nSelect an option below:",
        reply_markup=main_keyboard()
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, logout_notification_enabled
    
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if user_id != OWNER_ID and user_id not in admins:
        await query.edit_message_text("❌ Access Denied!")
        return
    
    if data == "main":
        await query.edit_message_text(
            "🤖 **HACKER AI CONTROL PANEL** 🤖\n\nSelect an option below:",
            reply_markup=main_keyboard()
        )
    
    elif data == "m_ar":
        running_count = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('running', False))
        status = "🟢 ON" if auto_reply_enabled else "🔴 OFF"
        sd = int(get_setting('seen_delay', 1))
        td = int(get_setting('typing_duration', 2))
        te = "🟢 ON" if get_setting('typing_enabled', True) else "🔴 OFF"
        text = f"📨 **Auto Reply** | {status}\n👁️ Seen Delay: {sd}s\n⌨️ Typing Effect: {te} ({td}s)\n✅ Running: {running_count}/{len(active_accounts)}"
        kb = [
            [InlineKeyboardButton(f"{'🔴' if auto_reply_enabled else '🟢'} Toggle Auto Reply", callback_data="ar_t")],
            [InlineKeyboardButton("▶️ Start All", callback_data="ar_start_all"), InlineKeyboardButton("⏹️ Stop All", callback_data="ar_stop_all")],
            [InlineKeyboardButton("👁️ Seen Delay", callback_data="ar_sd")],
            [InlineKeyboardButton("⌨️ Typing Duration", callback_data="ar_td")],
            [InlineKeyboardButton(f"🔤 Typing Effect {te}", callback_data="ar_te")],
            [InlineKeyboardButton("💬 Custom Replies", callback_data="ar_rp")],
            [InlineKeyboardButton("🚫 Ignored Messages", callback_data="ar_ig")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ar_t":
        auto_reply_enabled = not auto_reply_enabled
        await query.edit_message_text(f"✅ Auto Reply is now {'🟢 ON' if auto_reply_enabled else '🔴 OFF'}!")
        await asyncio.sleep(1)
        await handle_callback(update, context)
    
    elif data == "ar_te":
        cur = get_setting('typing_enabled', True)
        set_setting('typing_enabled', not cur)
        await query.edit_message_text(f"✅ Typing Effect is now {'🟢 ON' if not cur else '🔴 OFF'}!")
        await asyncio.sleep(1)
        await handle_callback(update, context)
    
    elif data == "ar_start_all":
        for acc in active_accounts:
            acc_id = acc['id']
            if acc_id not in account_clients:
                continue
            account_stats[acc_id]['running'] = True
        await query.edit_message_text(
            "✅ **Auto Reply Started for All Accounts!**\n\n"
            "All accounts will now auto-reply with typing effect.\n\n"
            "🔄 Seen Delay → Typing → Message Send",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]])
        )
    
    elif data == "ar_stop_all":
        for acc in active_accounts:
            acc_id = acc['id']
            account_stats[acc_id]['running'] = False
        await query.edit_message_text(
            "⏹️ **Auto Reply Stopped for All Accounts!**\n\nNo accounts will auto-reply now.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]])
        )
    
    elif data == "ar_sd":
        context.user_data['await'] = 'seen_delay'
        await query.edit_message_text(
            f"👁️ **Seen Delay**\nCurrent: {get_setting('seen_delay', 1)}s\n\nEnter new delay (1-5 seconds):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]])
        )
    
    elif data == "ar_td":
        context.user_data['await'] = 'typing_duration'
        await query.edit_message_text(
            f"⌨️ **Typing Duration**\nCurrent: {get_setting('typing_duration', 2)}s\n\nEnter new duration (1-5 seconds):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]])
        )
    
    elif data == "ar_ig":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "🚫 **Ignored Messages**\nMessages NOT to reply (one per line):\n\n"
        if cur:
            txt += f"Current:\n{cur}\n\n"
        txt += "Example:\nthanks\nbye\nok"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
    
    elif data == "ar_rp":
        replies = load_replies()
        pg = int(context.user_data.get('rp_pg', 0))
        pp = 5
        tp = max(1, (len(replies) + pp - 1) // pp)
        start = pg * pp
        end = start + pp
        pr = replies[start:end]
        txt = f"💬 **Replies** (Page {pg+1}/{tp})\n\n"
        for r in pr:
            txt += f"#{r['id']} `{r['keyword'][:15]}`\n  ➜ {r['reply'][:30]}...\n\n"
        kb = []
        nav = []
        if pg > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"rp_{pg-1}"))
        if pg < tp - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"rp_{pg+1}"))
        if nav:
            kb.append(nav)
        kb.extend([
            [InlineKeyboardButton("➕ Add Single", callback_data="ar_a1")],
            [InlineKeyboardButton("📦 Add Bulk", callback_data="ar_ab")],
            [InlineKeyboardButton("🗑️ Delete Reply", callback_data="ar_dl")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_ar")]
        ])
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("rp_"):
        context.user_data['rp_pg'] = int(data.split('_')[1])
        await handle_callback(update, context)
    
    elif data == "ar_a1":
        context.user_data['await'] = 'rk'
        await query.edit_message_text("💬 **Add Reply - Step 1**\n\nEnter keyword:\nEx: price", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
    
    elif data == "ar_ab":
        context.user_data['await'] = 'rb'
        await query.edit_message_text("📦 **Bulk Add Replies**\n\nEach line format:\n`keyword | reply | exact/contains`\n\nExample:\n`price | Price 99 | contains`\n`hello | Hello baby! | exact`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
    
    elif data == "ar_dl":
        replies = load_replies()[:15]
        if not replies:
            await query.edit_message_text("No replies!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ #{r['id']} {r['keyword'][:12]}", callback_data=f"ard_{r['id']}")] for r in replies]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="ar_rp")])
        await query.edit_message_text("Select to delete:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("ard_"):
        rid = int(data.split('_')[1])
        ok = delete_reply(rid)
        await query.edit_message_text("✅ Deleted!" if ok else "❌ Not found!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
    
    elif data == "m_gs":
        run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        st = "🟢 ON" if group_spam_enabled else "🔴 OFF"
        spd = get_setting('spam_speed', 'medium')
        sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        txt = f"📯 **Group Spam** | {st}\n🏃 Running: {run}/{len(active_accounts)}\n📤 Sent: {sent}\n⚡ Speed: {spd}"
        kb = [
            [InlineKeyboardButton(f"{'🔴' if group_spam_enabled else '🟢'} Toggle", callback_data="gs_t")],
            [InlineKeyboardButton("▶️ Start All", callback_data="gs_on"), InlineKeyboardButton("⏹️ Stop All", callback_data="gs_off")],
            [InlineKeyboardButton("👤 Specific Account", callback_data="gs_sp")],
            [InlineKeyboardButton("⚡ Speed", callback_data="gs_spd")],
            [InlineKeyboardButton("💬 Spam Messages", callback_data="gs_msg")],
            [InlineKeyboardButton("📊 Stats", callback_data="gs_st")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "gs_t":
        group_spam_enabled = not group_spam_enabled
        await query.edit_message_text(f"✅ Group Spam is now {'🟢 ON' if group_spam_enabled else '🔴 OFF'}!")
        await asyncio.sleep(1)
        await handle_callback(update, context)
    
    elif data == "gs_on":
        start_spam()
        await query.edit_message_text(
            "▶️ **Started All!**\n\nGroup spam is now running on all accounts.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]])
        )
    
    elif data == "gs_off":
        stop_spam()
        await query.edit_message_text(
            "⏹️ **Stopped All!**\n\nGroup spam stopped on all accounts.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]])
        )
    
    elif data == "gs_sp":
        if not active_accounts:
            await query.edit_message_text("❌ No accounts!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
            return
        kb = [[InlineKeyboardButton(f"{'🟢' if account_stats.get(a['id'], {}).get('spam_running', False) else '🔴'} {a.get('name','?')[:15]}", callback_data=f"gsa_{a['id']}")] for a in active_accounts]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_gs")])
        await query.edit_message_text("👤 **Toggle Accounts:**\n🟢=Running 🔴=Stopped", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("gsa_"):
        aid = data.replace("gsa_", "")
        if account_stats.get(aid, {}).get('spam_running', False):
            stop_spam(aid)
        else:
            start_spam(aid)
        await handle_callback(update, context)
    
    elif data == "gs_spd":
        cur = get_setting('spam_speed', 'medium')
        kb = [
            [InlineKeyboardButton(f"{'✅ ' if cur=='super_fast' else ''}⚡ Super Fast", callback_data="gs_sf")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='fast' else ''}🚀 Fast", callback_data="gs_fa")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='medium' else ''}🏃 Medium", callback_data="gs_me")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='slow' else ''}🐢 Slow", callback_data="gs_sl")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='custom' else ''}⚙️ Custom", callback_data="gs_cs")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_gs")]
        ]
        await query.edit_message_text(f"⚡ **Select Speed**\n\nCurrent: {cur}", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data in ["gs_sf", "gs_fa", "gs_me", "gs_sl", "gs_cs"]:
        m = {'gs_sf': 'super_fast', 'gs_fa': 'fast', 'gs_me': 'medium', 'gs_sl': 'slow', 'gs_cs': 'custom'}
        set_setting('spam_speed', m[data])
        if data == 'gs_cs':
            kb = [
                [InlineKeyboardButton("📦 Batch Size", callback_data="gs_bs")],
                [InlineKeyboardButton("⏱️ Batch Delay", callback_data="gs_bd")],
                [InlineKeyboardButton("🔄 Cycle Wait", callback_data="gs_cw")],
                [InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]
            ]
            await query.edit_message_text("⚙️ **Custom Settings**", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.edit_message_text(f"✅ Speed set to: {m[data]}!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
    
    elif data == "gs_bs":
        context.user_data['await'] = 'gs_bs'
        await query.edit_message_text(f"📦 **Batch Size**\nCurrent: {get_setting('spam_batch_size', 6)}\n\nEnter (1-50):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
    
    elif data == "gs_bd":
        context.user_data['await'] = 'gs_bd'
        await query.edit_message_text(f"⏱️ **Batch Delay**\nCurrent: {get_setting('spam_batch_delay', 3)}s\n\nEnter (0-30):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
    
    elif data == "gs_cw":
        context.user_data['await'] = 'gs_cw'
        await query.edit_message_text(f"🔄 **Cycle Wait**\nCurrent: {get_setting('spam_cycle_wait', 30)}s\n\nEnter (0-300):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
    
    elif data == "gs_msg":
        msgs = load_spam_messages()
        txt = "💬 **Spam Messages**\n\n"
        if msgs:
            for m in msgs:
                txt += f"📝 {m['text'][:40]}... [ID: {m['id']}]\n"
        else:
            txt += f"📝 Default: {get_setting('spam_message', '...')}\n\n"
        txt += "\nManage:"
        kb = [
            [InlineKeyboardButton("➕ Add Message", callback_data="gs_msg_add")],
            [InlineKeyboardButton("🗑️ Delete Message", callback_data="gs_msg_del")],
            [InlineKeyboardButton("📋 Show All", callback_data="gs_msg_list")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_gs")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "gs_msg_add":
        context.user_data['await'] = 'gs_msg_add'
        await query.edit_message_text("📝 **Enter new spam message:**\n\nType the message:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
    
    elif data == "gs_msg_list":
        msgs = load_spam_messages()
        txt = "📋 **All Spam Messages**\n\n"
        if msgs:
            for i, m in enumerate(msgs, 1):
                txt += f"{i}. {m['text']}\n"
        else:
            txt += "No custom messages. Using default.\n"
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
    
    elif data == "gs_msg_del":
        msgs = load_spam_messages()
        if not msgs:
            await query.edit_message_text("No messages!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {m['text'][:20]}...", callback_data=f"gsmd_{m['id']}")] for m in msgs[:10]]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="gs_msg")])
        await query.edit_message_text("Select to delete:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("gsmd_"):
        mid = int(data.split('_')[1])
        delete_spam_message(mid)
        msgs = load_spam_messages()
        for acc in active_accounts:
            acc_id = acc['id']
            account_spam_messages[acc_id] = [m['text'] for m in msgs]
        await query.edit_message_text("✅ Deleted!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
    
    elif data == "gs_st":
        txt = "📊 **Performance**\n\n"
        for a in active_accounts:
            s = account_stats.get(a['id'], {}).get('spam_sent', 0)
            r = "🟢 RUN" if account_stats.get(a['id'], {}).get('spam_running', False) else "🔴 STOP"
            txt += f"{r} {a.get('name', '?')}: {s}\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
    
    elif data == "m_acc":
        ma = len(get_main_accounts())
        ba = len(get_backup_accounts())
        act = len(active_accounts)
        txt = f"👤 **Account Management**\n\n📌 Main: {ma} | 💾 Backup: {ba} | 🟢 Active: {act}"
        kb = [
            [InlineKeyboardButton("📱 Phone + OTP", callback_data="ac_ph")],
            [InlineKeyboardButton("🔑 Session String", callback_data="ac_ss")],
            [InlineKeyboardButton("🗑️ Delete", callback_data="ac_del")],
            [InlineKeyboardButton("💾 Backup Mgmt", callback_data="ac_bk")],
            [InlineKeyboardButton("🔌 Proxy per Account", callback_data="ac_pr")],
            [InlineKeyboardButton("📋 List All", callback_data="ac_ls")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("📱 **Enter phone number**\n\nInternational format:\n`+8801XXXXXXXXX`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
    
    elif data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("🔑 **Paste Session String**\n\nGenerate:\n`pip install telethon`\n`python -c \"from telethon.sync import TelegramClient; from telethon.sessions import StringSession; c=TelegramClient(StringSession(), API_ID, 'API_HASH'); c.start(); print(c.session.save())\"`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
    
    elif data == "ac_del":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ No accounts to delete!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}", callback_data=f"acd_{a['id']}")] for a in all_a]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_acc")])
        await query.edit_message_text("🗑️ **Delete Account:**", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("acd_"):
        aid = data.split('_', 1)[1]
        a = find_account(aid)
        name = a.get('name', '?') if a else '?'
        if aid in account_keepalive_tasks:
            if not account_keepalive_tasks[aid].done():
                account_keepalive_tasks[aid].cancel()
                try: await account_keepalive_tasks[aid]
                except: pass
            del account_keepalive_tasks[aid]
        if aid in account_spam_tasks:
            if not account_spam_tasks[aid].done():
                account_spam_tasks[aid].cancel()
                try: await account_spam_tasks[aid]
                except: pass
            del account_spam_tasks[aid]
        if aid in account_clients:
            try:
                await account_clients[aid].disconnect()
                await asyncio.sleep(0.5)
            except: pass
            del account_clients[aid]
        active_accounts[:] = [x for x in active_accounts if x['id'] != aid]
        for d in [account_stats, account_stop_flags, account_spam_tasks, account_keepalive_tasks, account_spam_active]:
            if aid in d: del d[aid]
        remove_account_data(aid)
        remaining = find_account(aid)
        if remaining:
            remove_account_data(aid)
        await query.edit_message_text(f"✅ {name} permanently deleted!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        return
    
    elif data == "ac_bk":
        ba = get_backup_accounts()
        txt = f"💾 **Backup Accounts**\nTotal: {len(ba)}\n\nAuto-used when main banned.\n\n"
        for i, a in enumerate(ba, 1):
            txt += f"{i}. 👤 {a.get('name', '?')} ({a.get('phone', 'N/A')})\n"
        kb = [
            [InlineKeyboardButton("➕ Add Backup", callback_data="ac_bk_add")],
            [InlineKeyboardButton("🗑️ Remove", callback_data="ac_bk_del")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_acc")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_bk_add":
        context.user_data['await'] = 'ac_bk_ss'
        await query.edit_message_text("🔑 **Backup Session String**\n\nPaste:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
    
    elif data == "ac_bk_del":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ No backups!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="ac_bk")])
        await query.edit_message_text("🗑️ **Remove Backup:**", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("acbkd_"):
        bid = data.split('_')[1]
        remove_account_data(bid)
        await query.edit_message_text(f"✅ Backup removed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
    
    elif data == "ac_pr":
        if not active_accounts:
            await query.edit_message_text("❌ No active accounts!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"👤 {a.get('name','?')[:15]} {'🟢' if a.get('proxy') else '🔴'}", callback_data=f"acpr_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_acc")])
        await query.edit_message_text("🔌 **Set Proxy per Account**", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("acpr_"):
        aid = data.split('_')[1]
        context.user_data['pr_aid'] = aid
        context.user_data['await'] = 'proxy'
        await query.edit_message_text("🔌 **Proxy format**\n`type:ip:port:user:pass`\n\nEx: `socks5:1.2.3.4:1080:user:pass`\n\nType `remove` to clear", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_pr")]]))
    
    elif data == "ac_ls":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ None!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        txt = f"📋 **All Accounts ({len(all_a)})**\n\n"
        for i, a in enumerate(all_a, 1):
            n = a.get('name', '?')
            p = a.get('phone', 'N/A')
            uid = a.get('user_id', '?')
            tp = "📌 MAIN" if not a.get('is_backup') else "💾 BACKUP"
            st = "🟢 ACTIVE" if any(x['id'] == a['id'] for x in active_accounts) else "🔴 INACTIVE"
            txt += f"{tp} {st} {i}. {n}\n   📱 Phone:{p} | 🆔 ID:{uid}\n"
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
    
    elif data == "m_set":
        bp = "🟢 ON" if get_setting('block_photo_enabled', True) else "🔴 OFF"
        dr = "🟢 ON" if get_setting('default_reply_enabled', False) else "🔴 OFF"
        fs = "🟢 ON" if get_setting('flood_slow_mode', True) else "🔴 OFF"
        ln = "🟢 ON" if logout_notification_enabled else "🔴 OFF"
        kb = [
            [InlineKeyboardButton(f"🚫 Block Photo {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"💬 Default Reply {dr}", callback_data="st_dr")],
            [InlineKeyboardButton(f"🐢 Flood Slow {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"🔔 Logout Alert {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("📝 Welcome & Price", callback_data="st_wp")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        await query.edit_message_text("⚙️ **Settings**\n\nToggle options:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "st_bp":
        set_setting('block_photo_enabled', not get_setting('block_photo_enabled', True))
        await handle_callback(update, context)
    
    elif data == "st_dr":
        cur = get_setting('default_reply_enabled', False)
        set_setting('default_reply_enabled', not cur)
        if not cur:
            context.user_data['await'] = 'dr_txt'
            await query.edit_message_text("💬 **Enter default reply text:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))
        else:
            await handle_callback(update, context)
    
    elif data == "st_fs":
        set_setting('flood_slow_mode', not get_setting('flood_slow_mode', True))
        await handle_callback(update, context)
    
    elif data == "st_ln":
        logout_notification_enabled = not logout_notification_enabled
        await handle_callback(update, context)
    
    elif data == "st_wp":
        wm = get_setting('welcome_message', '') or "🔥 Welcome Baby!"
        wm2 = get_setting('welcome_message2', '') or "🛒 How to order?"
        wi = "✅ Set" if get_setting('welcome_image', '') else "❌ Not Set"
        wi2 = "✅ Set" if get_setting('welcome_image2', '') else "❌ Not Set"
        pi = "✅ Set" if get_setting('price_list_image', '') else "❌ Not Set"
        pt = get_setting('price_list_text', "🔥 10 MIN VC → ₹99")
        qr = "✅ Set" if get_setting('qr_code_path', '') else "❌ Not Set"
        upi = get_setting('upi_id', '') or "Not Set"
        paytm = get_setting('paytm_num', '') or "Not Set"
        txt = (
            "📝 **WELCOME & PRICE SETTINGS**\n\n"
            f"**1st Welcome:**\n`{wm[:40]}...`\n🖼️ Pic: {wi}\n\n"
            f"**2nd Welcome:**\n`{wm2[:40]}...`\n🖼️ Pic: {wi2}\n\n"
            f"💰 **Price Text:** `{pt[:40]}...`\n🖼️ Price Pic: {pi}\n\n"
            f"💳 **Payment:** UPI: `{upi}` | PayTm: `{paytm}`\n📷 QR: {qr}"
        )
        kb = [
            [InlineKeyboardButton("1️⃣ 1st Welcome Msg", callback_data="st_wm"), InlineKeyboardButton("🖼️ 1st Pic", callback_data="st_wi")],
            [InlineKeyboardButton("2️⃣ 2nd Welcome Msg", callback_data="st_wm2"), InlineKeyboardButton("🖼️ 2nd Pic", callback_data="st_wi2")],
            [InlineKeyboardButton("💰 Price Text", callback_data="st_pt"), InlineKeyboardButton("🖼️ Price Pic", callback_data="st_pi")],
            [InlineKeyboardButton("📱 UPI ID", callback_data="st_upi"), InlineKeyboardButton("💳 PayTm", callback_data="st_paytm")],
            [InlineKeyboardButton("📷 QR Code", callback_data="st_qr")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_set")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "st_wm":
        context.user_data['await'] = 'st_wm'
        cur = get_setting('welcome_message', '')
        txt = "👋 **1st Welcome Message (msg+pic)**\n\nSend text:\n"
        if cur: txt += f"Current: `{cur}`\n"
        txt += "\nSend `remove` to clear"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "st_wi":
        context.user_data['await'] = 'st_wi'
        cur = get_setting('welcome_image', '')
        txt = "🖼️ **1st Welcome Image**\n\nSend file path or URL:\n"
        if cur: txt += f"Current: `{cur}`\n"
        txt += "\n📸 Send photo directly\n🌐 Or send URL starting with http\n✏️ Or send `remove` to clear"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "st_wm2":
        context.user_data['await'] = 'st_wm2'
        cur = get_setting('welcome_message2', '')
        txt = "2️⃣ **2nd Welcome Message (msg only)**\n\nSend text:\n"
        if cur: txt += f"Current: `{cur}`\n"
        txt += "\nSend `remove` to clear"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "st_wi2":
        context.user_data['await'] = 'st_wi2'
        cur = get_setting('welcome_image2', '')
        txt = "🖼️ **2nd Welcome Image (optional)**\n\nSend file path or URL:\n"
        if cur: txt += f"Current: `{cur}`\n"
        txt += "\n📸 Send photo directly\n🌐 Or send URL starting with http\n✏️ Or send `remove` to clear"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "st_pt":
        context.user_data['await'] = 'st_pt'
        cur = get_setting('price_list_text', "🔥 10 MIN VC → ₹99")
        txt = f"💰 **Set Price List Text**\n\nCurrent:\n`{cur}`\n\nSend new:"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "st_pi":
        context.user_data['await'] = 'st_pi'
        cur = get_setting('price_list_image', '')
        txt = "🖼️ **Price List Image**\n\nSend file path or URL:\n"
        if cur: txt += f"Current: `{cur}`\n"
        txt += "\n📸 Send photo directly\n🌐 Or send URL starting with http\n✏️ Or send `remove` to clear"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "st_upi":
        context.user_data['await'] = 'st_upi'
        cur = get_setting('upi_id', '')
        txt = f"📱 **UPI ID**\n\nCurrent: `{cur or 'Not Set'}`\n\nSend new UPI:\nSend `remove` to clear"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "st_paytm":
        context.user_data['await'] = 'st_paytm'
        cur = get_setting('paytm_num', '')
        txt = f"💳 **PayTm**\n\nCurrent: `{cur or 'Not Set'}`\n\nSend new:\nSend `remove` to clear"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "st_qr":
        context.user_data['await'] = 'st_qr'
        cur = get_setting('qr_code_path', '')
        txt = "📷 **QR Code Image**\n\nSend file path or URL:\n"
        if cur: txt += f"Current: `{cur}`\n"
        txt += "\n📸 Send photo directly\n🌐 Or send URL starting with http\n✏️ Or send `remove` to clear"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_wp")]]))
    
    elif data == "m_stat":
        ar = "🟢 ON" if auto_reply_enabled else "🔴 OFF"
        gs = "🟢 ON" if group_spam_enabled else "🔴 OFF"
        ln = "🟢 ON" if logout_notification_enabled else "🔴 OFF"
        total_customers = len([k for k, v in customer_count.items() if v > 0])
        txt = (
            f"📊 **SYSTEM STATUS**\n\n"
            f"📨 Auto Reply: {ar}\n"
            f"📯 Group Spam: {gs}\n"
            f"🔔 Logout Alert: {ln}\n"
            f"👤 Total Accounts: {len(get_all_accounts())}\n"
            f"🟢 Active: {len(active_accounts)}\n"
            f"🏃 Spam Running: {sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))}\n"
            f"📤 Spam Sent: {sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)}\n"
            f"👥 Customers: {total_customers}\n"
            f"💾 Backups: {len(get_backup_accounts())}\n"
            f"⚡ Speed: {get_setting('spam_speed', 'medium')}"
        )
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="m_stat")], [InlineKeyboardButton("🏠 Menu", callback_data="main")]]))
    
    elif data == "m_adm":
        txt = f"🔐 **Admin Panel**\n\n👑 Owner: {OWNER_ID}\n👥 Admins: {len(admins)-1}\n\n"
        for a in admins:
            txt += f"{'👑' if a==OWNER_ID else '👤'} `{a}`\n"
        kb = [
            [InlineKeyboardButton("➕ Add Admin", callback_data="ad_add")],
            [InlineKeyboardButton("🗑️ Delete Admin", callback_data="ad_del")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main")]
        ]
        if user_id != OWNER_ID:
            kb = [[InlineKeyboardButton("🏠 Menu", callback_data="main")]]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ad_add" and user_id == OWNER_ID:
        context.user_data['await'] = 'ad_add'
        await query.edit_message_text("👤 **Enter user ID:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))
    
    elif data == "ad_del" and user_id == OWNER_ID:
        if len(admins) <= 1:
            await query.edit_message_text("❌ Only owner left!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ `{a}`", callback_data=f"addc_{a}")] for a in admins if a != OWNER_ID]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_adm")])
        await query.edit_message_text("Select to remove:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("addc_") and user_id == OWNER_ID:
        aid = int(data.split('_')[1])
        if aid in admins and aid != OWNER_ID:
            admins.remove(aid)
            await query.edit_message_text(f"✅ {aid} removed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))
    
    elif data == "rt_exact":
        context.user_data['rt'] = 'exact'
        await query.edit_message_text("✅ Match: **exact**\nNow send the reply text:")
        context.user_data['await'] = 'rt'
    
    elif data == "rt_cont":
        context.user_data['rt'] = 'contains'
        await query.edit_message_text("✅ Match: **contains**\nNow send the reply text:")
        context.user_data['await'] = 'rt'
        # ──────────────────────────────────────────────────────────
#  TEXT MESSAGE HANDLER
# ──────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main handler for all text messages"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id if update.effective_user else None
    text = update.message.text.strip()
    
    # ── Check if we're waiting for user input ──
    await_state = context.user_data.get('await')
    if await_state:
        await handle_await_input(update, context, text)
        return
    
    # ── Only admin commands ──
    if user_id not in admins and user_id != OWNER_ID:
        return
    
    # ── Account adding via phone ──
    if text.startswith('+') and await_state is None and user_id in admins:
        context.user_data['await'] = 'ac_ph_code'
        context.user_data['ac_ph'] = text
        await update.message.reply_text(
            f"📱 Phone: `{text}`\n📤 Sending code...\n\nEnter the OTP code when received:",
            parse_mode='Markdown'
        )
        asyncio.create_task(start_account_login(text, DEFAULT_API_ID, DEFAULT_API_HASH, update, context))
        return


async def handle_await_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle user input when waiting for specific data"""
    user_id = update.effective_user.id if update.effective_user else None
    await_state = context.user_data.get('await')
    msg = update.message
    
    # ── Custom batch size ──
    if await_state == 'gs_bs':
        try:
            v = max(1, min(50, int(text)))
            set_setting('spam_batch_size', v)
            await msg.reply_text(f"✅ Batch size: {v}")
        except:
            await msg.reply_text("❌ Invalid number!")
        del context.user_data['await']
        return
    
    # ── Custom batch delay ──
    elif await_state == 'gs_bd':
        try:
            v = max(0, min(30, int(text)))
            set_setting('spam_batch_delay', v)
            await msg.reply_text(f"✅ Batch delay: {v}s")
        except:
            await msg.reply_text("❌ Invalid number!")
        del context.user_data['await']
        return
    
    # ── Custom cycle wait ──
    elif await_state == 'gs_cw':
        try:
            v = max(0, min(300, int(text)))
            set_setting('spam_cycle_wait', v)
            await msg.reply_text(f"✅ Cycle wait: {v}s")
        except:
            await msg.reply_text("❌ Invalid number!")
        del context.user_data['await']
        return
    
    # ── Add spam message ──
    elif await_state == 'gs_msg_add':
        msgs = load_spam_messages()
        mid = max([m['id'] for m in msgs], default=0) + 1
        msgs.append({'id': mid, 'text': text})
        save_spam_messages(msgs)
        for acc in active_accounts:
            account_spam_messages[acc['id']] = [m['text'] for m in msgs]
        await msg.reply_text(f"✅ Added: {text[:30]}...")
        del context.user_data['await']
        return
    
    # ── Add admin ──
    elif await_state == 'ad_add' and user_id == OWNER_ID:
        try:
            new_id = int(text.strip())
            if new_id not in admins:
                admins.append(new_id)
                await msg.reply_text(f"✅ Admin added: `{new_id}`", parse_mode='Markdown')
            else:
                await msg.reply_text("⚠️ Already admin!")
        except:
            await msg.reply_text("❌ Invalid ID!")
        del context.user_data['await']
        return
    
    # ── Proxy per account ──
    elif await_state == 'proxy':
        aid = context.user_data.get('pr_aid')
        if text.lower() == 'remove':
            set_account_proxy(aid, None)
            await msg.reply_text("✅ Proxy removed!")
        else:
            parts = text.split(':')
            if len(parts) in [3, 5]:
                proxy = {'type': parts[0], 'ip': parts[1], 'port': parts[2]}
                if len(parts) == 5:
                    proxy['user'] = parts[3]
                    proxy['pass'] = parts[4]
                set_account_proxy(aid, proxy)
                await msg.reply_text(f"✅ Proxy set: {parts[0]}:{parts[1]}:{parts[2]}")
            else:
                await msg.reply_text("❌ Format: type:ip:port:user:pass OR type:ip:port")
        del context.user_data['await']
        if 'pr_aid' in context.user_data: del context.user_data['pr_aid']
        return
    
    # ── Backup session string ──
    elif await_state == 'ac_bk_ss':
        try:
            session_str = text.strip()
            client = TelegramClient(StringSession(session_str), DEFAULT_API_ID, DEFAULT_API_HASH)
            await client.connect()
            me = await client.get_me()
            phone = me.phone
            name = me.first_name or "Unknown"
            uid = me.id
            
            data = load_accounts()
            acc_id = str(uuid.uuid4())[:8]
            data['accounts'].append({
                'id': acc_id, 'phone': phone, 'name': name,
                'user_id': uid, 'session': session_str,
                'type': 'session', 'api_id': DEFAULT_API_ID,
                'api_hash': DEFAULT_API_HASH, 'is_backup': True,
                'proxy': None
            })
            save_accounts(data)
            active_accounts.append(data['accounts'][-1])
            account_stats[acc_id] = {'spam_running': False, 'spam_sent': 0, 'replies_sent': 0}
            account_stop_flags[acc_id] = asyncio.Event()
            account_stop_flags[acc_id].set()
            account_spam_messages[acc_id] = [m['text'] for m in load_spam_messages()]
            asyncio.create_task(start_account_client(client, me, acc_id, session_str, DEFAULT_API_ID, DEFAULT_API_HASH))
            await client.disconnect()
            await msg.reply_text(f"✅ Backup added: {name} ({phone})")
            await client.connect()
        except Exception as e:
            await msg.reply_text(f"❌ Error: {str(e)[:100]}")
        del context.user_data['await']
        return
    
    # ── Session string (main account) ──
    elif await_state == 'ac_ss':
        try:
            session_str = text.strip()
            client = TelegramClient(StringSession(session_str), DEFAULT_API_ID, DEFAULT_API_HASH)
            await client.connect()
            me = await client.get_me()
            phone = me.phone
            name = me.first_name or "Unknown"
            uid = me.id
            
            data = load_accounts()
            acc_id = str(uuid.uuid4())[:8]
            data['accounts'].append({
                'id': acc_id, 'phone': phone, 'name': name,
                'user_id': uid, 'session': session_str,
                'type': 'session', 'api_id': DEFAULT_API_ID,
                'api_hash': DEFAULT_API_HASH, 'is_backup': False,
                'proxy': None
            })
            save_accounts(data)
            active_accounts.append(data['accounts'][-1])
            account_stats[acc_id] = {'spam_running': False, 'spam_sent': 0, 'replies_sent': 0}
            account_stop_flags[acc_id] = asyncio.Event()
            account_stop_flags[acc_id].set()
            account_spam_messages[acc_id] = [m['text'] for m in load_spam_messages()]
            asyncio.create_task(start_account_client(client, me, acc_id, session_str, DEFAULT_API_ID, DEFAULT_API_HASH))
            await client.disconnect()
            await msg.reply_text(f"✅ Account added: {name} ({phone})")
            await client.connect()
        except Exception as e:
            await msg.reply_text(f"❌ Error: {str(e)[:100]}")
        del context.user_data['await']
        return
    
    # ── Default reply text ──
    elif await_state == 'dr_txt':
        set_setting('default_reply_text', text)
        await msg.reply_text(f"✅ Default reply set: `{text[:30]}...`", parse_mode='Markdown')
        del context.user_data['await']
        return
    
    # ── Welcome message 1 ──
    elif await_state == 'st_wm':
        if text.lower() == 'remove':
            set_setting('welcome_message', '')
            await msg.reply_text("✅ Cleared!")
        else:
            set_setting('welcome_message', text)
            await msg.reply_text(f"✅ Set: `{text[:30]}...`")
        del context.user_data['await']
        return
    
    # ── Welcome message 2 ──
    elif await_state == 'st_wm2':
        if text.lower() == 'remove':
            set_setting('welcome_message2', '')
            await msg.reply_text("✅ Cleared!")
        else:
            set_setting('welcome_message2', text)
            await msg.reply_text(f"✅ Set: `{text[:30]}...`")
        del context.user_data['await']
        return
    
    # ── Price list text ──
    elif await_state == 'st_pt':
        set_setting('price_list_text', text)
        await msg.reply_text(f"✅ Price set: `{text[:30]}...`")
        del context.user_data['await']
        return
    
    # ── UPI ID ──
    elif await_state == 'st_upi':
        if text.lower() == 'remove':
            set_setting('upi_id', '')
            await msg.reply_text("✅ Cleared!")
        else:
            set_setting('upi_id', text)
            await msg.reply_text(f"✅ UPI: `{text}`")
        del context.user_data['await']
        return
    
    # ── PayTm ──
    elif await_state == 'st_paytm':
        if text.lower() == 'remove':
            set_setting('paytm_num', '')
            await msg.reply_text("✅ Cleared!")
        else:
            set_setting('paytm_num', text)
            await msg.reply_text(f"✅ PayTm: `{text}`")
        del context.user_data['await']
        return


# ──────────────────────────────────────────────────────────
#  PHOTO HANDLER
# ──────────────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads for welcome/price images"""
    user_id = update.effective_user.id if update.effective_user else None
    if user_id not in admins and user_id != OWNER_ID:
        return
    
    await_state = context.user_data.get('await')
    if not await_state:
        return
    
    msg = update.message
    if not msg.photo:
        return
    
    # Download photo
    photo = msg.photo[-1]  # highest quality
    file = await photo.get_file()
    
    # Determine save path
    file_id = str(uuid.uuid4())[:8]
    ext = 'jpg'
    if file.file_path and '.' in file.file_path:
        ext = file.file_path.rsplit('.', 1)[-1].split('?')[0][:4]
    
    save_path = f"data/{await_state}_{file_id}.{ext}"
    
    try:
        await file.download_to_drive(save_path)
        
        if await_state == 'st_wi':
            set_setting('welcome_image', save_path)
            await msg.reply_text(f"✅ Welcome pic saved: `{save_path}`")
        elif await_state == 'st_wi2':
            set_setting('welcome_image2', save_path)
            await msg.reply_text(f"✅ 2nd Welcome pic saved: `{save_path}`")
        elif await_state == 'st_pi':
            set_setting('price_list_image', save_path)
            await msg.reply_text(f"✅ Price pic saved: `{save_path}`")
        elif await_state == 'st_qr':
            set_setting('qr_code_path', save_path)
            await msg.reply_text(f"✅ QR saved: `{save_path}`")
        else:
            await msg.reply_text(f"✅ Photo saved: `{save_path}`")
    except Exception as e:
        await msg.reply_text(f"❌ Error saving photo: {str(e)[:100]}")
    
    del context.user_data['await']


# ──────────────────────────────────────────────────────────
#  AUTO REPLY LOGIC
# ──────────────────────────────────────────────────────────
async def process_auto_reply(client, sender_id, message_text, chat_id, account_id):
    """Process auto-reply for a single message"""
    try:
        replies = load_replies()
        if not replies and not get_setting('default_reply_enabled', False):
            return
        
        matched = None
        
        # Check keyword replies first
        for r in replies:
            keyword = r.get('keyword', '').lower()
            reply_text = r.get('reply', '')
            match_type = r.get('type', 'contains')
            
            if not keyword or not reply_text:
                continue
            
            msg_lower = message_text.lower() if message_text else ''
            
            if match_type == 'exact' and msg_lower == keyword:
                matched = reply_text
                break
            elif match_type == 'contains' and keyword in msg_lower:
                matched = reply_text
                break
        
        # Default reply if no match
        if not matched and get_setting('default_reply_enabled', False):
            matched = get_setting('default_reply_text', '')
        
        if not matched:
            return
        
        # TYPING EFFECT — ON by default
        typing_enabled = get_setting('typing_effect_enabled', True)
        
        if typing_enabled:
            # Simulate typing effect (max 3 seconds to avoid delay)
            typing_delay = min(len(matched) * 0.015, 3.0)  # ~15ms per char, capped at 3s
            typing_delay = max(typing_delay, 0.5)  # minimum 0.5s for realism
            
            async with client.action(chat_id, 'typing'):
                await asyncio.sleep(typing_delay)
        
        # Send reply
        await client.send_message(chat_id, matched)
        
        # Update stats
        if account_id in account_stats:
            account_stats[account_id]['replies_sent'] = account_stats[account_id].get('replies_sent', 0) + 1
    
    except Exception as e:
        logger.error(f"Error in auto_reply ({account_id}): {str(e)[:80]}")


# ──────────────────────────────────────────────────────────
#  ACCOUNT CLIENT SETUP
# ──────────────────────────────────────────────────────────
async def start_account_client(client, me, acc_id, session_str, api_id, api_hash):
    """Setup Telethon client for an account"""
    try:
        await client.start()
        logger.info(f"✅ Account {me.first_name or '?'} ({me.phone or '?'}) connected")
        
        # ── Message handler for auto-reply ──
        @client.on(events.NewMessage(incoming=True))
        async def handler(event):
            if not auto_reply_enabled:
                return
            
            sender = await event.get_sender()
            if not sender:
                return
            
            sender_id = event.sender_id
            chat_id = event.chat_id
            
            # Skip own messages
            if sender_id == me.id:
                return
            
            # Only handle private chats (not groups)
            if hasattr(event.message, 'peer_id') and hasattr(event.message.peer_id, 'user_id'):
                pass
            else:
                return
            
            # Check if we should block photo senders
            if event.message.photo and get_setting('block_photo_enabled', True):
                await client.send_message(chat_id, "❌ No photo pls! Text only.")
                await client(BlockRequest(id=sender_id))
                logger.info(f"🚫 Blocked photo sender: {sender_id}")
                return
            
            # Process auto reply
            text = event.message.text or ''
            asyncio.create_task(process_auto_reply(
                client, sender_id, text, chat_id, acc_id
            ))
        
        # Mark as active
        if acc_id not in account_stats:
            account_stats[acc_id] = {'spam_running': False, 'spam_sent': 0, 'replies_sent': 0}
        if acc_id not in account_stop_flags:
            account_stop_flags[acc_id] = asyncio.Event()
            account_stop_flags[acc_id].set()
        
        # Load spam messages
        account_spam_messages[acc_id] = [m['text'] for m in load_spam_messages()]
        
        # Keep connection alive (minimal - just maintain)
        while True:
            try:
                await asyncio.sleep(120)  # Only ping every 2 min
                if not client.is_connected():
                    await client.connect()
                # Lightweight ping
                me_check = await client.get_me()
            except Exception as e:
                logger.warning(f"Account {acc_id} keepalive: {str(e)[:60]}")
                try:
                    await client.connect()
                except:
                    break
            await asyncio.sleep(0)
    
    except Exception as e:
        logger.error(f"❌ Account {acc_id} client error: {str(e)[:80]}")


# ──────────────────────────────────────────────────────────
#  GROUP SPAM LOGIC
# ──────────────────────────────────────────────────────────
async def run_group_spam(client, acc_id, spam_messages, stop_flag):
    """Spam groups with given messages until stopped"""
    config = get_spam_config()
    batch_size = config['batch_size']
    batch_delay = config['batch_delay']
    cycle_wait = config['cycle_wait']
    
    try:
        # Get all dialogs (chats)
        dialogs = await client.get_dialogs()
        groups = [d for d in dialogs if d.is_group or d.is_channel]
        
        if not groups:
            logger.warning(f"❌ No groups for account {acc_id}")
            return
        
        logger.info(f"🎯 Account {acc_id}: {len(groups)} groups found")
        
        while not stop_flag.is_set():
            for i in range(0, len(groups), batch_size):
                if stop_flag.is_set():
                    break
                
                batch = groups[i:i+batch_size]
                
                for dialog in batch:
                    if stop_flag.is_set():
                        break
                    
                    try:
                        # Pick random message
                        msg = random.choice(spam_messages) if spam_messages else get_setting('spam_message', "Hi!")
                        
                        await client.send_message(dialog.id, msg)
                        
                        if acc_id in account_stats:
                            account_stats[acc_id]['spam_sent'] = account_stats[acc_id].get('spam_sent', 0) + 1
                        
                        await asyncio.sleep(batch_delay)
                    
                    except FloodWaitError as e:
                        logger.warning(f"🌊 Flood wait {e.seconds}s on {acc_id}")
                        await asyncio.sleep(min(e.seconds, 60))
                    except Exception as e:
                        logger.debug(f"Spam error ({acc_id}): {str(e)[:50]}")
                        await asyncio.sleep(2)
            
            if not stop_flag.is_set():
                logger.info(f"⏳ Cycle complete. Waiting {cycle_wait}s...")
                await asyncio.sleep(cycle_wait)
    
    except Exception as e:
        logger.error(f"❌ Spam task {acc_id} crashed: {str(e)[:80]}")


def get_spam_config():
    """Get spam configuration"""
    speed = get_setting('spam_speed', 'medium')
    
    configs = {
        'super_fast': {'batch_size': 10, 'batch_delay': 1, 'cycle_wait': 15},
        'fast': {'batch_size': 7, 'batch_delay': 2, 'cycle_wait': 20},
        'medium': {'batch_size': 5, 'batch_delay': 3, 'cycle_wait': 30},
        'slow': {'batch_size': 3, 'batch_delay': 5, 'cycle_wait': 60},
    }
    
    if speed == 'custom':
        return {
            'batch_size': get_setting('spam_batch_size', 6),
            'batch_delay': get_setting('spam_batch_delay', 3),
            'cycle_wait': get_setting('spam_cycle_wait', 30),
        }
    
    return configs.get(speed, configs['medium'])


def start_spam(account_id=None):
    """Start spam for an account or all accounts"""
    global account_spam_tasks
    
    accounts = [a for a in active_accounts if a['id'] == account_id] if account_id else active_accounts
    
    for acc in accounts:
        acc_id = acc['id']
        if acc_id not in account_clients:
            continue
        
        if acc_id in account_spam_tasks and not account_spam_tasks[acc_id].done():
            continue  # Already running
        
        stop_flag = asyncio.Event()
        account_stop_flags[acc_id] = stop_flag
        
        msgs = account_spam_messages.get(acc_id, [m['text'] for m in load_spam_messages()])
        
        task = asyncio.create_task(run_group_spam(
            account_clients[acc_id], acc_id, msgs, stop_flag
        ))
        account_spam_tasks[acc_id] = task
        account_stats[acc_id]['spam_running'] = True
        account_spam_active[acc_id] = True


def stop_spam(account_id=None):
    """Stop spam for an account or all accounts"""
    if account_id:
        if account_id in account_stop_flags:
            account_stop_flags[account_id].set()
        if account_id in account_spam_tasks and not account_spam_tasks[account_id].done():
            account_spam_tasks[account_id].cancel()
        if account_id in account_stats:
            account_stats[account_id]['spam_running'] = False
        if account_id in account_spam_active:
            account_spam_active[account_id] = False
    else:
        for acc_id in list(account_spam_tasks.keys()):
            stop_spam(acc_id)


# ──────────────────────────────────────────────────────────
#  ACCOUNT LOGIN (Phone + OTP)
# ──────────────────────────────────────────────────────────
async def start_account_login(phone, api_id, api_hash, update, context):
    """Start login process for phone number"""
    try:
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        
        sent = await client.send_code_request(phone)
        phone_code_hash = sent.phone_code_hash
        
        # Store in user context
        context.user_data['ac_client'] = client
        context.user_data['ac_ph_hash'] = phone_code_hash
        context.user_data['ac_ph_phone'] = phone
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def complete_account_login(client, phone, phone_code_hash, code, update, context):
    """Complete login with OTP code"""
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        session_str = client.session.save()
        
        data = load_accounts()
        acc_id = str(uuid.uuid4())[:8]
        data['accounts'].append({
            'id': acc_id, 'phone': phone, 'name': me.first_name or "Unknown",
            'user_id': me.id, 'session': session_str,
            'type': 'session', 'api_id': DEFAULT_API_ID,
            'api_hash': DEFAULT_API_HASH, 'is_backup': False,
            'proxy': None
        })
        save_accounts(data)
        active_accounts.append(data['accounts'][-1])
        account_stats[acc_id] = {'spam_running': False, 'spam_sent': 0, 'replies_sent': 0}
        account_stop_flags[acc_id] = asyncio.Event()
        account_stop_flags[acc_id].set()
        account_spam_messages[acc_id] = [m['text'] for m in load_spam_messages()]
        asyncio.create_task(start_account_client(client, me, acc_id, session_str, DEFAULT_API_ID, DEFAULT_API_HASH))
        
        await update.message.reply_text(f"✅ Logged in: {me.first_name or '?'} ({phone})")
        return True
    
    except SessionPasswordNeededError:
        context.user_data['await'] = 'ac_ph_2fa'
        await update.message.reply_text("🔐 **2FA password required!**\nSend your password:", parse_mode='Markdown')
        return False
    
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await update.message.reply_text("❌ Code invalid/expired! Try again.")
        return False
    
    except Exception as e:
        await update.message.reply_text(f"❌ Login error: {str(e)[:100]}")
        return False


# ──────────────────────────────────────────────────────────
#  SETUP & RUN
# ──────────────────────────────────────────────────────────
def setup_application():
    """Setup and configure the bot application"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    return app


async def main():
    """Main entry point"""
    logger.info("🚀 Starting bot...")
    
    # Ensure data directory
    os.makedirs("data", exist_ok=True)
    
    # Load accounts
    data = load_accounts()
    accounts = data.get('accounts', [])
    logger.info(f"📂 Loaded {len(accounts)} accounts")
    
    # Start account clients
    for acc in accounts:
        if acc.get('type') != 'session':
            continue
        
        acc_id = acc['id']
        session_str = acc.get('session', '')
        api_id = acc.get('api_id', DEFAULT_API_ID)
        api_hash = acc.get('api_hash', DEFAULT_API_HASH)
        
        if not session_str:
            logger.warning(f"⚠️ Account {acc_id} has no session string")
            continue
        
        try:
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            me = await client.get_me()
            
            active_accounts.append(acc)
            account_clients[acc_id] = client
            account_stats[acc_id] = {'spam_running': False, 'spam_sent': 0, 'replies_sent': 0}
            account_stop_flags[acc_id] = asyncio.Event()
            account_stop_flags[acc_id].set()
            account_spam_messages[acc_id] = [m['text'] for m in load_spam_messages()]
            
            asyncio.create_task(start_account_client(client, me, acc_id, session_str, api_id, api_hash))
            
            await asyncio.sleep(0.5)  # Stagger connections
        
        except Exception as e:
            logger.error(f"❌ Failed to load account {acc_id}: {str(e)[:80]}")
    
    logger.info(f"🟢 Active accounts: {len(active_accounts)}")
    
    # Setup bot
    app = setup_application()
    
    # ── Start polling ──
    logger.info("📡 Starting polling (no webhook, no external URL needed)...")
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )
    
    logger.info(f"✅ Bot is running! Owner: {OWNER_ID}, Port: {PORT}")
    
    # Keep alive
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped.")
    except Exception as e:
        logger.exception(f"💥 Fatal error: {e}")

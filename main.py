#!/usr/bin/env python3
"""
UNIFIED TELEGRAM BOT - COMPLETE FIXED VERSION
All problems solved:
1. Group spam multiple messages working (rotates properly)
2. Auto Reply Start/Stop All with Back button
3. Typing effect added (seen delay → typing → message send)
4. Start All actually starts auto reply
"""

import os, sys, json, asyncio, random, logging, threading, time
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple, Set
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
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', '')
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
    AuthKeyUnregisteredError, UserDeactivatedError,
    PhoneNumberInvalidError
)
from telethon.tl.functions.messages import GetDialogsRequest, ReadHistoryRequest, SendTypingAction
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.types import InputPeerEmpty, SendMessageTypingAction

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
    'typing_enabled': True,
    'typing_duration': 2,
    'seen_delay': 2,
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
    'welcome_message': '',
    'qr_code_path': '',
    'price_list_image': '',
    'welcome_image': '',
    'payment_keyword_reply': 'Scan & Pay baby 😘🔥',
    'media_keyword_reply': 'Payment first baby 😘🔥',
    'offline_keyword_reply': 'Online only baby 😊',
    'greeting_replies': ['Hi baby, ready! 🔥', 'Hey baby! 😘', 'Hello! What you need? 🔥'],
    'default_replies': ['Ready baby! Pay karo! 🔥', 'Main ready hoon! 😘', 'Service ready! 💯']
}

# ============ PERSISTENCE HELPERS ============

def _load_settings_to_cache():
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
    _settings_cache_dirty = True
    try:
        tmp = SETTINGS_FILE.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_settings_cache, f, indent=2, ensure_ascii=False)
        tmp.replace(SETTINGS_FILE)
        _settings_cache_dirty = False
    except Exception as e:
        logger.error(f"Settings save failed: {e}")

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
        tmp = fp.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(fp)
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

# ============ TYPING EFFECT ============

async def send_with_typing(client, chat_id, message_text):
    """Send message with: seen delay → typing indicator → send"""
    seen_delay = int(get_setting('seen_delay', 1))
    typing_duration = int(get_setting('typing_duration', 2))
    typing_enabled = get_setting('typing_enabled', True)
    
    if seen_delay > 0:
        await asyncio.sleep(seen_delay)
    
    if typing_enabled and typing_duration > 0:
        try:
            await client(SendTypingAction(
                peer=await client.get_input_entity(chat_id),
                action=SendMessageTypingAction()
            ))
            await asyncio.sleep(typing_duration)
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

async def keep_alive_loop(acc_id, client, interval=30):
    acc = find_account(acc_id)
    name = acc.get('name', acc_id) if acc else acc_id
    logger.info(f"[KEEPALIVE] Started for {name} (every {interval}s)")
    while not account_stop_flags.get(acc_id, False):
        try:
            me = await client.get_me()
            if me:
                try:
                    await client(UpdateStatusRequest(offline=False))
                except:
                    pass
            else:
                raise AuthKeyUnregisteredError("Session returned None")
        except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
            logger.warning(f"[KEEPALIVE] {name} - SESSION DEAD: {e}")
            real_acc = find_account(acc_id)
            if real_acc:
                await send_logout_notification(real_acc, str(e)[:50])
                await handle_banned(real_acc)
            return
        except Exception as e:
            logger.warning(f"[KEEPALIVE] {name} - Error: {e}")
            await asyncio.sleep(5)
        for _ in range(interval):
            if account_stop_flags.get(acc_id, False):
                break
            await asyncio.sleep(1)

async def check_account_status_periodically():
    logger.info("[CHECKER] Account status monitor started (every 5s)")
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
        await asyncio.sleep(5)

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
        account_keepalive_tasks[acc_id] = asyncio.create_task(keep_alive_loop(acc_id, client, interval=30))
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
        await send_welcome(client, chat_id)
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

async def send_welcome(client, chat_id):
    welcome_text = get_setting('welcome_message', '')
    welcome_image = get_setting('welcome_image', '')
    if not welcome_text:
        welcome_text = "🔥 PRICE LIST 🔥\n\n10 MIN VC → ₹99\n20 MIN VC → ₹119"
    if welcome_image and Path(welcome_image).exists():
        try:
            await client.send_file(chat_id, welcome_image, caption=welcome_text)
            return
        except:
            pass
    await send_with_typing(client, chat_id, welcome_text)

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
    if qr_path and Path(qr_path).exists():
        try:
            await client.send_file(chat_id, qr_path, caption=payment_msg)
            return
        except:
            pass
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
                    # Rotate messages properly
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
        logger.info(f"Deleting account: {name} ({aid})")
        
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
        # ============ TEXT HANDLER ============

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in admins:
        return
    text = update.message.text.strip()
    aw = context.user_data.get('await')
    if not aw:
        return
    
    if aw == 'seen_delay':
        try:
            v = int(text)
            if 1 <= v <= 5:
                set_setting('seen_delay', v)
                await update.message.reply_text(f"✅ Seen Delay set to: {v}s!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
            else:
                await update.message.reply_text("⚠️ 1-5 only!")
        except:
            await update.message.reply_text("⚠️ Number pls!")
        context.user_data['await'] = None
    
    elif aw == 'typing_duration':
        try:
            v = int(text)
            if 1 <= v <= 5:
                set_setting('typing_duration', v)
                await update.message.reply_text(f"✅ Typing Duration set to: {v}s!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
            else:
                await update.message.reply_text("⚠️ 1-5 only!")
        except:
            await update.message.reply_text("⚠️ Number pls!")
        context.user_data['await'] = None
    
    elif aw == 'ignore':
        set_setting('ignored_messages', text)
        await update.message.reply_text("✅ Ignored messages updated!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        context.user_data['await'] = None
    
    elif aw == 'rk':
        context.user_data['rk'] = text
        context.user_data['await'] = 'rt'
        await update.message.reply_text(f"💬 Keyword: `{text}`\n\nSelect match type:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Exact", callback_data="rt_exact")],
            [InlineKeyboardButton("✅ Contains", callback_data="rt_cont")],
            [InlineKeyboardButton("❌ Cancel", callback_data="ar_rp")]
        ]))
    
    elif aw == 'rt':
        kw = context.user_data.get('rk', '')
        tp = context.user_data.get('rt', 'contains')
        rid = add_reply(kw, text, tp)
        await update.message.reply_text(f"✅ Reply added! (ID: {rid})", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
        context.user_data['await'] = None
    
    elif aw == 'rb':
        data_list = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 3:
                kw, reply, mt = parts[0], parts[1], parts[2].lower()
                if mt not in ['exact', 'contains']:
                    mt = 'contains'
                data_list.append((kw, reply, mt))
        if data_list:
            ids = add_replies_bulk(data_list)
            msg = f"✅ {len(ids)} replies added!"
        else:
            msg = "❌ No valid replies!\n\nFormat: `keyword | reply | exact/contains`"
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_rp")]]))
        context.user_data['await'] = None
    
    elif aw == 'gs_bs':
        try:
            v = int(text)
            if 1 <= v <= 50:
                set_setting('spam_batch_size', v)
                await update.message.reply_text(f"✅ Batch Size: {v}!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
            else:
                await update.message.reply_text("⚠️ 1-50!")
        except:
            await update.message.reply_text("⚠️ Number!")
        context.user_data['await'] = None
    
    elif aw == 'gs_bd':
        try:
            v = int(text)
            if 0 <= v <= 30:
                set_setting('spam_batch_delay', v)
                await update.message.reply_text(f"✅ Batch Delay: {v}s!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
            else:
                await update.message.reply_text("⚠️ 0-30!")
        except:
            await update.message.reply_text("⚠️ Number!")
        context.user_data['await'] = None
    
    elif aw == 'gs_cw':
        try:
            v = int(text)
            if 0 <= v <= 300:
                set_setting('spam_cycle_wait', v)
                await update.message.reply_text(f"✅ Cycle Wait: {v}s!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
            else:
                await update.message.reply_text("⚠️ 0-300!")
        except:
            await update.message.reply_text("⚠️ Number!")
        context.user_data['await'] = None
    
    elif aw == 'gs_msg_add':
        add_spam_message(text)
        msgs = load_spam_messages()
        for acc in active_accounts:
            acc_id = acc['id']
            account_spam_messages[acc_id] = [m['text'] for m in msgs]
        await update.message.reply_text(f"✅ Message added!\n\n{text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
        context.user_data['await'] = None
    
    elif aw == 'dr_txt':
        set_setting('default_reply_text', text)
        await update.message.reply_text("✅ Default reply text set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))
        context.user_data['await'] = None
    
    elif aw == 'ad_add':
        try:
            aid = int(text.strip())
            if aid not in admins:
                admins.append(aid)
                await update.message.reply_text(f"✅ Admin {aid} added!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))
            else:
                await update.message.reply_text("⚠️ Already admin!")
        except:
            await update.message.reply_text("⚠️ Valid ID pls!")
        context.user_data['await'] = None
    
    elif aw == 'ac_ph':
        phone = text.strip()
        if not phone.startswith('+'):
            phone = '+' + phone
        context.user_data['ac_ph'] = phone
        context.user_data['await'] = 'ac_otp'
        try:
            client = TelegramClient(StringSession(), DEFAULT_API_ID, DEFAULT_API_HASH, receive_updates=False)
            await client.connect()
            await client.send_code_request(phone)
            context.user_data['ac_cl'] = client
            await update.message.reply_text(f"📱 OTP sent to {phone}\n\nEnter OTP:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ {str(e)[:80]}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            context.user_data['await'] = None
    
    elif aw == 'ac_otp':
        code = text.strip()
        phone = context.user_data.get('ac_ph', '')
        client = context.user_data.get('ac_cl')
        twofa = context.user_data.get('ac_2fa', False)
        if not client:
            await update.message.reply_text("⏰ Session expired! Start again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            context.user_data['await'] = None
            return
        if twofa:
            await sign_in_with_2fa(code, client, update, context, phone)
        else:
            await sign_in_with_code(phone, code, client, update, context)
    
    elif aw in ['ac_ss', 'ac_bk_ss']:
        ss = text.strip()
        is_backup = (aw == 'ac_bk_ss')
        await update.message.reply_text("🔄 Testing session string...")
        success, name, uid, phone = await test_session(ss)
        if success:
            info = {
                'id': gen_acc_id(), 'user_id': uid, 'name': name,
                'phone': phone, 'session': ss,
                'api_id': DEFAULT_API_ID, 'api_hash': DEFAULT_API_HASH,
                'enabled': True, 'mode': 'ai', 'spam_active': False,
                'proxy': None, 'is_backup': is_backup,
                'added_at': datetime.now().isoformat()
            }
            added = add_account_data(info, is_backup=is_backup)
            if not added:
                await update.message.reply_text("⚠️ Duplicate account! Already exists.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
                context.user_data['await'] = None
                return
            if not is_backup:
                c2 = await start_account(info)
                if c2:
                    active_accounts.append(info)
                    account_clients[info['id']] = c2
                    account_stats[info['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': True, 'spam_running': False}
                    account_stop_flags[info['id']] = False
                    register_ar(c2, info)
            await update.message.reply_text(f"✅ {'Backup ' if is_backup else ''}Account Added!\n👤 {name}\n📱 {phone}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        else:
            await update.message.reply_text(f"❌ Invalid session!\nError: {name}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
        context.user_data['await'] = None
    
    elif aw == 'proxy':
        aid = context.user_data.get('pr_aid', '')
        if text.lower() == 'remove':
            all_d = load_accounts_data()
            for key in ['main', 'backup']:
                for i, a in enumerate(all_d[key]):
                    if a['id'] == aid:
                        all_d[key][i]['proxy'] = None
                        save_json(ACCOUNTS_FILE, all_d)
                        for ac in active_accounts:
                            if ac['id'] == aid:
                                ac['proxy'] = None
                        await update.message.reply_text("✅ Proxy removed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_pr")]]))
                        context.user_data['await'] = None
                        context.user_data['pr_aid'] = None
                        return
        else:
            parts = text.split(':')
            if len(parts) >= 3:
                proxy = {
                    'type': parts[0], 'addr': parts[1], 'port': int(parts[2]),
                    'rdns': True, 'username': parts[3] if len(parts) > 3 else '',
                    'password': parts[4] if len(parts) > 4 else ''
                }
                all_d = load_accounts_data()
                for key in ['main', 'backup']:
                    for i, a in enumerate(all_d[key]):
                        if a['id'] == aid:
                            all_d[key][i]['proxy'] = proxy
                            save_json(ACCOUNTS_FILE, all_d)
                            for ac in active_accounts:
                                if ac['id'] == aid:
                                    ac['proxy'] = proxy
                            await update.message.reply_text("✅ Proxy set! Account will use proxy on next reconnect.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_pr")]]))
                            context.user_data['await'] = None
                            context.user_data['pr_aid'] = None
                            return
                await update.message.reply_text("❌ Account not found!")
            else:
                await update.message.reply_text("❌ Invalid format! Use: `type:ip:port:user:pass`")
        context.user_data['await'] = None
        context.user_data['pr_aid'] = None
    
    else:
        await update.message.reply_text("❓ Unknown command. Use /start")
        context.user_data['await'] = None


# ============ SETUP & RUN ============

async def setup_and_run():
    global ptb_application, bot_ready, bot_event_loop
    logger.info("=" * 50)
    logger.info("STARTING TELEGRAM BOT - FIXED VERSION")
    logger.info("=" * 50)
    
    _load_settings_to_cache()
    _load_replies_to_cache()
    
    logger.info("Setting up Python-Telegram-Bot...")
    ptb_application = Application.builder().token(BOT_TOKEN).concurrent_updates(True).read_timeout(30).write_timeout(30).connect_timeout(30).build()
    ptb_application.add_handler(CommandHandler("start", start_command))
    ptb_application.add_handler(CallbackQueryHandler(handle_callback))
    ptb_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"PTB Error: {context.error}", exc_info=True)
    ptb_application.add_error_handler(error_handler)

    await ptb_application.initialize()

    if RENDER_URL:
        webhook_url = f"{RENDER_URL}/webhook"
        logger.info(f"Setting up webhook: {webhook_url}")
        await ptb_application.bot.set_webhook(url=webhook_url)
    else:
        logger.info("Starting polling...")
        await ptb_application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    await ptb_application.start()

    logger.info("Setting up auto-reply accounts...")
    await setup_auto_reply()
    logger.info(f"Active accounts: {len(active_accounts)}")
    
    asyncio.create_task(check_account_status_periodically())
    logger.info("Account status checker started (instant logout detection)")
    
    bot_ready = True
    logger.info("BOT IS READY! All fixes applied!")

    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await shutdown_bot()

async def shutdown_bot():
    global bot_ready
    logger.info("Shutting down bot...")
    bot_ready = False
    stop_spam()
    
    for task in account_keepalive_tasks.values():
        task.cancel()
    account_keepalive_tasks.clear()
    
    for acc_id, client in list(account_clients.items()):
        try:
            await client.disconnect()
        except:
            pass
    account_clients.clear()
    active_accounts.clear()
    if ptb_application:
        try:
            if RENDER_URL:
                await ptb_application.bot.delete_webhook()
            await ptb_application.stop()
            await ptb_application.shutdown()
        except:
            pass
    logger.info("Bot shutdown complete")

# ============ FLASK ENDPOINTS ============

@flask_app.route('/')
def home():
    return jsonify({
        'status': 'running' if bot_ready else 'starting',
        'active_accounts': len(active_accounts),
        'auto_reply': auto_reply_enabled,
        'group_spam': group_spam_enabled,
        'logout_alert': logout_notification_enabled,
        'customers_today': len(customer_count),
        'uptime': datetime.now().isoformat()
    })

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    if not bot_ready:
        return jsonify({'ok': False, 'error': 'Bot not ready'}), 503
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, ptb_application.bot)
        if update:
            asyncio.run_coroutine_threadsafe(ptb_application.process_update(update), bot_event_loop)
        return jsonify({'ok': True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@flask_app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'bot_ready': bot_ready,
        'timestamp': datetime.now().isoformat()
    })

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

def main():
    global bot_event_loop
    logger.info("Starting bot system (FIXED VERSION)...")
    bot_event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_event_loop)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask server started on port {PORT}")
    try:
        bot_event_loop.run_until_complete(setup_and_run())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        try:
            bot_event_loop.run_until_complete(shutdown_bot())
        except:
            pass
        bot_event_loop.close()
        logger.info("Bot stopped")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
UNIFIED TELEGRAM BOT - CUSTOM VERSION
Features:
- START ALL / STOP ALL buttons for Auto Reply & Group Spam
- Welcome Message with Text + Image (customizable from bot)
- QR Code upload from bot
- Typing effect (customizable time)
- Block Photo toggle
- Payment settings (UPI/Paytm/QR)
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
from telethon.tl.functions.messages import GetDialogsRequest, ReadHistoryRequest
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.types import InputPeerEmpty

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

from flask import Flask, jsonify

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
WELCOME_IMAGE_FILE = DATA_DIR / "welcome_image.jpg"
QR_CODE_FILE = DATA_DIR / "qr_code.jpg"

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

DEFAULT_SETTINGS = {
    'auto_reply_enabled': True,
    'group_spam_enabled': True,
    'welcome_enabled': True,
    'welcome_message': '🔥 Welcome baby! 🔥\n\nSend "price" for rates\nSend "pay" for payment',
    'block_photo_enabled': True,
    'typing_enabled': True,
    'typing_duration': 240,
    'seen_delay': 1,
    'spam_speed': 'medium',
    'spam_batch_size': 5,
    'spam_batch_delay': 3,
    'spam_cycle_wait': 30,
    'flood_slow_mode': True,
    'spam_message': '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘',
    'ignored_messages': '',
    'price_list_text': '🔥 10 MIN VC → ₹99\n🔥 20 MIN VC → ₹119\n🔥 30 MIN VC → ₹149',
    'upi_id': '',
    'paytm_num': '',
    'qr_code_path': '',
    'payment_keyword_reply': 'Scan & Pay baby 😘🔥',
    'media_keyword_reply': 'Payment first baby 😘🔥',
    'offline_keyword_reply': 'Online only baby 😊',
    'greeting_replies': ['Hi baby, ready! 🔥', 'Hey baby! 😘', 'Hello! What you need? 🔥'],
    'default_replies': ['Ready baby! Pay karo! 🔥', 'Main ready hoon! 😘', 'Service ready! 💯']
}

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

def get_setting(key, default=None):
    if not _settings_cache:
        _load_settings_to_cache()
    return _settings_cache.get(key, default if default is not None else DEFAULT_SETTINGS.get(key))

def set_setting(key, value):
    global _settings_cache
    if not _settings_cache:
        _load_settings_to_cache()
    _settings_cache[key] = value
    try:
        tmp = SETTINGS_FILE.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_settings_cache, f, indent=2, ensure_ascii=False)
        tmp.replace(SETTINGS_FILE)
    except Exception as e:
        logger.error(f"Settings save failed: {e}")

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
            logger.warning(f"Duplicate: {acc.get('name', 'Unknown')}")
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

# ====== NOTIFICATIONS ======
async def send_logout_notification(acc, reason="Unknown"):
    if not logout_notification_enabled:
        return
    try:
        name = acc.get('name', 'Unknown')
        phone = acc.get('phone', 'N/A')
        acc_id = acc.get('id', '?')
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=OWNER_ID, text=f"🚫 **ACCOUNT LOGOUT DETECTED!**\n\n👤 Name: {name}\n🆔 ID: {acc_id}\n📱 Phone: {phone}\n⚠️ Reason: {reason}\n🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n🔄 Auto-replacing with backup...", parse_mode='Markdown')
    except:
        pass

async def send_backup_activation_notification(backup):
    if not logout_notification_enabled:
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=OWNER_ID, text=f"✅ **BACKUP ACTIVATED!**\n\n👤 New Active: {backup.get('name', 'Unknown')}\n📱 Phone: {backup.get('phone', 'N/A')}\n🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n⚡ System is fully operational.", parse_mode='Markdown')
    except:
        pass

# ====== KEEPALIVE ======
async def keep_alive_loop(acc_id, client, interval=30):
    acc = find_account(acc_id)
    name = acc.get('name', acc_id) if acc else acc_id
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
            real_acc = find_account(acc_id)
            if real_acc:
                await send_logout_notification(real_acc, str(e)[:50])
                await handle_banned(real_acc)
            return
        except:
            await asyncio.sleep(5)
        for _ in range(interval):
            if account_stop_flags.get(acc_id, False):
                break
            await asyncio.sleep(1)

async def check_account_status_periodically():
    while not shutdown_event.is_set():
        try:
            for acc in list(active_accounts):
                acc_id = acc['id']
                if acc_id in account_clients:
                    try:
                        me = await account_clients[acc_id].get_me(timeout=5)
                        if not me:
                            raise AuthKeyUnregisteredError("No user returned")
                    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
                        await send_logout_notification(acc, str(e)[:50])
                        await handle_banned(acc)
                    except:
                        pass
        except:
            pass
        await asyncio.sleep(10)

# ====== ACCOUNT MGMT ======
async def start_account(acc):
    try:
        proxy_config = acc.get('proxy')
        proxy = None
        if proxy_config and proxy_config.get('addr'):
            proxy = (socks.SOCKS5, proxy_config.get('addr', ''), proxy_config.get('port', 1080),
                     proxy_config.get('rdns', True), proxy_config.get('username', ''), proxy_config.get('password', ''))
        client = TelegramClient(StringSession(acc['session']), acc.get('api_id', DEFAULT_API_ID),
                                acc.get('api_hash', DEFAULT_API_HASH), proxy=proxy, sequential_updates=True, receive_updates=True)
        await client.start()
        me = await client.get_me()
        acc_id = acc['id']
        custom_msgs = load_spam_messages()
        if custom_msgs:
            account_spam_messages[acc_id] = [m['text'] for m in custom_msgs]
        else:
            base_msg = get_setting('spam_message', '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')
            account_spam_messages[acc_id] = [f"{base_msg} ✨", f"{base_msg} 💋", f"{base_msg} 🔥", f"{base_msg} 💖", f"🔥 {base_msg}", f"💋 {base_msg}", f"✨ {base_msg} 😘", f"{base_msg} 👑"]
        if acc_id in account_keepalive_tasks:
            account_keepalive_tasks[acc_id].cancel()
        account_keepalive_tasks[acc_id] = asyncio.create_task(keep_alive_loop(acc_id, client, interval=30))
        return client
    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
        await send_logout_notification(acc, str(e)[:50])
        await handle_banned(acc)
        return None
    except Exception as e:
        logger.error(f"Start account failed: {e}")
        return None

async def handle_banned(acc):
    acc_id = acc['id']
    name = acc.get('name', 'Unknown')
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
            account_stats[backup_copy['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
            account_stop_flags[backup_copy['id']] = False
            account_spam_active[backup_copy['id']] = False
            register_ar(client, backup_copy)
    else:
        logger.warning("No backups!")

# ====== AUTO REPLY ======
ALL_EMOJIS = ['😀','😃','😄','😁','😆','😅','😂','🤣','😊','😇','🥰','😍','🤩','😘']

def get_random_emoji():
    return random.choice(ALL_EMOJIS)

def register_ar(client, acc):
    @client.on(events.NewMessage(incoming=True))
    async def auto_reply_handler(event):
        try:
            if not auto_reply_enabled: return
            if not event.is_private: return
            sender = await event.get_sender()
            if not sender: return
            uid = sender.id
            if uid == OWNER_ID or uid in admins: return
            if not acc.get('enabled', True): return
            if uid in processing_users: return
            processing_users.add(uid)
            try:
                if uid not in customer_count:
                    customer_count[uid] = 0
                await process_auto_reply_fast(event, client, acc, uid)
            finally:
                processing_users.discard(uid)
        except Exception as e:
            logger.error(f"AR error: {e}")
    return auto_reply_handler

async def process_auto_reply_fast(event, client, acc, uid):
    chat_id = event.chat_id
    message_text = event.message.text or ""
    if uid not in customer_count:
        customer_count[uid] = 0
    msg_count = customer_count[uid]
    
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
    
    if get_setting('typing_enabled', True):
        typing_duration = int(get_setting('typing_duration', 240))
        if typing_duration > 0:
            try:
                async with client.action(chat_id, 'typing'):
                    await asyncio.sleep(min(typing_duration, 300))
            except:
                pass
    
    if msg_count == 0 and get_setting('welcome_enabled', True):
        welcome_text = get_setting('welcome_message', '🔥 Welcome baby! 🔥')
        if WELCOME_IMAGE_FILE.exists():
            try:
                await client.send_file(chat_id, str(WELCOME_IMAGE_FILE), caption=welcome_text)
            except:
                await client.send_message(chat_id, welcome_text)
        else:
            await client.send_message(chat_id, welcome_text)
        customer_count[uid] = msg_count + 1
        return
    
    ignored = get_setting('ignored_messages', '')
    if ignored:
        for line in ignored.split('\n'):
            if line.strip().lower() == msg_lower:
                customer_count[uid] = msg_count + 1
                return
    
    payment_keywords = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'send', 'bhejo', 'screenshot', 'method', 'transfer', 'rupees', 'rs', 'money']
    if any(kw in msg_lower for kw in payment_keywords):
        await send_payment_info(client, chat_id, event)
        customer_count[uid] = msg_count + 1
        return
    
    media_keywords = ['pic', 'photo', 'image', 'nude', 'naked', 'dikhao', 'show', 'nangi', 'boob', 'mms']
    if any(kw in msg_lower for kw in media_keywords):
        await event.respond(get_setting('media_keyword_reply', 'Payment first baby 😘🔥'))
        customer_count[uid] = msg_count + 1
        return
    
    service_keywords = ['service', 'chahiye', 'kharid', 'demo', 'video', 'call', 'vc', 'price', 'rate']
    if any(kw in msg_lower for kw in service_keywords):
        price_text = get_setting('price_list_text', "🔥 10 MIN VC → ₹99\n🔥 20 MIN VC → ₹119")
        await event.respond(price_text)
        await asyncio.sleep(0.3)
        await event.respond(random.choice(["How many minutes? 🔥", "Pay and enjoy! 😘", "Tell me your choice 💋"]))
        customer_count[uid] = msg_count + 1
        return
    
    offline_keywords = ['real', 'meet', 'aao', 'ghar', 'location', 'offline']
    if any(kw in msg_lower for kw in offline_keywords):
        await event.respond(get_setting('offline_keyword_reply', 'Online only baby 😊'))
        customer_count[uid] = msg_count + 1
        return
    
    greeting_keywords = ['hi', 'hello', 'hey', 'hii', 'hy', 'hlo', 'hlw', 'helo']
    if any(w in msg_lower for w in greeting_keywords):
        greetings = get_setting('greeting_replies', ['Hi baby, ready! 🔥', 'Hey baby! 😘', 'Hello! What you need? 🔥'])
        await event.respond(random.choice(greetings))
        customer_count[uid] = msg_count + 1
        return
    
    defaults = get_setting('default_replies', ['Ready baby! Pay karo! 🔥', 'Main ready hoon! 😘', 'Service ready! 💯'])
    await event.respond(random.choice(defaults))
    customer_count[uid] = msg_count + 1

async def send_payment_info(client, chat_id, event):
    upi = get_setting('upi_id', '')
    paytm = get_setting('paytm_num', '')
    payment_msg = "**💰 Payment 💰**\n\n"
    if upi: payment_msg += f"📱 UPI: {upi}\n"
    if paytm: payment_msg += f"💳 PayTm: {paytm}\n"
    payment_msg += f"\n{get_setting('payment_keyword_reply', 'Scan & Pay baby 😘🔥')}"
    if QR_CODE_FILE.exists():
        try:
            await client.send_file(chat_id, str(QR_CODE_FILE), caption=payment_msg)
            return
        except:
            pass
    await event.respond(payment_msg)

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
        logger.error(f"Block failed: {e}")

async def handle_payment_screenshot(event, client, uid):
    try:
        if event.message.photo: photo = event.message.photo[-1]
        else: photo = event.message.document
        file_path = PAYMENT_SS_DIR / f"{uid}_{event.message.id}.jpg"
        await photo.download_async(str(file_path))
        customer_payment_photos[uid] = str(file_path)
        sender_name = getattr(event.sender, 'first_name', 'Unknown')
        await event.respond("✅ Payment screenshot received! Admin will contact you soon")
        try:
            await client.send_message(OWNER_ID, f"💳 **PAYMENT RECEIVED!**\n\n👤 Name: {sender_name}\n🆔 ID: {uid}", parse_mode='Markdown')
            await client.send_file(OWNER_ID, str(file_path))
        except: pass
        customer_count[uid] = -2
    except Exception as e:
        logger.error(f"Payment ss failed: {e}")

async def setup_auto_reply():
    _load_settings_to_cache()
    for acc in get_main_accounts():
        if acc['id'] not in [a['id'] for a in active_accounts]:
            client = await start_account(acc)
            if client:
                active_accounts.append(acc)
                account_clients[acc['id']] = client
                account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                account_stop_flags[acc['id']] = False
                register_ar(client, acc)
            await asyncio.sleep(1)

# ====== GROUP SPAM ======
async def get_user_groups(client):
    try:
        dialogs = await client(GetDialogsRequest(offset_date=None, offset_id=0, offset_peer=InputPeerEmpty(), limit=200, hash=0))
        groups = []
        for dialog in dialogs.dialogs:
            try:
                entity = await client.get_entity(dialog.peer)
                if hasattr(entity, 'title'):
                    is_group = (hasattr(entity, 'megagroup') and entity.megagroup) or (hasattr(entity, 'broadcast') and not entity.broadcast) or (not hasattr(entity, 'broadcast') and not hasattr(entity, 'megagroup'))
                    if is_group: groups.append(entity)
            except: pass
        return groups
    except:
        return []

async def spam_account(acc):
    acc_id = acc['id']
    acc_name = acc.get('name', acc_id)
    account_stop_flags[acc_id] = False
    account_stats[acc_id]['spam_running'] = True
    account_spam_active[acc_id] = True
    try:
        proxy_config = acc.get('proxy')
        proxy = None
        if proxy_config and proxy_config.get('addr'):
            proxy = (socks.SOCKS5, proxy_config.get('addr', ''), proxy_config.get('port', 1080), proxy_config.get('rdns', True), proxy_config.get('username', ''), proxy_config.get('password', ''))
        client = TelegramClient(StringSession(acc['session']), acc.get('api_id', DEFAULT_API_ID), acc.get('api_hash', DEFAULT_API_HASH), proxy=proxy, receive_updates=False)
        await client.start()
        groups = await get_user_groups(client)
        if not groups:
            account_stats[acc_id]['spam_running'] = False
            account_spam_active[acc_id] = False
            return
        speed = get_setting('spam_speed', 'medium')
        speed_configs = {
            'super_fast': {'batch_size': 999, 'batch_delay': 0, 'cycle_delay': 0, 'min_interval': 0, 'max_interval': 1.5},
            'fast': {'batch_size': 999, 'batch_delay': 0, 'cycle_delay': 5, 'min_interval': 0.5, 'max_interval': 2},
            'medium': {'batch_size': 5, 'batch_delay': 2, 'cycle_delay': 15, 'min_interval': 2, 'max_interval': 4},
            'slow': {'batch_size': 3, 'batch_delay': 5, 'cycle_delay': 30, 'min_interval': 5, 'max_interval': 8},
            'custom': {'batch_size': int(get_setting('spam_batch_size', 6)), 'batch_delay': int(get_setting('spam_batch_delay', 3)), 'cycle_delay': int(get_setting('spam_cycle_wait', 30)), 'min_interval': int(get_setting('spam_min_interval', 3)), 'max_interval': int(get_setting('spam_max_interval', 6))}
        }
        config = speed_configs.get(speed, speed_configs['medium'])
        flood_slow_mode = get_setting('flood_slow_mode', True)
        spam_messages = account_spam_messages.get(acc_id, [get_setting('spam_message', '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')])
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
                    emoji = get_random_emoji()
                    message = f"{spam_messages[msg_index % len(spam_messages)]} {emoji}"
                    await client.send_message(group, message)
                    account_stats[acc_id]['spam_sent'] += 1
                    error_count = 0
                    msg_index += 1
                except FloodWaitError as e:
                    error_count += 1
                    await asyncio.sleep(min(e.seconds, 30) if flood_slow_mode else e.seconds)
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
            if account_stop_flags.get(acc_id, False): break
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
                    client = TelegramClient(StringSession(acc['session']), acc.get('api_id', DEFAULT_API_ID), acc.get('api_hash', DEFAULT_API_HASH), proxy=proxy, receive_updates=False)
                    await client.start()
                    groups = await get_user_groups(client)
                    max_batch = min(config['batch_size'], len(groups))
                except: pass
            if config['cycle_delay'] > 0:
                for _ in range(config['cycle_delay']):
                    if account_stop_flags.get(acc_id, False): break
                    await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        if 'AuthKey' in str(e) or 'DEACTIVATED' in str(e):
            await send_logout_notification(acc, str(e)[:50])
            await handle_banned(acc)
    finally:
        account_stats[acc_id]['spam_running'] = False
        account_spam_active[acc_id] = False
        try: await client.disconnect()
        except: pass

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
        stats = account_stats.get(acc['id'], {})
        if not stats.get('spam_running', False):
            account_spam_active[acc['id']] = True
            account_stop_flags[acc['id']] = False
            task = asyncio.create_task(spam_account(acc))
            account_spam_tasks[acc['id']] = task

# ====== BOT UI ======
def main_keyboard():
    ar_status = "🟢 ACTIVE" if auto_reply_enabled else "🔴 STOPPED"
    gs_status = "🟢 ACTIVE" if group_spam_enabled else "🔴 STOPPED"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 Auto Reply [{ar_status}]", callback_data="m_ar")],
        [InlineKeyboardButton(f"📨 Group Spam [{gs_status}]", callback_data="m_gs")],
        [InlineKeyboardButton(f"👥 Accounts 📋", callback_data="m_acc")],
        [InlineKeyboardButton(f"⚙️ Settings 🔧", callback_data="m_set")],
        [InlineKeyboardButton(f"📊 Status 📈", callback_data="m_stat")],
        [InlineKeyboardButton(f"🛡️ Admin 👑", callback_data="m_adm")],
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in admins:
        await update.message.reply_text("⛔ Unauthorized!")
        return
    await update.message.reply_text("🔥 **CONTROL PANEL** 🔥\n\nSelect an option below:", parse_mode='Markdown', reply_markup=main_keyboard())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, logout_notification_enabled, active_accounts
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if user_id != OWNER_ID and user_id not in admins:
        await query.edit_message_text("⛔ Access Denied!")
        return
    
    if data == "main":
        await query.edit_message_text("🔥 **CONTROL PANEL** 🔥\n\nSelect an option below:", parse_mode='Markdown', reply_markup=main_keyboard())
    
    elif data == "m_ar":
        status = "🟢 ACTIVE" if auto_reply_enabled else "🔴 STOPPED"
        text = f"🤖 **AUTO REPLY**\n\nStatus: {status}\n\n▶️ Start All = সব একাউন্টের অটো রিপ্লাই চালু\n⏹️ Stop All = সব বন্ধ"
        kb = [
            [InlineKeyboardButton("▶️ START ALL", callback_data="ar_start")],
            [InlineKeyboardButton("⏹️ STOP ALL", callback_data="ar_stop")],
            [InlineKeyboardButton("👋 Welcome Msg + Pic", callback_data="ar_welcome")],
            [InlineKeyboardButton("🚫 Block Photo", callback_data="ar_blockphoto")],
            [InlineKeyboardButton("⌨️ Typing Time", callback_data="ar_typing")],
            [InlineKeyboardButton("🚫 Ignored Msgs", callback_data="ar_ignore")],
            [InlineKeyboardButton("📝 Custom Replies", callback_data="ar_replies")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ar_start":
        auto_reply_enabled = True
        await query.edit_message_text("✅ **Auto Reply চালু হয়েছে!** সব একাউন্ট রিপ্লাই দিবে।", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
    
    elif data == "ar_stop":
        auto_reply_enabled = False
        await query.edit_message_text("⏹️ **Auto Reply বন্ধ হয়েছে!** কোনো একাউন্ট রিপ্লাই দিবে না।", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
    
    elif data == "ar_welcome":
        enabled = get_setting('welcome_enabled', True)
        status = "🟢 ON" if enabled else "🔴 OFF"
        msg = get_setting('welcome_message', '🔥 Welcome baby! 🔥')
        has_img = "✅" if WELCOME_IMAGE_FILE.exists() else "❌"
        txt = f"👋 **Welcome Message**\n\nStatus: {status}\n\nText:\n`{msg}`\n\nImage: {has_img}"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Toggle", callback_data="ar_welcome_tog")],
            [InlineKeyboardButton("✏️ Change Text", callback_data="ar_welcome_edit")],
            [InlineKeyboardButton("📷 Upload/Change Image", callback_data="ar_welcome_img")],
            [InlineKeyboardButton("🗑️ Remove Image", callback_data="ar_welcome_img_del")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ar_welcome_tog":
        cur = get_setting('welcome_enabled', True)
        set_setting('welcome_enabled', not cur)
        await handle_callback(update, context)
    
    elif data == "ar_welcome_edit":
        context.user_data['await'] = 'welcome_text'
        await query.edit_message_text("✏️ **Enter new Welcome Message Text:**\n\nSend the text now:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_welcome")]]))
    
    elif data == "ar_welcome_img":
        context.user_data['await'] = 'welcome_image'
        await query.edit_message_text("📷 **Send the Welcome Image now:**\n\nJust send a photo.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_welcome")]]))
    
    elif data == "ar_welcome_img_del":
        if WELCOME_IMAGE_FILE.exists():
            WELCOME_IMAGE_FILE.unlink()
            await query.edit_message_text("✅ Image removed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_welcome")]]))
        else:
            await query.edit_message_text("❌ No image to remove!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_welcome")]]))
    
    elif data == "ar_blockphoto":
        enabled = get_setting('block_photo_enabled', True)
        status = "🟢 ON" if enabled else "🔴 OFF"
        txt = f"🚫 **Block Photo**\n\nStatus: {status}\n\nON = ফটো পেলে ব্লক করবে\nOFF = ফটো পেলে পেমেন্ট স্ক্রিনশট হিসেবে নিবে"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Toggle", callback_data="ar_blockphoto_tog")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ar_blockphoto_tog":
        cur = get_setting('block_photo_enabled', True)
        set_setting('block_photo_enabled', not cur)
        await handle_callback(update, context)
    
    elif data == "ar_typing":
        enabled = get_setting('typing_enabled', True)
        duration = int(get_setting('typing_duration', 240))
        status = "🟢 ON" if enabled else "🔴 OFF"
        txt = f"⌨️ **Typing Effect**\n\nStatus: {status}\n\nDuration: {duration} seconds\n\nমেসেজ পাঠানোর আগে এত সময় টাইপিং করবে।\n\nExample: 60 = 1 মিনিট, 240 = 4 মিনিট"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Toggle", callback_data="ar_typing_tog")],
            [InlineKeyboardButton("⏱️ Set Time", callback_data="ar_typing_time")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ar_typing_tog":
        cur = get_setting('typing_enabled', True)
        set_setting('typing_enabled', not cur)
        await handle_callback(update, context)
    
    elif data == "ar_typing_time":
        context.user_data['await'] = 'typing_time'
        await query.edit_message_text(f"⏱️ **Enter Typing Time (seconds):**\n\nCurrent: {get_setting('typing_duration', 240)}\n\nRange: 0-300\n\nEx: 60 = 1 মিনিট\n240 = 4 মিনিট", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_typing")]]))
    
    elif data == "ar_ignore":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "🚫 **Ignored Messages**\nযেসব মেসেজের রিপ্লাই দিবে না (এক লাইনে একটি):\n\n"
        if cur: txt += f"Current:\n`{cur}`\n\n"
        txt += "Example:\n`thanks`\n`bye`\n`ok`"
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
    
    elif data == "ar_replies":
        replies = load_json(REPLIES_FILE, [])
        txt = "📝 **Custom Replies**\n\n"
        if replies:
            for i, r in enumerate(replies[-10:], 1):
                txt += f"{i}. `{r['keyword'][:15]}` → {r['reply'][:25]}...\n"
        else:
            txt += "No custom replies added yet.\n"
        txt += "\nUse /add_reply command to add."
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
    
    elif data == "m_gs":
        run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        st = "🟢 ACTIVE" if group_spam_enabled else "🔴 STOPPED"
        spd = get_setting('spam_speed', 'medium')
        sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        txt = f"📨 **GROUP SPAM**\n\nStatus: {st}\nRunning: {run}/{len(active_accounts)}\nSent: {sent}\nSpeed: {spd}"
        kb = [
            [InlineKeyboardButton("▶️ START ALL", callback_data="gs_start"), InlineKeyboardButton("⏹️ STOP ALL", callback_data="gs_stop")],
            [InlineKeyboardButton("👤 Per Account", callback_data="gs_sp")],
            [InlineKeyboardButton("⚡ Speed", callback_data="gs_spd")],
            [InlineKeyboardButton("📝 Messages", callback_data="gs_msg")],
            [InlineKeyboardButton("📊 Stats", callback_data="gs_st")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "gs_start":
        group_spam_enabled = True
        start_spam()
        await query.edit_message_text("✅ **Group Spam চালু!** সব একাউন্ট স্প্যাম শুরু করেছে।", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
    
    elif data == "gs_stop":
        group_spam_enabled = False
        stop_spam()
        await query.edit_message_text("⏹️ **Group Spam বন্ধ!** সব স্প্যাম বন্ধ হয়েছে।", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
    
    elif data == "gs_sp":
        if not active_accounts:
            await query.edit_message_text("❌ No accounts!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
            return
        kb = [[InlineKeyboardButton(f"{'▶️' if account_stats.get(a['id'], {}).get('spam_running', False) else '⏹️'} {a.get('name','?')[:12]}", callback_data=f"gsa_{a['id']}")] for a in active_accounts]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_gs")])
        await query.edit_message_text("Toggle per account:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("gsa_"):
        aid = data.replace("gsa_", "")
        if account_stats.get(aid, {}).get('spam_running', False):
            stop_spam(aid)
        else:
            start_spam(aid)
        await handle_callback(update, context)
    
    elif data == "gs_spd":
        cur = get_setting('spam_speed', 'medium')
        kb = [[InlineKeyboardButton(f"{'✅' if cur=='super_fast' else ''} Super Fast", callback_data="gs_sf")],
              [InlineKeyboardButton(f"{'✅' if cur=='fast' else ''} Fast", callback_data="gs_fa")],
              [InlineKeyboardButton(f"{'✅' if cur=='medium' else ''} Medium", callback_data="gs_me")],
              [InlineKeyboardButton(f"{'✅' if cur=='slow' else ''} Slow", callback_data="gs_sl")],
              [InlineKeyboardButton(f"{'✅' if cur=='custom' else ''} Custom", callback_data="gs_cs")],
              [InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]
        await query.edit_message_text(f"⚡ **Speed**\nCurrent: {cur}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data in ["gs_sf", "gs_fa", "gs_me", "gs_sl", "gs_cs"]:
        m = {'gs_sf': 'super_fast', 'gs_fa': 'fast', 'gs_me': 'medium', 'gs_sl': 'slow', 'gs_cs': 'custom'}
        set_setting('spam_speed', m[data])
        if data == 'gs_cs':
            kb = [[InlineKeyboardButton("📦 Batch Size", callback_data="gs_bs")],
                  [InlineKeyboardButton("⏱️ Batch Delay", callback_data="gs_bd")],
                  [InlineKeyboardButton("🔄 Cycle Wait", callback_data="gs_cw")],
                  [InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]
            await query.edit_message_text("⚙️ **Custom Settings**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.edit_message_text(f"✅ Speed: {m[data]}!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
    
    elif data == "gs_bs":
        context.user_data['await'] = 'gs_bs'
        await query.edit_message_text(f"📦 Batch Size\nCurrent: {get_setting('spam_batch_size', 6)}\n\nEnter (1-50):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
    
    elif data == "gs_bd":
        context.user_data['await'] = 'gs_bd'
        await query.edit_message_text(f"⏱️ Batch Delay\nCurrent: {get_setting('spam_batch_delay', 3)}s\n\nEnter (0-30):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
    
    elif data == "gs_cw":
        context.user_data['await'] = 'gs_cw'
        await query.edit_message_text(f"🔄 Cycle Wait\nCurrent: {get_setting('spam_cycle_wait', 30)}s\n\nEnter (0-300):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
    
    elif data == "gs_msg":
        msgs = load_spam_messages()
        txt = "📝 **Spam Messages**\n\n"
        if msgs:
            for m in msgs:
                txt += f"• {m['text'][:40]}... [ID: {m['id']}]\n"
        else:
            txt += f"Default: {get_setting('spam_message', '...')}\n"
        kb = [[InlineKeyboardButton("➕ Add", callback_data="gs_msg_add")],
              [InlineKeyboardButton("🗑️ Delete", callback_data="gs_msg_del")],
              [InlineKeyboardButton("📋 Show All", callback_data="gs_msg_list")],
              [InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "gs_msg_add":
        context.user_data['await'] = 'gs_msg_add'
        await query.edit_message_text("✏️ Enter new spam message:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
    
    elif data == "gs_msg_del":
        msgs = load_spam_messages()
        if not msgs:
            await query.edit_message_text("❌ No custom messages!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {m['text'][:25]}", callback_data=f"gsmd_{m['id']}")] for m in msgs[:10]]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="gs_msg")])
        await query.edit_message_text("🗑️ **Select to delete:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("gsmd_"):
        mid = int(data.split('_')[1])
        delete_spam_message(mid)
        await query.edit_message_text("✅ Deleted!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))
    
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
            r = "▶️" if account_stats.get(a['id'], {}).get('spam_running', False) else "⏹️"
            txt += f"{r} {a.get('name', '?')}: {s}\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
    
    elif data == "m_acc":
        ma = len(get_main_accounts())
        ba = len(get_backup_accounts())
        act = len(active_accounts)
        txt = f"👥 **Account Management**\n\nMain: {ma} | Backup: {ba} | Active: {act}"
        kb = [[InlineKeyboardButton("📱 Phone + OTP", callback_data="ac_ph")],
              [InlineKeyboardButton("🔑 Session String", callback_data="ac_ss")],
              [InlineKeyboardButton("🗑️ Delete", callback_data="ac_del")],
              [InlineKeyboardButton("💾 Backup Mgmt", callback_data="ac_bk")],
              [InlineKeyboardButton("🌐 Proxy", callback_data="ac_pr")],
              [InlineKeyboardButton("📋 List All", callback_data="ac_ls")],
              [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("📱 Enter phone number\nInternational format:\n+8801XXXXXXXXX", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
    
    elif data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("🔑 Paste Session String", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
    
    elif data == "ac_del":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ No accounts!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}", callback_data=f"acd_{a['id']}")] for a in all_a]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_acc")])
        await query.edit_message_text("🗑️ **Delete Account:**\nPermanently removed!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
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
            try: await account_clients[aid].disconnect()
            except: pass
            del account_clients[aid]
        active_accounts = [x for x in active_accounts if x['id'] != aid]
        for d in [account_stats, account_stop_flags, account_spam_tasks, account_keepalive_tasks, account_spam_active]:
            if aid in d: del d[aid]
        remove_account_data(aid)
        await query.edit_message_text(f"✅ {name} permanently deleted!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
    
    elif data == "ac_bk":
        ba = get_backup_accounts()
        txt = f"💾 **Backup Accounts**\nTotal: {len(ba)}\n\nAuto-used when main banned.\n\n"
        for i, a in enumerate(ba, 1):
            txt += f"{i}. {a.get('name', '?')} ({a.get('phone', 'N/A')})\n"
        kb = [[InlineKeyboardButton("➕ Add Backup", callback_data="ac_bk_add")],
              [InlineKeyboardButton("🗑️ Remove", callback_data="ac_bk_del")],
              [InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_bk_add":
        context.user_data['await'] = 'ac_bk_ss'
        await query.edit_message_text("🔑 Backup Session String\n\nPaste:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
    
    elif data == "ac_bk_del":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ No backups!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="ac_bk")])
        await query.edit_message_text("🗑️ **Remove Backup:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("acbkd_"):
        bid = data.split('_')[1]
        remove_account_data(bid)
        await query.edit_message_text("✅ Backup removed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
    
    elif data == "ac_pr":
        if not active_accounts:
            await query.edit_message_text("❌ No active accounts!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"🌐 {a.get('name','?')[:12]} {'✅' if a.get('proxy') else '❌'}", callback_data=f"acpr_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_acc")])
        await query.edit_message_text("🌐 **Set Proxy per Account**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("acpr_"):
        aid = data.split('_')[1]
        context.user_data['pr_aid'] = aid
        context.user_data['await'] = 'proxy'
        await query.edit_message_text("🌐 Proxy format:\n`socks5:ip:port:user:pass`\n\nType `remove` to clear", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_pr")]]))
    
    elif data == "ac_ls":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ None!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        txt = f"📋 **All Accounts** ({len(all_a)})\n\n"
        for i, a in enumerate(all_a, 1):
            n = a.get('name', '?')
            p = a.get('phone', 'N/A')
            tp = "MAIN" if not a.get('is_backup') else "BACKUP"
            st = "🟢" if any(x['id'] == a['id'] for x in active_accounts) else "🔴"
            txt += f"{st} {tp} {i}. {n} 📱{p}\n"
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
    
    elif data == "m_set":
        bp = "🟢" if get_setting('block_photo_enabled', True) else "🔴"
        fs = "🟢" if get_setting('flood_slow_mode', True) else "🔴"
        ln = "🟢" if logout_notification_enabled else "🔴"
        has_qr = "✅" if QR_CODE_FILE.exists() else "❌"
        txt = f"⚙️ **Settings**\n\n🚫 Block Photo: {bp}\n🐢 Flood Slow: {fs}\n🔔 Logout Alert: {ln}\n📷 QR Code: {has_qr}"
        kb = [
            [InlineKeyboardButton(f"🚫 Block Photo {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"🐢 Flood Slow {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"🔔 Logout Alert {ln}", callback_data="st_ln")],
            [InlineKeyboardButton(f"💳 Payment Settings", callback_data="st_pay")],
            [InlineKeyboardButton(f"📷 QR Code {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_bp":
        cur = get_setting('block_photo_enabled', True)
        set_setting('block_photo_enabled', not cur)
        await handle_callback(update, context)

    elif data == "st_fs":
        cur = get_setting('flood_slow_mode', True)
        set_setting('flood_slow_mode', not cur)
        await handle_callback(update, context)

    elif data == "st_ln":
        logout_notification_enabled = not logout_notification_enabled
        await handle_callback(update, context)

    elif data == "st_pay":
        upi = get_setting('upi_id', '')
        paytm = get_setting('paytm_num', '')
        txt = f"💳 **Payment Settings**\n\n📱 UPI: {upi or '❌ Not Set'}\n💳 PayTm: {paytm or '❌ Not Set'}"
        kb = [
            [InlineKeyboardButton("✏️ Set UPI", callback_data="st_upi")],
            [InlineKeyboardButton("✏️ Set PayTm", callback_data="st_paytm")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_set")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_upi":
        context.user_data['await'] = 'upi'
        await query.edit_message_text("✏️ Enter UPI ID:\n\nEx: `user@upi`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_pay")]]))

    elif data == "st_paytm":
        context.user_data['await'] = 'paytm'
        await query.edit_message_text("✏️ Enter PayTm Number:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_pay")]]))

    elif data == "st_qr":
        context.user_data['await'] = 'qr_code'
        await query.edit_message_text("📷 Send QR Code image now:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))

    elif data == "m_stat":
        ar = "🟢" if auto_reply_enabled else "🔴"
        gs = "🟢" if group_spam_enabled else "🔴"
        ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
        ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        spm_act = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        txt = f"📊 **System Status**\n\n🤖 Auto Reply: {ar}\n📨 Group Spam: {gs}\n👤 Active: {len(active_accounts)}\n📨 Spamming: {spm_act}\n💬 Auto Sent: {ttl_auto}\n📬 Spam Sent: {ttl_spam}\n👥 Customers: {len(customer_count)}"
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="m_stat"), InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]))

    elif data == "m_adm":
        txt = "🛡️ **Admin Panel**\n\n"
        kb = [
            [InlineKeyboardButton("📢 Broadcast", callback_data="ad_bc")],
            [InlineKeyboardButton("📄 View Logs", callback_data="ad_lg")],
            [InlineKeyboardButton("🔄 Restart Bot", callback_data="ad_rt")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ad_bc":
        context.user_data['await'] = 'broadcast'
        await query.edit_message_text("📢 Enter broadcast message to send ALL customers:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))

    elif data == "ad_lg":
        log_path = Path(__file__).parent / "bot.log"
        if log_path.exists():
            with open(log_path, 'r') as f:
                lines = f.readlines()[-20:]
            txt = "📄 **Last 20 Log Lines**\n\n" + "".join(lines[-500:])
        else:
            txt = "📄 No log file found."
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))

    elif data == "ad_rt":
        await query.edit_message_text("🔄 Restarting bot... Please wait.")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    else:
        await query.edit_message_text(f"⚠️ Unknown callback: {data}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]))


# ====== TEXT MESSAGE HANDLER ======
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in admins:
        return

    text = update.message.text.strip()
    await_state = context.user_data.get('await')

    if not await_state:
        return

    # ─── Manage await states ───

    if await_state == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Welcome message updated!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_welcome")]]))

    elif await_state == 'typing_time':
        try:
            val = int(text)
            if 0 <= val <= 300:
                set_setting('typing_duration', val)
                context.user_data.pop('await', None)
                await update.message.reply_text(f"✅ Typing time set to {val}s!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_typing")]]))
            else:
                await update.message.reply_text("❌ Range 0-300!")
        except:
            await update.message.reply_text("❌ Enter a number!")

    elif await_state == 'ignore':
        set_setting('ignored_messages', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Ignored messages updated!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))

    elif await_state == 'upi':
        set_setting('upi_id', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ UPI set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_pay")]]))

    elif await_state == 'paytm':
        set_setting('paytm_num', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ PayTm set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="st_pay")]]))

    elif await_state == 'broadcast':
        context.user_data.pop('await', None)
        msg = f"📢 **BROADCAST**\n\n{text}"
        sent = 0
        for uid in customer_count:
            try:
                await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode='Markdown')
                sent += 1
                await asyncio.sleep(0.1)
            except:
                pass
        await update.message.reply_text(f"✅ Broadcast sent to {sent} customers!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))

    elif await_state == 'gs_msg_add':
        add_spam_message(text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Spam message added!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_msg")]]))

    elif await_state == 'gs_bs':
        try:
            val = max(1, min(50, int(text)))
            set_setting('spam_batch_size', val)
            set_setting('spam_speed', 'custom')
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Batch size: {val}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
        except:
            await update.message.reply_text("❌ Number only!")

    elif await_state == 'gs_bd':
        try:
            val = max(0, min(30, int(text)))
            set_setting('spam_batch_delay', val)
            set_setting('spam_speed', 'custom')
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Batch delay: {val}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
        except:
            await update.message.reply_text("❌ Number only!")

    elif await_state == 'gs_cw':
        try:
            val = max(0, min(300, int(text)))
            set_setting('spam_cycle_wait', val)
            set_setting('spam_speed', 'custom')
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Cycle wait: {val}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_spd")]]))
        except:
            await update.message.reply_text("❌ Number only!")

    elif await_state == 'proxy':
        aid = context.user_data.pop('pr_aid', None)
        context.user_data.pop('await', None)
        if text.lower() == 'remove':
            all_accs = get_all_accounts()
            for a in all_accs:
                if a['id'] == aid:
                    a['proxy'] = None
                    save_json(ACCOUNTS_FILE, {'main': [x for x in all_accs if not x.get('is_backup')], 'backup': [x for x in all_accs if x.get('is_backup')]})
                    break
            await update.message.reply_text("✅ Proxy removed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_pr")]]))
        else:
            parts = text.split(':')
            if len(parts) >= 3:
                proxy = {
                    'addr': parts[1],
                    'port': int(parts[2]),
                    'username': parts[3] if len(parts) > 3 else '',
                    'password': parts[4] if len(parts) > 4 else '',
                    'rdns': True
                }
                all_accs = get_all_accounts()
                for a in all_accs:
                    if a['id'] == aid:
                        a['proxy'] = proxy
                        save_json(ACCOUNTS_FILE, {'main': [x for x in all_accs if not x.get('is_backup')], 'backup': [x for x in all_accs if x.get('is_backup')]})
                        break
                await update.message.reply_text("✅ Proxy set! Restart account to apply.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_pr")]]))
            else:
                await update.message.reply_text("❌ Format: socks5:ip:port:user:pass")

    elif await_state == 'ac_ph':
        context.user_data['phone'] = text
        context.user_data['await'] = 'ac_otp'
        try:
            ac_api_id = int(get_setting('ac_api_id', DEFAULT_API_ID))
            ac_api_hash = get_setting('ac_api_hash', DEFAULT_API_HASH)
            client = TelegramClient(StringSession(), ac_api_id, ac_api_hash)
            await client.connect()
            send_code = await client.send_code_request(text)
            context.user_data['ac_client'] = client
            context.user_data['ac_phone_code_hash'] = send_code.phone_code_hash
            context.user_data['ac_api_id'] = ac_api_id
            context.user_data['ac_api_hash'] = ac_api_hash
            await update.message.reply_text(f"✅ OTP sent to {text}\n\nEnter OTP (or `00000` for test):", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ OTP send failed: {str(e)[:100]}")
            context.user_data.pop('await', None)

    elif await_state == 'ac_otp':
        otp = text.replace(' ', '')
        client = context.user_data.get('ac_client')
        phone = context.user_data.get('phone', '')
        pch = context.user_data.get('ac_phone_code_hash', '')
        api_id = context.user_data.get('ac_api_id', DEFAULT_API_ID)
        api_hash = context.user_data.get('ac_api_hash', DEFAULT_API_HASH)
        if not client:
            await update.message.reply_text("❌ Session expired. Start again.")
            context.user_data.pop('await', None)
            return
        try:
            await client.sign_in(phone=phone, code=otp, phone_code_hash=pch)
            me = await client.get_me()
            session_str = client.session.save()
            name = me.first_name or 'Unknown'
            user_id_val = me.id
            acc = {
                'id': gen_acc_id(),
                'name': name,
                'user_id': user_id_val,
                'phone': phone,
                'session': session_str,
                'api_id': api_id,
                'api_hash': api_hash,
                'proxy': None,
                'enabled': True,
                'is_backup': False,
                'added_at': datetime.now().isoformat()
            }
            add_account_data(acc)
            await client.disconnect()
            context.user_data.pop('await', None)
            context.user_data.pop('ac_client', None)
            context.user_data.pop('phone', None)
            await update.message.reply_text(f"✅ Account added!\n👤 {name}\n📱 {phone}\n\n🔄 Redeploy to activate.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    register_ar(n_client, acc)
                    await update.message.reply_text("✅ Account activated without redeploy!")
            except:
                pass
        except SessionPasswordNeededError:
            context.user_data['await'] = 'ac_2fa'
            await update.message.reply_text("🔐 2FA enabled! Enter password:")
        except PhoneCodeInvalidError:
            await update.message.reply_text("❌ Invalid OTP! Try again:")
        except PhoneCodeExpiredError:
            await update.message.reply_text("❌ OTP expired. Start again.")
            context.user_data.pop('await', None)

    elif await_state == 'ac_2fa':
        client = context.user_data.get('ac_client')
        phone = context.user_data.get('phone', '')
        api_id = context.user_data.get('ac_api_id', DEFAULT_API_ID)
        api_hash = context.user_data.get('ac_api_hash', DEFAULT_API_HASH)
        if not client:
            await update.message.reply_text("❌ Session expired.")
            context.user_data.pop('await', None)
            return
        try:
            await client.sign_in(password=text)
            me = await client.get_me()
            session_str = client.session.save()
            name = me.first_name or 'Unknown'
            acc = {
                'id': gen_acc_id(),
                'name': name,
                'user_id': me.id,
                'phone': phone,
                'session': session_str,
                'api_id': api_id,
                'api_hash': api_hash,
                'proxy': None,
                'enabled': True,
                'is_backup': False,
                'added_at': datetime.now().isoformat()
            }
            add_account_data(acc)
            await client.disconnect()
            context.user_data.pop('await', None)
            context.user_data.pop('ac_client', None)
            context.user_data.pop('phone', None)
            await update.message.reply_text(f"✅ Account added!\n👤 {name}\n📱 {phone}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    register_ar(n_client, acc)
                    await update.message.reply_text("✅ Auto-activated!")
            except:
                pass
        except Exception as e:
            await update.message.reply_text(f"❌ 2FA failed: {str(e)[:100]}")
            context.user_data.pop('await', None)

    elif await_state == 'ac_ss':
        if len(text) < 10:
            await update.message.reply_text("❌ Invalid session string!")
            return
        try:
            session_test = StringSession(text)
            client = TelegramClient(session_test, DEFAULT_API_ID, DEFAULT_API_HASH)
            await client.connect()
            me = await client.get_me()
            if me:
                name = me.first_name or 'Unknown'
                phone = me.phone or 'N/A'
                acc = {
                    'id': gen_acc_id(),
                    'name': name,
                    'user_id': me.id,
                    'phone': phone,
                    'session': text,
                    'api_id': DEFAULT_API_ID,
                    'api_hash': DEFAULT_API_HASH,
                    'proxy': None,
                    'enabled': True,
                    'is_backup': False,
                    'added_at': datetime.now().isoformat()
                }
                add_account_data(acc)
                await client.disconnect()
                context.user_data.pop('await', None)
                await update.message.reply_text(f"✅ Account added!\n👤 {name}\n📱 {phone}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
                try:
                    n_client = await start_account(acc)
                    if n_client:
                        active_accounts.append(acc)
                        account_clients[acc['id']] = n_client
                        account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                        account_stop_flags[acc['id']] = False
                        register_ar(n_client, acc)
                        await update.message.reply_text("✅ Auto-activated!")
                except:
                    pass
            else:
                await update.message.reply_text("❌ Could not get user info!")
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid session: {str(e)[:100]}")
        finally:
            context.user_data.pop('await', None)

    elif await_state == 'ac_bk_ss':
        if len(text) < 10:
            await update.message.reply_text("❌ Invalid session!")
            return
        try:
            session_test = StringSession(text)
            client = TelegramClient(session_test, DEFAULT_API_ID, DEFAULT_API_HASH)
            await client.connect()
            me = await client.get_me()
            if me:
                name = me.first_name or 'Unknown'
                phone = me.phone or 'N/A'
                acc = {
                    'id': gen_acc_id(),
                    'name': name,
                    'user_id': me.id,
                    'phone': phone,
                    'session': text,
                    'api_id': DEFAULT_API_ID,
                    'api_hash': DEFAULT_API_HASH,
                    'proxy': None,
                    'enabled': True,
                    'is_backup': True,
                    'added_at': datetime.now().isoformat()
                }
                add_account_data(acc, is_backup=True)
                await client.disconnect()
                context.user_data.pop('await', None)
                await update.message.reply_text(f"✅ Backup added!\n👤 {name}\n📱 {phone}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
            else:
                await update.message.reply_text("❌ Invalid session!")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
            context.user_data.pop('await', None)

    else:
        await update.message.reply_text(f"⚠️ Unknown state: {await_state}")
        context.user_data.pop('await', None)


# ====== PHOTO HANDLER ======
async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in admins:
        return

    await_state = context.user_data.get('await')

    if await_state == 'welcome_image':
        try:
            photo = await update.message.photo[-1].get_file()
            await photo.download_to_drive(str(WELCOME_IMAGE_FILE))
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ Welcome image updated!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_welcome")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:50]}")

    elif await_state == 'qr_code':
        try:
            photo = await update.message.photo[-1].get_file()
            await photo.download_to_drive(str(QR_CODE_FILE))
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ QR Code saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:50]}")

    else:
        await update.message.reply_text("ℹ️ No action expected.")


# ====== COMMANDS ======
async def add_reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ Unauthorized!")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add_reply keyword reply_text\nExample: /add_reply price See our price list!")
        return
    keyword = args[0].lower()
    reply = ' '.join(args[1:])
    replies = load_json(REPLIES_FILE, [])
    for r in replies:
        if r['keyword'] == keyword:
            r['reply'] = reply
            save_json(REPLIES_FILE, replies)
            await update.message.reply_text(f"✅ Reply updated for `{keyword}`", parse_mode='Markdown')
            return
    replies.append({'keyword': keyword, 'reply': reply, 'added_at': datetime.now().isoformat()})
    save_json(REPLIES_FILE, replies)
    await update.message.reply_text(f"✅ Reply added for `{keyword}`", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
    ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
    txt = f"📊 **STATUS**\n\n👤 Active: {len(active_accounts)}\n💬 Auto Sent: {ttl_auto}\n📬 Spam Sent: {ttl_spam}\n👥 Customers: {len(customer_count)}"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    txt = """**COMMANDS:**
/start - Open control panel
/status - Quick status
/add_reply keyword reply - Add custom reply
/help - This message

**FEATURES:**
• Auto Reply with custom messages
• Group Spam with speed control
• Welcome message + image
• QR code payment
• Block photo feature
• Typing effect
• Account mgmt via bot
• Backup accounts auto-activate
"""
    await update.message.reply_text(txt, parse_mode='Markdown')


# ====== FLASK ======
@flask_app.route('/')
def index():
    return jsonify({'status': 'running', 'accounts': len(active_accounts), 'time': datetime.now().isoformat()})

@flask_app.route('/health')
def health():
    return jsonify({'status': 'ok', 'bot_ready': bot_ready})

async def run_flask():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False))


# ====== MAIN SETUP ======
async def main_async():
    global ptb_application, bot_ready, bot_event_loop

    bot_event_loop = asyncio.get_event_loop()
    _load_settings_to_cache()

    # ─── Setup PTB ───
    ptb = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    ptb_application = ptb

    # ─── Add handlers ───
    ptb.add_handler(CommandHandler("start", start_command))
    ptb.add_handler(CommandHandler("status", status_command))
    ptb.add_handler(CommandHandler("help", help_command))
    ptb.add_handler(CommandHandler("add_reply", add_reply_command))
    ptb.add_handler(CallbackQueryHandler(handle_callback))
    ptb.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    ptb.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    # ─── Start polling ───
    await ptb.initialize()
    await ptb.start()
    await ptb.updater.start_polling(drop_pending_updates=True)

    # ─── Setup accounts ───
    await setup_auto_reply()

    # ─── Start background tasks ───
    asyncio.create_task(check_account_status_periodically())
    asyncio.create_task(run_flask())

    bot_ready = True

    # ─── Notify owner ───
    try:
        await ptb.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔥 **Bot Ready!**\n\n👤 Accounts: {len(active_accounts)}\n🤖 Auto Reply: {'ON' if auto_reply_enabled else 'OFF'}\n📨 Group Spam: {'ON' if group_spam_enabled else 'OFF'}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Owner notify failed: {e}")

    logger.info(f"Bot Ready! {len(active_accounts)} accounts active.")

    # ─── Keep alive ───
    await shutdown_event.wait()


async def shutdown_bot():
    global bot_ready
    logger.info("Shutting down...")
    bot_ready = False
    shutdown_event.set()

    for tid in list(account_spam_tasks.keys()):
        try:
            account_spam_tasks[tid].cancel()
        except: pass

    for tid in list(account_keepalive_tasks.keys()):
        try:
            account_keepalive_tasks[tid].cancel()
        except: pass

    for aid, cli in account_clients.items():
        try:
            await cli.disconnect()
        except: pass

    if ptb_application:
        try:
            await ptb_application.stop()
            await ptb_application.shutdown()
        except: pass

    logger.info("Shutdown complete.")


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        asyncio.run(shutdown_bot())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

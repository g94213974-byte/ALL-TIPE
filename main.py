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

from flask import Flask, jsonify, request

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
_settings_cache_dirty = False

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
        verify = load_accounts_data()
        for key in ['main', 'backup']:
            if any(a.get('id') == aid for a in verify[key]):
                verify[key] = [a for a in verify[key] if a.get('id') != aid]
                save_json(ACCOUNTS_FILE, verify)
                break
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
    
    # Typing effect before reply
    if get_setting('typing_enabled', True):
        typing_duration = int(get_setting('typing_duration', 240))
        if typing_duration > 0:
            try:
                async with client.action(chat_id, 'typing'):
                    await asyncio.sleep(min(typing_duration, 300))
            except:
                pass
    
    # Welcome message (first message only) - Text + Image
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
    
    # Check ignored messages
    ignored = get_setting('ignored_messages', '')
    if ignored:
        for line in ignored.split('\n'):
            if line.strip().lower() == msg_lower:
                customer_count[uid] = msg_count + 1
                return
    
    # Payment keywords
    payment_keywords = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'send', 'bhejo', 'screenshot', 'method', 'transfer', 'rupees', 'rs', 'money']
    if any(kw in msg_lower for kw in payment_keywords):
        await send_payment_info(client, chat_id, event)
        customer_count[uid] = msg_count + 1
        return
    
    # Media keywords
    media_keywords = ['pic', 'photo', 'image', 'nude', 'naked', 'dikhao', 'show', 'nangi', 'boob', 'mms']
    if any(kw in msg_lower for kw in media_keywords):
        await event.respond(get_setting('media_keyword_reply', 'Payment first baby 😘🔥'))
        customer_count[uid] = msg_count + 1
        return
    
    # Service keywords
    service_keywords = ['service', 'chahiye', 'kharid', 'demo', 'video', 'call', 'vc', 'price', 'rate']
    if any(kw in msg_lower for kw in service_keywords):
        price_text = get_setting('price_list_text', "🔥 10 MIN VC → ₹99\n🔥 20 MIN VC → ₹119")
        await event.respond(price_text)
        await asyncio.sleep(0.3)
        await event.respond(random.choice(["How many minutes? 🔥", "Pay and enjoy! 😘", "Tell me your choice 💋"]))
        customer_count[uid] = msg_count + 1
        return
    
    # Offline keywords
    offline_keywords = ['real', 'meet', 'aao', 'ghar', 'location', 'offline']
    if any(kw in msg_lower for kw in offline_keywords):
        await event.respond(get_setting('offline_keyword_reply', 'Online only baby 😊'))
        customer_count[uid] = msg_count + 1
        return
    
    # Greeting keywords
    greeting_keywords = ['hi', 'hello', 'hey', 'hii', 'hy', 'hlo', 'hlw', 'helo']
    if any(w in msg_lower for w in greeting_keywords):
        greetings = get_setting('greeting_replies', ['Hi baby, ready! 🔥', 'Hey baby! 😘', 'Hello! What you need? 🔥'])
        await event.respond(random.choice(greetings))
        customer_count[uid] = msg_count + 1
        return
    
    # Default reply
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
    
    # ====== AUTO REPLY (START ALL / STOP ALL) ======
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
        await asyncio.sleep(1)
        await handle_callback(update, context)
    
    elif data == "ar_stop":
        auto_reply_enabled = False
        await query.edit_message_text("⏹️ **Auto Reply বন্ধ হয়েছে!** কোনো একাউন্ট রিপ্লাই দিবে না।", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        await asyncio.sleep(1)
        await handle_callback(update, context)
    
    # Welcome Message Settings (Text + Image)
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
    
    # Block Photo Settings
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
    
    # Typing Time Settings
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
    
    # Ignored Messages
    elif data == "ar_ignore":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "🚫 **Ignored Messages**\nযেসব মেসেজের রিপ্লাই দিবে না (এক লাইনে একটি):\n\n"
        if cur: txt += f"Current:\n`{cur}`\n\n"
        txt += "Example:\n`thanks`\n`bye`\n`ok`"
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
    
    # Custom Replies
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
    
    # ====== GROUP SPAM (START ALL / STOP ALL) ======
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
    
    # ====== ACCOUNTS ======
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
    
    # ====== SETTINGS ======
    elif data == "m_set":
        bp = "🟢" if get_setting('block_photo_enabled', True) else "🔴"
        fs = "🟢" if get_setting('flood_slow_mode', True) else "🔴"
        ln = "🟢" if logout_notification_enabled else "🔴"
        has_qr = "✅" if QR_CODE_FILE.exists() else "❌"
        kb = [
            [InlineKeyboardButton(f"🚫 Block Photo {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"🐢 Flood Slow {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"🔔 Logout Alert {ln}", callback_data="st_ln")],
            [InlineKeyboardButton(f"💳 Payment Settings", callback_data="st_pay")],
            [InlineKeyboardButton(f"📷 QR Code {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text("⚙️ **Settings**\n
        elif data == "m_set":
            # Settings menu
            settings = load_settings()
            m = "🔧 *Settings*\n\n"
            m += f"🤖 Auto Reply: {'✅ ON' if settings.get('auto_reply', False) else '❌ OFF'}\n"
            m += f"📢 Group Spam: {'✅ ON' if settings.get('group_spam', False) else '❌ OFF'}\n"
            m += f"📸 Block Photo: {'✅ ON' if settings.get('block_photo', False) else '❌ OFF'}\n"
            m += f"⏱ Typing Delay: {settings.get('typing_delay', 240)} sec\n"
            m += f"💳 Payment: {settings.get('payment_method', 'UPI').upper()}\n"
            if settings.get('upi_id'):
                m += f"🏦 UPI: {settings['upi_id']}\n"
            if settings.get('paytm'):
                m += f"📱 Paytm: {settings['paytm']}\n"
            if settings.get('price'):
                m += f"💰 Price: ₹{settings['price']}\n"
            
            kb = [
                [InlineKeyboardButton(f"{'✅' if settings.get('auto_reply', False) else '❌'} Auto Reply", callback_data="tog_auto_reply"),
                 InlineKeyboardButton(f"{'✅' if settings.get('group_spam', False) else '❌'} Group Spam", callback_data="tog_group_spam")],
                [InlineKeyboardButton(f"{'✅' if settings.get('block_photo', False) else '❌'} Block Photo", callback_data="tog_block_photo")],
                [InlineKeyboardButton(f"⏱ Typing Delay: {settings.get('typing_delay', 240)}s", callback_data="edit_typing_delay")],
                [InlineKeyboardButton("💳 Payment Settings", callback_data="pay_settings")],
                [InlineKeyboardButton("📸 Welcome Image", callback_data="set_welcome_img")],
                [InlineKeyboardButton("🖼 QR Code", callback_data="set_qr")],
                [InlineKeyboardButton("◀️ Back", callback_data="main_menu")]
            ]
            await query.edit_message_text(m, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        
        elif data == "tog_auto_reply":
            settings = load_settings()
            settings['auto_reply'] = not settings.get('auto_reply', False)
            save_settings(settings)
            await query.answer(f"Auto Reply {'ON' if settings['auto_reply'] else 'OFF'}!")
            await handle_callback(query, "m_set")
        
        elif data == "tog_group_spam":
            settings = load_settings()
            settings['group_spam'] = not settings.get('group_spam', False)
            save_settings(settings)
            await query.answer(f"Group Spam {'ON' if settings['group_spam'] else 'OFF'}!")
            await handle_callback(query, "m_set")
        
        elif data == "tog_block_photo":
            settings = load_settings()
            settings['block_photo'] = not settings.get('block_photo', False)
            save_settings(settings)
            await query.answer(f"Block Photo {'ON' if settings['block_photo'] else 'OFF'}!")
            await handle_callback(query, "m_set")
        
        elif data == "edit_typing_delay":
            await query.message.reply_text("⏱ পাঠান typing delay (seconds):\nবর্তমান: {}s".format(load_settings().get('typing_delay', 240)))
            await query.answer()
            return  # wait for text input
        
        elif data == "pay_settings":
            settings = load_settings()
            kb = [
                [InlineKeyboardButton(f"{'✅' if settings.get('payment_method')=='upi' else '⚪'} UPI", callback_data="pay_method_upi"),
                 InlineKeyboardButton(f"{'✅' if settings.get('payment_method')=='paytm' else '⚪'} Paytm", callback_data="pay_method_paytm")],
                [InlineKeyboardButton("✏️ Set UPI ID", callback_data="set_upi")],
                [InlineKeyboardButton("✏️ Set Paytm", callback_data="set_paytm")],
                [InlineKeyboardButton("✏️ Set Price", callback_data="set_price")],
                [InlineKeyboardButton("◀️ Back", callback_data="m_set")]
            ]
            await query.edit_message_text("💳 *Payment Settings*\n\nMethod: {}\nUPI: {}\nPaytm: {}\nPrice: ₹{}".format(
                settings.get('payment_method', 'upi').upper(),
                settings.get('upi_id', 'Not set'),
                settings.get('paytm', 'Not set'),
                settings.get('price', 'Not set')
            ), reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        
        elif data == "pay_method_upi":
            settings = load_settings()
            settings['payment_method'] = 'upi'
            save_settings(settings)
            await query.answer("Payment method set to UPI!")
            await handle_callback(query, "pay_settings")
        
        elif data == "pay_method_paytm":
            settings = load_settings()
            settings['payment_method'] = 'paytm'
            save_settings(settings)
            await query.answer("Payment method set to Paytm!")
            await handle_callback(query, "pay_settings")
        
        elif data == "set_upi":
            await query.message.reply_text("📤 পাঠান আপনার UPI ID:")
            await query.answer()
            return
        
        elif data == "set_paytm":
            await query.message.reply_text("📤 পাঠান আপনার Paytm Number:")
            await query.answer()
            return
        
        elif data == "set_price":
            await query.message.reply_text("💰 পাঠান Price (₹):")
            await query.answer()
            return
        
        elif data == "set_welcome_img":
            await query.message.reply_text("📸 পাঠান Welcome Image (যে ছবি welcome message এ যাবে):")
            await query.answer()
            return
        
        elif data == "set_qr":
            await query.message.reply_text("🖼 পাঠান QR Code ছবি (payment QR):")
            await query.answer()
            return
        
        elif data == "start_all_auto":
            settings = load_settings()
            accounts = load_accounts()
            if not accounts:
                await query.answer("❌ No accounts found!", show_alert=True)
                return
            settings['auto_reply'] = True
            save_settings(settings)
            await query.answer("✅ Auto Reply STARTED for all accounts!")
            await handle_callback(query, "main_menu")
        
        elif data == "stop_all_auto":
            settings = load_settings()
            settings['auto_reply'] = False
            save_settings(settings)
            await query.answer("⏹ Auto Reply STOPPED for all accounts!")
            await handle_callback(query, "main_menu")
        
        elif data == "start_all_spam":
            settings = load_settings()
            accounts = load_accounts()
            if not accounts:
                await query.answer("❌ No accounts found!", show_alert=True)
                return
            settings['group_spam'] = True
            save_settings(settings)
            await query.answer("✅ Group Spam STARTED for all accounts!")
            await handle_callback(query, "main_menu")
        
        elif data == "stop_all_spam":
            settings = load_settings()
            settings['group_spam'] = False
            save_settings(settings)
            await query.answer("⏹ Group Spam STOPPED for all accounts!")
            await handle_callback(query, "main_menu")
        
        elif data == "group_spam_menu":
            settings = load_settings()
            accounts = load_accounts()
            active_count = len(accounts) if settings.get('group_spam', False) and accounts else 0
            
            kb = [
                [InlineKeyboardButton("➕ Add Groups", callback_data="add_groups")],
                [InlineKeyboardButton("📋 List Groups", callback_data="list_groups_spam")],
                [InlineKeyboardButton("✏️ Spam Message", callback_data="spam_msg")],
                [InlineKeyboardButton("⏱ Spam Delay", callback_data="spam_delay")],
                [InlineKeyboardButton("▶️ START ALL", callback_data="start_all_spam"),
                 InlineKeyboardButton("⏹ STOP ALL", callback_data="stop_all_spam")],
                [InlineKeyboardButton("◀️ Back", callback_data="main_menu")]
            ]
            await query.edit_message_text(
                f"📢 *Group Spam*\n\nStatus: {'🟢 Running' if settings.get('group_spam', False) else '🔴 Stopped'}\nAccounts: {active_count} active\nGroups: ?\nMessage: {settings.get('spam_message', 'Not set')[:30]}...\nDelay: {settings.get('spam_delay', 60)}s",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
            )
        
        elif data == "spam_msg":
            await query.message.reply_text("✏️ পাঠান Spam Message (যা গ্রুপে পাঠানো হবে):")
            await query.answer()
            return
        
        elif data == "spam_delay":
            await query.message.reply_text("⏱ পাঠান spam delay (seconds):")
            await query.answer()
            return
        
        elif data == "add_groups":
            await query.message.reply_text("📤 পাঠান গ্রুপের links/usernames (প্রতি লাইনে একটি):")
            await query.answer()
            return
        
        elif data == "list_groups_spam":
            groups = load_groups()
            if not groups:
                await query.answer("❌ No groups added yet!", show_alert=True)
                return
            msg = "📋 *Spam Groups:*\n\n"
            for i, g in enumerate(groups, 1):
                msg += f"{i}. {g}\n"
            await query.message.reply_text(msg, parse_mode="Markdown")
            await query.answer()
        
        elif data == "main_menu":
            settings = load_settings()
            m = f"*Main Menu*\n\nAccount: {len(load_accounts())} loaded\nAuto Reply: {'ON' if settings.get('auto_reply', False) else 'OFF'}\nGroup Spam: {'ON' if settings.get('group_spam', False) else 'OFF'}"
            kb = [
                [InlineKeyboardButton("📂 Accounts", callback_data="m_accounts")],
                [InlineKeyboardButton("🤖 Auto Reply", callback_data="m_auto")],
                [InlineKeyboardButton("📢 Group Spam", callback_data="group_spam_menu")],
                [InlineKeyboardButton("🔧 Settings", callback_data="m_set")],
                [InlineKeyboardButton("💾 Backup", callback_data="m_backup")]
            ]
            await query.edit_message_text(m, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    
    except Exception as e:
        print(f"Callback error: {e}")
        try:
            await query.answer(f"Error: {str(e)[:30]}", show_alert=True)
        except:
            pass


async def handle_text(client, message):
    """Handle text messages from bot owner"""
    try:
        if message.from_user.id not in ADMIN_IDS:
            return
        
        text = message.text.strip()
        
        # Check if waiting for settings input
        if message.chat.id in waiting_for_input:
            input_type = waiting_for_input.pop(message.chat.id)
            
            if input_type == "edit_typing_delay":
                try:
                    delay = int(text)
                    settings = load_settings()
                    settings['typing_delay'] = delay
                    save_settings(settings)
                    await message.reply_text(f"✅ Typing Delay set to {delay}s!")
                except ValueError:
                    await message.reply_text("❌ Invalid number!")
                return
            
            elif input_type == "set_upi":
                settings = load_settings()
                settings['upi_id'] = text
                save_settings(settings)
                await message.reply_text(f"✅ UPI ID set to: {text}")
                return
            
            elif input_type == "set_paytm":
                settings = load_settings()
                settings['paytm'] = text
                save_settings(settings)
                await message.reply_text(f"✅ Paytm set to: {text}")
                return
            
            elif input_type == "set_price":
                try:
                    price = float(text)
                    settings = load_settings()
                    settings['price'] = price
                    save_settings(settings)
                    await message.reply_text(f"✅ Price set to ₹{price}!")
                except ValueError:
                    await message.reply_text("❌ Invalid price!")
                return
            
            elif input_type == "spam_msg":
                settings = load_settings()
                settings['spam_message'] = text
                save_settings(settings)
                await message.reply_text(f"✅ Spam message set!")
                return
            
            elif input_type == "spam_delay":
                try:
                    delay = int(text)
                    settings = load_settings()
                    settings['spam_delay'] = delay
                    save_settings(settings)
                    await message.reply_text(f"✅ Spam delay set to {delay}s!")
                except ValueError:
                    await message.reply_text("❌ Invalid number!")
                return
            
            elif input_type == "add_groups":
                groups = [g.strip() for g in text.split('\n') if g.strip()]
                existing = load_groups()
                existing.extend(groups)
                save_groups(existing)
                await message.reply_text(f"✅ {len(groups)} groups added! Total: {len(existing)}")
                return
            
            elif input_type == "welcome_text":
                settings = load_settings()
                settings['welcome_text'] = text
                save_settings(settings)
                await message.reply_text("✅ Welcome text updated!")
                return
        
        # Command handlers
        if text == "/start":
            await show_main_menu(message)
        
        elif text.startswith("/broadcast"):
            msg = text.replace("/broadcast", "", 1).strip()
            if not msg:
                await message.reply_text("❌ Message required!\nUsage: /broadcast your message here")
                return
            await message.reply_text(f"📢 Broadcasting: {msg[:50]}...")
            # broadcast logic here
        
        else:
            await message.reply_text("❓ Unknown command. Use /start")
    
    except Exception as e:
        print(f"Text handler error: {e}")
        await message.reply_text(f"Error: {str(e)[:50]}")


async def handle_photo(client, message):
    """Handle photo uploads from bot owner"""
    try:
        if message.from_user.id not in ADMIN_IDS:
            return
        
        if message.chat.id in waiting_for_input:
            input_type = waiting_for_input.pop(message.chat.id)
            
            if input_type == "set_welcome_img":
                file = await message.download()
                import shutil
                shutil.move(file, "data/welcome_image.jpg")
                await message.reply_text("✅ Welcome image updated!")
                return
            
            elif input_type == "set_qr":
                file = await message.download()
                import shutil
                shutil.move(file, "data/qr_code.png")
                await message.reply_text("✅ QR code updated!")
                return
        
        await message.reply_text("❓ Unexpected photo. Use settings menu.")
    
    except Exception as e:
        print(f"Photo handler error: {e}")
        await message.reply_text(f"Error: {str(e)[:50]}")


# ============ AUTO REPLY LOGIC ============

async def auto_reply_worker():
    """Main auto-reply loop for all accounts"""
    while True:
        try:
            settings = load_settings()
            if not settings.get('auto_reply', False):
                await asyncio.sleep(5)
                continue
            
            accounts = load_accounts()
            if not accounts:
                await asyncio.sleep(5)
                continue
            
            replies = load_replies()
            if not replies:
                await asyncio.sleep(5)
                continue
            
            for acc in accounts:
                try:
                    api_id = acc.get('api_id')
                    api_hash = acc.get('api_hash')
                    phone = acc.get('phone')
                    session_file = f"sessions/{phone}.session"
                    
                    if not os.path.exists(session_file):
                        continue
                    
                    client = TelegramClient(session_file, api_id, api_hash)
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        await client.disconnect()
                        continue
                    
                    me = await client.get_me()
                    print(f"[AutoReply] Checking {me.first_name}...")
                    
                    dialogs = client.iter_dialogs()
                    
                    async for dialog in dialogs:
                        try:
                            if dialog.is_group or dialog.is_channel:
                                continue
                            
                            if not dialog.entity.username and not getattr(dialog.entity, 'phone', None):
                                continue
                            
                            # Check for blocked photo
                            if settings.get('block_photo', False):
                                # Skip if last message is photo
                                msg = await client.get_messages(dialog.entity, limit=1)
                                if msg and msg[0].photo:
                                    continue
                            
                            # Get last message
                            msgs = await client.get_messages(dialog.entity, limit=1)
                            if not msgs:
                                continue
                            
                            last_msg = msgs[0]
                            
                            # Skip if sent by us
                            if last_msg.out:
                                continue
                            
                            # Skip if already replied (check last 5 messages for our reply)
                            our_msgs = await client.get_messages(dialog.entity, limit=5)
                            already_replied = any(m.out for m in our_msgs if m.out)
                            if already_replied:
                                continue
                            
                            # Find matching reply
                            reply_text = None
                            msg_lower = (last_msg.text or "").lower()
                            
                            for keyword, reply in replies.items():
                                if keyword.lower() in msg_lower:
                                    reply_text = reply
                                    break
                            
                            if not reply_text:
                                # Send default reply if no keyword matched
                                default = replies.get('__default__')
                                if default:
                                    reply_text = default
                                else:
                                    continue
                            
                            # Typing effect
                            delay = settings.get('typing_delay', 240)
                            if delay > 0:
                                async with client.action(dialog.entity, 'typing'):
                                    await asyncio.sleep(min(delay, 10))  # cap at 10s for practical demo
                            
                            # Send welcome image if present (first time)
                            welcome_path = "data/welcome_image.jpg"
                            if os.path.exists(welcome_path):
                                try:
                                    welcome_text = settings.get('welcome_text', '👋 Welcome!')
                                    await client.send_file(dialog.entity, welcome_path, caption=welcome_text)
                                except:
                                    pass
                            
                            # Send reply
                            await client.send_message(dialog.entity, reply_text)
                            print(f"[AutoReply] Replied to {dialog.entity.id}: {reply_text[:30]}...")
                            
                            # Send payment info
                            payment_method = settings.get('payment_method', 'upi')
                            price = settings.get('price', 0)
                            upi_id = settings.get('upi_id', '')
                            paytm = settings.get('paytm', '')
                            qr_path = "data/qr_code.png"
                            
                            if price and (upi_id or paytm):
                                pay_msg = f"💳 *Payment*\nPrice: ₹{price}\n"
                                if payment_method == 'upi' and upi_id:
                                    pay_msg += f"UPI: `{upi_id}`"
                                elif payment_method == 'paytm' and paytm:
                                    pay_msg += f"Paytm: {paytm}"
                                
                                if os.path.exists(qr_path):
                                    try:
                                        await client.send_file(dialog.entity, qr_path, caption=pay_msg, parse_mode='markdown')
                                    except:
                                        await client.send_message(dialog.entity, pay_msg, parse_mode='markdown')
                                else:
                                    await client.send_message(dialog.entity, pay_msg, parse_mode='markdown')
                        
                        except Exception as e:
                            print(f"[AutoReply] Dialog error: {e}")
                            continue
                    
                    await client.disconnect()
                    
                except Exception as e:
                    print(f"[AutoReply] Account error: {e}")
                    continue
            
            # Wait before next check
            await asyncio.sleep(30)
        
        except Exception as e:
            print(f"[AutoReply] Worker error: {e}")
            await asyncio.sleep(10)


async def group_spam_worker():
    """Main group spam loop"""
    while True:
        try:
            settings = load_settings()
            if not settings.get('group_spam', False):
                await asyncio.sleep(5)
                continue
            
            accounts = load_accounts()
            if not accounts:
                await asyncio.sleep(5)
                continue
            
            groups = load_groups()
            if not groups:
                await asyncio.sleep(5)
                continue
            
            spam_msg = settings.get('spam_message', '')
            if not spam_msg:
                await asyncio.sleep(5)
                continue
            
            spam_delay = settings.get('spam_delay', 60)
            
            for acc in accounts:
                try:
                    api_id = acc.get('api_id')
                    api_hash = acc.get('api_hash')
                    phone = acc.get('phone')
                    session_file = f"sessions/{phone}.session"
                    
                    if not os.path.exists(session_file):
                        continue
                    
                    client = TelegramClient(session_file, api_id, api_hash)
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        await client.disconnect()
                        continue
                    
                    me = await client.get_me()
                    print(f"[GroupSpam] Spamming as {me.first_name}...")
                    
                    for group in groups:
                        try:
                            entity = await client.get_entity(group)
                            
                            # Typing effect
                            delay = settings.get('typing_delay', 240)
                            if delay > 0:
                                async with client.action(entity, 'typing'):
                                    await asyncio.sleep(min(delay, 5))
                            
                            await client.send_message(entity, spam_msg)
                            print(f"[GroupSpam] Sent to {group}: {spam_msg[:30]}...")
                            await asyncio.sleep(spam_delay)
                        
                        except Exception as e:
                            print(f"[GroupSpam] Group error {group}: {e}")
                            continue
                    
                    await client.disconnect()
                    
                except Exception as e:
                    print(f"[GroupSpam] Account error: {e}")
                    continue
            
            await asyncio.sleep(60)
        
        except Exception as e:
            print(f"[GroupSpam] Worker error: {e}")
            await asyncio.sleep(10)


# ============ MAIN SETUP ============

async def show_main_menu(message):
    """Show main menu"""
    settings = load_settings()
    m = f"*Main Menu*\n\nAccount: {len(load_accounts())} loaded\nAuto Reply: {'ON' if settings.get('auto_reply', False) else 'OFF'}\nGroup Spam: {'ON' if settings.get('group_spam', False) else 'OFF'}"
    kb = [
        [InlineKeyboardButton("📂 Accounts", callback_data="m_accounts")],
        [InlineKeyboardButton("🤖 Auto Reply", callback_data="m_auto")],
        [InlineKeyboardButton("📢 Group Spam", callback_data="group_spam_menu")],
        [InlineKeyboardButton("🔧 Settings", callback_data="m_set")],
        [InlineKeyboardButton("💾 Backup", callback_data="m_backup")]
    ]
    await message.reply_text(m, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")


# ============ FLASK SERVER ============

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is running!"

@app.route('/health')
def health():
    return jsonify({"status": "ok", "accounts": len(load_accounts()), "auto_reply": load_settings().get('auto_reply', False)})

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)


# ============ ENTRY POINT ============

async def main():
    print("=" * 50)
    print("🤖 TELEGRAM AUTO REPLY + SPAM BOT")
    print("=" * 50)
    
    # Ensure directories
    os.makedirs("data", exist_ok=True)
    os.makedirs("sessions", exist_ok=True)
    
    # Create default settings if not exist
    if not os.path.exists("data/settings.json"):
        default_settings = {
            "auto_reply": False,
            "group_spam": False,
            "block_photo": False,
            "typing_delay": 240,
            "welcome_text": "👋 Welcome!",
            "payment_method": "upi",
            "upi_id": "",
            "paytm": "",
            "price": 0,
            "spam_message": "",
            "spam_delay": 60
        }
        save_settings(default_settings)
    
    # Create default replies if not exist
    if not os.path.exists("data/replies.json"):
        save_replies({"__default__": "Hello! How can I help you?"})
    
    # Start bot client
    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    
    # Register handlers
    bot.add_event_handler(handle_text, events.NewMessage(incoming=True, func=lambda e: isinstance(e.message, types.Message) and not e.message.out))
    bot.add_event_handler(handle_callback, events.CallbackQuery())
    bot.add_event_handler(handle_photo, events.NewMessage(incoming=True, func=lambda e: isinstance(e.message, types.Message) and e.message.photo and not e.message.out))
    
    # Start workers
    asyncio.create_task(auto_reply_worker())
    asyncio.create_task(group_spam_worker())
    
    # Start Flask in a thread
    import threading
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("✅ Flask server running on port 8080")
    
    print("✅ Bot is running! Send /start to your bot to begin.")
    print("=" * 50)
    
    await bot.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹ Bot stopped by user.")
    except Exception as e:
        print(f"Fatal error: {e}")

#!/usr/bin/env python3
"""
UNIFIED TELEGRAM BOT - ENHANCED
================================
Features:
- Auto Reply with Wait Time + Typing
- Multiple message detection
- Welcome Message 1 (with image) + Welcome Message 2 (text only)
- START ALL / STOP ALL buttons with Running count
- Group Spam with speed control
- ★ Backup to Running (1 click add)
- ★ Account Hardening (name, dp, bio, device logout, 2FA)
- ★ Leave all chats+groups+channels + clear chat
- ★ Auto-join groups from link list
- ★ 1-day auto clear chat
- ★ ★ ★ RESTRICTED ACCOUNT AUTO LOGOUT (within seconds!)
- ★ ★ ★ One-click full account setup
"""

import os, sys, json, asyncio, random, logging, threading, time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple, Set
from collections import defaultdict
from pathlib import Path
import re

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
from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, SessionPasswordNeededError,
    PhoneCodeInvalidError, PhoneCodeExpiredError,
    AuthKeyUnregisteredError, UserDeactivatedError,
    PhoneNumberInvalidError
)
from telethon.tl.functions.messages import (
    GetDialogsRequest, ReadHistoryRequest, DeleteHistoryRequest
)
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.channels import LeaveChannelRequest, JoinChannelRequest
from telethon.tl.types import InputPeerEmpty, InputPeerChannel, InputPeerChat

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
HARDENING_DIR = BASE_DIR / "hardening_data"
for d in [DATA_DIR, PAYMENT_SS_DIR, HARDENING_DIR]:
    d.mkdir(parents=True, exist_ok=True)

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
REPLIES_FILE = DATA_DIR / "replies.json"
BANNED_FILE = DATA_DIR / "banned_accounts.json"
SPAM_MSG_FILE = DATA_DIR / "spam_messages.json"
WELCOME_IMAGE_FILE = DATA_DIR / "welcome_image.jpg"
QR_CODE_FILE = DATA_DIR / "qr_code.jpg"
AUTOJOIN_FILE = DATA_DIR / "autojoin_links.json"
HARDENING_TASKS_FILE = DATA_DIR / "harden_tasks.json"
TWOPA_FILE = DATA_DIR / "twofa_passwords.json"

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
    'welcome_message_2': '🔥 I am available now! 😘\n\nTell me what you need?',
    'block_photo_enabled': True,
    'typing_enabled': True,
    'typing_duration': 240,
    'seen_delay': 1,
    'wait_time': 300,
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
    'media_keyword_reply': 'Pay and come baby 😘🔥',
    'offline_keyword_reply': 'Online only baby 😊',
    'greeting_replies': ['i am ready baby pay and come🔥', 'Hey baby! 😘', 'Hello! kitna min cheye? 🔥'],
    'default_replies': ['Ready baby! Pay karo and come vc! 🔥', 'Main ready hoon! 😘', 'pay and come baby🥰'],
    'new_account_name': '',
    'new_account_bio': '',
    'auto_clear_chat_days': 1,
    'auto_join_enabled': True,
    'harden_remove_devices': True,
    'harden_set_2fa': True,
}

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

def get_setting(key, default=None):
    if not _settings_cache:
        _load_settings()
    return _settings_cache.get(key, default if default is not None else DEFAULT_SETTINGS.get(key))

def set_setting(key, value):
    global _settings_cache
    if not _settings_cache:
        _load_settings()
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

# ========== ACCOUNT DATA FUNCTIONS ==========
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

# ========== AUTOJOIN ==========
def load_autojoin_links():
    return load_json(AUTOJOIN_FILE, [])

def save_autojoin_links(links):
    save_json(AUTOJOIN_FILE, links)

def add_autojoin_link(link):
    links = load_autojoin_links()
    if link not in links:
        links.append(link)
        save_autojoin_links(links)
        return True
    return False

def remove_autojoin_link(link):
    links = load_autojoin_links()
    if link in links:
        links.remove(link)
        save_autojoin_links(links)
        return True
    return False

# ========== HARDENING TASKS ==========
def load_harden_tasks():
    return load_json(HARDENING_TASKS_FILE, {})

def save_harden_tasks(tasks):
    save_json(HARDENING_TASKS_FILE, tasks)

def add_harden_task(acc_id, task_type, status='pending'):
    tasks = load_harden_tasks()
    if acc_id not in tasks:
        tasks[acc_id] = []
    tasks[acc_id].append({
        'type': task_type,
        'status': status,
        'created_at': datetime.now().isoformat(),
        'completed_at': None
    })
    save_harden_tasks(tasks)

def update_harden_task(acc_id, task_type, status='completed'):
    tasks = load_harden_tasks()
    if acc_id in tasks:
        for t in tasks[acc_id]:
            if t['type'] == task_type:
                t['status'] = status
                t['completed_at'] = datetime.now().isoformat()
                break
        save_harden_tasks(tasks)

# ========== NOTIFICATIONS ==========
async def send_logout_notification(acc, reason="Unknown"):
    if not logout_notification_enabled:
        return
    try:
        name = acc.get('name', 'Unknown')
        phone = acc.get('phone', 'N/A')
        acc_id = acc.get('id', '?')
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=OWNER_ID,
            text=f"🚫 **ACCOUNT LOGOUT!**\n\n👤 Name: {name}\n🆔 ID: {acc_id}\n📱 Phone: {phone}\n⚠️ Reason: {reason}\n🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n🔄 ব্যাকআপ অ্যাক্টিভেট হচ্ছে...",
            parse_mode='Markdown')
    except:
        pass

async def send_backup_activation_notification(backup):
    if not logout_notification_enabled:
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=OWNER_ID,
            text=f"✅ **ব্যাকআপ অ্যাক্টিভেটেড!**\n\n👤 New: {backup.get('name', 'Unknown')}\n📱 Phone: {backup.get('phone', 'N/A')}\n🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n⚡ System fully operational.",
            parse_mode='Markdown')
    except:
        pass

# ========== ★★★ RESTRICTED ACCOUNT AUTO LOGOUT (SECONDS) ★★★ ==========
async def check_restricted_accounts_loop():
    """
    প্রতি ২ সেকেন্ডে সব অ্যাকাউন্ট চেক করে।
    রেস্ট্রিক্টেড অ্যাকাউন্ট পেলেই সাথে সাথে লগআউট করে + ব্যাকআপ অ্যাক্টিভেট করে।
    কোনো ক্লিক লাগবে না - সম্পূর্ণ অটোমেটিক!
    """
    logger.info("🔍 Restricted account checker started - checking every 2 seconds!")
    while not shutdown_event.is_set():
        try:
            for acc in list(active_accounts):
                acc_id = acc['id']
                if acc_id not in account_clients:
                    continue
                
                try:
                    client = account_clients[acc_id]
                    me = await client.get_me()
                    
                    if not me:
                        # অ্যাকাউন্ট ডিসকানেক্টেড
                        logger.warning(f"⚠️ Null user for {acc.get('name','?')} - logging out!")
                        await send_logout_notification(acc, "Session returned null user")
                        asyncio.create_task(handle_banned(acc))
                        continue
                    
                    # ★★★ রেস্ট্রিক্টেড চেক - এটাই মেইন ফিচার ★★★
                    if hasattr(me, 'restricted') and me.restricted:
                        logger.warning(f"🚫 RESTRICTED ACCOUNT: {acc.get('name','?')} - Auto logging out NOW!")
                        await send_logout_notification(acc, "Account Restricted by Telegram")
                        asyncio.create_task(handle_banned(acc))
                        continue
                    
                    # ডিলিটেড অ্যাকাউন্ট চেক
                    if hasattr(me, 'deleted') and me.deleted:
                        logger.warning(f"🗑️ DELETED ACCOUNT: {acc.get('name','?')} - Auto logging out!")
                        await send_logout_notification(acc, "Account Deleted")
                        asyncio.create_task(handle_banned(acc))
                        continue
                    
                except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
                    logger.warning(f"🔴 Auth failed for {acc.get('name','?')}: {str(e)[:30]}")
                    await send_logout_notification(acc, str(e)[:50])
                    asyncio.create_task(handle_banned(acc))
                    
                except Exception as e:
                    err_str = str(e).upper()
                    if 'FLOOD' in err_str:
                        pass  # ফ্লাড হলে ইগনোর
                    elif 'AUTHKEY' in err_str or 'DEACTIVATED' in err_str or 'SESSION' in err_str.upper():
                        await send_logout_notification(acc, str(e)[:50])
                        asyncio.create_task(handle_banned(acc))
            
            # প্রতি ২ সেকেন্ডে চেক (সেকেন্ডের মধ্যে ডিটেক্ট করার জন্য)
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Restricted checker error: {e}")
            await asyncio.sleep(2)

# ========== KEEPALIVE ==========
async def keep_alive_loop(acc_id, client, interval=30):
    acc = find_account(acc_id)
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
                asyncio.create_task(handle_banned(real_acc))
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
                        asyncio.create_task(handle_banned(acc))
                    except:
                        pass
        except:
            pass
        await asyncio.sleep(10)

# ========== ACCOUNT START/STOP ==========
async def start_account(acc):
    try:
        proxy_config = acc.get('proxy')
        proxy = None
        if proxy_config and proxy_config.get('addr'):
            proxy = (socks.SOCKS5, proxy_config.get('addr', ''), proxy_config.get('port', 1080),
                     proxy_config.get('rdns', True), proxy_config.get('username', ''), proxy_config.get('password', ''))
        client = TelegramClient(StringSession(acc['session']), acc.get('api_id', DEFAULT_API_ID),
                                acc.get('api_hash', DEFAULT_API_HASH), proxy=proxy, 
                                sequential_updates=True, receive_updates=True)
        await client.start()
        me = await client.get_me()
        acc_id = acc['id']
        custom_msgs = load_spam_messages()
        if custom_msgs:
            account_spam_messages[acc_id] = [m['text'] for m in custom_msgs]
        else:
            base_msg = get_setting('spam_message', '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')
            account_spam_messages[acc_id] = [
                f"{base_msg} ✨", f"{base_msg} 💋", f"{base_msg} 🔥", 
                f"{base_msg} 💖", f"🔥 {base_msg}", f"💋 {base_msg}", 
                f"✨ {base_msg} 😘", f"{base_msg} 👑"
            ]
        if acc_id in account_keepalive_tasks:
            account_keepalive_tasks[acc_id].cancel()
        account_keepalive_tasks[acc_id] = asyncio.create_task(
            keep_alive_loop(acc_id, client, interval=30))
        return client
    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
        await send_logout_notification(acc, str(e)[:50])
        asyncio.create_task(handle_banned(acc))
        return None
    except Exception as e:
        logger.error(f"Start account failed: {e}")
        return None

async def handle_banned(acc):
    """অ্যাকাউন্ট ব্যান/রেস্ট্রিক্ট হলে কল হবে + অটো ব্যাকআপ"""
    acc_id = acc['id']
    name = acc.get('name', 'Unknown')
    
    # ব্যান লিস্টে যুক্ত করি
    banned = load_json(BANNED_FILE, [])
    if not any(b['id'] == acc_id for b in banned):
        banned.append({
            'id': acc_id, 
            'name': name, 
            'phone': acc.get('phone', 'N/A'), 
            'banned_at': datetime.now().isoformat()
        })
        save_json(BANNED_FILE, banned)
    
    # কিল টাস্ক
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
    
    # ★★★ অটো ব্যাকআপ অ্যাক্টিভেট ★★★
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
            account_stats[backup_copy['id']] = {
                'auto_sent': 0, 'spam_sent': 0, 
                'running': False, 'spam_running': False
            }
            account_stop_flags[backup_copy['id']] = False
            account_spam_active[backup_copy['id']] = False
            register_ar(client, backup_copy)
            logger.info(f"✅ Backup activated: {backup_copy.get('name','?')}")
    else:
        logger.warning("⚠️ No backup accounts available!")

# ========== BACKUP TO RUNNING ==========
async def add_backup_to_running(backup_acc):
    """ব্যাকআপ অ্যাকাউন্ট ১ ক্লিকে রানিং-এ যোগ করো"""
    acc_id = backup_acc['id']
    
    if any(a['id'] == acc_id for a in active_accounts):
        return False, "❌ ইতিমধ্যে রানিং!"
    
    d = load_accounts_data()
    d['backup'] = [a for a in d['backup'] if a['id'] != acc_id]
    backup_acc['is_backup'] = False
    backup_acc['enabled'] = True
    d['main'].append(backup_acc)
    save_json(ACCOUNTS_FILE, d)
    
    client = await start_account(backup_acc)
    if client:
        active_accounts.append(backup_acc)
        account_clients[backup_acc['id']] = client
        account_stats[backup_acc['id']] = {
            'auto_sent': 0, 'spam_sent': 0, 
            'running': False, 'spam_running': False
        }
        account_stop_flags[backup_acc['id']] = False
        account_spam_active[backup_acc['id']] = False
        register_ar(client, backup_acc)
        return True, f"✅ {backup_acc.get('name','?')} রানিং হয়েছে! অটো রিপ্লাই + স্প্যাম শুরু।"
    else:
        return False, "❌ Start failed!"

# ========== AUTO JOIN GROUPS ==========
async def auto_join_groups_for_account(acc):
    if not get_setting('auto_join_enabled', True):
        return
    
    acc_id = acc['id']
    if acc_id not in account_clients:
        return
    
    client = account_clients[acc_id]
    links = load_autojoin_links()
    if not links:
        return
    
    joined = 0
    for link in links:
        try:
            if account_stop_flags.get(acc_id, False):
                break
            if 't.me/' in link or 'telegram.me/' in link:
                username = link.split('/')[-1].split('?')[0]
                if username:
                    try:
                        entity = await client.get_entity(username)
                        if hasattr(entity, 'title'):
                            await client(JoinChannelRequest(entity))
                            joined += 1
                            await asyncio.sleep(3)
                    except FloodWaitError as e:
                        await asyncio.sleep(min(e.seconds, 30))
                    except:
                        pass
        except:
            pass
    
    if joined > 0:
        logger.info(f"📌 {acc.get('name','?')} joined {joined} groups")

# ========== ACCOUNT HARDENING (1 CLICK) ==========
async def harden_account_one_click(acc):
    """১ ক্লিকে: নাম+ডিপি+বায়ো+ডিভাইস লগআউট+২এফএ+লিভ+ক্লিয়ার+জয়েন+অটো ক্লিয়ার"""
    acc_id = acc['id']
    if acc_id not in account_clients:
        return "❌ অ্যাকাউন্ট কানেক্টেড নয়!"
    
    client = account_clients[acc_id]
    results = []
    
    try:
        # 1. নাম চেঞ্জ
        new_name = get_setting('new_account_name', '')
        if new_name:
            try:
                parts = new_name.split(' ', 1)
                first = parts[0]
                last = parts[1] if len(parts) > 1 else ''
                await client(functions.account.UpdateProfileRequest(
                    first_name=first, last_name=last
                ))
                results.append("✅ নাম চেঞ্জ হয়েছে")
            except Exception as e:
                results.append(f"❌ নাম Failed: {str(e)[:30]}")
        
        # 2. বায়ো চেঞ্জ
        new_bio = get_setting('new_account_bio', '')
        if new_bio:
            try:
                await client(functions.account.UpdateProfileRequest(about=new_bio))
                results.append("✅ বায়ো চেঞ্জ হয়েছে")
            except:
                results.append("❌ বায়ো Failed")
        
        # 3. ডিভাইস লগআউট
        try:
            auths = await client(functions.account.GetAuthorizationsRequest())
            current_hash = getattr(auths.authorizations[0], 'hash', 0) if auths.authorizations else 0
            other_devices = [a for a in auths.authorizations if a.hash != current_hash]
            
            if other_devices:
                removed = 0
                for dev in other_devices:
                    now = time.time()
                    created_ts = getattr(dev, 'date_created', 0) or 0
                    time_passed = now - created_ts
                    
                    if time_passed >= 86400:  # 24 ঘন্টা পার
                        try:
                            await client(functions.account.ResetAuthorizationRequest(dev.hash))
                            removed += 1
                        except:
                            pass
                
                if removed > 0:
                    results.append(f"✅ {removed}টি ডিভাইস রিমুভ হয়েছে")
                else:
                    # যেগুলো ২৪ ঘন্টা পূর্ণ হয়নি সেগুলোর সময় দেখাই
                    pending = []
                    for dev in other_devices:
                        created_ts = getattr(dev, 'date_created', 0) or 0
                        remaining = max(0, 86400 - (time.time() - created_ts))
                        if remaining > 0:
                            hours = int(remaining // 3600)
                            mins = int((remaining % 3600) // 60)
                            app = dev.app_name or 'Unknown'
                            pending.append(f"  • {app}: ⏳ {hours}h {mins}m বাকি")
                    
                    if pending:
                        results.append(f"📱 অপেক্ষমাণ ডিভাইস:\n" + "\n".join(pending[:3]))
                    else:
                        results.append("✅ অন্য কোনো ডিভাইস নেই")
            else:
                results.append("✅ অন্য কোনো ডিভাইস নেই")
        except Exception as e:
            results.append(f"⚠️ ডিভাইস: {str(e)[:30]}")
        
        # 4. ২FA সেট (জিমেইল ছাড়া)
        if get_setting('harden_set_2fa', True):
            try:
                twofa_password = f"Secure@{random.randint(1000,9999)}#{acc.get('phone','')[-4:]}"
                await client(functions.account.SetPasswordRequest(
                    new_password=twofa_password,
                    new_hint=f"acc_{acc.get('phone','')[-4:]}",
                    email=None
                ))
                results.append(f"✅ ২FA সেট! Pass: `{twofa_password}`")
                
                twofa_data = load_json(TWOPA_FILE, {})
                twofa_data[acc_id] = {
                    'phone': acc.get('phone', ''),
                    'password': twofa_password,
                    'set_at': datetime.now().isoformat()
                }
                save_json(TWOPA_FILE, twofa_data)
            except Exception as e:
                results.append(f"⚠️ ২FA: {str(e)[:30]}")
        
        # 5. সব গ্রুপ/চ্যানেল লিভ + চ্যাট ক্লিয়ার
        try:
            dialogs = await client.get_dialogs(limit=200)
            leave_count = 0
            clear_count = 0
            
            for dialog in dialogs:
                if account_stop_flags.get(acc_id, False):
                    break
                try:
                    entity = dialog.entity
                    if hasattr(entity, 'title'):
                        try:
                            await client(LeaveChannelRequest(entity))
                            leave_count += 1
                        except:
                            try:
                                from telethon.tl.functions.messages import DeleteChatUserRequest
                                await client(DeleteChatUserRequest(chat_id=entity, user_id='me'))
                                leave_count += 1
                            except:
                                pass
                    
                    try:
                        await client(DeleteHistoryRequest(
                            peer=entity, max_id=0, just_clear=True, revoke=False
                        ))
                        clear_count += 1
                    except:
                        pass
                    
                    await asyncio.sleep(0.3)
                except:
                    pass
            
            results.append(f"✅ {leave_count}টি ছেড়েছে, {clear_count}টি ক্লিয়ার হয়েছে")
        except Exception as e:
            results.append(f"⚠️ লিভ/ক্লিয়ার: {str(e)[:30]}")
        
        # 6. অটো জয়েন
        try:
            await auto_join_groups_for_account(acc)
            results.append("✅ অটো জয়েন করা হয়েছে")
        except:
            results.append("⚠️ অটো জয়েন Failed")
        
        # 7. অটো ক্লিয়ার শিডিউল
        try:
            asyncio.create_task(schedule_auto_clear_chat(
                acc_id, client, days=get_setting('auto_clear_chat_days', 1)
            ))
            results.append(f"✅ {get_setting('auto_clear_chat_days', 1)} দিন পর অটো ক্লিয়ার সেট!")
        except:
            results.append("⚠️ অটো ক্লিয়ার Failed")
        
        # 8. অ্যাকাউন্ট ইনফো আপডেট
        me = await client.get_me()
        if me:
            acc['name'] = f"{me.first_name or ''} {me.last_name or ''}".strip()
            acc['phone'] = me.phone or acc.get('phone', 'N/A')
            d = load_accounts_data()
            for key in ['main', 'backup']:
                for i, a in enumerate(d[key]):
                    if a['id'] == acc_id:
                        d[key][i] = acc
                        break
            save_json(ACCOUNTS_FILE, d)
        
        return "\n".join(results)
    
    except Exception as e:
        return f"❌ Harden Failed: {str(e)[:100]}"

async def schedule_auto_clear_chat(acc_id, client, days=1):
    delay = days * 86400
    try:
        await asyncio.sleep(delay)
        if account_stop_flags.get(acc_id, False):
            return
        
        dialogs = await client.get_dialogs(limit=200)
        cleared = 0
        for dialog in dialogs:
            if account_stop_flags.get(acc_id, False):
                break
            try:
                await client(DeleteHistoryRequest(
                    peer=dialog.entity, max_id=0, just_clear=True, revoke=False
                ))
                cleared += 1
                await asyncio.sleep(0.3)
            except:
                pass
        
        logger.info(f"🧹 Auto-clear: {acc_id} cleared {cleared} chats")
        asyncio.create_task(schedule_auto_clear_chat(acc_id, client, days))
    except asyncio.CancelledError:
        pass
    except:
        pass

# ========== AUTO REPLY ==========
ALL_EMOJIS = ['😀','😃','😄','😁','😆','😅','😉','🙈','😊','😇','🥰','😍','🤩','😘']

def get_random_emoji():
    return random.choice(ALL_EMOJIS)

_user_last_msg_time = {}

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
    global _user_last_msg_time
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
    
    current_time = time.time()
    last_time = _user_last_msg_time.get(uid, 0)
    time_diff = current_time - last_time
    _user_last_msg_time[uid] = current_time
    
    if time_diff < 5 and msg_count > 0:
        try:
            input_chat = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=input_chat, max_id=event.message.id))
        except:
            pass
        customer_count[uid] = msg_count + 1
        return
    
    wait_time = int(get_setting('wait_time', 300))
    if wait_time > 0:
        try:
            input_chat = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=input_chat, max_id=event.message.id))
        except:
            pass
        await asyncio.sleep(wait_time)
    
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
        await asyncio.sleep(0.5)
        second_welcome = get_setting('welcome_message_2', '🔥 I am available now! 😘')
        await client.send_message(chat_id, second_welcome)
        customer_count[uid] = msg_count + 1
        return
    
    try:
        input_chat = await event.get_input_chat()
        await client(ReadHistoryRequest(peer=input_chat, max_id=event.message.id))
    except:
        pass
    
    ignored = get_setting('ignored_messages', '')
    if ignored:
        for line in ignored.split('\n'):
            if line.strip().lower() == msg_lower:
                customer_count[uid] = msg_count + 1
                return
    
    replies = load_json(REPLIES_FILE, [])
    for r in replies:
        kw = r.get('keyword', '').lower().strip()
        if r.get('type', 'contains') == 'exact':
            if msg_lower == kw:
                await event.respond(r.get('reply', ''))
                customer_count[uid] = msg_count + 1
                return
        else:
            if kw and kw in msg_lower:
                await event.respond(r.get('reply', ''))
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
        await event.respond(get_setting('price_list_text', "🔥 10 MIN VC → ₹99"))
        await asyncio.sleep(0.3)
        await event.respond(random.choice(["How many minutes? 🔥", "Pay and enjoy! 😘"]))
        customer_count[uid] = msg_count + 1
        return
    
    offline_keywords = ['real', 'meet', 'aao', 'ghar', 'location', 'offline']
    if any(kw in msg_lower for kw in offline_keywords):
        await event.respond(get_setting('offline_keyword_reply', 'Online only baby 😊'))
        customer_count[uid] = msg_count + 1
        return
    
    greeting_keywords = ['hi', 'hello', 'hey', 'hii', 'hy', 'hlo', 'hlw', 'helo']
    if any(w in msg_lower for w in greeting_keywords):
        greetings = get_setting('greeting_replies', ['Hi baby, ready! 🔥', 'Hey baby! 😘'])
        await event.respond(random.choice(greetings))
        customer_count[uid] = msg_count + 1
        return
    
    defaults = get_setting('default_replies', ['Ready baby! Pay karo! 🔥', 'Main ready hoon! 😘', 'pay and come! 💯'])
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
            await client.send_message(OWNER_ID, f"💳 **PAYMENT!**\n👤 {sender_name}\n🆔 {uid}", parse_mode='Markdown')
            await client.send_file(OWNER_ID, str(file_path))
        except: pass
        customer_count[uid] = -2
    except Exception as e:
        logger.error(f"Payment ss failed: {e}")

async def setup_auto_reply():
    _load_settings()
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

# ========== GROUP SPAM ==========
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
                        asyncio.create_task(handle_banned(acc))
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
            asyncio.create_task(handle_banned(acc))
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
        [InlineKeyboardButton(f"🔐 Account Hardening 🛡️", callback_data="m_harden")],
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in admins:
        await update.message.reply_text("⛔ Unauthorized!")
        return
    await update.message.reply_text("🔥 **কন্ট্রোল প্যানেল** 🔥\n\nনিচ থেকে অপশন সিলেক্ট করুন:", parse_mode='Markdown', reply_markup=main_keyboard())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, logout_notification_enabled
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if user_id != OWNER_ID and user_id not in admins:
        await query.edit_message_text("⛔ Access Denied!")
        return
    
    if data == "main":
        await query.edit_message_text("🔥 **কন্ট্রোল প্যানেল** 🔥\n\nনিচ থেকে অপশন সিলেক্ট করুন:", parse_mode='Markdown', reply_markup=main_keyboard())
    
    # ===== AUTO REPLY =====
    elif data == "m_ar":
        running = sum(1 for a in active_accounts if a.get('enabled', True))
        total = len(active_accounts)
        status = "🟢 ACTIVE" if auto_reply_enabled else "🔴 STOPPED"
        text = f"🤖 **অটো রিপ্লাই**\n\nস্ট্যাটাস: {status}\nচালু: {running}/{total}"
        kb = [
            [InlineKeyboardButton("▶️ সব চালু করো", callback_data="ar_start")],
            [InlineKeyboardButton("⏹️ সব বন্ধ করো", callback_data="ar_stop")],
            [InlineKeyboardButton("👋 ওয়েলকাম মেসেজ", callback_data="ar_welcome")],
            [InlineKeyboardButton("🚫 ফটো ব্লক", callback_data="ar_blockphoto")],
            [InlineKeyboardButton("⌨️ টাইপিং টাইম", callback_data="ar_typing")],
            [InlineKeyboardButton("⏱️ ওয়েট টাইম", callback_data="ar_waittime")],
            [InlineKeyboardButton("🚫 ইগনোর মেসেজ", callback_data="ar_ignore")],
            [InlineKeyboardButton("📝 কাস্টম রিপ্লাই", callback_data="ar_replies")],
            [InlineKeyboardButton("🏠 মেন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ar_start":
        auto_reply_enabled = True
        await query.edit_message_text("✅ **অটো রিপ্লাই চালু!** সব অ্যাকাউন্ট রিপ্লাই দিবে।", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))
    
    elif data == "ar_stop":
        auto_reply_enabled = False
        await query.edit_message_text("⏹️ **অটো রিপ্লাই বন্ধ!** কোনো অ্যাকাউন্ট রিপ্লাই দিবে না।", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))
    
    elif data == "ar_welcome":
        enabled = get_setting('welcome_enabled', True)
        status = "🟢 চালু" if enabled else "🔴 বন্ধ"
        msg1 = get_setting('welcome_message', '🔥 Welcome baby! 🔥')
        msg2 = get_setting('welcome_message_2', '🔥 I am available now! 😘')
        has_img = "✅ আছে" if WELCOME_IMAGE_FILE.exists() else "❌ নেই"
        txt = f"👋 **ওয়েলকাম মেসেজ**\n\nস্ট্যাটাস: {status}\n\n📝 টেক্সট ১ (ছবি সহ):\n`{msg1[:50]}...`\n\n📝 টেক্সট ২ (শুধু টেক্সট):\n`{msg2[:50]}...`\n\nছবি: {has_img}"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} অন/অফ", callback_data="ar_welcome_tog")],
            [InlineKeyboardButton("✏️ টেক্সট ১ এডিট", callback_data="ar_welcome_edit")],
            [InlineKeyboardButton("✏️ টেক্সট ২ এডিট", callback_data="ar_welcome_edit2")],
            [InlineKeyboardButton("📷 ছবি আপলোড", callback_data="ar_welcome_img")],
            [InlineKeyboardButton("🗑️ ছবি রিমুভ", callback_data="ar_welcome_img_del")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ar_welcome_tog":
        cur = get_setting('welcome_enabled', True)
        set_setting('welcome_enabled', not cur)
        await handle_callback(update, context)
    
    elif data == "ar_welcome_edit":
        context.user_data['await'] = 'welcome_text'
        await query.edit_message_text("✏️ **নতুন ওয়েলকাম টেক্সট ১ লিখুন (ছবি সহ):**\n\nএখন টেক্সট পাঠান:", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    elif data == "ar_welcome_edit2":
        context.user_data['await'] = 'welcome_text_2'
        await query.edit_message_text("✏️ **নতুন ওয়েলকাম টেক্সট ২ লিখুন (শুধু টেক্সট):**\n\nএখন টেক্সট পাঠান:", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    elif data == "ar_welcome_img":
        context.user_data['await'] = 'welcome_image'
        await query.edit_message_text("📷 **ওয়েলকাম ইমেজ পাঠান:**\n\nশুধু একটি ফটো পাঠান।", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    elif data == "ar_welcome_img_del":
        if WELCOME_IMAGE_FILE.exists():
            WELCOME_IMAGE_FILE.unlink()
            await query.edit_message_text("✅ Image removed!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
        else:
            await query.edit_message_text("❌ No image to remove!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    elif data == "ar_blockphoto":
        enabled = get_setting('block_photo_enabled', True)
        status = "🟢 ON" if enabled else "🔴 OFF"
        txt = f"🚫 **Block Photo**\n\nStatus: {status}\n\nON = ফটো পেলে ব্লক করবে\nOFF = ফটো পেলে পেমেন্ট স্ক্রিনশট হিসেবে নিবে"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Toggle", callback_data="ar_blockphoto_tog")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
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
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ar_typing_tog":
        cur = get_setting('typing_enabled', True)
        set_setting('typing_enabled', not cur)
        await handle_callback(update, context)
    
    elif data == "ar_typing_time":
        context.user_data['await'] = 'typing_time'
        await query.edit_message_text(f"⏱️ **Enter Typing Time (seconds):**\n\nCurrent: {get_setting('typing_duration', 240)}\n\nRange: 0-300\n\nEx: 60 = 1 মিনিট\n240 = 4 মিনিট", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_typing")]]))
    
    elif data == "ar_waittime":
        current = int(get_setting('wait_time', 300))
        txt = f"⏱️ **Wait Time Before Reply**\n\nCurrent: {current} seconds ({current//60} minutes)\n\nইউজার মেসেজ পাঠানোর পর এত সময় অপেক্ষা করবে তারপর টাইপিং শুরু করবে।\n\nRange: 0-600 seconds (0-10 min)"
        kb = [
            [InlineKeyboardButton("0s", callback_data="wt_0"), InlineKeyboardButton("60s", callback_data="wt_60")],
            [InlineKeyboardButton("120s", callback_data="wt_120"), InlineKeyboardButton("300s", callback_data="wt_300")],
            [InlineKeyboardButton("Custom", callback_data="wt_custom")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("wt_"):
        val = data.split("_")[1]
        if val == "custom":
            context.user_data['await'] = 'wait_time'
            await query.edit_message_text(f"⏱️ Enter wait time in seconds:\n\nCurrent: {get_setting('wait_time', 300)}s\n\nEx: 300 = 5 min", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))
        else:
            set_setting('wait_time', int(val))
            await query.edit_message_text(f"✅ Wait time set to {val}s!", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))
    
    elif data == "ar_ignore":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "🚫 **Ignored Messages**\nযেসব মেসেজের রিপ্লাই দিবে না (এক লাইনে একটি):\n\n"
        if cur: txt += f"Current:\n`{cur}`\n\n"
        txt += "Example:\n`thanks`\n`bye`\n`ok`"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))
    
    elif data == "ar_replies":
        replies = load_json(REPLIES_FILE, [])
        txt = "📝 **Custom Replies**\n\n"
        if replies:
            for i, r in enumerate(replies[-10:], 1):
                txt += f"{i}. `{r['keyword'][:15]}` → {r['reply'][:25]}...\n"
        else:
            txt += "No custom replies added yet.\n"
        txt += "\nUse /add_reply command to add."
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))
    
    # ===== GROUP SPAM =====
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
        await query.edit_message_text("✅ **Group Spam চালু!** সব একাউন্ট স্প্যাম শুরু করেছে।", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))
    
    elif data == "gs_stop":
        group_spam_enabled = False
        stop_spam()
        await query.edit_message_text("⏹️ **Group Spam বন্ধ!** সব স্প্যাম বন্ধ হয়েছে।", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))
    
    elif data == "gs_sp":
        if not active_accounts:
            await query.edit_message_text("❌ No accounts!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))
            return
        kb = [[InlineKeyboardButton(f"{'▶️' if account_stats.get(a['id'], {}).get('spam_running', False) else '⏹️'} {a.get('name','?')[:12]}", callback_data=f"gsa_{a['id']}")] for a in active_accounts]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")])
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
              [InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]
        await query.edit_message_text(f"⚡ **Speed**\nCurrent: {cur}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data in ["gs_sf", "gs_fa", "gs_me", "gs_sl", "gs_cs"]:
        m = {'gs_sf': 'super_fast', 'gs_fa': 'fast', 'gs_me': 'medium', 'gs_sl': 'slow', 'gs_cs': 'custom'}
        set_setting('spam_speed', m[data])
        if data == 'gs_cs':
            kb = [[InlineKeyboardButton("📦 Batch Size", callback_data="gs_bs")],
                  [InlineKeyboardButton("⏱️ Batch Delay", callback_data="gs_bd")],
                  [InlineKeyboardButton("🔄 Cycle Wait", callback_data="gs_cw")],
                  [InlineKeyboardButton("🔙 পিছনে", callback_data="gs_spd")]]
            await query.edit_message_text("⚙️ **Custom Settings**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.edit_message_text(f"✅ Speed: {m[data]}!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))
    
    elif data == "gs_bs":
        context.user_data['await'] = 'gs_bs'
        await query.edit_message_text(f"📦 Batch Size\nCurrent: {get_setting('spam_batch_size', 6)}\n\nEnter (1-50):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_spd")]]))
    
    elif data == "gs_bd":
        context.user_data['await'] = 'gs_bd'
        await query.edit_message_text(f"⏱️ Batch Delay\nCurrent: {get_setting('spam_batch_delay', 3)}s\n\nEnter (0-30):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_spd")]]))
    
    elif data == "gs_cw":
        context.user_data['await'] = 'gs_cw'
        await query.edit_message_text(f"🔄 Cycle Wait\nCurrent: {get_setting('spam_cycle_wait', 30)}s\n\nEnter (0-300):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_spd")]]))
    
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
              [InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "gs_msg_add":
        context.user_data['await'] = 'gs_msg_add'
        await query.edit_message_text("✏️ Enter new spam message:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))
    
    elif data == "gs_msg_del":
        msgs = load_spam_messages()
        if not msgs:
            await query.edit_message_text("❌ No custom messages!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {m['text'][:25]}", callback_data=f"gsmd_{m['id']}")] for m in msgs[:10]]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")])
        await query.edit_message_text("🗑️ **Select to delete:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("gsmd_"):
        mid = int(data.split('_')[1])
        delete_spam_message(mid)
        await query.edit_message_text("✅ Deleted!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))
    
    elif data == "gs_msg_list":
        msgs = load_spam_messages()
        txt = "📋 **All Spam Messages**\n\n"
        if msgs:
            for i, m in enumerate(msgs, 1):
                txt += f"{i}. {m['text']}\n"
        else:
            txt += "No custom messages. Using default.\n"
        await query.edit_message_text(txt[:4000],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))
    
    elif data == "gs_st":
        txt = "📊 **Performance**\n\n"
        for a in active_accounts:
            s = account_stats.get(a['id'], {}).get('spam_sent', 0)
            r = "▶️" if account_stats.get(a['id'], {}).get('spam_running', False) else "⏹️"
            txt += f"{r} {a.get('name', '?')}: {s}\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))
    
    # ===== ACCOUNTS =====
    elif data == "m_acc":
        ma = len(get_main_accounts())
        ba = len(get_backup_accounts())
        act = len(active_accounts)
        txt = f"👥 **Account Management**\n\nMain: {ma} | Backup: {ba} | Active: {act}"
        kb = [
            [InlineKeyboardButton("📱 Phone + OTP", callback_data="ac_ph")],
            [InlineKeyboardButton("🔑 Session String", callback_data="ac_ss")],
            [InlineKeyboardButton("🗑️ Delete", callback_data="ac_del")],
            [InlineKeyboardButton("💾 Backup Mgmt", callback_data="ac_bk")],
            [InlineKeyboardButton("🌐 Proxy", callback_data="ac_pr")],
            [InlineKeyboardButton("📋 List All", callback_data="ac_ls")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("📱 Enter phone number\nInternational format:\n+8801XXXXXXXXX",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
    
    elif data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("🔑 Paste Session String",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
    
    elif data == "ac_del":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ No accounts!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}", callback_data=f"acd_{a['id']}")] for a in all_a]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")])
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
        active_accounts[:] = [x for x in active_accounts if x['id'] != aid]
        for d in [account_stats, account_stop_flags, account_spam_tasks, account_keepalive_tasks, account_spam_active]:
            if aid in d: del d[aid]
        remove_account_data(aid)
        await query.edit_message_text(f"✅ {name} permanently deleted!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
    
    elif data == "ac_bk":
        ba = get_backup_accounts()
        txt = f"💾 **Backup Accounts**\nTotal: {len(ba)}\n\nAuto-used when main banned.\n\n"
        for i, a in enumerate(ba, 1):
            txt += f"{i}. {a.get('name', '?')} ({a.get('phone', 'N/A')})\n"
        kb = [
            [InlineKeyboardButton("➕ Add Backup", callback_data="ac_bk_add")],
            [InlineKeyboardButton("🗑️ Remove", callback_data="ac_bk_del")],
            [InlineKeyboardButton("➡️ Backup → Running (1 Click)", callback_data="ac_bk_to_run")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_bk_add":
        context.user_data['await'] = 'ac_bk_ss'
        await query.edit_message_text("🔑 Backup Session String\n\nPaste:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
    
    elif data == "ac_bk_del":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ No backups!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")])
        await query.edit_message_text("🗑️ **Remove Backup:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_bk_to_run":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ কোনো ব্যাকআপ অ্যাকাউন্ট নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"➡️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"b2r_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")])
        await query.edit_message_text("**কোন ব্যাকআপ অ্যাকাউন্ট রানিং করবেন?**\n\nএটা সাথে সাথে অটো রিপ্লাই + স্প্যাম শুরু করবে!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("b2r_"):
        bid = data.split('_')[1]
        backup_acc = None
        for a in get_backup_accounts():
            if a['id'] == bid:
                backup_acc = a
                break
        if not backup_acc:
            await query.edit_message_text("❌ অ্যাকাউন্ট খুঁজে পাইনি!")
            return
        
        success, msg = await add_backup_to_running(backup_acc)
        await query.edit_message_text(msg, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
    
    elif data.startswith("acbkd_"):
        bid = data.split('_')[1]
        remove_account_data(bid)
        await query.edit_message_text("✅ Backup removed!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
    
    elif data == "ac_pr":
        if not active_accounts:
            await query.edit_message_text("❌ No active accounts!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"🌐 {a.get('name','?')[:12]} {'✅' if a.get('proxy') else '❌'}", callback_data=f"acpr_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")])
        await query.edit_message_text("🌐 **Set Proxy per Account**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("acpr_"):
        aid = data.split('_')[1]
        context.user_data['pr_aid'] = aid
        context.user_data['await'] = 'proxy'
        await query.edit_message_text("🌐 Proxy format:\n`socks5:ip:port:user:pass`\n\nType `remove` to clear", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_pr")]]))
    
    elif data == "ac_ls":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ None!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            return
        txt = f"📋 **All Accounts** ({len(all_a)})\n\n"
        for i, a in enumerate(all_a, 1):
            n = a.get('name', '?')
            p = a.get('phone', 'N/A')
            tp = "MAIN" if not a.get('is_backup') else "BACKUP"
            st = "🟢" if any(x['id'] == a['id'] for x in active_accounts) else "🔴"
            txt += f"{st} {tp} {i}. {n} 📱{p}\n"
        await query.edit_message_text(txt[:4000],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
    
    # ===== SETTINGS =====
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
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_upi":
        context.user_data['await'] = 'upi'
        await query.edit_message_text("✏️ Enter UPI ID:\n\nEx: `user@upi`", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))

    elif data == "st_paytm":
        context.user_data['await'] = 'paytm'
        await query.edit_message_text("✏️ Enter PayTm Number:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))

    elif data == "st_qr":
        context.user_data['await'] = 'qr_code'
        await query.edit_message_text("📷 Send QR Code image now:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]]))

    elif data == "m_stat":
        ar = "🟢" if auto_reply_enabled else "🔴"
        gs = "🟢" if group_spam_enabled else "🔴"
        ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
        ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        spm_act = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        txt = f"📊 **System Status**\n\n🤖 Auto Reply: {ar}\n📨 Group Spam: {gs}\n👤 Active: {len(active_accounts)}\n📨 Spamming: {spm_act}\n💬 Auto Sent: {ttl_auto}\n📬 Spam Sent: {ttl_spam}\n👥 Customers: {len(customer_count)}"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="m_stat"), InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]))

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
        await query.edit_message_text("📢 Enter broadcast message to send ALL customers:", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))

    elif data == "ad_lg":
        log_path = Path(__file__).parent / "bot.log"
        if log_path.exists():
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-20:]
            txt = "📄 **Last 20 Log Lines**\n\n" + "".join(lines[-500:])
        else:
            txt = "📄 No log file found."
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))

    elif data == "ad_rt":
        await query.edit_message_text("🔄 Restarting bot... Please wait.")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # ===== ★★★ NEW: ACCOUNT HARDENING SECTION ★★★ =====
    elif data == "m_harden":
        txt = "🔐 **Account Hardening** 🔐\n\n"
        txt += "═══════════════════════\n"
        txt += "এখান থেকে অ্যাকাউন্টের:\n"
        txt += "✅ নাম, ডিপি, বায়ো চেঞ্জ\n"
        txt += "✅ অন্যান্য ডিভাইস লগআউট\n"
        txt += "✅ ২FA সেট (জিমেইল ছাড়া)\n"
        txt += "✅ সব চ্যাট/গ্রুপ/চ্যানেল লিভ\n"
        txt += "✅ চ্যাট ক্লিয়ার\n"
        txt += "✅ গ্রুপ অটো জয়েন\n"
        txt += "✅ ১ দিন পর অটো ক্লিয়ার\n"
        txt += "═══════════════════════\n"
        txt += "\n❗ **সবকিছু ১ ক্লিকেই!**\n"
        
        kb = [
            [InlineKeyboardButton("⚡ 1 Click Full Hardening", callback_data="harden_all")],
            [InlineKeyboardButton("✏️ Set New Name", callback_data="harden_name")],
            [InlineKeyboardButton("✏️ Set New Bio", callback_data="harden_bio")],
            [InlineKeyboardButton("📱 View Devices", callback_data="harden_devices")],
            [InlineKeyboardButton("🔑 Auto Join Links", callback_data="harden_links")],
            [InlineKeyboardButton("📋 Hardening History", callback_data="harden_history")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "harden_all":
        # কোন অ্যাকাউন্ট হার্ডেন করবে সেটা সিলেক্ট করো
        if not active_accounts:
            await query.edit_message_text("❌ কোনো অ্যাক্টিভ অ্যাকাউন্ট নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
            return
        
        kb = [[InlineKeyboardButton(f"🛡️ {a.get('name','?')[:15]} 📱{a.get('phone','N/A')[-4:]}", callback_data=f"hdn_{a['id']}")] for a in active_accounts]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")])
        await query.edit_message_text("**কোন অ্যাকাউন্ট হার্ডেন করবেন?**\n\n⚠️ ১ ক্লিকেই সব পরিবর্তন হবে!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("hdn_"):
        aid = data.split('_')[1]
        acc = find_account(aid)
        if not acc:
            await query.edit_message_text("❌ অ্যাকাউন্ট খুঁজে পাইনি!")
            return
        
        await query.edit_message_text(f"⏳ **হার্ডেনিং শুরু...**\n\nঅ্যাকাউন্ট: {acc.get('name','?')}\nদয়া করে অপেক্ষা করুন...", parse_mode='Markdown')
        
        result = await harden_account_one_click(acc)
        
        await query.edit_message_text(f"**হার্ডেনিং রেজাল্ট:**\n\n{result}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    elif data == "harden_name":
        context.user_data['await'] = 'harden_name'
        cur = get_setting('new_account_name', '')
        await query.edit_message_text(f"✏️ **নতুন নাম লিখুন:**\n\nবর্তমান: {cur or 'সেট করা হয়নি'}\n\nযেমন: Stylish Girl 🔥", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    elif data == "harden_bio":
        context.user_data['await'] = 'harden_bio'
        cur = get_setting('new_account_bio', '')
        await query.edit_message_text(f"✏️ **নতুন বায়ো লিখুন:**\n\nবর্তমান: {cur or 'সেট করা হয়নি'}\n\nযেমন: 🔞 VIP Service | DM for fun 😘", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    elif data == "harden_devices":
        if not active_accounts:
            await query.edit_message_text("❌ কোনো অ্যাক্টিভ অ্যাকাউন্ট নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
            return
        
        kb = [[InlineKeyboardButton(f"📱 {a.get('name','?')[:15]}", callback_data=f"hdv_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")])
        await query.edit_message_text("**কোন অ্যাকাউন্টের ডিভাইস দেখবেন?**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("hdv_"):
        aid = data.split('_')[1]
        info = await get_device_login_info(aid)
        await query.edit_message_text(f"📱 **Device Info:**\n\n{info[:3500]}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_devices")],
                                                [InlineKeyboardButton("🔄 Refresh", callback_data=f"hdv_{aid}")]]))
    
    elif data == "harden_links":
        links = load_autojoin_links()
        txt = "🔑 **Auto Join Links**\n\nযে সব গ্রুপ লিংকে অটো জয়েন হবে:\n\n"
        if links:
            for i, link in enumerate(links, 1):
                txt += f"{i}. {link[:40]}...\n"
        else:
            txt += "কোনো লিংক যোগ করা হয়নি।\n"
        txt += "\n/new_join_link কমান্ড ব্যবহার করে যোগ করুন।"
        kb = [
            [InlineKeyboardButton("➕ Add இல்", callback_data="harden_link_add")],
            [InlineKeyboardButton("🗑️ Remove লিংক", callback_data="harden_link_del")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "harden_link_add":
        context.user_data['await'] = 'harden_link_add'
        await query.edit_message_text("🔗 **গ্রুপ লিংক পাঠান:**\n\nযেমন: https://t.me/yourgroup", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))
    
    elif data == "harden_link_del":
        links = load_autojoin_links()
        if not links:
            await query.edit_message_text("❌ কোনো লিংক নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {link[:30]}", callback_data=f"hjdel_{i}")] for i, link in enumerate(links[:10])]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")])
        await query.edit_message_text("**কোন লিংক ডিলিট করবেন?**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("hjdel_"):
        idx = int(data.split('_')[1])
        links = load_autojoin_links()
        if idx < len(links):
            link = links.pop(idx)
            save_autojoin_links(links)
            await query.edit_message_text(f"✅ `{link[:30]}...` ডিলিট হয়েছে!",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))
    
    elif data == "harden_history":
        txt = "📋 **Hardening History**\n\n"
        has_data = False
        for acc in active_accounts:
            tasks = get_harden_tasks_for_account(acc['id'])
            if tasks:
                has_data = True
                txt += f"👤 {acc.get('name','?')}\n"
                for t in tasks[-5:]:
                    status = "✅" if t['status'] == 'completed' else "⏳"
                    txt += f"  {status} {t['type']} - {t['created_at'][:16]}\n"
                txt += "\n"
        
        if not has_data:
            txt += "কোনো হার্ডেনিং ডাটা নেই।\nউপরের 1 Click Full Hardening ব্যবহার করুন।"
        
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    else:
        await query.edit_message_text(f"⚠️ Unknown callback: {data}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]))


# ====== TEXT MESSAGE HANDLER ======
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in admins:
        return

    text = update.message.text.strip()
    await_state = context.user_data.get('await')

    if not await_state:
        return

    if await_state == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Welcome message 1 updated!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))

    elif await_state == 'welcome_text_2':
        set_setting('welcome_message_2', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Welcome message 2 updated!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    elif await_state == 'wait_time':
        try:
            val = max(0, min(600, int(text)))
            set_setting('wait_time', val)
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Wait time set to {val}s!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))
        except:
            await update.message.reply_text("❌ Enter a number (0-600)!")

    elif await_state == 'typing_time':
        try:
            val = int(text)
            if 0 <= val <= 300:
                set_setting('typing_duration', val)
                context.user_data.pop('await', None)
                await update.message.reply_text(f"✅ Typing time set to {val}s!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_typing")]]))
            else:
                await update.message.reply_text("❌ Range 0-300!")
        except:
            await update.message.reply_text("❌ Enter a number!")

    elif await_state == 'ignore':
        set_setting('ignored_messages', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Ignored messages updated!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    elif await_state == 'upi':
        set_setting('upi_id', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ UPI set!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))

    elif await_state == 'paytm':
        set_setting('paytm_num', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ PayTm set!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))

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
        await update.message.reply_text(f"✅ Broadcast sent to {sent} customers!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))

    elif await_state == 'gs_msg_add':
        add_spam_message(text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Spam message added!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))

    elif await_state == 'gs_bs':
        try:
            val = max(1, min(50, int(text)))
            set_setting('spam_batch_size', val)
            set_setting('spam_speed', 'custom')
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Batch size: {val}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_spd")]]))
        except:
            await update.message.reply_text("❌ Number only!")

    elif await_state == 'gs_bd':
        try:
            val = max(0, min(30, int(text)))
            set_setting('spam_batch_delay', val)
            set_setting('spam_speed', 'custom')
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Batch delay: {val}s",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_spd")]]))
        except:
            await update.message.reply_text("❌ Number only!")

    elif await_state == 'gs_cw':
        try:
            val = max(0, min(300, int(text)))
            set_setting('spam_cycle_wait', val)
            set_setting('spam_speed', 'custom')
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Cycle wait: {val}s",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_spd")]]))
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
            await update.message.reply_text("✅ Proxy removed!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_pr")]]))
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
                await update.message.reply_text("✅ Proxy set! Restart account to apply.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_pr")]]))
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
            await update.message.reply_text(f"✅ OTP sent to {text}\n\nEnter OTP:", parse_mode='Markdown')
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
            await update.message.reply_text(f"✅ Account added!\n👤 {name}\n📱 {phone}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
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
                'api_id': context.user_data.get('ac_api_id', DEFAULT_API_ID),
                'api_hash': context.user_data.get('ac_api_hash', DEFAULT_API_HASH),
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
            await update.message.reply_text(f"✅ Account added!\n👤 {name}\n📱 {phone}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
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
                await update.message.reply_text(f"✅ Account added!\n👤 {name}\n📱 {phone}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
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
                await update.message.reply_text(f"✅ Backup added!\n👤 {name}\n📱 {phone}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
            else:
                await update.message.reply_text("❌ Invalid session!")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
            context.user_data.pop('await', None)

    # ★★★ NEW: HARDENING TEXT HANDLERS ★★★
    elif await_state == 'harden_name':
        set_setting('new_account_name', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ নতুন নাম সেভ হয়েছে: `{text}`\n\nএখন **1 Click Full Hardening** ব্যবহার করলে এই নাম সেট হবে।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif await_state == 'harden_bio':
        set_setting('new_account_bio', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ নতুন বায়ো সেভ হয়েছে: `{text[:50]}...`\n\nএখন **1 Click Full Hardening** ব্যবহার করলে এই বায়ো সেট হবে।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif await_state == 'harden_link_add':
        link = text.strip()
        if 't.me/' in link or 'telegram.me/' in link:
            add_autojoin_link(link)
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ লিংক যোগ হয়েছে!\n\nপরবর্তী Hardening এ অ্যাকাউন্ট অটো জয়েন করবে।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))
        else:
            await update.message.reply_text("❌ ভ্যালিড টেলিগ্রাম লিংক দিন!\nযেমন: https://t.me/groupusername")

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
            await update.message.reply_text("✅ Welcome image updated!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:50]}")

    elif await_state == 'qr_code':
        try:
            photo = await update.message.photo[-1].get_file()
            await photo.download_to_drive(str(QR_CODE_FILE))
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ QR Code saved!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]]))
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
    replies.append({'keyword': keyword, 'reply': reply, 'type': 'contains', 'added_at': datetime.now().isoformat()})
    save_json(REPLIES_FILE, replies)
    await update.message.reply_text(f"✅ Reply added for `{keyword}`", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
    ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
    restricted_check = "🟢 Active" if any(True for _ in active_accounts) else "🔴 Inactive"
    txt = f"📊 **STATUS**\n\n👤 Active: {len(active_accounts)}\n💬 Auto Sent: {ttl_auto}\n📬 Spam Sent: {ttl_spam}\n👥 Customers: {len(customer_count)}\n🛡️ Restricted Check: {restricted_check}"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def new_join_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if len(args) < 1:
        links = load_autojoin_links()
        txt = "🔗 **Auto Join Links**\n\n"
        if links:
            for i, link in enumerate(links, 1):
                txt += f"{i}. {link}\n"
        else:
            txt += "কোনো লিংক নেই।"
        await update.message.reply_text(txt, parse_mode='Markdown')
        return
    link = args[0]
    if add_autojoin_link(link):
        await update.message.reply_text(f"✅ Link added!\n{link}")
    else:
        await update.message.reply_text("❌ Already exists or invalid!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    txt = """🔥 **BOT COMMANDS** 🔥

**BASIC:**
/start - Control panel খুলুন
/status - দ্রুত স্ট্যাটাস দেখুন
/help - এই মেসেজ

**REPLIES:**
/add_reply keyword reply - কাস্টম রিপ্লাই যোগ করুন

**AUTO JOIN:**
/new_join_link [link] - গ্রুপ জয়েন লিংক যোগ করুন

**★★★ MAIN FEATURES ★★★**
✅ অটো রিপ্লাই (ওয়েট + টাইপিং)
✅ মাল্টিপল মেসেজ ডিটেকশন
✅ গ্রুপ স্প্যাম (স্পীড কন্ট্রোল)
✅ QR কোড পেমেন্ট
✅ ফটো ব্লক ফিচার
✅ ব্যাকআপ → রানিং (1 ক্লিক)
✅ ★ Restricted Account Auto Logout (2 sec)
✅ ★ Account Hardening (1 Click)
  - নাম/বায়ো/ডিপি চেঞ্জ
  - ডিভাইস লগআউট
  - ২FA (জিমেইল ছাড়া)
  - সব গ্রুপ/চ্যানেল লিভ
  - চ্যাট ক্লিয়ার
  - অটো জয়েন
  - ১ দিন পর অটো ক্লিয়ার
"""
    await update.message.reply_text(txt, parse_mode='Markdown')


# ====== DEVICE LOGIN INFO HELPER ======
async def get_device_login_info(acc_id):
    if acc_id not in account_clients:
        return "❌ Account not connected!"
    
    client = account_clients[acc_id]
    try:
        from telethon.tl.functions.account import GetAuthorizationsRequest
        
        auths = await client(GetAuthorizationsRequest())
        current_hash = getattr(auths.authorizations[0], 'hash', 0) if auths.authorizations else 0
        
        info = []
        for i, auth in enumerate(auths.authorizations):
            app_name = auth.app_name or 'Unknown'
            device_model = auth.device_model or 'Unknown'
            platform = auth.platform or '?'
            country = auth.country or '??'
            date_active = datetime.fromtimestamp(auth.date_active) if hasattr(auth, 'date_active') and auth.date_active else 'N/A'
            date_created = datetime.fromtimestamp(auth.date_created) if hasattr(auth, 'date_created') and auth.date_created else 'N/A'
            
            is_current = "⭐ CURRENT" if auth.hash == current_hash else ""
            
            now = time.time()
            created_ts = getattr(auth, 'date_created', 0) or 0
            time_passed = now - created_ts
            time_remaining = max(0, 86400 - time_passed)
            
            if time_remaining > 0 and not is_current:
                hours_left = int(time_remaining // 3600)
                mins_left = int((time_remaining % 3600) // 60)
                can_delete = f"⏳ {hours_left}h {mins_left}m বাকি"
            elif is_current:
                can_delete = "🚫 বর্তমান ডিভাইস"
            else:
                can_delete = "✅ এখনই রিমুভ করা যাবে"
            
            info.append(f"{'⭐ ' if is_current else ''}{i+1}. **{app_name}**\n📱 {device_model} ({platform})\n🌍 {country}\n🕐 Active: {date_active}\n🔑 {can_delete}")
        
        return "\n\n".join(info) if info else "ℹ️ No login info found"
    
    except Exception as e:
        return f"❌ Error: {str(e)[:50]}"


# ====== FLASK ======
@flask_app.route('/')
def index():
    return jsonify({
        'status': 'running', 
        'accounts': len(active_accounts), 
        'time': datetime.now().isoformat(),
        'restricted_checker': '✅ Active (every 2s)'
    })

@flask_app.route('/health')
def health():
    return jsonify({'status': 'ok', 'bot_ready': bot_ready, 'accounts': len(active_accounts)})

async def run_flask():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False))


# ====== MAIN SETUP ======
async def main_async():
    global ptb_application, bot_ready, bot_event_loop

    bot_event_loop = asyncio.get_event_loop()
    _load_settings()

    # Setup PTB
    ptb = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    ptb_application = ptb

    # Add handlers
    ptb.add_handler(CommandHandler("start", start_command))
    ptb.add_handler(CommandHandler("status", status_command))
    ptb.add_handler(CommandHandler("help", help_command))
    ptb.add_handler(CommandHandler("add_reply", add_reply_command))
    ptb.add_handler(CommandHandler("new_join_link", new_join_link_command))
    ptb.add_handler(CallbackQueryHandler(handle_callback))
    ptb.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    ptb.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    # Start polling
    await ptb.initialize()
    await ptb.start()
    await ptb.updater.start_polling(drop_pending_updates=True)

    # Setup accounts
    await setup_auto_reply()

    # ★★★ START RESTRICTED ACCOUNT CHECKER (EVERY 2 SECONDS!) ★★★
    asyncio.create_task(check_restricted_accounts_loop())
    logger.info("🔍★ Restricted account checker started - checking every 2 seconds!")

    # Start background tasks
    asyncio.create_task(check_account_status_periodically())
    asyncio.create_task(run_flask())

    bot_ready = True

    # Notify owner
    try:
        await ptb.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔥 **Bot Ready!**\n\n"
                 f"👤 Accounts: {len(active_accounts)}\n"
                 f"🤖 Auto Reply: {'ON' if auto_reply_enabled else 'OFF'}\n"
                 f"📨 Group Spam: {'ON' if group_spam_enabled else 'OFF'}\n"
                 f"🛡️ Restricted Check: ✅ প্রতি ২ সেকেন্ডে\n"
                 f"🔐 Hardening: ✅ Available",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Owner notify failed: {e}")

    logger.info(f"Bot Ready! {len(active_accounts)} accounts active. Restricted checker: Active!")

    await shutdown_event.wait()


async def shutdown_bot():
    global bot_ready
    logger.info("Shutting down...")
    bot_ready = False
    shutdown_event.set()

    for tid in list(account_spam_tasks.keys()):
        try: account_spam_tasks[tid].cancel()
        except: pass

    for tid in list(account_keepalive_tasks.keys()):
        try: account_keepalive_tasks[tid].cancel()
        except: pass

    for aid, cli in account_clients.items():
        try: await cli.disconnect()
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

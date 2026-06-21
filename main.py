#!/usr/bin/env python3
"""
UNIFIED TELEGRAM BOT - ENHANCED V2
====================================
★ NEW: Channel Backup System
  - Backup channels store করে রাখে
  - Main channel থেকে kick/restrict হলে auto backup channel join
  - Backup channel এ auto spam শুরু
★ Restricted Account Auto Logout (2 sec)
★ 1 Click Account Hardening
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

# ─── ENV VARS ───
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
DEFAULT_API_ID = int(os.environ.get("API_ID", "0"))
DEFAULT_API_HASH = os.environ.get("API_HASH", "")
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', '')
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

import socks
from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, SessionPasswordNeededError,
    PhoneCodeInvalidError, PhoneCodeExpiredError,
    AuthKeyUnregisteredError, UserDeactivatedError,
    PhoneNumberInvalidError, ChannelPrivateError,
    ChatAdminRequiredError, UserNotParticipantError
)
from telethon.tl.functions.messages import (
    GetDialogsRequest, ReadHistoryRequest, DeleteHistoryRequest
)
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.channels import (
    LeaveChannelRequest, JoinChannelRequest,
    GetParticipantRequest, GetFullChannelRequest
)
from telethon.tl.types import (
    InputPeerEmpty, InputPeerChannel, InputPeerChat,
    Channel, Chat, ChannelParticipantsSearch
)

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
# ★ NEW: Channel Backup File
CHANNEL_BACKUP_FILE = DATA_DIR / "channel_backup.json"

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
    # ★ NEW: Channel Backup Settings
    'channel_backup_enabled': True,
    'channel_spam_enabled': True,
    'channel_check_interval': 30,  # প্রতি ৩০ সেকেন্ডে চেক
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

# ========== ACCOUNT DATA ==========
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

# ========== ★★ NEW: CHANNEL BACKUP SYSTEM ★★ ==========
def load_channel_backup():
    """চ্যানেল ব্যাকআপ ডাটা লোড করে"""
    return load_json(CHANNEL_BACKUP_FILE, {
        'main_channels': [],    # মূল চ্যানেল
        'backup_channels': [],  # ব্যাকআপ চ্যানেল
        'active_channel': None  # বর্তমানে কোন চ্যানেল active
    })

def save_channel_backup(data):
    """চ্যানেল ব্যাকআপ ডাটা সেভ করে"""
    save_json(CHANNEL_BACKUP_FILE, data)

def add_main_channel(channel_info):
    """মূল চ্যানেল যোগ করো"""
    data = load_channel_backup()
    # ডুপ্লিকেট চেক
    for ch in data['main_channels']:
        if ch['id'] == channel_info['id']:
            return False
    data['main_channels'].append(channel_info)
    save_channel_backup(data)
    return True

def add_backup_channel(channel_info):
    """ব্যাকআপ চ্যানেল যোগ করো"""
    data = load_channel_backup()
    for ch in data['backup_channels']:
        if ch['id'] == channel_info['id']:
            return False
    data['backup_channels'].append(channel_info)
    save_channel_backup(data)
    return True

def remove_channel(channel_id):
    """চ্যানেল রিমুভ করো"""
    data = load_channel_backup()
    found = False
    
    data['main_channels'] = [ch for ch in data['main_channels'] if ch['id'] != channel_id]
    data['backup_channels'] = [ch for ch in data['backup_channels'] if ch['id'] != channel_id]
    
    if data['active_channel'] and data['active_channel']['id'] == channel_id:
        data['active_channel'] = None
    
    save_channel_backup(data)
    return True

async def check_main_channel_status(acc_id, main_channel_info):
    """মূল চ্যানেল চেক করে - কিক/রেস্ট্রিক্টেড কিনা"""
    if acc_id not in account_clients:
        return False, "Account not connected"
    
    client = account_clients[acc_id]
    try:
        channel_entity = await client.get_entity(int(main_channel_info['id']))
        
        # চেক করি ইউজার চ্যানেলে আছে কিনা
        try:
            me = await client.get_me()
            participant = await client(GetParticipantRequest(
                channel=channel_entity,
                participant=me.id
            ))
            return True, "Member"  # সদস্য আছে = OK
        except UserNotParticipantError:
            return False, "KICKED"  # কিক করা হয়েছে
        except ChatAdminRequiredError:
            return False, "NO_ACCESS"  # এক্সেস নেই
        except Exception as e:
            err = str(e).upper()
            if 'USER_NOT_PARTICIPANT' in err:
                return False, "KICKED"
            elif 'CHANNEL_PRIVATE' in err:
                return False, "PRIVATE"
            elif 'USER_BANNED' in err:
                return False, "BANNED"
            return True, f"Unknown: {str(e)[:30]}"
            
    except ChannelPrivateError:
        return False, "CHANNEL_PRIVATE"
    except ValueError:
        return False, "INVALID_ID"
    except Exception as e:
        return False, f"Error: {str(e)[:30]}"

async def switch_to_backup_channel(acc_id, main_channel, backup_channels):
    """মূল চ্যানেল ব্যর্থ হলে ব্যাকআপ চ্যানেলে সুইচ করো"""
    if not backup_channels:
        return None, "❌ কোনো ব্যাকআপ চ্যানেল নেই!"
    
    if acc_id not in account_clients:
        return None, "❌ Account not connected"
    
    client = account_clients[acc_id]
    
    for backup_ch in backup_channels:
        try:
            # ব্যাকআপ চ্যানেলে জয়েন করার চেষ্টা
            entity = await client.get_entity(int(backup_ch['id']))
            
            try:
                await client(JoinChannelRequest(entity))
                logger.info(f"✅ Joined backup channel: {backup_ch.get('title','?')}")
                
                # ব্যাকআপ চ্যানেলে স্প্যাম শুরু করি
                asyncio.create_task(spam_in_channel(acc_id, entity))
                
                # ডাটা আপডেট
                data = load_channel_backup()
                data['active_channel'] = backup_ch
                save_channel_backup(data)
                
                return backup_ch, f"✅ ব্যাকআপ চ্যানেলে সুইচ করা হয়েছে: {backup_ch.get('title','?')}"
                
            except Exception as e:
                logger.warning(f"❌ Cannot join {backup_ch.get('title','?')}: {e}")
                continue
                
        except Exception as e:
            continue
    
    return None, "❌ কোনো ব্যাকআপ চ্যানেল জয়ন করতে পারিনি!"

async def spam_in_channel(acc_id, channel_entity):
    """ব্যাকআপ চ্যানেলে স্প্যাম করো"""
    account_stop_flags[f"ch_spam_{acc_id}"] = False
    
    spam_messages = account_spam_messages.get(acc_id, [
        get_setting('spam_message', '𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')
    ])
    
    client = account_clients.get(acc_id)
    if not client:
        return
    
    msg_index = 0
    while not account_stop_flags.get(f"ch_spam_{acc_id}", False):
        if not get_setting('channel_spam_enabled', True):
            await asyncio.sleep(5)
            continue
        
        try:
            emoji = random.choice(['😘', '🔥', '💋', '💖', '✨', '👑'])
            message = f"{spam_messages[msg_index % len(spam_messages)]} {emoji}"
            
            await client.send_message(channel_entity, message)
            account_stats[acc_id]['spam_sent'] += 1
            msg_index += 1
            
            # র‍্যান্ডম ইন্টারভাল (৫-১৫ সেকেন্ড)
            await asyncio.sleep(random.uniform(5, 15))
            
        except FloodWaitError as e:
            await asyncio.sleep(min(e.seconds, 60))
        except Exception as e:
            if 'DEACTIVATED' in str(e).upper() or 'AUTHKEY' in str(e).upper():
                break
            await asyncio.sleep(10)

def stop_channel_spam(acc_id):
    """চ্যানেল স্প্যাম বন্ধ করো"""
    account_stop_flags[f"ch_spam_{acc_id}"] = True

# ★★★ CHANNEL BACKUP MONITORING LOOP ★★★
async def monitor_channels_loop():
    """প্রতি ৩০ সেকেন্ডে চ্যানেল চেক করে - কিক/রেস্ট্রিক্টেড হলে ব্যাকআপে সুইচ"""
    logger.info("📡★ Channel backup monitor started - checking every 30s!")
    
    while not shutdown_event.is_set():
        try:
            if not get_setting('channel_backup_enabled', True):
                await asyncio.sleep(30)
                continue
            
            data = load_channel_backup()
            main_channels = data.get('main_channels', [])
            backup_channels = data.get('backup_channels', [])
            
            if not main_channels or not backup_channels:
                await asyncio.sleep(30)
                continue
            
            for acc in active_accounts:
                acc_id = acc['id']
                if acc_id not in account_clients:
                    continue
                
                for main_ch in main_channels:
                    status, reason = await check_main_channel_status(acc_id, main_ch)
                    
                    if not status:
                        # ★★★ চ্যানেল থেকে কিক/রেস্ট্রিক্টেড! ★★★
                        logger.warning(f"🚫 Channel issue! {main_ch.get('title','?')}: {reason}")
                        
                        # ব্যাকআপে সুইচ করো
                        backup_ch, msg = await switch_to_backup_channel(acc_id, main_ch, backup_channels)
                        
                        # ওনারকে নোটিফাই করি
                        try:
                            bot = Bot(token=BOT_TOKEN)
                            await bot.send_message(
                                chat_id=OWNER_ID,
                                text=f"🚫 **চ্যানেল প্রোবলেম!**\n\n"
                                     f"📛 চ্যানেল: {main_ch.get('title','?')}\n"
                                     f"⚠️ কারণ: {reason}\n"
                                     f"🕐 সময়: {datetime.now().strftime('%H:%M:%S')}\n\n"
                                     f"{msg}",
                                parse_mode='Markdown'
                            )
                        except:
                            pass
                        
                        # ব্যাকআপ ফাউন্ড না হলে ব্যাকআপ অ্যাকাউন্ট অ্যাক্টিভেট করি
                        if not backup_ch:
                            logger.warning("⚠️ No backup channel! Activating backup account...")
                            backups = get_backup_accounts()
                            if backups:
                                await add_backup_to_running(backups[0])
                        
                        # শুধু প্রথম ইস্যুতে নোটিফাই করি, লুপ থামাই
                        break
                
                await asyncio.sleep(5)  # প্রতিটি অ্যাকাউন্টের মাঝে ৫ সেকেন্ড
            
            await asyncio.sleep(get_setting('channel_check_interval', 30))
            
        except Exception as e:
            logger.error(f"Channel monitor error: {e}")
            await asyncio.sleep(30)

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
            text=f"🚫 **ACCOUNT LOGOUT!**\n\n"
                 f"👤 Name: {name}\n🆔 ID: {acc_id}\n📱 Phone: {phone}\n"
                 f"⚠️ Reason: {reason}\n🕐 Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
                 f"🔄 ব্যাকআপ অ্যাক্টিভেট হচ্ছে...",
            parse_mode='Markdown')
    except:
        pass

async def send_backup_activation_notification(backup):
    if not logout_notification_enabled:
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=OWNER_ID,
            text=f"✅ **ব্যাকআপ অ্যাক্টিভেটেড!**\n\n"
                 f"👤 New: {backup.get('name', 'Unknown')}\n📱 Phone: {backup.get('phone', 'N/A')}\n"
                 f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}\n\n⚡ System back online!",
            parse_mode='Markdown')
    except:
        pass

async def send_channel_switch_notification(main_ch, backup_ch, reason):
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=OWNER_ID,
            text=f"🔄 **চ্যানেল সুইচ!**\n\n"
                 f"📛 আগের: {main_ch.get('title','?')}\n"
                 f"✅ নতুন: {backup_ch.get('title','?')}\n"
                 f"⚠️ কারণ: {reason}\n"
                 f"🕐 সময়: {datetime.now().strftime('%H:%M:%S')}",
            parse_mode='Markdown')
    except:
        pass

# ========== ★★★ RESTRICTED ACCOUNT AUTO LOGOUT ★★★ ==========
async def check_restricted_accounts_loop():
    """প্রতি ২ সেকেন্ডে সব অ্যাকাউন্ট চেক করে"""
    logger.info("🔍 Restricted checker started - every 2 seconds!")
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
                        logger.warning(f"⚠️ Null user for {acc.get('name','?')}")
                        await send_logout_notification(acc, "Session null")
                        asyncio.create_task(handle_banned(acc))
                        continue
                    
                    # Restricted check
                    if hasattr(me, 'restricted') and me.restricted:
                        logger.warning(f"🚫 RESTRICTED: {acc.get('name','?')}")
                        await send_logout_notification(acc, "Account Restricted by Telegram")
                        asyncio.create_task(handle_banned(acc))
                        continue
                    
                    if hasattr(me, 'deleted') and me.deleted:
                        logger.warning(f"🗑️ DELETED: {acc.get('name','?')}")
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
                        pass
                    elif 'AUTHKEY' in err_str or 'DEACTIVATED' in err_str or 'SESSION' in err_str:
                        await send_logout_notification(acc, str(e)[:50])
                        asyncio.create_task(handle_banned(acc))
            
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Restricted checker error: {e}")
            await asyncio.sleep(2)

# ========== KEEPALIVE ==========
async def keep_alive_loop(acc_id, client, interval=30):
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
        account_keepalive_tasks[acc_id] = asyncio.create_task(keep_alive_loop(acc_id, client, interval=30))
        return client
    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
        await send_logout_notification(acc, str(e)[:50])
        asyncio.create_task(handle_banned(acc))
        return None
    except Exception as e:
        logger.error(f"Start account failed: {e}")
        return None

async def handle_banned(acc):
    """অ্যাকাউন্ট ব্যান/রেস্ট্রিক্ট হলে"""
    acc_id = acc['id']
    name = acc.get('name', 'Unknown')
    
    # Stop channel spam for this account
    stop_channel_spam(acc_id)
    
    banned = load_json(BANNED_FILE, [])
    if not any(b['id'] == acc_id for b in banned):
        banned.append({
            'id': acc_id, 'name': name, 'phone': acc.get('phone', 'N/A'), 
            'banned_at': datetime.now().isoformat()
        })
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
    
    # Auto backup activation
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
        logger.warning("⚠️ No backup accounts!")

# ========== BACKUP TO RUNNING ==========
async def add_backup_to_running(backup_acc):
    """ব্যাকআপ অ্যাকাউন্ট ১ ক্লিকে রানিং"""
    acc_id = backup_acc['id']
    if any(a['id'] == acc_id for a in active_accounts):
        return False, "❌ Already running!"
    
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
        account_stats[backup_acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
        account_stop_flags[backup_acc['id']] = False
        account_spam_active[backup_acc['id']] = False
        register_ar(client, backup_acc)
        return True, f"✅ {backup_acc.get('name','?')} রানিং হয়েছে!"
    else:
        return False, "❌ Start failed!"

# ========== AUTO JOIN ==========
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

# ========== ACCOUNT HARDENING ==========
async def harden_account_one_click(acc):
    acc_id = acc['id']
    if acc_id not in account_clients:
        return "❌ Account not connected!"
    
    client = account_clients[acc_id]
    results = []
    
    try:
        new_name = get_setting('new_account_name', '')
        if new_name:
            try:
                parts = new_name.split(' ', 1)
                first = parts[0]
                last = parts[1] if len(parts) > 1 else ''
                await client(functions.account.UpdateProfileRequest(first_name=first, last_name=last))
                results.append("✅ Name changed")
            except Exception as e:
                results.append(f"❌ Name: {str(e)[:30]}")
        
        new_bio = get_setting('new_account_bio', '')
        if new_bio:
            try:
                await client(functions.account.UpdateProfileRequest(about=new_bio))
                results.append("✅ Bio changed")
            except:
                results.append("❌ Bio failed")
        
        try:
            auths = await client(functions.account.GetAuthorizationsRequest())
            current_hash = getattr(auths.authorizations[0], 'hash', 0) if auths.authorizations else 0
            other_devices = [a for a in auths.authorizations if a.hash != current_hash]
            
            if other_devices:
                removed = 0
                for dev in other_devices:
                    now = time.time()
                    created_ts = getattr(dev, 'date_created', 0) or 0
                    if (now - created_ts) >= 86400:
                        try:
                            await client(functions.account.ResetAuthorizationRequest(dev.hash))
                            removed += 1
                        except:
                            pass
                
                if removed > 0:
                    results.append(f"✅ {removed} devices removed")
                else:
                    pending = []
                    for dev in other_devices:
                        created_ts = getattr(dev, 'date_created', 0) or 0
                        remaining = max(0, 86400 - (time.time() - created_ts))
                        if remaining > 0:
                            hours = int(remaining // 3600)
                            mins = int((remaining % 3600) // 60)
                            app = dev.app_name or 'Unknown'
                            pending.append(f"  • {app}: ⏳ {hours}h {mins}m left")
                    
                    if pending:
                        results.append(f"📱 Devices waiting:\n" + "\n".join(pending[:3]))
                    else:
                        results.append("✅ No other devices")
            else:
                results.append("✅ No other devices")
        except Exception as e:
            results.append(f"⚠️ Devices: {str(e)[:30]}")
        
        if get_setting('harden_set_2fa', True):
            try:
                twofa_password = f"Secure@{random.randint(1000,9999)}#{acc.get('phone','')[-4:]}"
                await client(functions.account.SetPasswordRequest(
                    new_password=twofa_password,
                    new_hint=f"acc_{acc.get('phone','')[-4:]}",
                    email=None
                ))
                results.append(f"✅ 2FA set! Pass: `{twofa_password}`")
                
                twofa_data = load_json(TWOPA_FILE, {})
                twofa_data[acc_id] = {'phone': acc.get('phone', ''), 'password': twofa_password, 'set_at': datetime.now().isoformat()}
                save_json(TWOPA_FILE, twofa_data)
            except Exception as e:
                results.append(f"⚠️ 2FA: {str(e)[:30]}")
        
        try:
            dialogs = await client.get_dialogs(limit=200)
            leave_count = 0
            clear_count = 0
            
            for dialog in dialogs:
                if account_stop_flags.get(acc_id, False): break
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
                            except: pass
                    
                    try:
                        await client(DeleteHistoryRequest(peer=entity, max_id=0, just_clear=True, revoke=False))
                        clear_count += 1
                    except: pass
                    
                    await asyncio.sleep(0.3)
                except: pass
            
            results.append(f"✅ Left {leave_count}, Cleared {clear_count}")
        except Exception as e:
            results.append(f"⚠️ Leave/Clear: {str(e)[:30]}")
        
        try:
            await auto_join_groups_for_account(acc)
            results.append("✅ Auto-join done")
        except:
            results.append("⚠️ Auto-join failed")
        
        try:
            asyncio.create_task(schedule_auto_clear_chat(acc_id, client, days=get_setting('auto_clear_chat_days', 1)))
            results.append(f"✅ Auto-clear in {get_setting('auto_clear_chat_days', 1)} day(s)")
        except:
            results.append("⚠️ Auto-clear failed")
        
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
        return f"❌ Harden failed: {str(e)[:100]}"

async def schedule_auto_clear_chat(acc_id, client, days=1):
    delay = days * 86400
    try:
        await asyncio.sleep(delay)
        if account_stop_flags.get(acc_id, False): return
        
        dialogs = await client.get_dialogs(limit=200)
        cleared = 0
        for dialog in dialogs:
            if account_stop_flags.get(acc_id, False): break
            try:
                await client(DeleteHistoryRequest(peer=dialog.entity, max_id=0, just_clear=True, revoke=False))
                cleared += 1
                await asyncio.sleep(0.3)
            except: pass
        
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
                if uid not in customer_count: customer_count[uid] = 0
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
    if uid not in customer_count: customer_count[uid] = 0
    msg_count = customer_count[uid]
    
    if event.message.photo or (event.message.document and event.message.document.mime_type and 'image' in event.message.document.mime_type):
        if get_setting('block_photo_enabled', True):
            asyncio.create_task(block_user_and_delete_photos(event, client, uid))
        else:
            asyncio.create_task(handle_payment_screenshot(event, client, uid))
        return
    
    if not message_text.strip(): return
    msg_lower = message_text.lower().strip()
    
    current_time = time.time()
    last_time = _user_last_msg_time.get(uid, 0)
    time_diff = current_time - last_time
    _user_last_msg_time[uid] = current_time
    
    if time_diff < 5 and msg_count > 0:
        try:
            input_chat = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=input_chat, max_id=event.message.id))
        except: pass
        customer_count[uid] = msg_count + 1
        return
    
    wait_time = int(get_setting('wait_time', 300))
    if wait_time > 0:
        try:
            input_chat = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=input_chat, max_id=event.message.id))
        except: pass
        await asyncio.sleep(wait_time)
    
    if get_setting('typing_enabled', True):
        typing_duration = int(get_setting('typing_duration', 240))
        if typing_duration > 0:
            try:
                async with client.action(chat_id, 'typing'):
                    await asyncio.sleep(min(typing_duration, 300))
            except: pass
    
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
    except: pass
    
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
    
    defaults = get_setting('default_replies', ['Ready baby! Pay karo! 🔥', 'Main ready hoon! 😘'])
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
        except: pass
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
        await event.respond("✅ Payment screenshot received!")
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
                if account_stop_flags.get(acc_id, False) or not account_spam_active.get(acc_id, True): break
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
        for acc in active_accounts: stop_spam(acc['id'])

def start_spam(acc_id=None):
    targets = [a for a in active_accounts if a['id'] == acc_id] if acc_id else active_accounts
    for acc in targets:
        stats = account_stats.get(acc['id'], {})
        if not stats.get('spam_running', False):
            account_spam_active[acc['id']] = True
            account_stop_flags[acc['id']] = False
            task = asyncio.create_task(spam_account(acc))
            account_spam_tasks[acc['id']] = task

# ========== BOT UI ==========
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
        [InlineKeyboardButton(f"🔐 Hardening 🛡️", callback_data="m_harden")],
        [InlineKeyboardButton(f"📡 Channel Backup 🔄", callback_data="m_channel")],
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in admins:
        await update.message.reply_text("⛔ Unauthorized!")
        return
    await update.message.reply_text(
        "🔥 **কন্ট্রোল প্যানেল** 🔥\n\nনিচ থেকে অপশন সিলেক্ট করুন:",
        parse_mode='Markdown', reply_markup=main_keyboard()
    )

# ========== CALLBACK HANDLER ==========
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
        await query.edit_message_text(
            "🔥 **কন্ট্রোল প্যানেল** 🔥\n\nনিচ থেকে অপশন সিলেক্ট করুন:",
            parse_mode='Markdown', reply_markup=main_keyboard()
        )
    
    # ===== ★★ NEW: CHANNEL BACKUP SECTION ★★ =====
    elif data == "m_channel":
        ch_data = load_channel_backup()
        main_chs = ch_data.get('main_channels', [])
        bk_chs = ch_data.get('backup_channels', [])
        active_ch = ch_data.get('active_channel', None)
        
        txt = f"📡 **চ্যানেল ব্যাকআপ সিস্টেম** 📡\n\n"
        txt += f"═══════════════════════\n"
        txt += f"মূল চ্যানেল: {len(main_chs)}টি\n"
        txt += f"ব্যাকআপ চ্যানেল: {len(bk_chs)}টি\n"
        txt += f"একটিভ: {active_ch.get('title','❌ None') if active_ch else '❌ None'}\n"
        txt += f"═══════════════════════\n\n"
        txt += "যখন মূল চ্যানেল থেকে কিক/রেস্ট্রিক্ট করবে,\n"
        txt += "অটোমেটিক ব্যাকআপ চ্যানেলে জয়েন হবে\n"
        txt += "এবং সেখানে স্প্যামিং শুরু করবে!\n"
        txt += "তোমার কাস্টমার কখনো হারাবে না! 🔥"
        
        kb = [
            [InlineKeyboardButton("➕ মূল চ্যানেল যোগ করো", callback_data="ch_add_main")],
            [InlineKeyboardButton("➕ ব্যাকআপ চ্যানেল যোগ করো", callback_data="ch_add_backup")],
            [InlineKeyboardButton("📋 লিস্ট দেখো", callback_data="ch_list")],
            [InlineKeyboardButton("🗑️ চ্যানেল রিমুভ", callback_data="ch_remove")],
            [InlineKeyboardButton(f"🔄 চেক {'🟢 চালু' if get_setting('channel_backup_enabled', True) else '🔴 বন্ধ'}", callback_data="ch_toggle")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ch_add_main":
        context.user_data['await'] = 'ch_add_main'
        await query.edit_message_text(
            "📡 **মূল চ্যানেলের আইডি বা ইউজারনেম দিন:**\n\n"
            "যেমন: `@yourchannel` অথবা `-1001234567890`\n\n"
            "⚠️ নোট: অ্যাকাউন্ট অবশ্যই চ্যানেলের মেম্বার হতে হবে!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
        )

    elif data == "ch_add_backup":
        context.user_data['await'] = 'ch_add_backup'
        await query.edit_message_text(
            "📡 **ব্যাকআপ চ্যানেলের আইডি বা ইউজারনেম দিন:**\n\n"
            "যেমন: `@backupchannel` অথবা `-1001234567890`\n\n"
            "যখন মূল চ্যানেল থেকে কিক খাবে, অটো এই চ্যানেলে জয়েন হবে!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
        )

    elif data == "ch_list":
        ch_data = load_channel_backup()
        txt = "📋 **চ্যানেল লিস্ট:**\n\n"
        
        txt += "═══ **মূল চ্যানেল:** ═══\n"
        if ch_data['main_channels']:
            for i, ch in enumerate(ch_data['main_channels'], 1):
                txt += f"{i}. {ch.get('title','?')} (`{ch.get('id','?')}`)\n"
        else:
            txt += "❌ কোনো মূল চ্যানেল নেই\n"
        
        txt += "\n═══ **ব্যাকআপ চ্যানেল:** ═══\n"
        if ch_data['backup_channels']:
            for i, ch in enumerate(ch_data['backup_channels'], 1):
                txt += f"{i}. {ch.get('title','?')} (`{ch.get('id','?')}`)\n"
        else:
            txt += "❌ কোনো ব্যাকআপ চ্যানেল নেই\n"
        
        txt += f"\n**একটিভ চ্যানেল:** {ch_data['active_channel'].get('title','❌ None') if ch_data['active_channel'] else '❌ None'}"
        
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif data == "ch_remove":
        ch_data = load_channel_backup()
        all_chs = ch_data['main_channels'] + ch_data['backup_channels']
        
        if not all_chs:
            await query.edit_message_text("❌ কোনো চ্যানেল নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))
            return
        
        kb = []
        for ch in all_chs:
            label = f"🗑️ {ch.get('title','?')[:20]}"
            kb.append([InlineKeyboardButton(label, callback_data=f"chrm_{ch['id']}_{ch.get('type','main')}")])
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")])
        
        await query.edit_message_text("🗑️ **কোন চ্যানেল রিমুভ করবেন?**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("chrm_"):
        parts = data.split('_')
        ch_id = parts[1]
        ch_type = parts[2]
        
        data_ch = load_channel_backup()
        if ch_type == 'main':
            data_ch['main_channels'] = [ch for ch in data_ch['main_channels'] if str(ch['id']) != ch_id]
        else:
            data_ch['backup_channels'] = [ch for ch in data_ch['backup_channels'] if str(ch['id']) != ch_id]
        
        if data_ch['active_channel'] and str(data_ch['active_channel']['id']) == ch_id:
            data_ch['active_channel'] = None
        
        save_channel_backup(data_ch)
        
        await query.edit_message_text("✅ চ্যানেল রিমুভ হয়েছে!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif data == "ch_toggle":
        cur = get_setting('channel_backup_enabled', True)
        set_setting('channel_backup_enabled', not cur)
        status = "🟢 চালু" if not cur else "🔴 বন্ধ"
        await query.edit_message_text(f"✅ চ্যানেল ব্যাকআপ {status} হয়েছে!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

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
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_start":
        auto_reply_enabled = True
        await query.edit_message_text("✅ **অটো রিপ্লাই চালু!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    elif data == "ar_stop":
        auto_reply_enabled = False
        await query.edit_message_text("⏹️ **অটো রিপ্লাই বন্ধ!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))
    
    elif data == "ar_welcome":
        enabled = get_setting('welcome_enabled', True)
        status = "🟢 চালু" if enabled else "🔴 বন্ধ"
        has_img = "✅ আছে" if WELCOME_IMAGE_FILE.exists() else "❌ নেই"
        txt = f"👋 **ওয়েলকাম মেসেজ**\nস্ট্যাটাস: {status}\nছবি: {has_img}"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} অন/অফ", callback_data="ar_welcome_tog")],
            [InlineKeyboardButton("✏️ টেক্সট ১", callback_data="ar_welcome_edit")],
            [InlineKeyboardButton("✏️ টেক্সট ২", callback_data="ar_welcome_edit2")],
            [InlineKeyboardButton("📷 ইমেজ", callback_data="ar_welcome_img")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_welcome_tog":
        cur = get_setting('welcome_enabled', True)
        set_setting('welcome_enabled', not cur)
        await handle_callback(update, context)

    elif data == "ar_welcome_edit":
        context.user_data['await'] = 'welcome_text'
        await query.edit_message_text("✏️ নতুন টেক্সট ১ লিখুন:", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))

    elif data == "ar_welcome_edit2":
        context.user_data['await'] = 'welcome_text_2'
        await query.edit_message_text("✏️ নতুন টেক্সট ২ লিখুন:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))

    elif data == "ar_welcome_img":
        context.user_data['await'] = 'welcome_image'
        await query.edit_message_text("📷 ইমেজ পাঠান:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))

    elif data == "ar_welcome_img_del":
        if WELCOME_IMAGE_FILE.exists():
            WELCOME_IMAGE_FILE.unlink()
            await query.edit_message_text("✅ ইমেজ ডিলিট!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
        else:
            await query.edit_message_text("❌ কোনো ইমেজ নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))

    elif data == "ar_blockphoto":
        enabled = get_setting('block_photo_enabled', True)
        txt = f"🚫 Block Photo: {'🟢 ON' if enabled else '🔴 OFF'}"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Toggle", callback_data="ar_blockphoto_tog")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_blockphoto_tog":
        cur = get_setting('block_photo_enabled', True)
        set_setting('block_photo_enabled', not cur)
        await handle_callback(update, context)

    elif data == "ar_typing":
        enabled = get_setting('typing_enabled', True)
        duration = int(get_setting('typing_duration', 240))
        txt = f"⌨️ Typing: {'🟢 ON' if enabled else '🔴 OFF'} | {duration}s"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Toggle", callback_data="ar_typing_tog")],
            [InlineKeyboardButton("⏱️ Set Time", callback_data="ar_typing_time")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_typing_tog":
        cur = get_setting('typing_enabled', True)
        set_setting('typing_enabled', not cur)
        await handle_callback(update, context)

    elif data == "ar_typing_time":
        context.user_data['await'] = 'typing_time'
        await query.edit_message_text(f"⏱️ Time (0-300s):\nCurrent: {get_setting('typing_duration', 240)}s",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_typing")]]))

    elif data == "ar_waittime":
        current = int(get_setting('wait_time', 300))
        txt = f"⏱️ Wait: {current}s ({current//60}মি)"
        kb = [
            [InlineKeyboardButton("0s", callback_data="wt_0"), InlineKeyboardButton("60s", callback_data="wt_60")],
            [InlineKeyboardButton("120s", callback_data="wt_120"), InlineKeyboardButton("300s", callback_data="wt_300")],
            [InlineKeyboardButton("Custom", callback_data="wt_custom")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("wt_"):
        val = data.split("_")[1]
        if val == "custom":
            context.user_data['await'] = 'wait_time'
            await query.edit_message_text(f"Enter seconds (0-600):\nCurrent: {get_setting('wait_time', 300)}s",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))
        else:
            set_setting('wait_time', int(val))
            await query.edit_message_text(f"✅ {val}s!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))

    elif data == "ar_ignore":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "🚫 Ignore:\nএক লাইনে একটি\n\n"
        if cur: txt += f"Current:\n`{cur}`"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    elif data == "ar_replies":
        replies = load_json(REPLIES_FILE, [])
        txt = "📝 Custom Replies:\n"
        if replies:
            for r in replies[-10:]:
                txt += f"`{r['keyword'][:12]}` → {r['reply'][:20]}...\n"
        else: txt += "কিছু নেই। /add_reply ব্যবহার করুন।\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    # ===== GROUP SPAM =====
    elif data == "m_gs":
        run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        st = "🟢 ACTIVE" if group_spam_enabled else "🔴 STOPPED"
        sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        txt = f"📨 **GROUP SPAM**\n{st} | চলছে: {run}/{len(active_accounts)} | পাঠানো: {sent}"
        kb = [
            [InlineKeyboardButton("▶️ START ALL", callback_data="gs_start"), InlineKeyboardButton("⏹️ STOP ALL", callback_data="gs_stop")],
            [InlineKeyboardButton("⚡ Speed", callback_data="gs_spd")],
            [InlineKeyboardButton("📝 Messages", callback_data="gs_msg")],
            [InlineKeyboardButton("📊 Stats", callback_data="gs_st")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "gs_start":
        group_spam_enabled = True
        start_spam()
        await query.edit_message_text("✅ স্প্যাম চালু!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

    elif data == "gs_stop":
        group_spam_enabled = False
        stop_spam()
        await query.edit_message_text("⏹️ স্প্যাম বন্ধ!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

    elif data == "gs_spd":
        cur = get_setting('spam_speed', 'medium')
        kb = [
            [InlineKeyboardButton(f"{'✅' if cur=='super_fast' else ''} Super Fast", callback_data="gs_sf")],
            [InlineKeyboardButton(f"{'✅' if cur=='fast' else ''} Fast", callback_data="gs_fa")],
            [InlineKeyboardButton(f"{'✅' if cur=='medium' else ''} Medium", callback_data="gs_me")],
            [InlineKeyboardButton(f"{'✅' if cur=='slow' else ''} Slow", callback_data="gs_sl")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]
        ]
        await query.edit_message_text(f"⚡ Speed: {cur}", reply_markup=InlineKeyboardMarkup(kb))

    elif data in ["gs_sf", "gs_fa", "gs_me", "gs_sl"]:
        m = {'gs_sf': 'super_fast', 'gs_fa': 'fast', 'gs_me': 'medium', 'gs_sl': 'slow'}
        set_setting('spam_speed', m[data])
        await query.edit_message_text(f"✅ Speed: {m[data]}!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

    elif data == "gs_msg":
        msgs = load_spam_messages()
        txt = "📝 **Messages:**\n"
        if msgs:
            for m in msgs[:5]:
                txt += f"• {m['text'][:30]}...\n"
        else:
            txt += "Default message ব্যবহার হচ্ছে।\n"
        kb = [
            [InlineKeyboardButton("➕ Add", callback_data="gs_msg_add")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "gs_msg_add":
        context.user_data['await'] = 'gs_msg_add'
        await query.edit_message_text("✏️ স্প্যাম মেসেজ পাঠান:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))

    elif data == "gs_st":
        txt = "📊 **Stats:**\n"
        for a in active_accounts:
            s = account_stats.get(a['id'], {}).get('spam_sent', 0)
            r = "▶️" if account_stats.get(a['id'], {}).get('spam_running', False) else "⏹️"
            txt += f"{r} {a.get('name','?')[:10]}: {s}\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

    # ===== ACCOUNTS =====
    elif data == "m_acc":
        ma = len(get_main_accounts())
        ba = len(get_backup_accounts())
        act = len(active_accounts)
        txt = f"👥 **Account**\nMain: {ma} | Backup: {ba} | Active: {act}"
        kb = [
            [InlineKeyboardButton("📱 Phone + OTP", callback_data="ac_ph")],
            [InlineKeyboardButton("🔑 Session String", callback_data="ac_ss")],
            [InlineKeyboardButton("🗑️ Delete", callback_data="ac_del")],
            [InlineKeyboardButton("💾 Backup Mgmt", callback_data="ac_bk")],
            [InlineKeyboardButton("📋 List All", callback_data="ac_ls")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        # ===== CALLBACK HANDLER (Continued) =====
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("📱 **ফোন নম্বর দিন:**\n\nফরম্যাট: `+8801XXXXXXXXX`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
    
    elif data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("🔑 **Session String পেস্ট করুন:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
    
    elif data == "ac_del":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ কোনো অ্যাকাউন্ট নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}", callback_data=f"acd_{a['id']}")] for a in all_a]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")])
        await query.edit_message_text("🗑️ **ডিলিট করার জন্য অ্যাকাউন্ট সিলেক্ট করুন:**",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("acd_"):
        aid = data.split('_', 1)[1]
        a = find_account(aid)
        name = a.get('name', '?') if a else '?'
        
        # Stop all tasks
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
        await query.edit_message_text(f"✅ **{name}** permanently deleted!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
    
    elif data == "ac_bk":
        ba = get_backup_accounts()
        txt = f"💾 **ব্যাকআপ অ্যাকাউন্ট**\nমোট: {len(ba)}\n\n"
        for i, a in enumerate(ba, 1):
            txt += f"{i}. {a.get('name', '?')} ({a.get('phone', 'N/A')})\n"
        
        kb = [
            [InlineKeyboardButton("➕ ব্যাকআপ যোগ করো", callback_data="ac_bk_add")],
            [InlineKeyboardButton("🗑️ ব্যাকআপ রিমুভ", callback_data="ac_bk_del")],
            [InlineKeyboardButton("➡️ ব্যাকআপ → রানিং (1 Click)", callback_data="ac_bk_to_run")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_bk_add":
        context.user_data['await'] = 'ac_bk_ss'
        await query.edit_message_text("🔑 **ব্যাকআপ Session String পেস্ট করুন:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
    
    elif data == "ac_bk_del":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ কোনো ব্যাকআপ নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")])
        await query.edit_message_text("🗑️ **রিমুভ করবেন?**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "ac_bk_to_run":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ কোনো ব্যাকআপ নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"➡️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"b2r_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")])
        await query.edit_message_text("**কোন ব্যাকআপ রানিং করবেন?**\n\nঅটো রিপ্লাই + স্প্যাম শুরু হবে!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
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
        await query.edit_message_text(msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
    
    elif data.startswith("acbkd_"):
        bid = data.split('_')[1]
        remove_account_data(bid)
        await query.edit_message_text("✅ ব্যাকআপ রিমুভ হয়েছে!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
    
    elif data == "ac_ls":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ কোনো অ্যাকাউন্ট নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            return
        txt = f"📋 **সব অ্যাকাউন্ট** ({len(all_a)})\n\n"
        for i, a in enumerate(all_a, 1):
            n = a.get('name', '?')
            p = a.get('phone', 'N/A')
            tp = "MAIN" if not a.get('is_backup') else "BKP"
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
        txt = f"⚙️ **Settings**\n🚫 Block Photo: {bp}\n🐢 Flood Slow: {fs}\n🔔 Logout Alert: {ln}\n📷 QR Code: {has_qr}"
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
        txt = f"💳 **Payment**\n📱 UPI: {upi or '❌'}\n💳 PayTm: {paytm or '❌'}"
        kb = [
            [InlineKeyboardButton("✏️ Set UPI", callback_data="st_upi")],
            [InlineKeyboardButton("✏️ Set PayTm", callback_data="st_paytm")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_upi":
        context.user_data['await'] = 'upi'
        await query.edit_message_text("✏️ **UPI ID দিন:**\n`user@upi`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))

    elif data == "st_paytm":
        context.user_data['await'] = 'paytm'
        await query.edit_message_text("✏️ **PayTm নাম্বার দিন:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))

    elif data == "st_qr":
        context.user_data['await'] = 'qr_code'
        await query.edit_message_text("📷 **QR Code ইমেজ পাঠান:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]]))

    # ===== STATS =====
    elif data == "m_stat":
        ar = "🟢" if auto_reply_enabled else "🔴"
        gs = "🟢" if group_spam_enabled else "🔴"
        ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
        ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        spm_act = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        txt = f"📊 **স্ট্যাটাস**\n\n🤖 Auto Reply: {ar}\n📨 Spam: {gs}\n👤 Active: {len(active_accounts)}\n📨 Spamming: {spm_act}\n💬 Auto Sent: {ttl_auto}\n📬 Spam Sent: {ttl_spam}\n👥 Customers: {len(customer_count)}"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="m_stat"), InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]))

    # ===== ADMIN =====
    elif data == "m_adm":
        txt = "🛡️ **Admin Panel**"
        kb = [
            [InlineKeyboardButton("📢 Broadcast", callback_data="ad_bc")],
            [InlineKeyboardButton("📄 View Logs", callback_data="ad_lg")],
            [InlineKeyboardButton("🔄 Restart Bot", callback_data="ad_rt")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ad_bc":
        context.user_data['await'] = 'broadcast'
        await query.edit_message_text("📢 **ব্রডকাস্ট মেসেজ লিখুন:**\n\nসব কাস্টমারকে পাঠানো হবে!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))

    elif data == "ad_lg":
        log_path = Path(__file__).parent / "bot.log"
        if log_path.exists():
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-20:]
            txt = "📄 **Last 20 Logs**\n\n" + "".join(lines[-500:])
        else:
            txt = "📄 No log file found."
        await query.edit_message_text(txt[:4000],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))

    elif data == "ad_rt":
        await query.edit_message_text("🔄 **Restarting...**")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # ===== HARDENING =====
    elif data == "m_harden":
        txt = "🔐 **Account Hardening** 🔐\n\n"
        txt += "═══════════════════════\n"
        txt += "✅ নাম, বায়ো চেঞ্জ\n"
        txt += "✅ অন্যান্য ডিভাইস লগআউট\n"
        txt += "✅ ২FA সেট (জিমেইল ছাড়া)\n"
        txt += "✅ সব চ্যাট/গ্রুপ/চ্যানেল লিভ\n"
        txt += "✅ গ্রুপ অটো জয়েন\n"
        txt += "✅ ১ দিন পর অটো ক্লিয়ার\n"
        txt += "═══════════════════════\n"
        txt += "\n❗ **সবকিছু ১ ক্লিকেই!**"
        
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
        if not active_accounts:
            await query.edit_message_text("❌ কোনো একটিভ অ্যাকাউন্ট নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
            return
        
        kb = [[InlineKeyboardButton(f"🛡️ {a.get('name','?')[:15]} 📱{a.get('phone','N/A')[-4:]}", callback_data=f"hdn_{a['id']}")] for a in active_accounts]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")])
        await query.edit_message_text("**কোন অ্যাকাউন্ট হার্ডেন করবেন?**\n\n⚠️ ১ ক্লিকেই সব পরিবর্তন!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("hdn_"):
        aid = data.split('_')[1]
        acc = find_account(aid)
        if not acc:
            await query.edit_message_text("❌ অ্যাকাউন্ট খুঁজে পাইনি!")
            return
        
        await query.edit_message_text(f"⏳ **হার্ডেনিং শুরু...**\nঅ্যাকাউন্ট: {acc.get('name','?')}\nঅপেক্ষা করুন...", parse_mode='Markdown')
        result = await harden_account_one_click(acc)
        await query.edit_message_text(f"**রেজাল্ট:**\n\n{result}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    elif data == "harden_name":
        context.user_data['await'] = 'harden_name'
        cur = get_setting('new_account_name', '')
        await query.edit_message_text(f"✏️ **নতুন নাম লিখুন:**\nবর্তমান: {cur or 'সেট নেই'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    elif data == "harden_bio":
        context.user_data['await'] = 'harden_bio'
        cur = get_setting('new_account_bio', '')
        await query.edit_message_text(f"✏️ **নতুন বায়ো লিখুন:**\nবর্তমান: {cur or 'সেট নেই'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    elif data == "harden_devices":
        if not active_accounts:
            await query.edit_message_text("❌ কোনো একটিভ অ্যাকাউন্ট নেই!",
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_devices"), InlineKeyboardButton("🔄 Refresh", callback_data=f"hdv_{aid}")]]))
    
    elif data == "harden_links":
        links = load_autojoin_links()
        txt = "🔑 **Auto Join Links**\n\nযে সব লিংকে অটো জয়েন হবে:\n\n"
        if links:
            for i, link in enumerate(links, 1):
                txt += f"{i}. {link[:40]}...\n"
        else:
            txt += "কোনো লিংক নেই।\n"
        txt += "\n/new_join_link কমান্ড ব্যবহার করুন।"
        kb = [
            [InlineKeyboardButton("➕ Add Link", callback_data="harden_link_add")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "harden_link_add":
        context.user_data['await'] = 'harden_link_add'
        await query.edit_message_text("🔗 **গ্রুপ লিংক পাঠান:**\nযেমন: https://t.me/yourgroup",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))
    
    elif data == "harden_history":
        txt = "📋 **Hardening History**\n\n"
        has_data = False
        for acc in active_accounts:
            tasks = load_harden_tasks().get(acc['id'], [])
            if tasks:
                has_data = True
                txt += f"👤 {acc.get('name','?')}\n"
                for t in tasks[-5:]:
                    status = "✅" if t['status'] == 'completed' else "⏳"
                    txt += f"  {status} {t['type']} - {t['created_at'][:16]}\n"
                txt += "\n"
        if not has_data:
            txt += "কোনো ডাটা নেই। 1 Click Hardening ব্যবহার করুন।"
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    else:
        await query.edit_message_text(f"⚠️ Unknown: {data}",
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

    # Welcome texts
    if await_state == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ ওয়েলকাম টেক্সট ১ আপডেট!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    elif await_state == 'welcome_text_2':
        set_setting('welcome_message_2', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ ওয়েলকাম টেক্সট ২ আপডেট!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    # Wait time
    elif await_state == 'wait_time':
        try:
            val = max(0, min(600, int(text)))
            set_setting('wait_time', val)
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Wait time: {val}s",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))
        except:
            await update.message.reply_text("❌ সংখ্যা দিন (0-600)!")
    
    # Typing time
    elif await_state == 'typing_time':
        try:
            val = int(text)
            if 0 <= val <= 300:
                set_setting('typing_duration', val)
                context.user_data.pop('await', None)
                await update.message.reply_text(f"✅ Typing: {val}s",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_typing")]]))
            else:
                await update.message.reply_text("❌ 0-300 এর মধ্যে দিন!")
        except:
            await update.message.reply_text("❌ সংখ্যা দিন!")
    
    # Ignore messages
    elif await_state == 'ignore':
        set_setting('ignored_messages', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ ইগনোর মেসেজ আপডেট!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))
    
    # UPI / Paytm
    elif await_state == 'upi':
        set_setting('upi_id', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ UPI সেট!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))
    
    elif await_state == 'paytm':
        set_setting('paytm_num', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ PayTm সেট!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))
    
    # Broadcast
    elif await_state == 'broadcast':
        context.user_data.pop('await', None)
        msg = f"📢 **BROADCAST**\n\n{text}"
        sent = 0
        for uid in customer_count:
            try:
                await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode='Markdown')
                sent += 1
                await asyncio.sleep(0.1)
            except: pass
        await update.message.reply_text(f"✅ {sent} কাস্টমারকে পাঠানো হয়েছে!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))
    
    # Spam message add
    elif await_state == 'gs_msg_add':
        add_spam_message(text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ স্প্যাম মেসেজ যোগ!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))
    
    # Phone number entry
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
            await update.message.reply_text(f"✅ OTP পাঠানো হয়েছে {text}\n\nOTP দিন:")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:100]}")
            context.user_data.pop('await', None)
    
    # OTP entry
    elif await_state == 'ac_otp':
        otp = text.replace(' ', '')
        client = context.user_data.get('ac_client')
        phone = context.user_data.get('phone', '')
        pch = context.user_data.get('ac_phone_code_hash', '')
        
        if not client:
            await update.message.reply_text("❌ Session expired! আবার শুরু করুন।")
            context.user_data.pop('await', None)
            return
        
        try:
            await client.sign_in(phone=phone, code=otp, phone_code_hash=pch)
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
            
            await update.message.reply_text(f"✅ অ্যাকাউন্ট যোগ!\n👤 {name}\n📱 {phone}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            
            # Auto activate
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    register_ar(n_client, acc)
                    await update.message.reply_text("✅ অটো-অ্যাক্টিভেটেড!")
            except: pass
            
        except SessionPasswordNeededError:
            context.user_data['await'] = 'ac_2fa'
            await update.message.reply_text("🔐 ২FA পাসওয়ার্ড দিন:")
        except PhoneCodeInvalidError:
            await update.message.reply_text("❌ ভুল OTP! আবার দিন:")
        except PhoneCodeExpiredError:
            await update.message.reply_text("❌ OTP expired. আবার শুরু করুন /start")
            context.user_data.pop('await', None)
    
    # 2FA password
    elif await_state == 'ac_2fa':
        client = context.user_data.get('ac_client')
        phone = context.user_data.get('phone', '')
        
        if not client:
            await update.message.reply_text("❌ Session expired!")
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
            
            await update.message.reply_text(f"✅ অ্যাকাউন্ট যোগ!\n👤 {name}\n📱 {phone}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            
            # Auto activate
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    register_ar(n_client, acc)
                    await update.message.reply_text("✅ অটো-অ্যাক্টিভেটেড!")
            except: pass
            
        except Exception as e:
            await update.message.reply_text(f"❌ ২FA failed: {str(e)[:100]}")
            context.user_data.pop('await', None)
    
    # Session string
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
                await update.message.reply_text(f"✅ অ্যাকাউন্ট যোগ!\n👤 {name}\n📱 {phone}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
                
                # Auto activate
                try:
                    n_client = await start_account(acc)
                    if n_client:
                        active_accounts.append(acc)
                        account_clients[acc['id']] = n_client
                        account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                        account_stop_flags[acc['id']] = False
                        register_ar(n_client, acc)
                        await update.message.reply_text("✅ অটো-অ্যাক্টিভেটেড!")
                except: pass
            else:
                await update.message.reply_text("❌ ইউজার ইনফো পাওয়া যায়নি!")
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid session: {str(e)[:100]}")
        finally:
            context.user_data.pop('await', None)
    
    # Backup session string
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
                await update.message.reply_text(f"✅ ব্যাকআপ যোগ!\n👤 {name}\n📱 {phone}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
            else:
                await update.message.reply_text("❌ Invalid session!")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
            context.user_data.pop('await', None)
    
    # ★ NEW: Channel backup handlers
    elif await_state == 'ch_add_main':
        channel_identifier = text.strip()
        try:
            # প্রথম একটিভ অ্যাকাউন্ট ব্যবহার করে চ্যানেল ভেরিফাই
            if active_accounts and active_accounts[0]['id'] in account_clients:
                client = account_clients[active_accounts[0]['id']]
                
                # আইডি বা ইউজারনেম পার্স
                if channel_identifier.startswith('-100'):
                    entity = await client.get_entity(int(channel_identifier))
                elif channel_identifier.startswith('@'):
                    entity = await client.get_entity(channel_identifier)
                else:
                    # লিংক থেকে ইউজারনেম বের করি
                    if 't.me/' in channel_identifier:
                        username = channel_identifier.split('/')[-1].split('?')[0]
                        entity = await client.get_entity(username)
                    else:
                        entity = await client.get_entity(channel_identifier)
                
                if hasattr(entity, 'title'):
                    channel_info = {
                        'id': entity.id,
                        'title': entity.title,
                        'username': getattr(entity, 'username', ''),
                        'type': 'main',
                        'added_at': datetime.now().isoformat()
                    }
                    if add_main_channel(channel_info):
                        await update.message.reply_text(f"✅ মূল চ্যানেল যোগ!\n📛 {entity.title}\n🆔 {entity.id}",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))
                    else:
                        await update.message.reply_text("❌ ইতিমধ্যে যোগ করা আছে!",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))
                else:
                    await update.message.reply_text("❌ এটি একটি চ্যানেল নয়!")
            else:
                await update.message.reply_text("❌ কোনো একটিভ অ্যাকাউন্ট নেই!")
        except Exception as e:
            await update.message.reply_text(f"❌ চ্যানেল খুঁজে পাইনি: {str(e)[:50]}")
        
        context.user_data.pop('await', None)
    
    elif await_state == 'ch_add_backup':
        channel_identifier = text.strip()
        try:
            if active_accounts and active_accounts[0]['id'] in account_clients:
                client = account_clients[active_accounts[0]['id']]
                
                if channel_identifier.startswith('-100'):
                    entity = await client.get_entity(int(channel_identifier))
                elif channel_identifier.startswith('@'):
                    entity = await client.get_entity(channel_identifier)
                else:
                    if 't.me/' in channel_identifier:
                        username = channel_identifier.split('/')[-1].split('?')[0]
                        entity = await client.get_entity(username)
                    else:
                        entity = await client.get_entity(channel_identifier)
                
                if hasattr(entity, 'title'):
                    channel_info = {
                        'id': entity.id,
                        'title': entity.title,
                        'username': getattr(entity, 'username', ''),
                        'type': 'backup',
                        'added_at': datetime.now().isoformat()
                    }
                    if add_backup_channel(channel_info):
                        await update.message.reply_text(f"✅ ব্যাকআপ চ্যানেল যোগ!\n📛 {entity.title}\n🆔 {entity.id}",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))
                    else:
                        await update.message.reply_text("❌ ইতিমধ্যে যোগ করা আছে!",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))
                else:
                    await update.message.reply_text("❌ এটি একটি চ্যানেল নয়!")
            else:
                await update.message.reply_text("❌ কোনো একটিভ অ্যাকাউন্ট নেই!")
        except Exception as e:
            await update.message.reply_text(f"❌ চ্যানেল খুঁজে পাইনি: {str(e)[:50]}")
        
        context.user_data.pop('await', None)
    
    # Hardening handlers
    elif await_state == 'harden_name':
        set_setting('new_account_name', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ নাম সেভ!\n1 Click Hardening করলে সেট হবে।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    elif await_state == 'harden_bio':
        set_setting('new_account_bio', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ বায়ো সেভ!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
    
    elif await_state == 'harden_link_add':
        link = text.strip()
        if 't.me/' in link or 'telegram.me/' in link:
            add_autojoin_link(link)
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ লিংক যোগ! পরবর্তী Hardening এ অটো জয়েন হবে।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))
        else:
            await update.message.reply_text("❌ ভ্যালিড টেলিগ্রাম লিংক দিন!")
    
    else:
        await update.message.reply_text(f"⚠️ Unknown: {await_state}")
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
            await update.message.reply_text("✅ ওয়েলকাম ইমেজ আপডেট!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:50]}")

    elif await_state == 'qr_code':
        try:
            photo = await update.message.photo[-1].get_file()
            await photo.download_to_drive(str(QR_CODE_FILE))
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ QR Code সেভ!",
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
        await update.message.reply_text("Usage: /add_reply keyword reply\nExample: /add_reply price Check price!")
        return
    keyword = args[0].lower()
    reply = ' '.join(args[1:])
    replies = load_json(REPLIES_FILE, [])
    for r in replies:
        if r['keyword'] == keyword:
            r['reply'] = reply
            save_json(REPLIES_FILE, replies)
            await update.message.reply_text(f"✅ `{keyword}` আপডেট!", parse_mode='Markdown')
            return
    replies.append({'keyword': keyword, 'reply': reply, 'type': 'contains', 'added_at': datetime.now().isoformat()})
    save_json(REPLIES_FILE, replies)
    await update.message.reply_text(f"✅ `{keyword}` যোগ!", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
    ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
    txt = f"📊 **STATUS**\n\n👤 Active: {len(active_accounts)}\n💬 Auto Sent: {ttl_auto}\n📬 Spam Sent: {ttl_spam}\n👥 Customers: {len(customer_count)}"
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
        else: txt += "কোনো লিংক নেই।"
        await update.message.reply_text(txt, parse_mode='Markdown')
        return
    link = args[0]
    if add_autojoin_link(link):
        await update.message.reply_text(f"✅ লিংক যোগ!\n{link}")
    else:
        await update.message.reply_text("❌ Already exists or invalid!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    txt = """🔥 **HELP** 🔥

**Commands:**
/start - Control Panel
/status - Quick Status
/help - এই মেসেজ
/add_reply kw text - কাস্টম রিপ্লাই
/new_join_link link - গ্রুপ জয়েন লিংক

**★★★ MAIN FEATURES ★★★**
✅ Auto Reply (Wait + Typing)
✅ Multiple Message Detection
✅ Group Spam (Speed Control)
✅ QR Code Payment
✅ Block Photo
✅ Backup → Running (1 Click)
✅ ★ Restricted Auto Logout (2 sec)
✅ ★ Account Hardening (1 Click)
✅ ★ Channel Backup System
  - Main + Backup Channel সেট
  - Kick/Block হলে Auto Backup Join
  - Backup Channel এ Auto Spam
  - Customer কখনো হারাবে না! 🔥
"""
    await update.message.reply_text(txt, parse_mode='Markdown')


# ====== DEVICE LOGIN INFO ======
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
            is_current = "⭐ CURRENT" if auth.hash == current_hash else ""
            
            now = time.time()
            created_ts = getattr(auth, 'date_created', 0) or 0
            remaining = max(0, 86400 - (now - created_ts))
            
            if remaining > 0 and not is_current:
                h, m = int(remaining // 3600), int((remaining % 3600) // 60)
                can_delete = f"⏳ {h}h {m}m বাকি"
            elif is_current:
                can_delete = "🚫 বর্তমান"
            else:
                can_delete = "✅ এখনই রিমুভ করা যাবে"
            
            info.append(f"{'⭐ ' if is_current else ''}{i+1}. **{app_name}**\n📱 {device_model} ({platform})\n🌍 {country}\n🔑 {can_delete}")
        
        return "\n\n".join(info) if info else "ℹ️ No login info"
    except Exception as e:
        return f"❌ Error: {str(e)[:50]}"


# ====== FLASK ======
@flask_app.route('/')
def index():
    return jsonify({
        'status': 'running',
        'accounts': len(active_accounts),
        'time': datetime.now().isoformat(),
        'restricted_checker': '✅ Active (every 2s)',
        'channel_monitor': '✅ Active (every 30s)'
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

    # ★★★ START BACKGROUND TASKS ★★★
    # 1. Restricted account checker (every 2 seconds)
    asyncio.create_task(check_restricted_accounts_loop())
    logger.info("🔍★ Restricted account checker - every 2 seconds!")
    
    # 2. Channel backup monitor (every 30 seconds)
    asyncio.create_task(monitor_channels_loop())
    logger.info("📡★ Channel backup monitor - every 30 seconds!")
    
    # 3. Periodic status check
    asyncio.create_task(check_account_status_periodically())
    
    # 4. Flask web server
    asyncio.create_task(run_flask())

    bot_ready = True

    # Notify owner
    try:
        await ptb.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔥 **Bot Ready!** 🔥\n\n"
                 f"👤 Accounts: {len(active_accounts)}\n"
                 f"🤖 Auto Reply: {'ON' if auto_reply_enabled else 'OFF'}\n"
                 f"📨 Group Spam: {'ON' if group_spam_enabled else 'OFF'}\n"
                 f"🛡️ Restricted Check: ✅ প্রতি ২ সেকেন্ডে\n"
                 f"📡 Channel Backup: ✅ প্রতি ৩০ সেকেন্ডে\n"
                 f"🔐 Hardening: ✅ Available\n\n"
                 f"⚡ সিস্টেম সম্পূর্ণ প্রস্তুত!",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Owner notify failed: {e}")

    logger.info(f"✅ Bot Ready! {len(active_accounts)} accounts. All systems active.")

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

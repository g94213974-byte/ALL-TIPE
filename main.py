import os, sys, json, asyncio, logging, time, hashlib, hmac, base64, re, secrets, threading, uuid, socket, ssl, random, string, urllib.parse, subprocess, shutil, requests, html, math, ipaddress, traceback
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from typing import Optional, Dict, List, Tuple, Any, Callable, Union
from functools import partial, wraps
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse, urljoin, quote, unquote
from contextlib import contextmanager

# ====== LOGGING ======
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('bot.log', encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ====== TELEGRAM IMPORTS ======
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatMember, Chat, Message, User, InputFile, constants
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackContext
    from telegram.error import TelegramError, Forbidden, BadRequest, RetryAfter, TimedOut, NetworkError
    import telegram
    logger.info(f"PTB version: {telegram.__version__ if hasattr(telegram, '__version__') else 'unknown'}")
    PTB_AVAILABLE = True
except ImportError as e:
    logger.error(f"PTB import error: {e}")
    PTB_AVAILABLE = False

try:
    from telethon import TelegramClient, events, functions, types, errors
    from telethon.tl.types import *
    from telethon.tl.functions.messages import *
    from telethon.tl.functions.channels import *
    from telethon.tl.functions.account import *
    from telethon.tl.functions.contacts import *
    from telethon.tl.functions.users import *
    from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, PhoneNumberBannedError, PhoneNumberOccupiedError, RPCError, AuthKeyUnregisteredError, UserDeactivatedError, UserDeactivatedBanError
    import telethon
    logger.info(f"Telethon version: {telethon.__version__ if hasattr(telethon, '__version__') else 'unknown'}")
    TELETHON_AVAILABLE = True
except ImportError as e:
    logger.error(f"Telethon import error: {e}")
    TELETHON_AVAILABLE = False

try:
    from telethon.sessions import StringSession
    STRING_SESSION_AVAILABLE = True
except ImportError:
    STRING_SESSION_AVAILABLE = False

try:
    from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session as flask_session
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# ====== ENVIRONMENT CONFIG ======
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'default_secret_change_me')
API_HASH = os.environ.get('API_HASH', '')
API_ID = int(os.environ.get('API_ID', '0'))
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
CRYPTO_KEY = hashlib.sha256(os.environ.get('CRYPTO_KEY', 'default_crypto_key').encode()).digest()

ADMIN_IDS = list(map(int, filter(None, os.environ.get('ADMIN_IDS', '').split(','))))
OWNER_ID = int(os.environ.get('OWNER_ID', ADMIN_IDS[0] if ADMIN_IDS else '0'))

USE_PROXY = os.environ.get('USE_PROXY', 'false').lower() == 'true'
PROXY_CONFIG = None
if USE_PROXY:
    PROXY_CONFIG = {
        'proxy_type': os.environ.get('PROXY_TYPE', 'socks5'),
        'addr': os.environ.get('PROXY_ADDR', '127.0.0.1'),
        'port': int(os.environ.get('PROXY_PORT', '9050')),
        'username': os.environ.get('PROXY_USER', '') or None,
        'password': os.environ.get('PROXY_PASS', '') or None
    }

DEFAULT_API_ID = 2040
DEFAULT_API_HASH = 'b18441a1ff7492a7e5c1c1a6b6a7c8d9'

# ====== DATA DIRECTORY ======
USER_DATA_DIR = Path('user_data')
USER_DATA_DIR.mkdir(exist_ok=True)

ACCOUNTS_FILE = USER_DATA_DIR / 'accounts.json'
TASKS_FILE = USER_DATA_DIR / 'tasks.json'
CONFIG_FILE = USER_DATA_DIR / 'config.json'
SETTINGS_FILE = USER_DATA_DIR / 'settings.json'
AUTO_DELETE_FILE = USER_DATA_DIR / 'auto_delete.json'
SPAM_MESSAGES_FILE = USER_DATA_DIR / 'spam_messages.json'
REPLIES_FILE = USER_DATA_DIR / 'replies.json'
CUSTOMERS_FILE = USER_DATA_DIR / 'customers.json'
CHANNEL_BACKUP_FILE = USER_DATA_DIR / 'channel_backup.json'
AUTOJOIN_LINKS_FILE = USER_DATA_DIR / 'autojoin_links.json'
HARDEN_TASKS_FILE = USER_DATA_DIR / 'harden_tasks.json'
QR_CODE_FILE = USER_DATA_DIR / 'qr_code.png'
WELCOME_IMAGE_FILE = USER_DATA_DIR / 'welcome_image.png'

# ====== GLOBAL STATE ======
accounts_lock = asyncio.Lock()
active_accounts = []
account_clients = {}
account_stats = {}
account_stop_flags = {}
account_spam_tasks = {}
account_keepalive_tasks = {}
account_spam_active = {}
auto_reply_enabled = False
group_spam_enabled = False
logout_notification_enabled = True
customer_count = set()
account_id_counter = 0

# ====== JSON HELPERS ======
def load_json(path, default=None):
    try:
        if path and path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Load failed {path}: {e}")
    return default if default is not None else {}

def save_json(path, data):
    try:
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            return True
    except Exception as e:
        logger.error(f"Save failed {path}: {e}")
    return False

# ====== ACCOUNT DATA FUNCTIONS ======
async def get_accounts():
    async with accounts_lock:
        return load_json(ACCOUNTS_FILE, {})

async def save_accounts(data):
    async with accounts_lock:
        return save_json(ACCOUNTS_FILE, data)

def get_all_accounts():
    data = load_json(ACCOUNTS_FILE, {})
    return list(data.values())

def get_main_accounts():
    data = load_json(ACCOUNTS_FILE, {})
    return [a for a in data.values() if not a.get('is_backup')]

def get_backup_accounts():
    data = load_json(ACCOUNTS_FILE, {})
    return [a for a in data.values() if a.get('is_backup')]

def find_account(aid):
    data = load_json(ACCOUNTS_FILE, {})
    for k, v in data.items():
        if v['id'] == aid:
            return v
    return None

def add_account_data(acc):
    data = load_json(ACCOUNTS_FILE, {})
    data[acc['id']] = acc
    return save_json(ACCOUNTS_FILE, data)

def remove_account_data(aid):
    data = load_json(ACCOUNTS_FILE, {})
    if aid in data:
        del data[aid]
        return save_json(ACCOUNTS_FILE, data)
    return False

def gen_acc_id():
    global account_id_counter
    account_id_counter += 1
    return f"ACC_{int(time.time())}_{account_id_counter}"

# ====== SETTINGS ======
def get_setting(key, default=None):
    data = load_json(SETTINGS_FILE, {})
    return data.get(key, default)

def set_setting(key, value):
    data = load_json(SETTINGS_FILE, {})
    data[key] = value
    return save_json(SETTINGS_FILE, data)

# ====== SPAM MESSAGES ======
def load_spam_messages():
    return load_json(SPAM_MESSAGES_FILE, [])

def save_spam_messages(msgs):
    return save_json(SPAM_MESSAGES_FILE, msgs)

def add_spam_message(text):
    msgs = load_spam_messages()
    msgs.append({"text": text, "added_at": datetime.now().isoformat()})
    return save_spam_messages(msgs)

# ====== CUSTOMER TRACKING ======
def load_customers():
    return load_json(CUSTOMERS_FILE, set())

def save_customers(customers):
    return save_json(CUSTOMERS_FILE, list(customers))

def add_customer(uid):
    global customer_count
    customer_count.add(str(uid))
    save_customers(customer_count)

# ====== CHANNEL BACKUP ======
def load_channel_backup():
    return load_json(CHANNEL_BACKUP_FILE, {"main_channels": [], "backup_channels": [], "active_channel": None})

def save_channel_backup(data):
    return save_json(CHANNEL_BACKUP_FILE, data)

# ====== AUTO-JOIN LINKS ======
def load_autojoin_links():
    return load_json(AUTOJOIN_LINKS_FILE, [])

def save_autojoin_links(links):
    return save_json(AUTOJOIN_LINKS_FILE, links)

# ====== HARDEN TASKS ======
def load_harden_tasks():
    return load_json(HARDEN_TASKS_FILE, {})

def save_harden_tasks(data):
    return save_json(HARDEN_TASKS_FILE, data)

# ====== REPLIES ======
def load_replies():
    return load_json(REPLIES_FILE, [])

def save_replies(data):
    return save_json(REPLIES_FILE, data)

# ====== AUTO-DELETE TIMER SYSTEM ======
def load_auto_delete_data():
    return load_json(AUTO_DELETE_FILE, {
        "enabled": False,
        "days": 1,
        "chats": {},
        "deleted_count": 0
    })

def save_auto_delete_data(data):
    return save_json(AUTO_DELETE_FILE, data)

def register_chat_for_auto_delete(phone, chat_id, chat_title=""):
    data = load_auto_delete_data()
    key = f"{phone}:{chat_id}"
    now = datetime.now(timezone.utc).isoformat()
    data["chats"][key] = {
        "phone": phone,
        "chat_id": chat_id,
        "chat_title": chat_title,
        "registered_at": now,
        "last_message_at": now
    }
    save_auto_delete_data(data)
    return True

async def auto_delete_messages_loop(app=None):
    global account_clients, active_accounts
    await asyncio.sleep(60)
    while True:
        try:
            data = load_auto_delete_data()
            if not data.get("enabled", False):
                await asyncio.sleep(1800)
                continue
            days = data.get("days", 1)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            deleted_count = data.get("deleted_count", 0)
            chats_to_remove = []
            for key, info in data["chats"].items():
                phone = info.get("phone")
                chat_id = info.get("chat_id")
                last_msg_str = info.get("last_message_at")
                if not last_msg_str or not phone or not chat_id:
                    continue
                try:
                    last_msg_time = datetime.fromisoformat(last_msg_str)
                    if last_msg_time.tzinfo is None:
                        last_msg_time = last_msg_time.replace(tzinfo=timezone.utc)
                except:
                    continue
                if last_msg_time < cutoff:
                    try:
                        c = None
                        for ac in active_accounts:
                            if ac.get('phone') == phone and ac['id'] in account_clients:
                                c = account_clients[ac['id']]
                                break
                        if c:
                            try:
                                async for msg in c.iter_messages(int(chat_id), limit=100):
                                    if msg and msg.out and msg.date:
                                        msg_date = msg.date
                                        if msg_date.tzinfo is None:
                                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                                        if msg_date < cutoff:
                                            try:
                                                await c.delete_messages(int(chat_id), [msg.id])
                                                deleted_count += 1
                                                await asyncio.sleep(0.5)
                                            except:
                                                pass
                            except Exception as e:
                                logger.debug(f"Fetch error {chat_id}: {e}")
                    except:
                        pass
                    chats_to_remove.append(key)
            for key in chats_to_remove:
                data["chats"].pop(key, None)
            data["deleted_count"] = deleted_count
            save_auto_delete_data(data)
        except Exception as e:
            logger.error(f"Auto-delete loop error: {e}")
        await asyncio.sleep(1800)

# ====== ENCRYPTION ======
def encrypt_data(data: str) -> str:
    if not data:
        return data
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(CRYPTO_KEY[:32])
        f = Fernet(key)
        return f.encrypt(data.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        return base64.b64encode(data.encode()).decode()

def decrypt_data(data: str) -> str:
    if not data:
        return data
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(CRYPTO_KEY[:32])
        f = Fernet(key)
        return f.decrypt(data.encode()).decode()
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        try:
            return base64.b64decode(data.encode()).decode()
        except:
            return data
            # ====== CLIENT MANAGEMENT ======
async def create_client(phone, session_name=None):
    if session_name is None:
        session_name = f"session_{phone}"
    session_path = USER_DATA_DIR / session_name
    client = TelegramClient(
        str(session_path),
        API_ID,
        API_HASH,
        proxy=PROXY_CONFIG,
        device_model="HackerAI Pentest",
        system_version="4.16.30-vx",
        app_version="1.0.0",
        connection_retries=5,
        retry_delay=2
    )
    return client

async def start_client(phone, client):
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, "Not authorized"
        return True, "Connected"
    except Exception as e:
        return False, str(e)

async def stop_client(phone):
    for ac in active_accounts:
        if ac.get('phone') == phone and ac['id'] in account_clients:
            try:
                await account_clients[ac['id']].disconnect()
            except:
                pass
            if ac['id'] in account_clients:
                del account_clients[ac['id']]

async def start_account(acc):
    try:
        client = TelegramClient(
            StringSession(acc.get('session', '')),
            acc.get('api_id', API_ID),
            acc.get('api_hash', API_HASH),
            proxy=PROXY_CONFIG
        )
        await client.connect()
        me = await client.get_me()
        if me:
            return client
        return None
    except Exception as e:
        logger.error(f"Failed to start account {acc.get('name','?')}: {e}")
        return None

async def get_device_login_info(aid):
    acc = find_account(aid)
    if not acc:
        return "Account not found"
    try:
        client = TelegramClient(
            StringSession(acc.get('session', '')),
            acc.get('api_id', API_ID),
            acc.get('api_hash', API_HASH),
            proxy=PROXY_CONFIG
        )
        await client.connect()
        auths = await client(functions.account.GetAuthorizationsRequest())
        txt = f"**Devices for {acc.get('name','?')}**\n\n"
        for a in auths.authorizations:
            txt += f"• {a.device_model} | {a.app_name} {a.app_version}\n"
            txt += f"  IP: {a.ip} | {a.country}\n"
            txt += f"  Date: {a.date_created}\n"
            if a.current:
                txt += "  ✅ CURRENT\n"
            txt += "\n"
        await client.disconnect()
        return txt or "No devices found"
    except Exception as e:
        return f"Error: {str(e)[:100]}"

async def harden_account_one_click(acc):
    """Complete account hardening without 24-hour logout timer."""
    results = []
    try:
        client = TelegramClient(
            StringSession(acc.get('session', '')),
            acc.get('api_id', API_ID),
            acc.get('api_hash', API_HASH),
            proxy=PROXY_CONFIG
        )
        await client.connect()
        me = await client.get_me()
        if not me:
            return "❌ Not authorized"
        
        # 1. Revoke ALL old sessions immediately (no 24-hour timer)
        try:
            auths = await client(functions.account.GetAuthorizationsRequest())
            revoked = 0
            for auth in auths.authorizations:
                if not auth.current:
                    try:
                        await client(functions.account.ResetAuthorizationRequest(hash=auth.hash))
                        revoked += 1
                        await asyncio.sleep(0.5)
                    except:
                        pass
            results.append(f"✅ Revoked {revoked} old sessions")
        except Exception as e:
            results.append(f"⚠️ Session revoke: {str(e)[:50]}")
        
        # 2. Set privacy settings
        try:
            privacy_sets = [
                (types.InputPrivacyKeyStatusTimestamp(), [types.InputPrivacyValueAllowAll()]),
                (types.InputPrivacyKeyProfilePhoto(), [types.InputPrivacyValueAllowContacts()]),
                (types.InputPrivacyKeyForwards(), [types.InputPrivacyValueAllowContacts()]),
                (types.InputPrivacyKeyChatInvite(), [types.InputPrivacyValueAllowAll()]),
                (types.InputPrivacyKeyPhoneNumber(), [types.InputPrivacyValueDisallowAll()]),
                (types.InputPrivacyKeyAddedByPhone(), [types.InputPrivacyValueDisallowAll()]),
                (types.InputPrivacyKeyPhoneCall(), [types.InputPrivacyValueAllowContacts()]),
                (types.InputPrivacyKeyPhoneP2P(), [types.InputPrivacyValueDisallowAll()]),
                (types.InputPrivacyKeyAbout(), [types.InputPrivacyValueAllowContacts()])
            ]
            for key, val in privacy_sets:
                try:
                    await client(functions.account.SetPrivacyRequest(key=key, rules=val))
                except:
                    pass
            results.append("✅ Privacy settings hardened")
        except Exception as e:
            results.append(f"⚠️ Privacy: {str(e)[:50]}")
        
        # 3. Change profile - set name and bio if configured
        new_name = get_setting('new_account_name', '')
        new_bio = get_setting('new_account_bio', '')
        try:
            if new_name:
                await client(functions.account.UpdateProfileRequest(first_name=new_name))
                results.append(f"✅ Name changed to: {new_name}")
            if new_bio:
                await client(functions.account.UpdateProfileRequest(about=new_bio))
                results.append(f"✅ Bio updated")
        except Exception as e:
            results.append(f"⚠️ Profile update: {str(e)[:50]}")
        
        # 4. Leave all groups/channels
        try:
            left_count = 0
            async for dialog in client.iter_dialogs():
                if dialog.is_group or dialog.is_channel:
                    try:
                        await client(functions.channels.LeaveChannelRequest(channel=dialog.entity))
                        left_count += 1
                        await asyncio.sleep(0.5)
                    except:
                        pass
                    if left_count >= 50:
                        break
            results.append(f"✅ Left {left_count} groups/channels")
        except Exception as e:
            results.append(f"⚠️ Leave groups: {str(e)[:50]}")
        
        # 5. Auto-join configured links
        try:
            links = load_autojoin_links()
            joined = 0
            for link in links:
                try:
                    if 'joinchat' in link or '+' in link:
                        hash_val = link.split('/')[-1].split('+')[-1]
                        await client(functions.messages.ImportChatInviteRequest(hash=hash_val))
                    else:
                        username = link.split('/')[-1].replace('@', '')
                        await client(functions.channels.JoinChannelRequest(channel=username))
                    joined += 1
                    await asyncio.sleep(1)
                except:
                    pass
            if joined:
                results.append(f"✅ Joined {joined} groups")
        except Exception as e:
            results.append(f"⚠️ Auto-join: {str(e)[:50]}")
        
        # 6. Register for auto-delete timer (1 day)
        phone = acc.get('phone', me.phone or 'unknown')
        try:
            async for dialog in client.iter_dialogs():
                register_chat_for_auto_delete(phone, dialog.id, dialog.name or str(dialog.id))
            results.append("✅ Auto-delete timer registered (1 day)")
        except Exception as e:
            results.append(f"⚠️ Auto-delete reg: {str(e)[:30]}")
        
        await client.disconnect()
        
        # Save hardening task record
        tasks = load_harden_tasks()
        if acc['id'] not in tasks:
            tasks[acc['id']] = []
        tasks[acc['id']].append({
            'type': 'full_harden',
            'status': 'completed',
            'created_at': datetime.now().isoformat(),
            'results': results
        })
        save_harden_tasks(tasks)
        
        return "\n".join(results)
        
    except Exception as e:
        return f"❌ Hardening failed: {str(e)[:200]}"

# ====== BACKGROUND TASKS ======
async def keepalive_loop():
    """Keep accounts alive by periodic ping."""
    global account_clients, active_accounts
    while True:
        try:
            for aid, client in list(account_clients.items()):
                try:
                    me = await client.get_me()
                    if not me:
                        logger.warning(f"Account {aid} disconnected")
                except:
                    logger.warning(f"Account {aid} keepalive failed")
                    if aid in account_clients:
                        try:
                            await account_clients[aid].disconnect()
                        except:
                            pass
                        del account_clients[aid]
                    acc = find_account(aid)
                    if acc:
                        try:
                            nc = await start_account(acc)
                            if nc:
                                account_clients[aid] = nc
                                logger.info(f"Reconnected {aid}")
                        except:
                            pass
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Keepalive loop: {e}")
            await asyncio.sleep(60)

async def account_health_loop():
    """Monitor account health and report issues."""
    global account_clients, account_stats
    while True:
        try:
            for aid, client in list(account_clients.items()):
                try:
                    me = await client.get_me()
                    if me:
                        account_stats.setdefault(aid, {})['healthy'] = True
                        account_stats[aid]['last_checked'] = datetime.now().isoformat()
                    else:
                        account_stats.setdefault(aid, {})['healthy'] = False
                except:
                    account_stats.setdefault(aid, {})['healthy'] = False
            await asyncio.sleep(600)
        except:
            await asyncio.sleep(60)

# ====== BOT HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_customer(user.id)
    await update.message.reply_text(
        f"👋 *Welcome to HackerAI Pentest Bot, {user.first_name}!*\n\n"
        "This bot helps you manage Telegram accounts for security testing.\n\n"
        "📌 *Main Features:*\n"
        "• Add and manage Telegram accounts\n"
        "• One-click account hardening\n"
        "• Auto-reply and mass messaging\n"
        "• Account health monitoring\n"
        "• Auto-delete message timer (1 day)\n\n"
        "Use /menu to see the main menu.",
        parse_mode='Markdown'
    )
    await show_main_menu(update, context)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📱 Manage Accounts", callback_data='m_acc')],
        [InlineKeyboardButton("🔐 Account Hardening", callback_data='m_harden')],
        [InlineKeyboardButton("🤖 Auto Reply", callback_data='m_ar')],
        [InlineKeyboardButton("📨 Group Spam", callback_data='m_gs')],
        [InlineKeyboardButton("📡 Channel Backup", callback_data='m_channel')],
        [InlineKeyboardButton("📊 Status & Stats", callback_data='m_stat')],
        [InlineKeyboardButton("⏰ Auto-Delete Timer", callback_data='auto_delete_menu')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='m_set')],
        [InlineKeyboardButton("🛡️ Admin Panel", callback_data='m_adm')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🤖 *HackerAI Pentest Bot - Main Menu*\n\nSelect an option below:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ====== BUTTON CALLBACK HANDLER ======
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, logout_notification_enabled, account_id_counter, account_clients, active_accounts, account_stats, account_stop_flags, account_keepalive_tasks, account_spam_tasks, customer_count
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID and user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ You are not authorized to use this bot.")
        return

    # ====== MAIN MENU ======
    if data == "main" or data == "back_to_menu":
        await show_main_menu(update, context)
    
    # ====== AUTO-DELETE TIMER MENU ======
    elif data == "auto_delete_menu":
        ad_data = load_auto_delete_data()
        enabled = ad_data.get("enabled", False)
        days = ad_data.get("days", 1)
        chats_count = len(ad_data.get("chats", {}))
        deleted = ad_data.get("deleted_count", 0)
        
        status = "✅ চালু" if enabled else "❌ বন্ধ"
        txt = (
            f"⏰ **অটো-ডিলিট টাইমার**\n\n"
            f"স্ট্যাটাস: {status}\n"
            f"ডিলিট হবে: {days} দিন পর\n"
            f"ট্র্যাক করা চ্যাট: {chats_count} টি\n"
            f"ইতিমধ্যে ডিলিট: {deleted} টি\n\n"
            f"🔹 চালু থাকলে সব আউটগোয়িং মেসেজ {days} দিন পর অটো ডিলিট হবে\n"
            f"🔹 প্রতি ৩০ মিনিট পর চেক করে\n"
            f"🔹 শুধু তোমার সেন্ট মেসেজ ডিলিট হবে"
        )
        kb = [
            [InlineKeyboardButton(f"{'⏸️ বন্ধ করো' if enabled else '▶️ চালু করো'}", callback_data="auto_delete_toggle")],
            [InlineKeyboardButton("📅 ডে সেট করো", callback_data="auto_delete_days_menu")],
            [InlineKeyboardButton("📋 ট্র্যাক করা চ্যাট", callback_data="auto_delete_list")],
            [InlineKeyboardButton("➕ চ্যাট যোগ করো", callback_data="auto_delete_add_ask")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        
    elif data == "auto_delete_toggle":
        ad_data = load_auto_delete_data()
        ad_data["enabled"] = not ad_data.get("enabled", False)
        save_auto_delete_data(ad_data)
        status = "চালু ✅" if ad_data["enabled"] else "বন্ধ ❌"
        await query.edit_message_text(f"⏰ অটো-ডিলিট টাইমার এখন {status}!", parse_mode='Markdown')
        await asyncio.sleep(1)
        await button_handler(update, context)
        
    elif data == "auto_delete_days_menu":
        kb = [
            [InlineKeyboardButton("1 দিন", callback_data="auto_delete_days_1")],
            [InlineKeyboardButton("3 দিন", callback_data="auto_delete_days_3")],
            [InlineKeyboardButton("7 দিন", callback_data="auto_delete_days_7")],
            [InlineKeyboardButton("14 দিন", callback_data="auto_delete_days_14")],
            [InlineKeyboardButton("30 দিন", callback_data="auto_delete_days_30")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="auto_delete_menu")]
        ]
        await query.edit_message_text(
            "📅 **দিন সেট করো:**\n\nকত দিন পর মেসেজ অটো ডিলিট হবে?",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb)
        )
        
    elif data.startswith("auto_delete_days_"):
        days = int(data.split("_")[-1])
        ad_data = load_auto_delete_data()
        ad_data["days"] = days
        save_auto_delete_data(ad_data)
        await query.edit_message_text(f"✅ {days} দিন সেট করা হয়েছে!", parse_mode='Markdown')
        await asyncio.sleep(1)
        await button_handler(update, context)
        
    elif data == "auto_delete_list":
        ad_data = load_auto_delete_data()
        chats = ad_data.get("chats", {})
        if not chats:
            txt = "📋 কোনো গ্রুপ ট্র্যাক করা হচ্ছে না।"
        else:
            txt = f"📋 **ট্র্যাক করা গ্রুপ ({len(chats)})**\n\n"
            for i, (key, info) in enumerate(list(chats.items())[:15], 1):
                title = info.get("chat_title", "?")[:20]
                phone = info.get("phone", "?")[-8:]
                txt += f"{i}. {title} (`{phone}`)\n"
            if len(chats) > 15:
                txt += f"\n...আরও {len(chats)-15} টি"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="auto_delete_menu")]]))
        
    elif data == "auto_delete_add_ask":
        context.user_data['await'] = 'autodel_add_chat'
        await query.edit_message_text(
            "📝 **যে গ্রুপ/চ্যাটে ট্র্যাকিং যোগ করতে চাও, সেই গ্রুপের আইডি দিন:**\n\n"
            "ফরম্যাট: `-1001234567890`\n\n"
            "অথবা গ্রুপ থেকে একটা মেসেজ ফরোয়ার্ড করো।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="auto_delete_menu")]])
        )

    # ====== ACCOUNT HARDENING ======
    elif data == "m_harden":
        wait_24h = get_setting('harden_24h_wait', False)
        txt = "🔐 **Account Hardening** 🔐\n\n"
        txt += "═══════════════════════\n"
        txt += "✅ নাম, বায়ো চেঞ্জ\n"
        txt += "✅ ইমিডিয়েট ডিভাইস রিমুভ\n"
        txt += "✅ প্রাইভেসি সেটিংস শক্ত করা\n"
        txt += "✅ সব চ্যাট/গ্রুপ/চ্যানেল লিভ\n"
        txt += "✅ গ্রুপ অটো জয়েন\n"
        txt += "✅ ১ দিন পর অটো ডিলিট টাইমার\n"
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
        if not active_accounts:
            await query.edit_message_text("❌ কোনো একটিভ অ্যাকাউন্ট নেই!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
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
        await query.edit_message_text(f"**রেজাল্ট:**\n\n{result}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif data == "harden_name":
        context.user_data['await'] = 'harden_name'
        cur = get_setting('new_account_name', '')
        await query.edit_message_text(f"✏️ **নতুন নাম লিখুন:**\nবর্তমান: {cur or 'সেট নেই'}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif data == "harden_bio":
        context.user_data['await'] = 'harden_bio'
        cur = get_setting('new_account_bio', '')
        await query.edit_message_text(f"✏️ **নতুন বায়ো লিখুন:**\nবর্তমান: {cur or 'সেট নেই'}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif data == "harden_devices":
        if not active_accounts:
            await query.edit_message_text("❌ কোনো একটিভ অ্যাকাউন্ট নেই!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
            return
        kb = [[InlineKeyboardButton(f"📱 {a.get('name','?')[:15]}", callback_data=f"hdv_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")])
        await query.edit_message_text("**কোন অ্যাকাউন্টের ডিভাইস দেখবেন?**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("hdv_"):
        aid = data.split('_')[1]
        info = await get_device_login_info(aid)
        await query.edit_message_text(f"📱 **Device Info:**\n\n{info[:3500]}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_devices"), InlineKeyboardButton("🔄 Refresh", callback_data=f"hdv_{aid}")]]))

    elif data == "harden_links":
        links = load_autojoin_links()
        txt = "🔑 **Auto Join Links**\n\nযে সব লিংকে অটো জয়েন হবে:\n\n"
        if links:
            for i, link in enumerate(links, 1):
                txt += f"{i}. {link[:40]}...\n"
        else:
            txt += "কোনো লিংক নেই। /new_join_link কমান্ড ব্যবহার করুন।\n"
        kb = [
            [InlineKeyboardButton("➕ Add Link", callback_data="harden_link_add")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_link_add":
        context.user_data['await'] = 'harden_link_add'
        await query.edit_message_text("🔗 **গ্রুপ লিংক পাঠান:**\nযেমন: https://t.me/yourgroup", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))

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
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    # ====== ACCOUNT MANAGEMENT ======
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
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("📱 **ফোন নম্বর দিন:**\n\nফরম্যাট: `+8801XXXXXXXXX`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))

    elif data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("🔑 **Session String পেস্ট করুন:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))

    elif data == "ac_del":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ কোনো অ্যাকাউন্ট নেই!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}", callback_data=f"acd_{a['id']}")] for a in all_a]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")])
        await query.edit_message_text("🗑️ **ডিলিট করার জন্য অ্যাকাউন্ট সিলেক্ট করুন:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

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
        await query.edit_message_text(f"✅ **{name}** permanently deleted!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))

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
        await query.edit_message_text("🔑 **ব্যাকআপ Session String পেস্ট করুন:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))

    elif data == "ac_bk_del":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ কোনো ব্যাকআপ নেই!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")])
        await query.edit_message_text("🗑️ **রিমুভ করবেন?**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_bk_to_run":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ কোনো ব্যাকআপ নেই!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
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
        backup_acc['is_backup'] = False
        add_account_data(backup_acc)
        remove_account_data(bid)
        try:
            nc = await start_account(backup_acc)
            if nc:
                active_accounts.append(backup_acc)
                account_clients[backup_acc['id']] = nc
                account_stats[backup_acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                account_stop_flags[backup_acc['id']] = False
                await query.edit_message_text(f"✅ **{backup_acc.get('name','?')}** এখন রানিং!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
        except Exception as e:
            await query.edit_message_text(f"❌ Failed: {str(e)[:100]}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))

    elif data.startswith("acbkd_"):
        bid = data.split('_')[1]
        remove_account_data(bid)
        await query.edit_message_text("✅ ব্যাকআপ রিমুভ হয়েছে!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))

    elif data == "ac_ls":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ কোনো অ্যাকাউন্ট নেই!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            return
        txt = f"📋 **সব অ্যাকাউন্ট** ({len(all_a)})\n\n"
        for i, a in enumerate(all_a, 1):
            n = a.get('name', '?')
            p = a.get('phone', 'N/A')
            tp = "MAIN" if not a.get('is_backup') else "BKP"
            st = "🟢" if any(x['id'] == a['id'] for x in active_accounts) else "🔴"
            txt += f"{st} {tp} {i}. {n} 📱{p}\n"
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))

    # ====== CHANNEL BACKUP ======
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
        await query.edit_message_text("📡 **মূল চ্যানেলের আইডি বা ইউজারনেম দিন:**\n\nযেমন: `@yourchannel` অথবা `-1001234567890`\n\n⚠️ নোট: অ্যাকাউন্ট অবশ্যই চ্যানেলের মেম্বার হতে হবে!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif data == "ch_add_backup":
        context.user_data['await'] = 'ch_add_backup'
        await query.edit_message_text("📡 **ব্যাকআপ চ্যানেলের আইডি বা ইউজারনেম দিন:**\n\nযেমন: `@backupchannel` অথবা `-1001234567890`\n\nযখন মূল চ্যানেল থেকে কিক খাবে, অটো এই চ্যানেলে জয়েন হবে!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

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
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif data == "ch_remove":
        ch_data = load_channel_backup()
        all_chs = ch_data['main_channels'] + ch_data['backup_channels']
        if not all_chs:
            await query.edit_message_text("❌ কোনো চ্যানেল নেই!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))
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
        await query.edit_message_text("✅ চ্যানেল রিমুভ হয়েছে!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif data == "ch_toggle":
        cur = get_setting('channel_backup_enabled', True)
        set_setting('channel_backup_enabled', not cur)
        status = "🟢 চালু" if not cur else "🔴 বন্ধ"
        await query.edit_message_text(f"✅ চ্যানেল ব্যাকআপ {status} হয়েছে!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    # ====== AUTO REPLY ======
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
        await query.edit_message_text("✅ **অটো রিপ্লাই চালু!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    elif data == "ar_stop":
        auto_reply_enabled = False
        await query.edit_message_text("⏹️ **অটো রিপ্লাই বন্ধ!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

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
        enabled = not cur
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

    elif data == "ar_welcome_edit":
        context.user_data['await'] = 'welcome_text'
        await query.edit_message_text("✏️ নতুন টেক্সট ১ লিখুন:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))

    elif data == "ar_welcome_edit2":
        context.user_data['await'] = 'welcome_text_2'
        await query.edit_message_text("✏️ নতুন টেক্সট ২ লিখুন:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))

    elif data == "ar_welcome_img":
        context.user_data['await'] = 'welcome_image'
        await query.edit_message_text("📷 ইমেজ পাঠান:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))

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
        enabled = not cur
        txt = f"🚫 Block Photo: {'🟢 ON' if enabled else '🔴 OFF'}"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Toggle", callback_data="ar_blockphoto_tog")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

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
        enabled = not cur
        duration = int(get_setting('typing_duration', 240))
        txt = f"⌨️ Typing: {'🟢 ON' if enabled else '🔴 OFF'} | {duration}s"
        kb = [
            [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Toggle", callback_data="ar_typing_tog")],
            [InlineKeyboardButton("⏱️ Set Time", callback_data="ar_typing_time")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_typing_time":
        context.user_data['await'] = 'typing_time'
        await query.edit_message_text(f"⏱️ Time (0-300s):\nCurrent: {get_setting('typing_duration', 240)}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_typing")]]))

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
            await query.edit_message_text(f"Enter seconds (0-600):\nCurrent: {get_setting('wait_time', 300)}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))
        else:
            set_setting('wait_time', int(val))
            await query.edit_message_text(f"✅ {val}s!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))

    elif data == "ar_ignore":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "🚫 Ignore:\nএক লাইনে একটি\n\n"
        if cur: txt += f"Current:\n`{cur}`"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    elif data == "ar_replies":
        replies = load_json(REPLIES_FILE, [])
        txt = "📝 Custom Replies:\n"
        if replies:
            for r in replies[-10:]:
                txt += f"`{r['keyword'][:12]}` → {r['reply'][:20]}...\n"
        else: txt += "কিছু নেই। /add_reply ব্যবহার করুন।\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    # ====== GROUP SPAM ======
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
        await query.edit_message_text("✅ স্প্যাম চালু!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

    elif data == "gs_stop":
        group_spam_enabled = False
        await query.edit_message_text("⏹️ স্প্যাম বন্ধ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

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
        await query.edit_message_text(f"✅ Speed: {m[data]}!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

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
        await query.edit_message_text("✏️ স্প্যাম মেসেজ পাঠান:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))

    elif data == "gs_st":
        txt = "📊 **Stats:**\n"
        for a in active_accounts:
            s = account_stats.get(a['id'], {}).get('spam_sent', 0)
            r = "▶️" if account_stats.get(a['id'], {}).get('spam_running', False) else "⏹️"
            txt += f"{r} {a.get('name','?')[:10]}: {s}\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

    # ====== SETTINGS ======
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
        cur = not cur
        bp = "🟢" if cur else "🔴"
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

    elif data == "st_fs":
        cur = get_setting('flood_slow_mode', True)
        set_setting('flood_slow_mode', not cur)
        cur = not cur
        bp = "🟢" if get_setting('block_photo_enabled', True) else "🔴"
        fs = "🟢" if cur else "🔴"
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

    elif data == "st_ln":
        logout_notification_enabled = not logout_notification_enabled
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
        await query.edit_message_text("✏️ **UPI ID দিন:**\n`user@upi`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))

    elif data == "st_paytm":
        context.user_data['await'] = 'paytm'
        await query.edit_message_text("✏️ **PayTm নাম্বার দিন:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))

    elif data == "st_qr":
        context.user_data['await'] = 'qr_code'
        await query.edit_message_text("📷 **QR Code ইমেজ পাঠান:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]]))

    # ====== STATUS ======
    elif data == "m_stat":
        ar = "🟢" if auto_reply_enabled else "🔴"
        gs = "🟢" if group_spam_enabled else "🔴"
        ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
        ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        spm_act = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        ad_data = load_auto_delete_data()
        deleted = ad_data.get('deleted_count', 0)
        txt = f"📊 **স্ট্যাটাস**\n\n🤖 Auto Reply: {ar}\n📨 Spam: {gs}\n👤 Active: {len(active_accounts)}\n📨 Spamming: {spm_act}\n💬 Auto Sent: {ttl_auto}\n📬 Spam Sent: {ttl_spam}\n👥 Customers: {len(customer_count)}\n🧹 Auto Deleted: {deleted} messages"
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="m_stat"), InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]))

    # ====== ADMIN PANEL ======
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
        await query.edit_message_text("📢 **ব্রডকাস্ট মেসেজ লিখুন:**\n\nসব কাস্টমারকে পাঠানো হবে!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))

    elif data == "ad_lg":
        log_path = Path('bot.log')
        if log_path.exists():
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-20:]
            txt = "📄 **Last 20 Logs**\n\n" + "".join(lines[-500:])
        else:
            txt = "📄 No log file found."
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))

    elif data == "ad_rt":
        await query.edit_message_text("🔄 **Restarting...**")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    else:
        await query.edit_message_text(f"⚠️ Unknown: {data}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main")]]))
        # ====== TEXT MESSAGE HANDLER ======
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, customer_count, account_clients, active_accounts, account_stats, account_stop_flags
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in ADMIN_IDS:
        return
    text = update.message.text.strip()
    await_state = context.user_data.get('await')
    if not await_state:
        # Check for commands
        if text == '/menu':
            await show_main_menu(update, context)
        elif text.startswith('/add_reply'):
            parts = text.split(' ', 2)
            if len(parts) >= 3:
                replies = load_replies()
                replies.append({'keyword': parts[1].lower(), 'reply': parts[2], 'added_at': datetime.now().isoformat()})
                save_replies(replies)
                await update.message.reply_text(f"✅ রিপ্লাই যোগ: `{parts[1]}` → {parts[2][:30]}", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Usage: /add_reply keyword reply_text")
        elif text == '/new_join_link':
            context.user_data['await'] = 'harden_link_add'
            await update.message.reply_text("🔗 **গ্রুপ লিংক পাঠান:**", parse_mode='Markdown')
        else:
            await update.message.reply_text("❓ Unknown command. Use /menu")
        return

    if await_state == 'autodel_add_chat':
        chat_id = None
        if text.startswith('-100') or text.startswith('-'):
            try:
                chat_id = int(text)
            except:
                pass
        elif update.message.forward_from_chat:
            chat_id = update.message.forward_from_chat.id
        
        if chat_id and active_accounts:
            phone = active_accounts[0].get('phone', 'unknown')
            register_chat_for_auto_delete(phone, chat_id, str(chat_id))
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ চ্যাট ট্র্যাকিংয়ে যোগ করা হয়েছে!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="auto_delete_menu")]]))
        else:
            await update.message.reply_text("❌ ভ্যালিড চ্যাট আইডি দিন বা ফরোয়ার্ড মেসেজ পাঠান!")

    elif await_state == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ ওয়েলকাম টেক্সট ১ আপডেট!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    elif await_state == 'welcome_text_2':
        set_setting('welcome_message_2', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ ওয়েলকাম টেক্সট ২ আপডেট!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
    
    elif await_state == 'wait_time':
        try:
            val = max(0, min(600, int(text)))
            set_setting('wait_time', val)
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Wait time: {val}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]]))
        except:
            await update.message.reply_text("❌ সংখ্যা দিন (0-600)!")
    
    elif await_state == 'typing_time':
        try:
            val = int(text)
            if 0 <= val <= 300:
                set_setting('typing_duration', val)
                context.user_data.pop('await', None)
                await update.message.reply_text(f"✅ Typing: {val}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_typing")]]))
            else:
                await update.message.reply_text("❌ 0-300 এর মধ্যে দিন!")
        except:
            await update.message.reply_text("❌ সংখ্যা দিন!")
    
    elif await_state == 'ignore':
        set_setting('ignored_messages', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ ইগনোর মেসেজ আপডেট!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    elif await_state == 'harden_name':
        set_setting('new_account_name', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ নাম সেট: {text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif await_state == 'harden_bio':
        set_setting('new_account_bio', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ বায়ো সেট!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif await_state == 'harden_link_add':
        links = load_autojoin_links()
        links.append(text)
        save_autojoin_links(links)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ লিংক যোগ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))

    elif await_state == 'ch_add_main':
        ch_data = load_channel_backup()
        ch_data['main_channels'].append({'id': text, 'title': text, 'type': 'main'})
        save_channel_backup(ch_data)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ মূল চ্যানেল যোগ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif await_state == 'ch_add_backup':
        ch_data = load_channel_backup()
        ch_data['backup_channels'].append({'id': text, 'title': text, 'type': 'backup'})
        save_channel_backup(ch_data)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ ব্যাকআপ চ্যানেল যোগ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif await_state == 'upi':
        set_setting('upi_id', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ UPI সেট!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))
    
    elif await_state == 'paytm':
        set_setting('paytm_num', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ PayTm সেট!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]]))
    
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
        await update.message.reply_text(f"✅ {sent} কাস্টমারকে পাঠানো হয়েছে!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))
    
    elif await_state == 'gs_msg_add':
        add_spam_message(text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ স্প্যাম মেসেজ যোগ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]]))

    elif await_state == 'ac_ph':
        context.user_data['phone'] = text
        context.user_data['await'] = 'ac_otp'
        try:
            # পরিবর্তন ১: Environment Variable থেকে নাও, তারপর DEFAULT
ac_api_id = int(os.environ.get('API_ID', str(DEFAULT_API_ID)))
ac_api_hash = os.environ.get('API_HASH', DEFAULT_API_HASH)
            client = TelegramClient(StringSession(), ac_api_id, ac_api_hash)
            await client.connect()
            send_code = await client.send_code_request(text)
            context.user_data['ac_client'] = client
            context.user_data['ac_phone_code_hash'] = send_code.phone_code_hash
            await update.message.reply_text(f"✅ OTP পাঠানো হয়েছে {text}\n\nOTP দিন:")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:100]}")
            context.user_data.pop('await', None)

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
            await update.message.reply_text(f"✅ অ্যাকাউন্ট যোগ!\n👤 {name}\n📱 {phone}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
            except: pass
        except SessionPasswordNeededError:
            context.user_data['await'] = 'ac_2fa'
            await update.message.reply_text("🔐 ২FA পাসওয়ার্ড দিন:")
        except PhoneCodeInvalidError:
            await update.message.reply_text("❌ ভুল OTP! আবার দিন:")
        except PhoneCodeExpiredError:
            await update.message.reply_text("❌ OTP expired. আবার শুরু করুন")
            context.user_data.pop('await', None)

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
            await update.message.reply_text(f"✅ অ্যাকাউন্ট যোগ!\n👤 {name}\n📱 {phone}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
            except: pass
        except Exception as e:
            await update.message.reply_text(f"❌ ২FA failed: {str(e)[:100]}")
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
                await update.message.reply_text(f"✅ অ্যাকাউন্ট যোগ!\n👤 {name}\n📱 {phone}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
                try:
                    n_client = await start_account(acc)
                    if n_client:
                        active_accounts.append(acc)
                        account_clients[acc['id']] = n_client
                        account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                        account_stop_flags[acc['id']] = False
                except: pass
            else:
                await update.message.reply_text("❌ ইউজার ইনফো পাওয়া যায়নি!")
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid session: {str(e)[:100]}")
        finally:
            context.user_data.pop('await', None)

    elif await_state == 'ac_bk_ss':
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
                    'is_backup': True,
                    'added_at': datetime.now().isoformat()
                }
                add_account_data(acc)
                await client.disconnect()
                context.user_data.pop('await', None)
                await update.message.reply_text(f"✅ ব্যাকআপ অ্যাকাউন্ট যোগ!\n👤 {name}\n📱 {phone}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]]))
            else:
                await update.message.reply_text("❌ ইউজার ইনফো পাওয়া যায়নি!")
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid session: {str(e)[:100]}")
        finally:
            context.user_data.pop('await', None)

    else:
        context.user_data.pop('await', None)
        await update.message.reply_text("❓ Unknown input. Use /menu")


# ====== PHOTO MESSAGE HANDLER ======
async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in ADMIN_IDS:
        return
    await_state = context.user_data.get('await')
    if not await_state:
        return
    
    if await_state == 'welcome_image':
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(WELCOME_IMAGE_FILE)
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ ওয়েলকাম ইমেজ সেট!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:80]}")
    
    elif await_state == 'qr_code':
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(QR_CODE_FILE)
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ QR Code সেট!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:80]}")
    
    else:
        await update.message.reply_text("❓ Unexpected photo.")


# ====== ERROR HANDLER ======
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(f"⚠️ Error: {str(context.error)[:100]}")
    except:
        pass


# ====== MAIN FUNCTION ======
async def main():
    """Main entry point - no Updater error, no run_polling crash."""
    logger.info("Starting HackerAI Pentest Bot...")
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    # Build application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_error_handler(error_handler)
    
    # Initialize
    await app.initialize()
    await app.start()
    
    # Load customer count
    global customer_count
    customer_count = set(load_json(CUSTOMERS_FILE, []))
    
    # Load active accounts from disk
    all_accs = get_all_accounts()
    for acc in all_accs:
        if not acc.get('is_backup'):
            try:
                nc = await start_account(acc)
                if nc:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = nc
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    logger.info(f"Loaded account: {acc.get('name')} ({acc.get('phone')})")
            except Exception as e:
                logger.error(f"Failed to load account {acc.get('name')}: {e}")
    
    # Start background tasks
    asyncio.create_task(auto_delete_messages_loop(app))
    asyncio.create_task(keepalive_loop())
    asyncio.create_task(account_health_loop())
    
    # Start polling - this is the FIX for the Updater error
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info(f"Bot started! {len(active_accounts)} accounts loaded.")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except asyncio.CancelledError:
        logger.info("Tasks cancelled, shutting down...")
    finally:
        logger.info("Stopping bot...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        # Disconnect all accounts
        for aid, client in list(account_clients.items()):
            try:
                await client.disconnect()
            except:
                pass
        logger.info("Bot stopped.")


# ====== FLASK WEBHOOK (optional) ======
if FLASK_AVAILABLE:
    flask_app = Flask(__name__)
    flask_app.secret_key = WEBHOOK_SECRET
    
    @flask_app.route('/')
    def home():
        return jsonify({"status": "running", "accounts": len(active_accounts), "customers": len(customer_count)})
    
    @flask_app.route('/health')
    def health():
        return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})
    
    def run_flask():
        flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)


# ====== ENTRY POINT ======
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("HackerAI Pentest Bot Starting...")
    logger.info(f"Python: {sys.version}")
    logger.info(f"PTB Available: {PTB_AVAILABLE}")
    logger.info(f"Telethon Available: {TELETHON_AVAILABLE}")
    logger.info(f"Flask Available: {FLASK_AVAILABLE}")
    logger.info(f"Accounts file: {ACCOUNTS_FILE}")
    logger.info(f"Auto-delete file: {AUTO_DELETE_FILE}")
    logger.info("=" * 50)
    
    # Start Flask in a thread if available (for Render web service)
    if FLASK_AVAILABLE and os.environ.get('RENDER', ''):
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info("Flask web server started in background thread")
    
    # Run main async function
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)

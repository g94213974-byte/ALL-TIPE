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
ACCOUNT_PROXIES_FILE = USER_DATA_DIR / 'account_proxies.json'

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

# Auto reply and spam handlers registry
auto_reply_handlers = {}
spam_worker_tasks = {}

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

# ====== ACCOUNT PROXY FUNCTIONS ======
def load_account_proxies():
    return load_json(ACCOUNT_PROXIES_FILE, {})

def save_account_proxy(account_id, proxy_config):
    data = load_account_proxies()
    data[account_id] = proxy_config
    return save_json(ACCOUNT_PROXIES_FILE, data)

def remove_account_proxy(account_id):
    data = load_account_proxies()
    if account_id in data:
        del data[account_id]
        return save_json(ACCOUNT_PROXIES_FILE, data)
    return False

def get_account_proxy(account_id):
    data = load_account_proxies()
    return data.get(account_id, None)

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
        "seconds": 86400,  # Default 1 day
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
            seconds = data.get("seconds", 86400)
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
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
async def create_client(phone, session_name=None, proxy_config=None):
    if session_name is None:
        session_name = f"session_{phone}"
    session_path = USER_DATA_DIR / session_name
    client = TelegramClient(
        str(session_path),
        API_ID,
        API_HASH,
        proxy=proxy_config or PROXY_CONFIG,
        device_model="SecureBot",
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
        proxy_config = get_account_proxy(acc['id']) or PROXY_CONFIG
        client = TelegramClient(
            StringSession(acc.get('session', '')),
            acc.get('api_id', API_ID),
            acc.get('api_hash', API_HASH),
            proxy=proxy_config
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
        proxy_config = get_account_proxy(aid) or PROXY_CONFIG
        client = TelegramClient(
            StringSession(acc.get('session', '')),
            acc.get('api_id', API_ID),
            acc.get('api_hash', API_HASH),
            proxy=proxy_config
        )
        await client.connect()
        auths = await client(functions.account.GetAuthorizationsRequest())
        txt = f"Devices for {acc.get('name','?')}\n\n"
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
    """Complete account hardening with all features."""
    results = []
    try:
        proxy_config = get_account_proxy(acc['id']) or PROXY_CONFIG
        client = TelegramClient(
            StringSession(acc.get('session', '')),
            acc.get('api_id', API_ID),
            acc.get('api_hash', API_HASH),
            proxy=proxy_config
        )
        await client.connect()
        me = await client.get_me()
        if not me:
            return "❌ Not authorized"
        
        # 1. Revoke ALL old sessions immediately
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
        
        # 3. Change profile name and bio
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
        
        # 4. Delete profile photo if requested
        if get_setting('delete_dp_enabled', False):
            try:
                photos = await client(functions.photos.GetUserPhotosRequest(user_id=me.id, offset=0, max_id=0, limit=100))
                if photos and photos.photos:
                    await client(functions.photos.DeletePhotosRequest(id=photos.photos))
                    results.append(f"✅ Deleted {len(photos.photos)} profile photo(s)")
                else:
                    results.append("ℹ️ No profile photos to delete")
            except Exception as e:
                results.append(f"⚠️ DP delete: {str(e)[:50]}")
        
        # 5. Leave all groups/channels
        leave_enabled = get_setting('leave_all_enabled', False)
        if leave_enabled:
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
                        if left_count >= 100:
                            break
                results.append(f"✅ Left {left_count} groups/channels")
            except Exception as e:
                results.append(f"⚠️ Leave groups: {str(e)[:50]}")
        
        # 6. Delete all chats if enabled
        delete_chats_enabled = get_setting('delete_all_chats_enabled', False)
        if delete_chats_enabled:
            try:
                deleted_count = 0
                async for dialog in client.iter_dialogs():
                    if not dialog.is_group and not dialog.is_channel and not dialog.is_user:
                        continue
                    try:
                        if dialog.is_user:
                            await client(functions.messages.DeleteHistoryRequest(peer=dialog.id, revoke=True))
                        else:
                            await client(functions.messages.DeleteHistoryRequest(peer=dialog.entity, revoke=True))
                        deleted_count += 1
                        await asyncio.sleep(0.5)
                    except:
                        pass
                    if deleted_count >= 50:
                        break
                results.append(f"✅ Deleted {deleted_count} chat histories")
            except Exception as e:
                results.append(f"⚠️ Delete chats: {str(e)[:50]}")
        
        # 7. Auto-join configured links
        join_enabled = get_setting('auto_join_enabled', False)
        if join_enabled:
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
        
        # 8. Register for auto-delete timer if enabled
        ad_enabled = get_setting('auto_delete_harden_enabled', False)
        if ad_enabled:
            phone = acc.get('phone', me.phone or 'unknown')
            seconds = int(get_setting('auto_delete_seconds', 86400))
            try:
                registered_count = 0
                async for dialog in client.iter_dialogs(limit=50):
                    register_chat_for_auto_delete(phone, dialog.id, dialog.name or str(dialog.id))
                    registered_count += 1
                    await asyncio.sleep(0.05)
                
                ad_data = load_auto_delete_data()
                ad_data["enabled"] = True
                ad_data["seconds"] = seconds
                save_auto_delete_data(ad_data)
                
                time_str = f"{seconds//86400}d" if seconds >= 86400 else f"{seconds//3600}h" if seconds >= 3600 else f"{seconds}s"
                results.append(f"✅ Auto-delete timer set ({time_str}) for {registered_count} chats")
            except Exception as e:
                results.append(f"⚠️ Auto-delete reg: {str(e)[:30]}")
        
        # 9. Set new profile photo if file exists
        profile_pic_path = USER_DATA_DIR / 'new_profile_pic.jpg'
        if profile_pic_path.exists():
            try:
                await client(functions.photos.UploadProfilePhotoRequest(
                    file=await client.upload_file(str(profile_pic_path))
                ))
                results.append("✅ New profile photo set")
            except Exception as e:
                results.append(f"⚠️ Profile photo upload: {str(e)[:50]}")
        
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

# ====== AUTO REPLY LOGIC ======
async def setup_auto_reply_for_account(aid, client):
    """Set up auto reply with proper message seen timing."""
    global auto_reply_enabled, auto_reply_handlers
    
    if aid in auto_reply_handlers:
        try:
            client.remove_event_handler(auto_reply_handlers[aid])
        except:
            pass
    
    @client.on(events.NewMessage(incoming=True))
    async def auto_reply_handler(event):
        global auto_reply_enabled
        
        if not auto_reply_enabled:
            return
        
        try:
            sender = await event.get_sender()
            if not sender:
                return
            
            me = await client.get_me()
            if sender.id == me.id:
                return
            if sender.id in [OWNER_ID] + ADMIN_IDS:
                return
            
            if event.photo and get_setting('block_photo_enabled', True):
                return
            
            ignored = get_setting('ignored_messages', '')
            if ignored:
                ignored_list = [ig.strip().lower() for ig in ignored.split('\n') if ig.strip()]
                msg_text = (event.raw_text or '').lower()
                if any(ig in msg_text for ig in ignored_list):
                    return
            
            wait_time = int(get_setting('wait_time', 300))
            actual_wait = min(wait_time, 30)
            
            if actual_wait > 0:
                await asyncio.sleep(actual_wait)
            
            try:
                await client.send_read_acknowledge(event.chat_id, max_id=event.id)
                logger.debug(f"Message marked as read for {aid}")
            except Exception as e:
                logger.debug(f"Read acknowledge error: {e}")
            
            await asyncio.sleep(0.5)
            
            if get_setting('typing_enabled', True):
                typing_dur = int(get_setting('typing_duration', 240))
                actual_typing = min(typing_dur, 8)
                
                async with client.action(event.chat_id, 'typing'):
                    await asyncio.sleep(actual_typing)
            
            replies = load_replies()
            welcome_msg = get_setting('welcome_message', '')
            welcome_msg_2 = get_setting('welcome_message_2', '')
            
            reply_text = welcome_msg or "Hello! How can I help you?"
            
            if replies and event.raw_text:
                msg_lower = event.raw_text.lower()
                for r in replies:
                    if r['keyword'].lower() in msg_lower:
                        reply_text = r['reply']
                        break
            
            try:
                if WELCOME_IMAGE_FILE.exists():
                    await client.send_file(event.chat_id, str(WELCOME_IMAGE_FILE), caption=reply_text, reply_to=event.id)
                else:
                    await event.reply(reply_text)
                
                account_stats.setdefault(aid, {})['auto_sent'] = account_stats.get(aid, {}).get('auto_sent', 0) + 1
                
                if welcome_msg_2:
                    await asyncio.sleep(30)
                    try:
                        await event.reply(welcome_msg_2)
                    except:
                        pass
                
            except Exception as e:
                logger.error(f"Auto reply send error: {e}")
                
        except Exception as e:
            logger.error(f"Auto reply handler error: {e}")
    
    auto_reply_handlers[aid] = auto_reply_handler
    logger.info(f"Auto reply handler set up for account {aid}")

async def setup_auto_reply_all():
    """Set up auto reply for all active accounts."""
    for aid, client in account_clients.items():
        try:
            await setup_auto_reply_for_account(aid, client)
        except Exception as e:
            logger.error(f"Failed to setup auto reply for {aid}: {e}")

async def remove_auto_reply_all():
    """Remove auto reply handlers from all accounts."""
    global auto_reply_handlers
    for aid, client in account_clients.items():
        if aid in auto_reply_handlers:
            try:
                client.remove_event_handler(auto_reply_handlers[aid])
            except:
                pass
    auto_reply_handlers = {}

# ====== GROUP SPAM LOGIC ======
async def spam_worker(aid, client):
    """Send spam messages to groups continuously."""
    global group_spam_enabled
    
    acc = find_account(aid)
    if not acc:
        return
    
    logger.info(f"Spam worker started for {acc.get('name', '?')}")
    
    channels = load_channel_backup()
    target_chats = []
    
    for ch in channels.get('main_channels', []):
        try:
            target_chats.append(int(ch['id']))
        except:
            target_chats.append(ch['id'])
    
    if not target_chats:
        try:
            async for dialog in client.iter_dialogs():
                if dialog.is_group or dialog.is_channel:
                    target_chats.append(dialog.id)
                if len(target_chats) >= 50:
                    break
        except Exception as e:
            logger.error(f"Error fetching dialogs: {e}")
    
    if not target_chats:
        logger.warning(f"No target chats for {aid}")
        account_stats.setdefault(aid, {})['spam_running'] = False
        return
    
    speed_config = {
        'super_fast': (0.3, 0.8),
        'fast': (1, 2),
        'medium': (3, 6),
        'slow': (8, 15)
    }
    speed = get_setting('spam_speed', 'medium')
    min_wait, max_wait = speed_config.get(speed, (3, 6))
    
    messages = load_spam_messages()
    if not messages:
        messages = [{"text": "Hello! 👋 This is an automated message."}]
    
    msg_idx = 0
    chat_idx = 0
    failed_chats = []
    
    account_stats.setdefault(aid, {})['spam_running'] = True
    account_stop_flags[aid] = False
    
    while group_spam_enabled and not account_stop_flags.get(aid, False):
        try:
            target_chats = [c for c in target_chats if c not in failed_chats]
            
            if not target_chats:
                logger.warning(f"No target chats left for {aid}")
                break
            
            chat_id = target_chats[chat_idx % len(target_chats)]
            msg_text = messages[msg_idx % len(messages)]['text']
            
            try:
                await client.send_message(int(chat_id) if isinstance(chat_id, str) and chat_id.lstrip('-').isdigit() else chat_id, msg_text)
                account_stats[aid]['spam_sent'] = account_stats[aid].get('spam_sent', 0) + 1
                
                msg_idx += 1
                chat_idx += 1
                
                await asyncio.sleep(random.uniform(min_wait, max_wait))
                
            except FloodWaitError as e:
                wait_seconds = e.seconds if hasattr(e, 'seconds') else 60
                logger.warning(f"Flood wait {wait_seconds}s for {aid}")
                await asyncio.sleep(wait_seconds + 5)
                
            except Exception as e:
                error_str = str(e)
                if "FORBIDDEN" in error_str or "USER_BANNED" in error_str or "CHANNEL_PRIVATE" in error_str:
                    failed_chats.append(chat_id)
                    
                    if channels.get('backup_channels'):
                        bk = channels['backup_channels'][0]
                        try:
                            await client(functions.channels.JoinChannelRequest(channel=bk['id']))
                            target_chats.append(bk['id'])
                            channels['active_channel'] = bk
                            save_channel_backup(channels)
                        except:
                            pass
                    
                    chat_idx += 1
                    await asyncio.sleep(3)
                    
                elif "FLOOD_WAIT" in error_str:
                    import re as re_mod
                    match = re_mod.search(r'(\d+)', error_str)
                    wait_sec = int(match.group(1)) if match else 60
                    await asyncio.sleep(wait_sec + 5)
                    
                else:
                    logger.error(f"Spam error for {aid}: {error_str[:100]}")
                    chat_idx += 1
                    await asyncio.sleep(10)
        
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Spam loop error {aid}: {e}")
            await asyncio.sleep(15)
    
    account_stats.setdefault(aid, {})['spam_running'] = False
    logger.info(f"Spam worker stopped for {acc.get('name', '?')}")

async def start_spam_all():
    """Start spam workers for all active accounts."""
    global group_spam_enabled, spam_worker_tasks
    
    group_spam_enabled = True
    
    for aid, client in account_clients.items():
        if aid not in spam_worker_tasks or spam_worker_tasks[aid].done():
            task = asyncio.create_task(spam_worker(aid, client))
            spam_worker_tasks[aid] = task
            await asyncio.sleep(1)
    
    logger.info(f"Started spam for {len(spam_worker_tasks)} accounts")

async def stop_spam_all():
    """Stop all spam workers."""
    global group_spam_enabled, spam_worker_tasks
    
    group_spam_enabled = False
    
    for aid in spam_worker_tasks:
        if not spam_worker_tasks[aid].done():
            spam_worker_tasks[aid].cancel()
    
    for aid in account_stop_flags:
        account_stop_flags[aid] = True
    
    await asyncio.sleep(2)
    
    for aid in list(spam_worker_tasks.keys()):
        try:
            await spam_worker_tasks[aid]
        except:
            pass
    
    spam_worker_tasks = {}
    logger.info("All spam workers stopped")

# ====== AUTO DELETE TIMER - FAST SETUP ======
async def setup_auto_delete_fast(seconds=None):
    """Fast auto-delete timer setup for all accounts."""
    global account_clients, active_accounts
    
    ad_data = load_auto_delete_data()
    if seconds is not None:
        ad_data["seconds"] = seconds
    
    if "chats" not in ad_data:
        ad_data["chats"] = {}
    
    total_registered = 0
    now = datetime.now(timezone.utc).isoformat()
    
    for acc in active_accounts:
        aid = acc['id']
        if aid not in account_clients:
            continue
        
        client = account_clients[aid]
        phone = acc.get('phone', 'unknown')
        acc_registered = 0
        
        try:
            async for dialog in client.iter_dialogs(limit=50):
                chat_id = dialog.id
                chat_title = dialog.name or str(dialog.id)
                key = f"{phone}:{chat_id}"
                
                if key not in ad_data["chats"]:
                    ad_data["chats"][key] = {
                        "phone": phone,
                        "chat_id": chat_id,
                        "chat_title": chat_title,
                        "registered_at": now,
                        "last_message_at": now
                    }
                    acc_registered += 1
                
                await asyncio.sleep(0.05)
            
            total_registered += acc_registered
            logger.info(f"Auto-delete: {acc_registered} chats for {acc.get('name','?')}")
            
        except Exception as e:
            logger.error(f"Auto-delete fast setup for {aid}: {e}")
    
    ad_data["enabled"] = True
    save_auto_delete_data(ad_data)
    
    return total_registered

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
                                if auto_reply_enabled:
                                    await setup_auto_reply_for_account(aid, nc)
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
        f"Welcome, {user.first_name}!\n\n"
        "Bot is ready.\n"
        "Use /menu to see available options.",
        parse_mode='Markdown'
    )
    await show_main_menu(update, context)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Manage Accounts", callback_data='m_acc')],
        [InlineKeyboardButton("Account Hardening", callback_data='m_harden')],
        [InlineKeyboardButton("Auto Reply", callback_data='m_ar')],
        [InlineKeyboardButton("Group Spam", callback_data='m_gs')],
        [InlineKeyboardButton("Channel Backup", callback_data='m_channel')],
        [InlineKeyboardButton("Status & Stats", callback_data='m_stat')],
        [InlineKeyboardButton("Settings", callback_data='m_set')],
        [InlineKeyboardButton("Admin Panel", callback_data='m_adm')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "Main Menu\n\nSelect an option:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ====== BUTTON CALLBACK HANDLER ======
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, logout_notification_enabled, account_id_counter, account_clients, active_accounts, account_stats, account_stop_flags, account_spam_tasks, account_keepalive_tasks, account_spam_active, customer_count
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

    # ====== ACCOUNT HARDENING ======
    elif data == "m_harden":
        txt = "Account Hardening\n\n"
        txt += "═══════════════════════\n"
        txt += "• Change name, bio\n"
        txt += "• Immediate device removal\n"
        txt += "• Privacy settings hardening\n"
        txt += "• Delete profile photo + set new\n"
        txt += "• Leave all chats/groups/channels\n"
        txt += "• Delete all chat history\n"
        txt += "• Auto join groups\n"
        txt += "• Auto-delete messages (1s - 30 days)\n"
        txt += "• Proxy configuration\n"
        txt += "═══════════════════════\n"
        txt += "\nAll in 1 click!"
        kb = [
            [InlineKeyboardButton("1 Click Full Hardening", callback_data="harden_all")],
            [InlineKeyboardButton("Configure Hardening Options", callback_data="harden_config")],
            [InlineKeyboardButton("Set New Name", callback_data="harden_name")],
            [InlineKeyboardButton("Set New Bio", callback_data="harden_bio")],
            [InlineKeyboardButton("Manage Profile Photo", callback_data="harden_photo")],
            [InlineKeyboardButton("View Devices", callback_data="harden_devices")],
            [InlineKeyboardButton("Auto Join Links", callback_data="harden_links")],
            [InlineKeyboardButton("Account Proxy", callback_data="harden_proxy")],
            [InlineKeyboardButton("Hardening History", callback_data="harden_history")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_config":
        dp_del = "✅" if get_setting('delete_dp_enabled', False) else "❌"
        leave_all = "✅" if get_setting('leave_all_enabled', False) else "❌"
        del_chats = "✅" if get_setting('delete_all_chats_enabled', False) else "❌"
        join_en = "✅" if get_setting('auto_join_enabled', False) else "❌"
        ad_en = "✅" if get_setting('auto_delete_harden_enabled', False) else "❌"
        ad_sec = int(get_setting('auto_delete_seconds', 86400))
        ad_time = f"{ad_sec//86400}d" if ad_sec >= 86400 else f"{ad_sec//3600}h" if ad_sec >= 3600 else f"{ad_sec}s"
        
        txt = (
            "Hardening Options Configuration\n\n"
            f"Delete DP: {dp_del}\n"
            f"Leave All Groups: {leave_all}\n"
            f"Delete All Chats: {del_chats}\n"
            f"Auto Join Groups: {join_en}\n"
            f"Auto-Delete Timer: {ad_en} ({ad_time})\n\n"
            "Toggle what you want to include in 1-click hardening:"
        )
        kb = [
            [InlineKeyboardButton(f"{'✅' if get_setting('delete_dp_enabled', False) else '❌'} Delete Profile Photo", callback_data="hcfg_dp")],
            [InlineKeyboardButton(f"{'✅' if get_setting('leave_all_enabled', False) else '❌'} Leave All Groups/Channels", callback_data="hcfg_leave")],
            [InlineKeyboardButton(f"{'✅' if get_setting('delete_all_chats_enabled', False) else '❌'} Delete All Chat History", callback_data="hcfg_delchat")],
            [InlineKeyboardButton(f"{'✅' if get_setting('auto_join_enabled', False) else '❌'} Auto Join Groups", callback_data="hcfg_join")],
            [InlineKeyboardButton(f"{'✅' if get_setting('auto_delete_harden_enabled', False) else '❌'} Auto-Delete Timer", callback_data="hcfg_ad")],
            [InlineKeyboardButton("Set Auto-Delete Time", callback_data="hcfg_ad_time")],
            [InlineKeyboardButton("Hardening Menu", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "hcfg_dp":
        cur = get_setting('delete_dp_enabled', False)
        set_setting('delete_dp_enabled', not cur)
        await query.edit_message_text(f"{'✅ Enabled' if not cur else '❌ Disabled'} delete profile photo during hardening", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_config")]]))
    elif data == "hcfg_leave":
        cur = get_setting('leave_all_enabled', False)
        set_setting('leave_all_enabled', not cur)
        await query.edit_message_text(f"{'✅ Enabled' if not cur else '❌ Disabled'} leave all groups/channels during hardening", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_config")]]))
    elif data == "hcfg_delchat":
        cur = get_setting('delete_all_chats_enabled', False)
        set_setting('delete_all_chats_enabled', not cur)
        await query.edit_message_text(f"{'✅ Enabled' if not cur else '❌ Disabled'} delete all chat history during hardening", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_config")]]))
    elif data == "hcfg_join":
        cur = get_setting('auto_join_enabled', False)
        set_setting('auto_join_enabled', not cur)
        await query.edit_message_text(f"{'✅ Enabled' if not cur else '❌ Disabled'} auto join groups during hardening", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_config")]]))
    elif data == "hcfg_ad":
        cur = get_setting('auto_delete_harden_enabled', False)
        set_setting('auto_delete_harden_enabled', not cur)
        await query.edit_message_text(f"{'✅ Enabled' if not cur else '❌ Disabled'} auto-delete timer during hardening", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_config")]]))

    elif data == "hcfg_ad_time":
        context.user_data['await'] = 'harden_ad_time'
        seconds = int(get_setting('auto_delete_seconds', 86400))
        await query.edit_message_text(
            "Enter auto-delete timer duration in seconds:\n\n"
            "Examples:\n"
            "1 = 1 second\n"
            "60 = 1 minute\n"
            "3600 = 1 hour\n"
            "86400 = 1 day (default)\n"
            "2592000 = 30 days\n\n"
            f"Current: {seconds}s",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_config")]])
        )

    elif data == "harden_all":
        if not active_accounts:
            await query.edit_message_text("❌ No active accounts!", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))
            return
        
        # Build account selection - use phone/name from active_accounts list directly
        kb = []
        for a in active_accounts:
            name = a.get('name', 'Unknown')[:15]
            phone = a.get('phone', 'N/A')
            btn_text = f" {name} | {phone[-4:]}"
            kb.append([InlineKeyboardButton(btn_text, callback_data=f"hdn_{a['id']}")])
        kb.append([InlineKeyboardButton(" Back", callback_data="m_harden")])
        await query.edit_message_text(
            "Select account to harden:\n\n"
            "All configured options will be applied in 1 click!\n"
            "Check Hardening Options first to customize.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("hdn_"):
        aid = data.split('_')[1]
        # Find account from active_accounts list directly
        acc = None
        for a in active_accounts:
            if a['id'] == aid:
                acc = a
                break
        if not acc:
            acc = find_account(aid)
        if not acc:
            await query.edit_message_text("❌ Account not found! Try adding the account first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))
            return
        await query.edit_message_text(f"⏳ Hardening started...\nAccount: {acc.get('name', 'Unknown')}\nPlease wait...", parse_mode='Markdown')
        result = await harden_account_one_click(acc)
        await query.edit_message_text(f"Results:\n\n{result}", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))

    elif data == "harden_name":
        context.user_data['await'] = 'harden_name'
        cur = get_setting('new_account_name', '')
        await query.edit_message_text(f"Enter new name:\nCurrent: {cur or 'Not set'}", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))

    elif data == "harden_bio":
        context.user_data['await'] = 'harden_bio'
        cur = get_setting('new_account_bio', '')
        await query.edit_message_text(f"Enter new bio:\nCurrent: {cur or 'Not set'}", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))

    elif data == "harden_photo":
        txt = "Profile Photo Management\n\n"
        if (USER_DATA_DIR / 'new_profile_pic.jpg').exists():
            txt += "New photo ready to upload (new_profile_pic.jpg)\n"
        else:
            txt += "No new photo set. Send a photo to save as new profile pic.\n"
        txt += "\nOptions:"
        kb = [
            [InlineKeyboardButton("Delete Current DP (during hardening)", callback_data="hcfg_dp")],
            [InlineKeyboardButton("Upload New Profile Pic", callback_data="harden_upload_photo")],
            [InlineKeyboardButton("Back", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_upload_photo":
        context.user_data['await'] = 'harden_photo_upload'
        await query.edit_message_text(
            "Send the photo you want to set as new profile picture.\n\n"
            "It will be saved and applied during 1-click hardening.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_photo")]])
        )

    elif data == "harden_devices":
        if not active_accounts:
            await query.edit_message_text("❌ No active accounts!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))
            return
        kb = [[InlineKeyboardButton(f"{a.get('name','?')[:15]}", callback_data=f"hdv_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("Back", callback_data="m_harden")])
        await query.edit_message_text("Select account to view devices:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("hdv_"):
        aid = data.split('_')[1]
        info = await get_device_login_info(aid)
        await query.edit_message_text(f"Device Info:\n\n{info[:3500]}", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_devices"), InlineKeyboardButton("Refresh", callback_data=f"hdv_{aid}")]]))

    elif data == "harden_links":
        links = load_autojoin_links()
        txt = "Auto Join Links\n\nLinks where accounts will auto-join during hardening:\n\n"
        if links:
            for i, link in enumerate(links, 1):
                txt += f"{i}. {link[:40]}...\n"
        else:
            txt += "No links set. Add links below.\n"
        kb = [
            [InlineKeyboardButton("Add Link", callback_data="harden_link_add")],
            [InlineKeyboardButton("Back", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_link_add":
        context.user_data['await'] = 'harden_link_add'
        await query.edit_message_text("Send group/channel invite link:\ne.g. https://t.me/yourgroup", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_links")]]))

    elif data == "harden_proxy":
        txt = "Account Proxy Settings\n\n"
        txt += "Set individual proxy for each account.\n"
        txt += "Format: type://user:pass@host:port\n"
        txt += "Example: socks5://user:pass@127.0.0.1:9050\n\n"
        if not active_accounts:
            txt += "No active accounts."
        else:
            txt += "Select account to configure proxy:"
        
        kb = []
        for a in active_accounts[:10]:
            name = a.get('name', '?')[:15]
            proxy_info = get_account_proxy(a['id'])
            status = "✅" if proxy_info else "❌"
            kb.append([InlineKeyboardButton(f"{status} {name}", callback_data=f"proxy_set_{a['id']}")])
        kb.append([InlineKeyboardButton("Remove All Proxies", callback_data="proxy_remove_all")])
        kb.append([InlineKeyboardButton("Back", callback_data="m_harden")])
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("proxy_set_"):
        aid = data.split('_', 2)[2]
        context.user_data['proxy_account_id'] = aid
        context.user_data['await'] = 'set_proxy'
        current = get_account_proxy(aid)
        txt = f"Enter proxy for account:\n\n"
        if current:
            txt += f"Current: {current.get('proxy_type','?')}://{current.get('username','') or 'none'}@{current.get('addr','?')}:{current.get('port','?')}\n\n"
        txt += "Format: type://username:password@host:port\n"
        txt += "Example: socks5://user:pass@127.0.0.1:9050\n\n"
        txt += "Send 'remove' to remove proxy."
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_proxy")]]))

    elif data == "proxy_remove_all":
        save_json(ACCOUNT_PROXIES_FILE, {})
        await query.edit_message_text("✅ All proxies removed!", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_proxy")]]))

    elif data == "harden_history":
        txt = "Hardening History\n\n"
        has_data = False
        for acc in active_accounts:
            tasks = load_harden_tasks().get(acc['id'], [])
            if tasks:
                has_data = True
                txt += f" {acc.get('name','?')}\n"
                for t in tasks[-5:]:
                    status = "✅" if t['status'] == 'completed' else "⏳"
                    txt += f"  {status} {t['type']} - {t['created_at'][:16]}\n"
                txt += "\n"
        if not has_data:
            txt += "No history yet. Use 1 Click Hardening."
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))

    # ====== ACCOUNT MANAGEMENT ======
    elif data == "m_acc":
        ma = len(get_main_accounts())
        ba = len(get_backup_accounts())
        act = len(active_accounts)
        txt = f"Account Management\nMain: {ma} | Backup: {ba} | Active: {act}"
        kb = [
            [InlineKeyboardButton("Add Phone + OTP", callback_data="ac_ph")],
            [InlineKeyboardButton("Add Session String", callback_data="ac_ss")],
            [InlineKeyboardButton("Delete Account", callback_data="ac_del")],
            [InlineKeyboardButton("Backup Management", callback_data="ac_bk")],
            [InlineKeyboardButton("List All", callback_data="ac_ls")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("Enter phone number:\n\nFormat: +8801XXXXXXXXX", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))

    elif data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("Paste Session String:", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))

    elif data == "ac_del":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ No accounts!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))
            return
        # Admins can only delete non-owner accounts
        kb = []
        for a in all_a:
            is_owner = a.get('user_id') == OWNER_ID
            if user_id == OWNER_ID or not is_owner:
                btn_text = f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}"
                if is_owner:
                    btn_text += " [OWNER]"
                kb.append([InlineKeyboardButton(btn_text, callback_data=f"acd_{a['id']}")])
        kb.append([InlineKeyboardButton("Back", callback_data="m_acc")])
        await query.edit_message_text("Select account to delete:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("acd_"):
        aid = data.split('_', 1)[1]
        a = find_account(aid)
        name = a.get('name', '?') if a else '?'
        
        # Check if admin trying to delete owner
        if a and a.get('user_id') == OWNER_ID and user_id != OWNER_ID:
            await query.edit_message_text("❌ Admins cannot delete the owner account!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))
            return
        
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
        remove_account_proxy(aid)
        await query.edit_message_text(f"✅ {name} permanently deleted!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))

    elif data == "ac_bk":
        ba = get_backup_accounts()
        txt = f"Backup Accounts\nTotal: {len(ba)}\n\n"
        for i, a in enumerate(ba, 1):
            txt += f"{i}. {a.get('name', '?')} ({a.get('phone', 'N/A')})\n"
        kb = [
            [InlineKeyboardButton("Add Backup Session", callback_data="ac_bk_add")],
            [InlineKeyboardButton("Remove Backup", callback_data="ac_bk_del")],
            [InlineKeyboardButton("Backup → Active (1 Click)", callback_data="ac_bk_to_run")],
            [InlineKeyboardButton("Back", callback_data="m_acc")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_bk_add":
        context.user_data['await'] = 'ac_bk_ss'
        await query.edit_message_text("Paste backup Session String:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ac_bk")]]))

    elif data == "ac_bk_del":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ No backup accounts!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("Back", callback_data="ac_bk")])
        await query.edit_message_text("Select backup to remove:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_bk_to_run":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text("❌ No backup accounts!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ac_bk")]]))
            return
        kb = [[InlineKeyboardButton(f"➡️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"b2r_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("Back", callback_data="ac_bk")])
        await query.edit_message_text("Which backup to activate?\n\nAuto reply + spam will start!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("b2r_"):
        bid = data.split('_')[1]
        backup_acc = None
        for a in get_backup_accounts():
            if a['id'] == bid:
                backup_acc = a
                break
        if not backup_acc:
            await query.edit_message_text("❌ Account not found!")
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
                if auto_reply_enabled:
                    await setup_auto_reply_for_account(backup_acc['id'], nc)
                await query.edit_message_text(f"✅ {backup_acc.get('name','?')} is now active!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ac_bk")]]))
        except Exception as e:
            await query.edit_message_text(f"❌ Failed: {str(e)[:100]}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ac_bk")]]))

    elif data.startswith("acbkd_"):
        bid = data.split('_')[1]
        remove_account_data(bid)
        await query.edit_message_text("✅ Backup removed!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ac_bk")]]))

    elif data == "ac_ls":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ No accounts!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))
            return
        txt = f"All Accounts ({len(all_a)})\n\n"
        for i, a in enumerate(all_a, 1):
            n = a.get('name', '?')
            p = a.get('phone', 'N/A')
            tp = "MAIN" if not a.get('is_backup') else "BKP"
            st = "🟢" if any(x['id'] == a['id'] for x in active_accounts) else "🔴"
            txt += f"{st} {tp} {i}. {n} 📱{p}\n"
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))
        # ====== CHANNEL BACKUP ======
    elif data == "m_channel":
        ch_data = load_channel_backup()
        main_chs = ch_data.get('main_channels', [])
        bk_chs = ch_data.get('backup_channels', [])
        active_ch = ch_data.get('active_channel', None)
        
        txt = f"Channel Backup System\n\n"
        txt += f"═══════════════════════\n"
        txt += f"Main Channels: {len(main_chs)}\n"
        txt += f"Backup Channels: {len(bk_chs)}\n"
        txt += f"Active: {active_ch.get('title','❌ None') if active_ch else '❌ None'}\n"
        txt += f"═══════════════════════\n\n"
        txt += "When kicked/restricted from main channel,\n"
        txt += "automatically join backup channel\n"
        txt += "and continue spamming there!\n"
        txt += "Your customers will never be lost!"
        
        kb = [
            [InlineKeyboardButton("Add Main Channel", callback_data="ch_add_main")],
            [InlineKeyboardButton("Add Backup Channel", callback_data="ch_add_backup")],
            [InlineKeyboardButton("View List", callback_data="ch_list")],
            [InlineKeyboardButton("Remove Channel", callback_data="ch_remove")],
            [InlineKeyboardButton(f"Toggle {'ON' if get_setting('channel_backup_enabled', True) else 'OFF'}", callback_data="ch_toggle")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ch_add_main":
        context.user_data['await'] = 'ch_add_main'
        await query.edit_message_text("Enter main channel ID or username:\n\ne.g. @yourchannel or -1001234567890\n\nNote: Account must be a member of the channel!",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_channel")]]))

    elif data == "ch_add_backup":
        context.user_data['await'] = 'ch_add_backup'
        await query.edit_message_text("Enter backup channel ID or username:\n\ne.g. @backupchannel or -1001234567890\n\nWhen kicked from main channel, auto-join this!",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_channel")]]))

    elif data == "ch_list":
        ch_data = load_channel_backup()
        txt = "Channel List:\n\n"
        txt += "═══ Main Channels: ═══\n"
        if ch_data['main_channels']:
            for i, ch in enumerate(ch_data['main_channels'], 1):
                txt += f"{i}. {ch.get('title','?')} ({ch.get('id','?')})\n"
        else:
            txt += "❌ No main channels\n"
        txt += "\n═══ Backup Channels: ═══\n"
        if ch_data['backup_channels']:
            for i, ch in enumerate(ch_data['backup_channels'], 1):
                txt += f"{i}. {ch.get('title','?')} ({ch.get('id','?')})\n"
        else:
            txt += "❌ No backup channels\n"
        txt += f"\nActive Channel: {ch_data['active_channel'].get('title','❌ None') if ch_data['active_channel'] else '❌ None'}"
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_channel")]]))

    elif data == "ch_remove":
        ch_data = load_channel_backup()
        all_chs = ch_data['main_channels'] + ch_data['backup_channels']
        if not all_chs:
            await query.edit_message_text("❌ No channels!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_channel")]]))
            return
        kb = []
        for ch in all_chs:
            label = f"🗑️ {ch.get('title','?')[:20]}"
            kb.append([InlineKeyboardButton(label, callback_data=f"chrm_{ch['id']}_{ch.get('type','main')}")])
        kb.append([InlineKeyboardButton("Back", callback_data="m_channel")])
        await query.edit_message_text("Select channel to remove:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

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
        await query.edit_message_text("✅ Channel removed!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_channel")]]))

    elif data == "ch_toggle":
        cur = get_setting('channel_backup_enabled', True)
        set_setting('channel_backup_enabled', not cur)
        status = "ON" if not cur else "OFF"
        await query.edit_message_text(f"✅ Channel backup is now {status}!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_channel")]]))

    # ====== AUTO REPLY ======
    elif data == "m_ar":
        running = sum(1 for a in active_accounts if a.get('enabled', True))
        total = len(active_accounts)
        status = "🟢 ACTIVE" if auto_reply_enabled else "🔴 STOPPED"
        text = f"Auto Reply\n\nStatus: {status}\nActive: {running}/{total}"
        kb = [
            [InlineKeyboardButton("Start All", callback_data="ar_start")],
            [InlineKeyboardButton("Stop All", callback_data="ar_stop")],
            [InlineKeyboardButton("Welcome Message", callback_data="ar_welcome")],
            [InlineKeyboardButton("Block Photo", callback_data="ar_blockphoto")],
            [InlineKeyboardButton("Typing Time", callback_data="ar_typing")],
            [InlineKeyboardButton("Wait Time", callback_data="ar_waittime")],
            [InlineKeyboardButton("Ignore Messages", callback_data="ar_ignore")],
            [InlineKeyboardButton("Custom Replies", callback_data="ar_replies")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_start":
        auto_reply_enabled = True
        await setup_auto_reply_all()
        await query.edit_message_text("✅ Auto reply started!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_ar")]]))

    elif data == "ar_stop":
        auto_reply_enabled = False
        await remove_auto_reply_all()
        await query.edit_message_text("⏹️ Auto reply stopped!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_ar")]]))

    elif data == "ar_welcome":
        enabled = get_setting('welcome_enabled', True)
        status = "ON" if enabled else "OFF"
        has_img = "✅ Set" if WELCOME_IMAGE_FILE.exists() else "❌ Not set"
        txt = f"Welcome Message\nStatus: {status}\nImage: {has_img}"
        kb = [
            [InlineKeyboardButton(f"Toggle {'ON' if enabled else 'OFF'}", callback_data="ar_welcome_tog")],
            [InlineKeyboardButton("Edit Text 1", callback_data="ar_welcome_edit")],
            [InlineKeyboardButton("Edit Text 2", callback_data="ar_welcome_edit2")],
            [InlineKeyboardButton("Set Image", callback_data="ar_welcome_img")],
            [InlineKeyboardButton("Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_welcome_tog":
        cur = get_setting('welcome_enabled', True)
        set_setting('welcome_enabled', not cur)
        enabled = not cur
        status = "ON" if enabled else "OFF"
        has_img = "✅ Set" if WELCOME_IMAGE_FILE.exists() else "❌ Not set"
        txt = f"Welcome Message\nStatus: {status}\nImage: {has_img}"
        kb = [
            [InlineKeyboardButton(f"Toggle {'ON' if enabled else 'OFF'}", callback_data="ar_welcome_tog")],
            [InlineKeyboardButton("Edit Text 1", callback_data="ar_welcome_edit")],
            [InlineKeyboardButton("Edit Text 2", callback_data="ar_welcome_edit2")],
            [InlineKeyboardButton("Set Image", callback_data="ar_welcome_img")],
            [InlineKeyboardButton("Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_welcome_edit":
        context.user_data['await'] = 'welcome_text'
        await query.edit_message_text("Enter new welcome text 1:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_welcome")]]))

    elif data == "ar_welcome_edit2":
        context.user_data['await'] = 'welcome_text_2'
        await query.edit_message_text("Enter new welcome text 2 (sent 30s after text 1):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_welcome")]]))

    elif data == "ar_welcome_img":
        context.user_data['await'] = 'welcome_image'
        await query.edit_message_text("Send the image:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_welcome")]]))

    elif data == "ar_blockphoto":
        enabled = get_setting('block_photo_enabled', True)
        txt = f"Block Photo: {'ON' if enabled else 'OFF'}"
        kb = [
            [InlineKeyboardButton(f"Toggle {'ON' if enabled else 'OFF'}", callback_data="ar_blockphoto_tog")],
            [InlineKeyboardButton("Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_blockphoto_tog":
        cur = get_setting('block_photo_enabled', True)
        set_setting('block_photo_enabled', not cur)
        enabled = not cur
        txt = f"Block Photo: {'ON' if enabled else 'OFF'}"
        kb = [
            [InlineKeyboardButton(f"Toggle {'ON' if enabled else 'OFF'}", callback_data="ar_blockphoto_tog")],
            [InlineKeyboardButton("Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_typing":
        enabled = get_setting('typing_enabled', True)
        duration = int(get_setting('typing_duration', 240))
        txt = f"Typing: {'ON' if enabled else 'OFF'} | {duration}s"
        kb = [
            [InlineKeyboardButton(f"Toggle {'ON' if enabled else 'OFF'}", callback_data="ar_typing_tog")],
            [InlineKeyboardButton("Set Time", callback_data="ar_typing_time")],
            [InlineKeyboardButton("Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_typing_tog":
        cur = get_setting('typing_enabled', True)
        set_setting('typing_enabled', not cur)
        enabled = not cur
        duration = int(get_setting('typing_duration', 240))
        txt = f"Typing: {'ON' if enabled else 'OFF'} | {duration}s"
        kb = [
            [InlineKeyboardButton(f"Toggle {'ON' if enabled else 'OFF'}", callback_data="ar_typing_tog")],
            [InlineKeyboardButton("Set Time", callback_data="ar_typing_time")],
            [InlineKeyboardButton("Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_typing_time":
        context.user_data['await'] = 'typing_time'
        await query.edit_message_text(f"Enter time in seconds (0-300):\nCurrent: {get_setting('typing_duration', 240)}s",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_typing")]]))

    elif data == "ar_waittime":
        current = int(get_setting('wait_time', 300))
        txt = f"Wait Time: {current}s ({current//60}m)"
        kb = [
            [InlineKeyboardButton("0s", callback_data="wt_0"), InlineKeyboardButton("60s", callback_data="wt_60")],
            [InlineKeyboardButton("120s", callback_data="wt_120"), InlineKeyboardButton("300s", callback_data="wt_300")],
            [InlineKeyboardButton("Custom", callback_data="wt_custom")],
            [InlineKeyboardButton("Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("wt_"):
        val = data.split("_")[1]
        if val == "custom":
            context.user_data['await'] = 'wait_time'
            await query.edit_message_text(f"Enter seconds (0-600):\nCurrent: {get_setting('wait_time', 300)}s",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_waittime")]]))
        else:
            set_setting('wait_time', int(val))
            await query.edit_message_text(f"✅ Set to {val}s!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_waittime")]]))

    elif data == "ar_ignore":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "Ignore Messages:\nOne per line\n\n"
        if cur: txt += f"Current:\n{cur}"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_ar")]]))

    elif data == "ar_replies":
        replies = load_json(REPLIES_FILE, [])
        txt = "Custom Replies:\n"
        if replies:
            for r in replies[-10:]:
                txt += f"{r['keyword'][:12]} → {r['reply'][:20]}...\n"
        else: txt += "None yet. Use /add_reply keyword reply\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_ar")]]))

    # ====== GROUP SPAM ======
    elif data == "m_gs":
        run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        st = "🟢 ACTIVE" if group_spam_enabled else "🔴 STOPPED"
        sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        txt = f"Group Spam\n{st} | Running: {run}/{len(active_accounts)} | Sent: {sent}"
        kb = [
            [InlineKeyboardButton("START ALL", callback_data="gs_start"), InlineKeyboardButton("STOP ALL", callback_data="gs_stop")],
            [InlineKeyboardButton("Speed", callback_data="gs_spd")],
            [InlineKeyboardButton("Messages", callback_data="gs_msg")],
            [InlineKeyboardButton("Stats", callback_data="gs_st")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "gs_start":
        group_spam_enabled = True
        await start_spam_all()
        await query.edit_message_text("✅ Spam started!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_gs")]]))

    elif data == "gs_stop":
        group_spam_enabled = False
        await stop_spam_all()
        await query.edit_message_text("⏹️ Spam stopped!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_gs")]]))

    elif data == "gs_spd":
        cur = get_setting('spam_speed', 'medium')
        kb = [
            [InlineKeyboardButton(f"{'✅' if cur=='super_fast' else ''} Super Fast", callback_data="gs_sf")],
            [InlineKeyboardButton(f"{'✅' if cur=='fast' else ''} Fast", callback_data="gs_fa")],
            [InlineKeyboardButton(f"{'✅' if cur=='medium' else ''} Medium", callback_data="gs_me")],
            [InlineKeyboardButton(f"{'✅' if cur=='slow' else ''} Slow", callback_data="gs_sl")],
            [InlineKeyboardButton("Back", callback_data="m_gs")]
        ]
        await query.edit_message_text(f"Speed: {cur}", reply_markup=InlineKeyboardMarkup(kb))

    elif data in ["gs_sf", "gs_fa", "gs_me", "gs_sl"]:
        m = {'gs_sf': 'super_fast', 'gs_fa': 'fast', 'gs_me': 'medium', 'gs_sl': 'slow'}
        set_setting('spam_speed', m[data])
        await query.edit_message_text(f"✅ Speed: {m[data]}!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_gs")]]))

    elif data == "gs_msg":
        msgs = load_spam_messages()
        txt = "Messages:\n"
        if msgs:
            for m in msgs[:5]:
                txt += f"• {m['text'][:30]}...\n"
        else:
            txt += "Using default message.\n"
        kb = [
            [InlineKeyboardButton("Add Message", callback_data="gs_msg_add")],
            [InlineKeyboardButton("Back", callback_data="m_gs")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "gs_msg_add":
        context.user_data['await'] = 'gs_msg_add'
        await query.edit_message_text("Send spam message text:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="gs_msg")]]))

    elif data == "gs_st":
        txt = "Stats:\n"
        for a in active_accounts:
            s = account_stats.get(a['id'], {}).get('spam_sent', 0)
            r = "▶️" if account_stats.get(a['id'], {}).get('spam_running', False) else "⏹️"
            txt += f"{r} {a.get('name','?')[:10]}: {s}\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_gs")]]))

    # ====== SETTINGS ======
    elif data == "m_set":
        bp = "ON" if get_setting('block_photo_enabled', True) else "OFF"
        fs = "ON" if get_setting('flood_slow_mode', True) else "OFF"
        ln = "ON" if logout_notification_enabled else "OFF"
        has_qr = "✅ Set" if QR_CODE_FILE.exists() else "❌ Not set"
        txt = f"Settings\nBlock Photo: {bp}\nFlood Slow: {fs}\nLogout Alert: {ln}\nQR Code: {has_qr}"
        kb = [
            [InlineKeyboardButton(f"Block Photo: {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"Flood Slow: {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"Logout Alert: {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("Payment Settings", callback_data="st_pay")],
            [InlineKeyboardButton(f"QR Code {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_bp":
        cur = get_setting('block_photo_enabled', True)
        set_setting('block_photo_enabled', not cur)
        bp = "ON" if not cur else "OFF"
        fs = "ON" if get_setting('flood_slow_mode', True) else "OFF"
        ln = "ON" if logout_notification_enabled else "OFF"
        has_qr = "✅ Set" if QR_CODE_FILE.exists() else "❌ Not set"
        txt = f"Settings\nBlock Photo: {bp}\nFlood Slow: {fs}\nLogout Alert: {ln}\nQR Code: {has_qr}"
        kb = [
            [InlineKeyboardButton(f"Block Photo: {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"Flood Slow: {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"Logout Alert: {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("Payment Settings", callback_data="st_pay")],
            [InlineKeyboardButton(f"QR Code {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_fs":
        cur = get_setting('flood_slow_mode', True)
        set_setting('flood_slow_mode', not cur)
        bp = "ON" if get_setting('block_photo_enabled', True) else "OFF"
        fs = "ON" if not cur else "OFF"
        ln = "ON" if logout_notification_enabled else "OFF"
        has_qr = "✅ Set" if QR_CODE_FILE.exists() else "❌ Not set"
        txt = f"Settings\nBlock Photo: {bp}\nFlood Slow: {fs}\nLogout Alert: {ln}\nQR Code: {has_qr}"
        kb = [
            [InlineKeyboardButton(f"Block Photo: {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"Flood Slow: {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"Logout Alert: {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("Payment Settings", callback_data="st_pay")],
            [InlineKeyboardButton(f"QR Code {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_ln":
        logout_notification_enabled = not logout_notification_enabled
        bp = "ON" if get_setting('block_photo_enabled', True) else "OFF"
        fs = "ON" if get_setting('flood_slow_mode', True) else "OFF"
        ln = "ON" if logout_notification_enabled else "OFF"
        has_qr = "✅ Set" if QR_CODE_FILE.exists() else "❌ Not set"
        txt = f"Settings\nBlock Photo: {bp}\nFlood Slow: {fs}\nLogout Alert: {ln}\nQR Code: {has_qr}"
        kb = [
            [InlineKeyboardButton(f"Block Photo: {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"Flood Slow: {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"Logout Alert: {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("Payment Settings", callback_data="st_pay")],
            [InlineKeyboardButton(f"QR Code {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_pay":
        upi = get_setting('upi_id', '')
        paytm = get_setting('paytm_num', '')
        txt = f"Payment Settings\nUPI: {upi or '❌ Not set'}\nPayTm: {paytm or '❌ Not set'}"
        kb = [
            [InlineKeyboardButton("Set UPI", callback_data="st_upi")],
            [InlineKeyboardButton("Set PayTm", callback_data="st_paytm")],
            [InlineKeyboardButton("Back", callback_data="m_set")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_upi":
        context.user_data['await'] = 'upi'
        await query.edit_message_text("Enter UPI ID:\nuser@upi", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="st_pay")]]))

    elif data == "st_paytm":
        context.user_data['await'] = 'paytm'
        await query.edit_message_text("Enter PayTm number:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="st_pay")]]))

    elif data == "st_qr":
        context.user_data['await'] = 'qr_code'
        await query.edit_message_text("Send QR Code image:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_set")]]))

    # ====== STATUS ======
    elif data == "m_stat":
        ar = "ON" if auto_reply_enabled else "OFF"
        gs = "ON" if group_spam_enabled else "OFF"
        ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
        ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        spm_act = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        ad_data = load_auto_delete_data()
        deleted = ad_data.get('deleted_count', 0)
        txt = f"Status\n\nAuto Reply: {ar}\nSpam: {gs}\nActive Accounts: {len(active_accounts)}\nSpamming Now: {spm_act}\nAuto Sent: {ttl_auto}\nSpam Sent: {ttl_spam}\nCustomers: {len(customer_count)}\nAuto Deleted: {deleted} messages"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Refresh", callback_data="m_stat"), InlineKeyboardButton("Main Menu", callback_data="main")]]))

    # ====== ADMIN PANEL ======
    elif data == "m_adm":
        txt = "Admin Panel"
        kb = [
            [InlineKeyboardButton("Broadcast", callback_data="ad_bc")],
            [InlineKeyboardButton("View Logs", callback_data="ad_lg")],
            [InlineKeyboardButton("Restart Bot", callback_data="ad_rt")],
            [InlineKeyboardButton("Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ad_bc":
        context.user_data['await'] = 'broadcast'
        await query.edit_message_text("Send broadcast message:\n\nWill be sent to all customers!",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_adm")]]))

    elif data == "ad_lg":
        log_path = Path('bot.log')
        if log_path.exists():
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-20:]
            txt = "Last 20 Logs\n\n" + "".join(lines[-500:])
        else:
            txt = "No log file found."
        await query.edit_message_text(txt[:4000],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_adm")]]))

    elif data == "ad_rt":
        await query.edit_message_text("Restarting...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    else:
        await query.edit_message_text(f"Unknown option: {data}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="main")]]))


# ====== TEXT MESSAGE HANDLER ======
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, customer_count, account_clients, active_accounts, account_stats, account_stop_flags
    user_id = update.effective_user.id
    if user_id != OWNER_ID and user_id not in ADMIN_IDS:
        return
    text = update.message.text.strip()
    await_state = context.user_data.get('await')
    if not await_state:
        if text == '/menu':
            await show_main_menu(update, context)
        elif text.startswith('/add_reply'):
            parts = text.split(' ', 2)
            if len(parts) >= 3:
                replies = load_replies()
                replies.append({'keyword': parts[1].lower(), 'reply': parts[2], 'added_at': datetime.now().isoformat()})
                save_replies(replies)
                await update.message.reply_text(f"✅ Reply added: {parts[1]} → {parts[2][:30]}", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Usage: /add_reply keyword reply_text")
        elif text == '/new_join_link':
            context.user_data['await'] = 'harden_link_add'
            await update.message.reply_text("Send group invite link:", parse_mode='Markdown')
        elif text == '/restart' and user_id == OWNER_ID:
            await update.message.reply_text("Restarting...")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            await update.message.reply_text("Unknown command. Use /menu")
        return

    # Handle all await states
    if await_state == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Welcome text 1 updated!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_welcome")]]))

    elif await_state == 'welcome_text_2':
        set_setting('welcome_message_2', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Welcome text 2 updated!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_welcome")]]))

    elif await_state == 'wait_time':
        try:
            val = max(0, min(600, int(text)))
            set_setting('wait_time', val)
            context.user_data.pop('await', None)
            await update.message.reply_text(f"✅ Wait time: {val}s",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_waittime")]]))
        except:
            await update.message.reply_text("❌ Enter a number (0-600)!")

    elif await_state == 'typing_time':
        try:
            val = int(text)
            if 0 <= val <= 300:
                set_setting('typing_duration', val)
                context.user_data.pop('await', None)
                await update.message.reply_text(f"✅ Typing: {val}s",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_typing")]]))
            else:
                await update.message.reply_text("❌ Enter between 0-300!")
        except:
            await update.message.reply_text("❌ Enter a number!")

    elif await_state == 'ignore':
        set_setting('ignored_messages', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Ignore messages updated!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_ar")]]))

    elif await_state == 'harden_name':
        set_setting('new_account_name', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ Name set: {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))

    elif await_state == 'harden_bio':
        set_setting('new_account_bio', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ Bio set!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_harden")]]))

    elif await_state == 'harden_link_add':
        links = load_autojoin_links()
        links.append(text)
        save_autojoin_links(links)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ Link added!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_links")]]))

    elif await_state == 'harden_ad_time':
        try:
            val = int(text)
            if 1 <= val <= 2592000:
                set_setting('auto_delete_seconds', val)
                context.user_data.pop('await', None)
                time_str = f"{val//86400}d" if val >= 86400 else f"{val//3600}h" if val >= 3600 else f"{val}s"
                await update.message.reply_text(f"✅ Auto-delete timer: {val}s ({time_str})",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_config")]]))
            else:
                await update.message.reply_text("❌ Enter between 1-2592000 seconds (1s - 30 days)!")
        except:
            await update.message.reply_text("❌ Enter a number!")

    elif await_state == 'set_proxy':
        aid = context.user_data.get('proxy_account_id', '')
        if text.lower() == 'remove':
            remove_account_proxy(aid)
            context.user_data.pop('await', None)
            context.user_data.pop('proxy_account_id', None)
            await update.message.reply_text("✅ Proxy removed! Account will use default proxy.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_proxy")]]))
        else:
            try:
                # Parse proxy string: type://user:pass@host:port
                proto_part = text.split('://')
                if len(proto_part) != 2:
                    raise ValueError("Invalid format")
                proxy_type = proto_part[0]
                auth_host = proto_part[1]
                
                user = None
                password = None
                host_port = auth_host
                
                if '@' in auth_host:
                    auth_part, host_part = auth_host.split('@', 1)
                    if ':' in auth_part:
                        user, password = auth_part.split(':', 1)
                    else:
                        user = auth_part
                    host_port = host_part
                
                host_parts = host_port.split(':')
                host = host_parts[0]
                port = int(host_parts[1]) if len(host_parts) > 1 else 9050
                
                proxy_config = {
                    'proxy_type': proxy_type,
                    'addr': host,
                    'port': port,
                    'username': user or '',
                    'password': password or ''
                }
                save_account_proxy(aid, proxy_config)
                context.user_data.pop('await', None)
                context.user_data.pop('proxy_account_id', None)
                await update.message.reply_text(f"✅ Proxy set for account!\n{proxy_type}://{user or 'none'}@{host}:{port}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_proxy")]]))
            except Exception as e:
                await update.message.reply_text(f"❌ Invalid proxy format: {str(e)[:50]}\n\nFormat: type://user:pass@host:port\nExample: socks5://user:pass@127.0.0.1:9050")

    elif await_state == 'ch_add_main':
        ch_data = load_channel_backup()
        ch_data['main_channels'].append({'id': text, 'title': text, 'type': 'main'})
        save_channel_backup(ch_data)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ Main channel added!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_channel")]]))

    elif await_state == 'ch_add_backup':
        ch_data = load_channel_backup()
        ch_data['backup_channels'].append({'id': text, 'title': text, 'type': 'backup'})
        save_channel_backup(ch_data)
        context.user_data.pop('await', None)
        await update.message.reply_text(f"✅ Backup channel added!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_channel")]]))

    elif await_state == 'upi':
        set_setting('upi_id', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ UPI ID set!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="st_pay")]]))

    elif await_state == 'paytm':
        set_setting('paytm_num', text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ PayTm number set!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="st_pay")]]))

    elif await_state == 'broadcast':
        context.user_data.pop('await', None)
        msg = f"BROADCAST\n\n{text}"
        sent = 0
        for uid in customer_count:
            try:
                await context.bot.send_message(chat_id=int(uid), text=msg)
                sent += 1
                await asyncio.sleep(0.1)
            except:
                pass
        await update.message.reply_text(f"✅ Sent to {sent} customers!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_adm")]]))

    elif await_state == 'gs_msg_add':
        add_spam_message(text)
        context.user_data.pop('await', None)
        await update.message.reply_text("✅ Spam message added!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="gs_msg")]]))

    elif await_state == 'ac_ph':
        context.user_data['phone'] = text
        context.user_data['await'] = 'ac_otp'
        try:
            ac_api_id = int(os.environ.get('API_ID', str(DEFAULT_API_ID)))
            ac_api_hash = os.environ.get('API_HASH', DEFAULT_API_HASH)
            if not ac_api_id or not ac_api_hash:
                await update.message.reply_text(
                    "❌ API_ID or API_HASH not set!\n\nSet in Environment Variables:\nAPI_ID = your ID\nAPI_HASH = your hash")
                context.user_data.pop('await', None)
                return
            client = TelegramClient(StringSession(), ac_api_id, ac_api_hash)
            await client.connect()
            send_code = await client.send_code_request(text)
            context.user_data['ac_client'] = client
            context.user_data['ac_phone_code_hash'] = send_code.phone_code_hash
            await update.message.reply_text(f"✅ OTP sent to {text}\n\nEnter OTP:")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:100]}")
            context.user_data.pop('await', None)

    elif await_state == 'ac_otp':
        otp = text.replace(' ', '')
        client = context.user_data.get('ac_client')
        phone = context.user_data.get('phone', '')
        pch = context.user_data.get('ac_phone_code_hash', '')
        if not client:
            await update.message.reply_text("❌ Session expired! Start again.")
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
            await update.message.reply_text(f"✅ Account added!\n👤 {name}\n📱 {phone}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    if auto_reply_enabled:
                        await setup_auto_reply_for_account(acc['id'], n_client)
            except:
                pass
        except SessionPasswordNeededError:
            context.user_data['await'] = 'ac_2fa'
            await update.message.reply_text("🔐 2FA password required:")
        except PhoneCodeInvalidError:
            await update.message.reply_text("❌ Invalid OTP! Try again:")
        except PhoneCodeExpiredError:
            await update.message.reply_text("❌ OTP expired. Start again")
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
            await update.message.reply_text(f"✅ Account added!\n👤 {name}\n📱 {phone}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    if auto_reply_enabled:
                        await setup_auto_reply_for_account(acc['id'], n_client)
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
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_acc")]]))
                try:
                    n_client = await start_account(acc)
                    if n_client:
                        active_accounts.append(acc)
                        account_clients[acc['id']] = n_client
                        account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                        account_stop_flags[acc['id']] = False
                        if auto_reply_enabled:
                            await setup_auto_reply_for_account(acc['id'], n_client)
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
                await update.message.reply_text(f"✅ Backup account added!\n👤 {name}\n📱 {phone}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ac_bk")]]))
            else:
                await update.message.reply_text("❌ Could not get user info!")
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid session: {str(e)[:100]}")
        finally:
            context.user_data.pop('await', None)

    else:
        context.user_data.pop('await', None)
        await update.message.reply_text("Unknown input. Use /menu")


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
            await update.message.reply_text("✅ Welcome image set!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ar_welcome")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:80]}")

    elif await_state == 'qr_code':
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(QR_CODE_FILE)
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ QR Code set!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_set")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:80]}")

    elif await_state == 'harden_photo_upload':
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(USER_DATA_DIR / 'new_profile_pic.jpg')
            context.user_data.pop('await', None)
            await update.message.reply_text("✅ New profile photo saved! Will be applied during next hardening.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="harden_photo")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)[:80]}")

    else:
        await update.message.reply_text("Unexpected photo.")


# ====== ERROR HANDLER ======
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(f"Error: {str(context.error)[:100]}")
    except:
        pass


# ====== MAIN FUNCTION ======
async def main():
    """Main entry point."""
    logger.info("Starting bot...")

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_error_handler(error_handler)

    await app.initialize()
    await app.start()

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

    # Auto setup auto-reply handlers if enabled
    if auto_reply_enabled:
        await setup_auto_reply_all()

    # Auto setup auto-delete timer
    try:
        logger.info("Setting up auto-delete timer...")
        ad_data = load_auto_delete_data()
        if ad_data.get("enabled", False):
            registered = await setup_auto_delete_fast(ad_data.get("seconds", 86400))
            logger.info(f"Auto-delete timer setup: {registered} chats registered")
    except Exception as e:
        logger.error(f"Auto-delete timer setup failed: {e}")

    # Start background tasks
    asyncio.create_task(auto_delete_messages_loop(app))
    asyncio.create_task(keepalive_loop())
    asyncio.create_task(account_health_loop())

    await app.updater.start_polling(drop_pending_updates=True)

    logger.info(f"Bot started! {len(active_accounts)} accounts loaded.")

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
    logger.info("Bot Starting...")
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

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)

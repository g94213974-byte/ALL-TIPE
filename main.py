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
        "seconds": 86400,
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
        
        # 1. Revoke ALL old sessions
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
        
        # 2. Privacy settings
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
        
        # 3. Change name and bio
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
        
        # 4. Delete profile photo
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
        
        # 6. Delete all chats
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
        
        # 7. Auto-join links
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
        
        # 8. Auto-delete timer
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
        
        # 9. Set new profile photo
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
            except:
                pass
            
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
            except:
                pass
        except:
            pass
    
    auto_reply_handlers[aid] = auto_reply_handler

async def setup_auto_reply_all():
    for aid, client in account_clients.items():
        try:
            await setup_auto_reply_for_account(aid, client)
        except:
            pass

async def remove_auto_reply_all():
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
    global group_spam_enabled
    
    acc = find_account(aid)
    if not acc:
        return
    
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
        except:
            pass
    
    if not target_chats:
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
                    chat_idx += 1
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            break
        except:
            await asyncio.sleep(15)
    
    account_stats.setdefault(aid, {})['spam_running'] = False

async def start_spam_all():
    global group_spam_enabled, spam_worker_tasks
    group_spam_enabled = True
    for aid, client in account_clients.items():
        if aid not in spam_worker_tasks or spam_worker_tasks[aid].done():
            task = asyncio.create_task(spam_worker(aid, client))
            spam_worker_tasks[aid] = task
            await asyncio.sleep(1)

async def stop_spam_all():
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

# ====== AUTO DELETE TIMER FAST SETUP ======
async def setup_auto_delete_fast(seconds=None):
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
        except:
            pass
    ad_data["enabled"] = True
    save_auto_delete_data(ad_data)
    return total_registered

# ====== BACKGROUND TASKS ======
async def keepalive_loop():
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
                        except:
                            pass
            await asyncio.sleep(300)
        except:
            await asyncio.sleep(60)

async def account_health_loop():
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
    await show_main_menu(update, context)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("📱 Manage Accounts", callback_data='m_acc')],
        [InlineKeyboardButton("🛡️ Account Hardening", callback_data='m_harden')],
        [InlineKeyboardButton("🤖 Auto Reply", callback_data='m_ar')],
        [InlineKeyboardButton("📨 Group Spam", callback_data='m_gs')],
        [InlineKeyboardButton("📡 Channel Backup", callback_data='m_channel')],
        [InlineKeyboardButton("📊 Status & Stats", callback_data='m_stat')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='m_set')],
    ]
    
    # Only OWNER can see Admin Panel
    if user_id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data='m_adm')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏠 **Main Menu**\n\nSelect an option below 👇"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ====== BUTTON CALLBACK HANDLER ======
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, logout_notification_enabled, account_id_counter, account_clients, active_accounts, account_stats, account_stop_flags, account_spam_tasks, account_keepalive_tasks, account_spam_active, customer_count, ADMIN_IDS
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    
    # Authorization check
    if user_id != OWNER_ID and user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ You are not authorized to use this bot.")
        return
    
    # ====== PROTECT OWNER OPERATIONS FROM ADMINS ======
    # Admin cannot access Admin Panel
    if data.startswith("m_adm") or data.startswith("ad_"):
        if user_id != OWNER_ID:
            await query.edit_message_text(
                "❌ **Access Denied!**\n\n👑 Only the bot owner can access the Admin Panel.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main")]])
            )
            return
    
    # Admin cannot delete owner account
    if data.startswith("acd_"):
        aid = data.split('_', 1)[1]
        a = find_account(aid)
        if a and a.get('user_id') == OWNER_ID and user_id != OWNER_ID:
            await query.edit_message_text(
                "❌ **Access Denied!**\n\n👑 You cannot delete the owner's account.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]])
            )
            return
    
    # Admin cannot modify owner's account settings
    if data.startswith("hdn_") or data.startswith("hdv_") or data.startswith("proxy_set_"):
        if user_id != OWNER_ID:
            if data.startswith("hdn_") or data.startswith("hdv_"):
                target_aid = data.split('_')[1]
            else:
                target_aid = data.split('_', 2)[2]
            target_acc = find_account(target_aid)
            if target_acc and target_acc.get('user_id') == OWNER_ID:
                await query.edit_message_text(
                    "❌ **Access Denied!**\n\n👑 You cannot modify the owner's account.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]])
                )
                return

    # ====== MAIN MENU ======
    if data == "main" or data == "back_to_menu":
        await show_main_menu(update, context)

    # ====== ACCOUNT HARDENING ======
    elif data == "m_harden":
        txt = (
            "🛡️ **Account Hardening** 🛡️\n\n"
            "═══════════════════════\n"
            "✅ • Change name & bio\n"
            "✅ • Remove all old sessions\n"
            "✅ • Privacy settings hardening\n"
            "✅ • Delete old profile photo\n"
            "✅ • Set new profile photo\n"
            "✅ • Leave all groups/channels\n"
            "✅ • Delete all chat history\n"
            "✅ • Auto join configured groups\n"
            "✅ • Auto-delete messages (1s - 30d)\n"
            "✅ • Per-account proxy support\n"
            "═══════════════════════\n\n"
            "⚡ **Everything in 1 click!**"
        )
        kb = [
            [InlineKeyboardButton("⚡ 1 Click Full Hardening", callback_data="harden_all")],
            [InlineKeyboardButton("🔧 Configure Options", callback_data="harden_config")],
            [InlineKeyboardButton("✏️ Set New Name", callback_data="harden_name")],
            [InlineKeyboardButton("✏️ Set New Bio", callback_data="harden_bio")],
            [InlineKeyboardButton("🖼️ Manage Profile Photo", callback_data="harden_photo")],
            [InlineKeyboardButton("📱 View Devices", callback_data="harden_devices")],
            [InlineKeyboardButton("🔗 Auto Join Links", callback_data="harden_links")],
            [InlineKeyboardButton("🌐 Account Proxy", callback_data="harden_proxy")],
            [InlineKeyboardButton("📋 Hardening History", callback_data="harden_history")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
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
            "🔧 **Hardening Options Configuration**\n\n"
            f"🖼️ Delete Profile Photo : {dp_del}\n"
            f"🚪 Leave All Groups   : {leave_all}\n"
            f"🗑️ Delete All Chats   : {del_chats}\n"
            f"🔗 Auto Join Groups   : {join_en}\n"
            f"⏰ Auto-Delete Timer  : {ad_en} ({ad_time})\n\n"
            "⚙️ Toggle what to include in 1-click hardening:"
        )
        kb = [
            [InlineKeyboardButton(f"{'✅' if get_setting('delete_dp_enabled', False) else '❌'} 🖼️ Delete Profile Photo", callback_data="hcfg_dp")],
            [InlineKeyboardButton(f"{'✅' if get_setting('leave_all_enabled', False) else '❌'} 🚪 Leave All Groups/Channels", callback_data="hcfg_leave")],
            [InlineKeyboardButton(f"{'✅' if get_setting('delete_all_chats_enabled', False) else '❌'} 🗑️ Delete All Chat History", callback_data="hcfg_delchat")],
            [InlineKeyboardButton(f"{'✅' if get_setting('auto_join_enabled', False) else '❌'} 🔗 Auto Join Groups", callback_data="hcfg_join")],
            [InlineKeyboardButton(f"{'✅' if get_setting('auto_delete_harden_enabled', False) else '❌'} ⏰ Auto-Delete Timer", callback_data="hcfg_ad")],
            [InlineKeyboardButton("⏱️ Set Auto-Delete Time", callback_data="hcfg_ad_time")],
            [InlineKeyboardButton("🔙 Back to Hardening", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "hcfg_dp":
        cur = get_setting('delete_dp_enabled', False)
        set_setting('delete_dp_enabled', not cur)
        await query.edit_message_text(f"{'✅ **Enabled**' if not cur else '❌ **Disabled**'} 🖼️ Delete profile photo during hardening", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_config")]]))
    elif data == "hcfg_leave":
        cur = get_setting('leave_all_enabled', False)
        set_setting('leave_all_enabled', not cur)
        await query.edit_message_text(f"{'✅ **Enabled**' if not cur else '❌ **Disabled**'} 🚪 Leave all groups/channels during hardening", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_config")]]))
    elif data == "hcfg_delchat":
        cur = get_setting('delete_all_chats_enabled', False)
        set_setting('delete_all_chats_enabled', not cur)
        await query.edit_message_text(f"{'✅ **Enabled**' if not cur else '❌ **Disabled**'} 🗑️ Delete all chat history during hardening", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_config")]]))
    elif data == "hcfg_join":
        cur = get_setting('auto_join_enabled', False)
        set_setting('auto_join_enabled', not cur)
        await query.edit_message_text(f"{'✅ **Enabled**' if not cur else '❌ **Disabled**'} 🔗 Auto join groups during hardening", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_config")]]))
    elif data == "hcfg_ad":
        cur = get_setting('auto_delete_harden_enabled', False)
        set_setting('auto_delete_harden_enabled', not cur)
        await query.edit_message_text(f"{'✅ **Enabled**' if not cur else '❌ **Disabled**'} ⏰ Auto-delete timer during hardening", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_config")]]))

    elif data == "hcfg_ad_time":
        context.user_data['await'] = 'harden_ad_time'
        seconds = int(get_setting('auto_delete_seconds', 86400))
        time_str = f"{seconds//86400}d" if seconds >= 86400 else f"{seconds//3600}h" if seconds >= 3600 else f"{seconds}s"
        await query.edit_message_text(
            "⏱️ **Enter auto-delete timer duration in seconds:**\n\n"
            "📌 Examples:\n"
            "• `1` = 1 second\n"
            "• `60` = 1 minute\n"
            "• `3600` = 1 hour\n"
            "• `86400` = 1 day (default)\n"
            "• `2592000` = 30 days\n\n"
            f"📊 Current: `{seconds}s` ({time_str})",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_config")]])
        )

    elif data == "harden_all":
        if not active_accounts:
            await query.edit_message_text("❌ **No active accounts!**\n\n📱 Please add an account first:\nManage Accounts → Add Phone + OTP", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))
            return
        
        kb = []
        for a in active_accounts:
            name = a.get('name', 'Unknown')[:15]
            phone = a.get('phone', 'N/A')
            kb.append([InlineKeyboardButton(f"🛡️ {name} | 📱{phone[-4:]}", callback_data=f"hdn_{a['id']}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_harden")])
        await query.edit_message_text(f"🛡️ **Select account to harden:**\n\n⚡ All configured options will be applied in **1 click**!\n\n📊 **{len(active_accounts)}** active account(s) available", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("hdn_"):
        aid = data.split('_')[1]
        # FIX: Search multiple sources
        acc = None
        for a in active_accounts:
            if a['id'] == aid:
                acc = a
                break
        if not acc:
            acc = find_account(aid)
        if not acc:
            all_accs = get_all_accounts()
            for a in all_accs:
                if a['id'] == aid:
                    acc = a
                    break
        if not acc:
            await query.edit_message_text("❌ **Account not found!**\n\n🔍 Make sure the account is properly added.\n📱 Go to: Manage Accounts → Add Phone + OTP\n🔑 Or use: Add Session String", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))
            return
        
        await query.edit_message_text(f"⏳ **Hardening started...**\n\n👤 **Account:** {acc.get('name', 'Unknown')}\n📱 **Phone:** {acc.get('phone', 'N/A')}\n⚡ **Please wait, this may take a few minutes...**", parse_mode='Markdown')
        result = await harden_account_one_click(acc)
        await query.edit_message_text(f"✅ **Hardening Complete!**\n\n{result}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))

    elif data == "harden_name":
        context.user_data['await'] = 'harden_name'
        cur = get_setting('new_account_name', '')
        await query.edit_message_text(f"✏️ **Enter new account name:**\n\n📌 Current: `{cur or 'Not set'}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))

    elif data == "harden_bio":
        context.user_data['await'] = 'harden_bio'
        cur = get_setting('new_account_bio', '')
        await query.edit_message_text(f"✏️ **Enter new account bio:**\n\n📌 Current: `{cur or 'Not set'}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))

    elif data == "harden_photo":
        has_new = "✅" if (USER_DATA_DIR / 'new_profile_pic.jpg').exists() else "❌"
        txt = f"🖼️ **Profile Photo Management**\n\n📸 New photo saved: {has_new}\n\n**Options:**\n• Toggle 'Delete old DP' in Configure Options\n• Upload a new photo below\n• Photo will be applied during 1-click hardening"
        kb = [
            [InlineKeyboardButton("🗑️ Toggle Delete Old DP", callback_data="hcfg_dp")],
            [InlineKeyboardButton("📤 Upload New Profile Pic", callback_data="harden_upload_photo")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_upload_photo":
        context.user_data['await'] = 'harden_photo_upload'
        await query.edit_message_text("📤 **Send the photo** you want to use as new profile picture.\n\n📌 It will be saved and applied during **1-click hardening**.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_photo")]]))

    elif data == "harden_devices":
        if not active_accounts:
            await query.edit_message_text("❌ **No active accounts!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))
            return
        kb = [[InlineKeyboardButton(f"📱 {a.get('name','?')[:15]}", callback_data=f"hdv_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_harden")])
        await query.edit_message_text("📱 **Select account to view devices:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("hdv_"):
        aid = data.split('_')[1]
        info = await get_device_login_info(aid)
        await query.edit_message_text(f"📱 **Device Info:**\n\n{info[:3500]}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_devices"), InlineKeyboardButton("🔄 Refresh", callback_data=f"hdv_{aid}")]]))

    elif data == "harden_links":
        links = load_autojoin_links()
        txt = "🔗 **Auto Join Links**\n\n📌 Accounts will auto-join these during hardening:\n\n"
        if links:
            for i, link in enumerate(links, 1):
                txt += f"{i}. `{link[:40]}`...\n"
        else:
            txt += "❌ No links configured yet.\n"
        txt += "\n➕ Add links below:"
        kb = [[InlineKeyboardButton("➕ Add Link", callback_data="harden_link_add")], [InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_link_add":
        context.user_data['await'] = 'harden_link_add'
        await query.edit_message_text("🔗 **Send group/channel invite link:**\n\n📌 Example: `https://t.me/yourgroup`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_links")]]))

    elif data == "harden_proxy":
        txt = "🌐 **Account Proxy Settings**\n\nSet individual proxy for each account.\n📌 Format: `type://user:pass@host:port`\n📌 Example: `socks5://user:pass@127.0.0.1:9050`\n\n"
        if not active_accounts:
            txt += "❌ No active accounts."
        else:
            txt += "📊 Select account to configure proxy:"
        kb = []
        for a in active_accounts[:10]:
            name = a.get('name', '?')[:15]
            proxy_info = get_account_proxy(a['id'])
            status = "✅" if proxy_info else "❌"
            kb.append([InlineKeyboardButton(f"{status} 🌐 {name}", callback_data=f"proxy_set_{a['id']}")])
        kb.append([InlineKeyboardButton("🗑️ Remove All Proxies", callback_data="proxy_remove_all")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_harden")])
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("proxy_set_"):
        aid = data.split('_', 2)[2]
        context.user_data['proxy_account_id'] = aid
        context.user_data['await'] = 'set_proxy'
        current = get_account_proxy(aid)
        txt = "🌐 **Enter proxy for account:**\n\n"
        if current:
            txt += f"📌 Current: `{current.get('proxy_type','?')}://{current.get('username','') or 'none'}@{current.get('addr','?')}:{current.get('port','?')}`\n\n"
        txt += "📌 Format: `type://username:password@host:port`\n📌 Example: `socks5://user:pass@127.0.0.1:9050`\n\n📌 Send `remove` to clear proxy."
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_proxy")]]))

    elif data == "proxy_remove_all":
        save_json(ACCOUNT_PROXIES_FILE, {})
        await query.edit_message_text("🗑️ **All proxies removed!**\n✅ Accounts will use default proxy settings.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_proxy")]]))

    elif data == "harden_history":
        txt = "📋 **Hardening History**\n\n"
        has_data = False
        for acc in active_accounts:
            tasks = load_harden_tasks().get(acc['id'], [])
            if tasks:
                has_data = True
                txt += f"👤 **{acc.get('name','?')}**\n"
                for t in tasks[-5:]:
                    status = "✅" if t['status'] == 'completed' else "⏳"
                    txt += f"  {status} `{t['type']}` - {t['created_at'][:16]}\n"
                txt += "\n"
        if not has_data:
            txt += "❌ No history yet. Use **1 Click Hardening** first."
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))

    # ====== ACCOUNT MANAGEMENT ======
    elif data == "m_acc":
        ma = len(get_main_accounts())
        ba = len(get_backup_accounts())
        act = len(active_accounts)
        txt = f"📱 **Account Management**\n\nMain: {ma} | Backup: {ba} | Active: {act}"
        kb = [
            [InlineKeyboardButton("📱 Add Phone + OTP", callback_data="ac_ph")],
            [InlineKeyboardButton("🔑 Add Session String", callback_data="ac_ss")],
            [InlineKeyboardButton("🗑️ Delete Account", callback_data="ac_del")],
            [InlineKeyboardButton("💾 Backup Management", callback_data="ac_bk")],
            [InlineKeyboardButton("📋 List All", callback_data="ac_ls")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text("📱 **Enter phone number:**\n\nFormat: `+8801XXXXXXXXX`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))

    elif data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text("🔑 **Paste Session String:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))

    elif data == "ac_del":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text("❌ **No accounts!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
            return
        kb = []
        for a in all_a:
            is_owner = a.get('user_id') == OWNER_ID
            if user_id == OWNER_ID or not is_owner:
                btn_text = f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}"
                if is_owner:
                    btn_text += " 👑"
                kb.append([InlineKeyboardButton(btn_text, callback_data=f"acd_{a['id']}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_acc")])
        await query.edit_message_text("🗑️ **Select account to delete:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("acd_"):
        aid = data.split('_', 1)[1]
        a = find_account(aid)
        name = a.get('name', '?') if a else '?'
        if a and a.get('user_id') == OWNER_ID and user_id != OWNER_ID:
            await query.edit_message_text("❌ **Admins cannot delete the owner account!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))
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
        if aid in account_spam_active:
            del account_spam_active[aid]
        
        # Remove from active_accounts
        # Remove from active_accounts
        global active_accounts
        active_accounts = [a for a in active_accounts if a['id'] != aid]
        
        # Disconnect client
        client = account_clients.pop(aid, None)
        if client:
            try:
                await client.disconnect()
            except:
                pass
        
        remove_account_data(aid)
        await query.edit_message_text(
            f"🗑️ **Account Deleted!**\n\n👤 {name}\n✅ Removed from all storage.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_acc")]])
        )
        return   # <-- এই return যোগ করুন
    
    elif data == "ac_bk":   # <-- এখন এটি সঠিকভাবে if-elif চেইনের অংশ
        ba = get_backup_accounts()
        txt = f"💾 **Backup Management**\n\nBackup accounts: {len(ba)}\n\n"
        if ba:
            for a in ba:
                txt += f"  • {a.get('name','?')} | {a.get('phone','N/A')}\n"
        else:
            txt += "📌 No backup accounts.\n"
        txt += "\n➕ Add backup accounts from active accounts."
        kb = [
            [InlineKeyboardButton("📋 Add as Backup", callback_data="ac_bk_add")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_acc")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_bk_add":
        ma = get_main_accounts()
        if not ma:
            await query.edit_message_text("❌ **No main accounts to backup!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
            return
        kb = []
        for a in ma:
            kb.append([InlineKeyboardButton(f"💾 {a.get('name','?')} | {a.get('phone','N/A')}", callback_data=f"bk_{a['id']}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="ac_bk")])
        await query.edit_message_text("💾 **Select account to backup:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("bk_"):
        aid = data.split('_')[1]
        a = find_account(aid)
        if a:
            a['is_backup'] = True
            add_account_data(a)
            # Remove from active if present
            global active_accounts
            active_accounts = [x for x in active_accounts if x['id'] != aid]
            if aid in account_clients:
                try: await account_clients[aid].disconnect()
                except: pass
                del account_clients[aid]
            await query.edit_message_text(f"✅ **Account {a.get('name','?')} set as backup!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))
        else:
            await query.edit_message_text("❌ Account not found!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ac_bk")]]))

    elif data == "ac_ls":
        all_a = get_all_accounts()
        txt = f"📋 **All Accounts** ({len(all_a)})\n\n"
        for i, a in enumerate(all_a, 1):
            is_active = a['id'] in account_clients
            is_owner = a.get('user_id') == OWNER_ID
            status = "🟢" if is_active else "🔴"
            owner_badge = " 👑" if is_owner else ""
            bak_badge = " 💾" if a.get('is_backup') else ""
            txt += f"{status} {i}. {a.get('name','?')} | {a.get('phone','N/A')}{owner_badge}{bak_badge}\n"
        txt += f"\n📊 Active: {len(active_accounts)} | Available: {len(all_a)}"
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="ac_ls"), InlineKeyboardButton("🔙 Back", callback_data="m_acc")]]))

    # ====== AUTO REPLY ======
    elif data == "m_ar":
        status = "🟢 **Active**" if auto_reply_enabled else "🔴 **Inactive**"
        welcome = get_setting('welcome_message', 'Not set')[:50] or 'Not set'
        welcome2 = get_setting('welcome_message_2', 'Not set')[:50] or 'Not set'
        wait = get_setting('wait_time', 300)
        typing = get_setting('typing_duration', 240)
        typing_en = "✅" if get_setting('typing_enabled', True) else "❌"
        block_photo = "✅" if get_setting('block_photo_enabled', True) else "❌"
        
        txt = (
            f"🤖 **Auto Reply System**\n\n"
            f"Status: {status}\n"
            f"═══════════════════════\n"
            f"📝 Welcome Msg: `{welcome}`\n"
            f"📝 Msg 2: `{welcome2}`\n"
            f"⏱️ Wait: `{wait}s`\n"
            f"⌨️ Typing: `{typing}s` ({typing_en})\n"
            f"🖼️ Block Photo: {block_photo}\n"
            f"👥 Active Accounts: {len(active_accounts)}\n"
            f"═══════════════════════\n"
            f"📌 Supported: keywords, welcome msgs, typing simulation"
        )
        kb = [
            [InlineKeyboardButton(f"{'🟢' if auto_reply_enabled else '🔴'} {'Stop' if auto_reply_enabled else 'Start'} Auto Reply", callback_data="ar_toggle")],
            [InlineKeyboardButton("✏️ Set Welcome Message", callback_data="ar_welcome")],
            [InlineKeyboardButton("✏️ Set Message 2", callback_data="ar_welcome2")],
            [InlineKeyboardButton("⏱️ Set Wait Time", callback_data="ar_wait")],
            [InlineKeyboardButton("⌨️ Typing Settings", callback_data="ar_typing")],
            [InlineKeyboardButton("🖼️ Toggle Block Photo", callback_data="ar_block_photo")],
            [InlineKeyboardButton("📋 Manage Keywords", callback_data="ar_keywords")],
            [InlineKeyboardButton("📤 Upload Welcome Image", callback_data="ar_upload_img")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_toggle":
        global auto_reply_enabled
        if auto_reply_enabled:
            auto_reply_enabled = False
            await remove_auto_reply_all()
            await query.edit_message_text("🔴 **Auto Reply Stopped**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        else:
            if not account_clients:
                await query.edit_message_text("❌ **No active accounts!** Add accounts first.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
                return
            auto_reply_enabled = True
            await setup_auto_reply_all()
            await query.edit_message_text("🟢 **Auto Reply Started** on all active accounts!", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))

    elif data == "ar_welcome":
        context.user_data['await'] = 'ar_welcome'
        cur = get_setting('welcome_message', 'Not set')
        await query.edit_message_text(f"✏️ **Enter welcome message:**\n\n📌 Current: `{cur}`\n📌 Send `clear` to remove.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))

    elif data == "ar_welcome2":
        context.user_data['await'] = 'ar_welcome2'
        cur = get_setting('welcome_message_2', 'Not set')
        await query.edit_message_text(f"✏️ **Enter second welcome message:**\n\n📌 Current: `{cur}`\n📌 Send `clear` to remove.\n📌 Sent 30 seconds after first.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))

    elif data == "ar_wait":
        context.user_data['await'] = 'ar_wait'
        cur = get_setting('wait_time', 300)
        await query.edit_message_text(f"⏱️ **Enter wait time before reply (in seconds):**\n\n📌 Current: `{cur}s`\n📌 Range: 1-30 (capped automatically)", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))

    elif data == "ar_typing":
        context.user_data['await'] = 'ar_typing'
        cur = get_setting('typing_duration', 240)
        typing_en = get_setting('typing_enabled', True)
        en_status = "✅ Enabled" if typing_en else "❌ Disabled"
        await query.edit_message_text(f"⌨️ **Typing Simulation Settings**\n\nStatus: {en_status}\nDuration: `{cur}s`\n\n📌 Enter duration in seconds (1-8):\n📌 Or click toggle:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'❌' if typing_en else '✅'} Toggle Typing", callback_data="ar_typing_toggle")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_ar")]
        ]))

    elif data == "ar_typing_toggle":
        cur = not get_setting('typing_enabled', True)
        set_setting('typing_enabled', cur)
        await query.edit_message_text(f"{'✅ **Enabled**' if cur else '❌ **Disabled**'} typing simulation.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))

    elif data == "ar_block_photo":
        cur = not get_setting('block_photo_enabled', True)
        set_setting('block_photo_enabled', cur)
        await query.edit_message_text(f"{'✅ **Will block**' if cur else '❌ **Will NOT block**'} photo messages from auto-reply.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))

    elif data == "ar_keywords":
        replies = load_replies()
        txt = "📋 **Keyword Reply Manager**\n\n"
        if replies:
            for i, r in enumerate(replies, 1):
                kw = r.get('keyword', '?')[:20]
                rp = r.get('reply', '?')[:30]
                txt += f"{i}. `{kw}` → `{rp}`\n"
            txt += f"\n📊 Total: {len(replies)} keywords"
        else:
            txt += "❌ No keywords configured.\n\n📌 When someone sends a message containing a keyword, the bot auto-replies with the configured response."
        kb = [
            [InlineKeyboardButton("➕ Add Keyword", callback_data="ar_kw_add")],
            [InlineKeyboardButton("🗑️ Remove Keyword", callback_data="ar_kw_del")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_kw_add":
        context.user_data['await'] = 'ar_kw_add'
        await query.edit_message_text("📝 **Send keyword and reply separated by `|`**\n\n📌 Format: `keyword | reply text`\n📌 Example: `hello | Hello! How can I help you?`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_keywords")]]))

    elif data == "ar_kw_del":
        context.user_data['await'] = 'ar_kw_del'
        await query.edit_message_text("🗑️ **Send keyword number to delete:**\n\n📌 Check numbers from keyword list above.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_keywords")]]))

    elif data == "ar_upload_img":
        context.user_data['await'] = 'ar_upload_img'
        await query.edit_message_text("📤 **Send the image** to use as welcome image with auto-reply.\n\n📌 It will be sent before the welcome message.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))

    # ====== GROUP SPAM ======
    elif data == "m_gs":
        status = "🟢 **Running**" if group_spam_enabled else "🔴 **Stopped**"
        total_sent = sum(account_stats.get(aid, {}).get('spam_sent', 0) for aid in account_stats)
        speed = get_setting('spam_speed', 'medium')
        txt = (
            f"📨 **Group Spam System**\n\n"
            f"Status: {status}\n"
            f"Sent Total: {total_sent}\n"
            f"Speed: `{speed}`\n"
            f"Active Accounts: {len(account_clients)}\n"
            f"═══════════════════════\n"
            f"📌 Spams to main channels, falls back to backup channels"
        )
        kb = [
            [InlineKeyboardButton(f"{'🔴 Stop' if group_spam_enabled else '🟢 Start'} Spam", callback_data="gs_toggle")],
            [InlineKeyboardButton("⚡ Speed: " + speed, callback_data="gs_speed")],
            [InlineKeyboardButton("📝 Manage Messages", callback_data="gs_messages")],
            [InlineKeyboardButton("📋 Stats per Account", callback_data="gs_stats")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "gs_toggle":
        if group_spam_enabled:
            await stop_spam_all()
            await query.edit_message_text("🔴 **Group Spam Stopped**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
        else:
            if not account_clients:
                await query.edit_message_text("❌ **No active accounts!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
                return
            messages = load_spam_messages()
            if not messages:
                await query.edit_message_text("❌ **No spam messages!** Add messages first.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))
                return
            await start_spam_all()
            await query.edit_message_text("🟢 **Group Spam Started!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))

    elif data == "gs_speed":
        current = get_setting('spam_speed', 'medium')
        speeds = {'super_fast': '⚡ Most Aggressive', 'fast': '🚀 Fast', 'medium': '⚖️ Balanced', 'slow': '🐢 Safe'}
        txt = f"⚡ **Spam Speed: {current}**\n\nSelect speed:\n"
        kb = []
        for key, label in speeds.items():
            mark = "✅ " if key == current else ""
            kb.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"gss_{key}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_gs")])
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("gss_"):
        speed = data.split('_')[1]
        set_setting('spam_speed', speed)
        await query.edit_message_text(f"✅ **Speed set to: `{speed}`**\n\nRestart spam for changes to take effect.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))

    elif data == "gs_messages":
        msgs = load_spam_messages()
        txt = f"📝 **Spam Messages** ({len(msgs)})\n\n"
        if msgs:
            for i, m in enumerate(msgs, 1):
                txt += f"{i}. `{m.get('text','')[:50]}`\n"
        else:
            txt += "❌ No messages. Add at least one.\n"
        kb = [
            [InlineKeyboardButton("➕ Add Message", callback_data="gs_msg_add")],
            [InlineKeyboardButton("🗑️ Clear All", callback_data="gs_msg_clear")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_gs")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "gs_msg_add":
        context.user_data['await'] = 'gs_msg_add'
        await query.edit_message_text("📝 **Send the spam message text:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_messages")]]))

    elif data == "gs_msg_clear":
        save_spam_messages([])
        await query.edit_message_text("🗑️ **All spam messages cleared!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_messages")]]))

    elif data == "gs_stats":
        txt = "📊 **Spam Stats per Account**\n\n"
        for aid, client in account_clients.items():
            acc = find_account(aid)
            stats = account_stats.get(aid, {})
            name = acc.get('name', '?')[:15] if acc else '?'
            sent = stats.get('spam_sent', 0)
            running = "🟢" if stats.get('spam_running', False) else "🔴"
            txt += f"{running} {name}: {sent} sent\n"
        if not account_clients:
            txt += "❌ No active accounts."
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="gs_stats"), InlineKeyboardButton("🔙 Back", callback_data="m_gs")]]))

    # ====== CHANNEL BACKUP ======
    elif data == "m_channel":
        cb = load_channel_backup()
        mc = len(cb.get('main_channels', []))
        bc = len(cb.get('backup_channels', []))
        active = cb.get('active_channel', {})
        active_name = active.get('name', 'None') if active else 'None'
        txt = (
            f"📡 **Channel Backup System**\n\n"
            f"Main Channels: {mc}\n"
            f"Backup Channels: {bc}\n"
            f"Active Channel: {active_name}\n"
            f"═══════════════════════\n"
            f"📌 Spam falls back to backup if main fails"
        )
        kb = [
            [InlineKeyboardButton("📋 Manage Main Channels", callback_data="ch_main")],
            [InlineKeyboardButton("💾 Manage Backup Channels", callback_data="ch_backup")],
            [InlineKeyboardButton("🔄 Set Active Channel", callback_data="ch_active")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ch_main":
        cb = load_channel_backup()
        txt = "📋 **Main Channels**\n\n"
        channels = cb.get('main_channels', [])
        if channels:
            for i, ch in enumerate(channels, 1):
                txt += f"{i}. {ch.get('name','?')} (`{ch.get('id','?')}`)\n"
        else:
            txt += "❌ None configured.\n"
        kb = [
            [InlineKeyboardButton("➕ Add", callback_data="ch_main_add")],
            [InlineKeyboardButton("🗑️ Remove", callback_data="ch_main_rm")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_channel")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ch_main_add":
        context.user_data['await'] = 'ch_main_add'
        await query.edit_message_text("📡 **Send channel ID or username:**\n\n📌 Example: `-1001234567890` or `@channel`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ch_main")]]))

    elif data == "ch_main_rm":
        context.user_data['await'] = 'ch_main_rm'
        await query.edit_message_text("🗑️ **Send channel number to remove (from list above):**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ch_main")]]))

    elif data == "ch_backup":
        cb = load_channel_backup()
        txt = "💾 **Backup Channels**\n\n"
        channels = cb.get('backup_channels', [])
        if channels:
            for i, ch in enumerate(channels, 1):
                txt += f"{i}. {ch.get('name','?')} (`{ch.get('id','?')}`)\n"
        else:
            txt += "❌ None configured.\n"
        kb = [
            [InlineKeyboardButton("➕ Add", callback_data="ch_bk_add")],
            [InlineKeyboardButton("🗑️ Remove", callback_data="ch_bk_rm")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_channel")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ch_bk_add":
        context.user_data['await'] = 'ch_bk_add'
        await query.edit_message_text("💾 **Send backup channel ID or username:**\n\n📌 Example: `-1001234567890` or `@channel`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ch_backup")]]))

    elif data == "ch_bk_rm":
        context.user_data['await'] = 'ch_bk_rm'
        await query.edit_message_text("🗑️ **Send backup channel number to remove:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ch_backup")]]))

    elif data == "ch_active":
        cb = load_channel_backup()
        all_ch = cb.get('main_channels', []) + cb.get('backup_channels', [])
        if not all_ch:
            await query.edit_message_text("❌ **No channels to select!**\nAdd main/backup channels first.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_channel")]]))
            return
        kb = []
        for ch in all_ch:
            mark = "✅ " if cb.get('active_channel', {}).get('id') == ch.get('id') else ""
            kb.append([InlineKeyboardButton(f"{mark}{ch.get('name','?')}", callback_data=f"ch_set_active_{ch.get('id','?')}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_channel")])
        await query.edit_message_text("🔄 **Select active channel:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("ch_set_active_"):
        ch_id = data.split('_', 3)[3]
        cb = load_channel_backup()
        all_ch = cb.get('main_channels', []) + cb.get('backup_channels', [])
        for ch in all_ch:
            if ch.get('id') == ch_id:
                cb['active_channel'] = ch
                save_channel_backup(cb)
                await query.edit_message_text(f"✅ **Active channel set to: {ch.get('name','?')}**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_channel")]]))
                return
        await query.edit_message_text("❌ **Channel not found!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_channel")]]))

    # ====== STATUS & STATS ======
    elif data == "m_stat":
        uptime_info = ""
        if hasattr(context.bot_data, 'start_time'):
            uptime = datetime.now() - context.bot_data.start_time
            uptime_info = f"⏱️ Uptime: {uptime.days}d {uptime.seconds//3600}h\n"
        
        total_msgs = sum(account_stats.get(aid, {}).get('auto_sent', 0) for aid in account_stats)
        total_spam = sum(account_stats.get(aid, {}).get('spam_sent', 0) for aid in account_stats)
        ad_data = load_auto_delete_data()
        deleted_count = ad_data.get('deleted_count', 0)
        registered_chats = len(ad_data.get('chats', {}))
        
        customers = len(load_customers()) or len(customer_count) or 1
        
        txt = (
            f"📊 **Status & Statistics**\n\n"
            f"═══════════════════════\n"
            f"👤 Total Users: {customers}\n"
            f"📱 Active Accounts: {len(active_accounts)}\n"
            f"🟢 Online Clients: {len(account_clients)}\n"
            f"📨 Total Auto-Replies: {total_msgs}\n"
            f"📧 Total Spam Sent: {total_spam}\n"
            f"🗑️ Auto-Deleted Msgs: {deleted_count}\n"
            f"💬 Registered Chats: {registered_chats}\n"
            f"{uptime_info}"
            f"═══════════════════════\n"
            f"🤖 SecureBot v1.0"
        )
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="m_stat")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]))

    # ====== SETTINGS ======
    elif data == "m_set":
        auto_del_en = "✅" if load_auto_delete_data().get('enabled', False) else "❌"
        auto_del_sec = int(load_auto_delete_data().get('seconds', 86400))
        auto_del_time = f"{auto_del_sec//86400}d" if auto_del_sec >= 86400 else f"{auto_del_sec//3600}h" if auto_del_sec >= 3600 else f"{auto_del_sec}s"
        notif = "✅" if logout_notification_enabled else "❌"
        
        txt = (
            f"⚙️ **Settings**\n\n"
            f"🗑️ Auto Delete: {auto_del_en} ({auto_del_time})\n"
            f"🔔 Logout Notify: {notif}\n"
            f"👤 Admin Count: {len(ADMIN_IDS)}\n"
            f"═══════════════════════\n"
            f"📌 Configure bot behavior"
        )
        kb = [
            [InlineKeyboardButton(f"🗑️ Auto-Delete: {auto_del_en}", callback_data="set_ad")],
            [InlineKeyboardButton("⏱️ Set Auto-Delete Time", callback_data="set_ad_time")],
            [InlineKeyboardButton(f"🔔 Notifications: {notif}", callback_data="set_notif")],
            [InlineKeyboardButton("📝 Ignored Messages", callback_data="set_ignored")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "set_ad":
        ad_data = load_auto_delete_data()
        ad_data["enabled"] = not ad_data.get("enabled", False)
        save_auto_delete_data(ad_data)
        await query.edit_message_text(f"{'✅ **Auto-Delete ON**' if ad_data['enabled'] else '❌ **Auto-Delete OFF**'}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))

    elif data == "set_ad_time":
        context.user_data['await'] = 'set_ad_time'
        sec = int(load_auto_delete_data().get('seconds', 86400))
        time_str = f"{sec//86400}d" if sec >= 86400 else f"{sec//3600}h" if sec >= 3600 else f"{sec}s"
        await query.edit_message_text(
            "⏱️ **Enter auto-delete timer in seconds:**\n\n"
            "📌 Range: `1` (1s) to `2592000` (30 days)\n"
            f"📌 Current: `{sec}s` ({time_str})",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]])
        )

    elif data == "set_notif":
        global logout_notification_enabled
        logout_notification_enabled = not logout_notification_enabled
        set_setting('logout_notification', logout_notification_enabled)
        await query.edit_message_text(f"{'✅ **Logout notifications ON**' if logout_notification_enabled else '❌ **Logout notifications OFF**'}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))

    elif data == "set_ignored":
        context.user_data['await'] = 'set_ignored'
        cur = get_setting('ignored_messages', '') or 'None'
        await query.edit_message_text(f"📝 **Ignored Messages**\n\nBot will NOT auto-reply to these.\n\n📌 Send keyword(s) (one per line):\n📌 Current: `{cur}`\n📌 Send `clear` to reset.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))

    # ====== ADMIN PANEL (OWNER ONLY) ======
    elif data == "m_adm":
        if user_id != OWNER_ID:
            return
        txt = (
            "👑 **Admin Panel**\n\n"
            f"📊 Admins: {len(ADMIN_IDS)}\n"
            f"👤 Owner: {OWNER_ID}\n"
            f"📱 Active Accounts: {len(active_accounts)}\n"
            f"═══════════════════════\n"
            f"📌 Manage bot administrators"
        )
        kb = [
            [InlineKeyboardButton("➕ Add Admin", callback_data="ad_add")],
            [InlineKeyboardButton("🗑️ Remove Admin", callback_data="ad_remove")],
            [InlineKeyboardButton("📋 List Admins", callback_data="ad_list")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ad_add":
        if user_id != OWNER_ID:
            return
        context.user_data['await'] = 'admin_add'
        await query.edit_message_text("➕ **Send Telegram User ID** to add as admin:\n\n📌 You can get user ID from @userinfobot", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))

    elif data == "ad_remove":
        if user_id != OWNER_ID:
            return
        if not ADMIN_IDS:
            await query.edit_message_text("❌ **No admins to remove!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))
            return
        txt = "🗑️ **Select admin to remove:**\n\n"
        kb = []
        for aid in ADMIN_IDS:
            txt += f"• `{aid}`\n"
            kb.append([InlineKeyboardButton(f"🗑️ {aid}", callback_data=f"ad_rem_{aid}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="m_adm")])
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("ad_rem_"):
        if user_id != OWNER_ID:
            return
        rem_id = int(data.split('_')[2])
        if rem_id == OWNER_ID:
            await query.edit_message_text("❌ **Cannot remove yourself!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))
            return
        ADMIN_IDS = [x for x in ADMIN_IDS if x != rem_id]
        set_setting('admin_ids', ADMIN_IDS)
        await query.edit_message_text(f"✅ **Admin `{rem_id}` removed!**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))

    elif data == "ad_list":
        if user_id != OWNER_ID:
            return
        txt = f"👑 **Owner:** `{OWNER_ID}`\n\n**Admins:**\n"
        if ADMIN_IDS:
            for aid in ADMIN_IDS:
                txt += f"• `{aid}`\n"
        else:
            txt += "❌ None\n"
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))
async def process_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for various bot configuration states."""
    global auto_reply_enabled, active_accounts, account_clients, account_id_counter, ADMIN_IDS
    
    user = update.effective_user
    if user.id != OWNER_ID and user.id not in ADMIN_IDS:
        return
    
    text = update.message.text.strip()
    await_state = context.user_data.get('await', None)
    
    if not await_state:
        return
    
    # ====== ACCOUNT MANAGEMENT ======
    if await_state == 'ac_ph':
        phone = text.strip()
        if not phone.startswith('+'):
            phone = '+' + phone
        
        context.user_data['temp_phone'] = phone
        context.user_data['await'] = 'ac_otp'
        
        # Create client and send OTP
        try:
            phone_num = phone
            client = TelegramClient(
                StringSession(),
                API_ID or DEFAULT_API_ID,
                API_HASH or DEFAULT_API_HASH,
                device_model="SecureBot",
                system_version="4.16.30-vx",
                app_version="1.0.0"
            )
            await client.connect()
            
            sent = await client.send_code_request(phone_num)
            context.user_data['temp_client'] = client
            context.user_data['temp_phone_code_hash'] = sent.phone_code_hash
            
            await update.message.reply_text(
                f"📱 **OTP Sent to:** `{phone}`\n\n"
                "📌 Please enter the OTP code you received.\n"
                "📌 If using 2FA, enter password after OTP.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="m_acc")]])
            )
        except Exception as e:
            await update.message.reply_text(f"❌ **Error:** `{str(e)[:200]}`", parse_mode='Markdown')
            context.user_data['await'] = None
        
        return
    
    elif await_state == 'ac_otp':
        otp = text.strip()
        temp_client = context.user_data.get('temp_client')
        phone = context.user_data.get('temp_phone')
        phone_code_hash = context.user_data.get('temp_phone_code_hash')
        
        if not temp_client:
            await update.message.reply_text("❌ **Session expired.** Start again.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Add Phone", callback_data="ac_ph")]]))
            context.user_data['await'] = None
            return
        
        try:
            await temp_client.sign_in(phone=phone, code=otp, phone_code_hash=phone_code_hash)
            me = await temp_client.get_me()
            
            # Save account
            aid = gen_acc_id()
            acc = {
                'id': aid,
                'name': me.first_name or 'User',
                'phone': phone,
                'user_id': user.id,
                'api_id': API_ID or DEFAULT_API_ID,
                'api_hash': API_HASH or DEFAULT_API_HASH,
                'session': temp_client.session.save(),
                'is_backup': False,
                'created_at': datetime.now().isoformat(),
                'last_active': datetime.now().isoformat()
            }
            add_account_data(acc)
            active_accounts.append(acc)
            account_clients[aid] = temp_client
            
            context.user_data['await'] = None
            del context.user_data['temp_client']
            del context.user_data['temp_phone']
            del context.user_data['temp_phone_code_hash']
            
            await update.message.reply_text(
                f"✅ **Account Added!**\n\n"
                f"👤 Name: {me.first_name}\n"
                f"📱 Phone: {phone}\n"
                f"🆔 ID: {aid}\n\n"
                f"🟢 Account is now active.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Accounts", callback_data="m_acc")]])
            )
            
        except SessionPasswordNeededError:
            context.user_data['await'] = 'ac_2fa'
            await update.message.reply_text("🔑 **2FA Password Required**\n\n📌 Enter your Telegram 2FA password:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="m_acc")]]))
        
        except PhoneCodeInvalidError:
            await update.message.reply_text("❌ **Invalid OTP!** Try again.", parse_mode='Markdown')
        
        except PhoneCodeExpiredError:
            await update.message.reply_text("❌ **OTP Expired!** Start again.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Add Phone", callback_data="ac_ph")]]))
            context.user_data['await'] = None
        
        except Exception as e:
            await update.message.reply_text(f"❌ **Error:** `{str(e)[:200]}`", parse_mode='Markdown')
            context.user_data['await'] = None
        
        return
    
    elif await_state == 'ac_2fa':
        password = text.strip()
        temp_client = context.user_data.get('temp_client')
        phone = context.user_data.get('temp_phone')
        
        if not temp_client:
            await update.message.reply_text("❌ **Session expired.**", parse_mode='Markdown')
            context.user_data['await'] = None
            return
        
        try:
            await temp_client.sign_in(password=password)
            me = await temp_client.get_me()
            
            aid = gen_acc_id()
            acc = {
                'id': aid,
                'name': me.first_name or 'User',
                'phone': phone,
                'user_id': user.id,
                'api_id': API_ID or DEFAULT_API_ID,
                'api_hash': API_HASH or DEFAULT_API_HASH,
                'session': temp_client.session.save(),
                'is_backup': False,
                'created_at': datetime.now().isoformat(),
                'last_active': datetime.now().isoformat()
            }
            add_account_data(acc)
            active_accounts.append(acc)
            account_clients[aid] = temp_client
            
            context.user_data['await'] = None
            del context.user_data['temp_client']
            del context.user_data['temp_phone']
            
            await update.message.reply_text(
                f"✅ **Account Added!**\n\n"
                f"👤 Name: {me.first_name}\n"
                f"📱 Phone: {phone}\n"
                f"🆔 ID: {aid}\n\n"
                f"🟢 Account is now active.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Accounts", callback_data="m_acc")]])
            )
        except Exception as e:
            await update.message.reply_text(f"❌ **2FA Error:** `{str(e)[:200]}`", parse_mode='Markdown')
        
        return
    
    elif await_state == 'ac_ss':
        session_str = text.strip()
        try:
            client = TelegramClient(StringSession(session_str), API_ID or DEFAULT_API_ID, API_HASH or DEFAULT_API_HASH)
            await client.connect()
            me = await client.get_me()
            if not me:
                await update.message.reply_text("❌ **Invalid session string!**", parse_mode='Markdown')
                return
            
            phone = me.phone or f"user_{me.id}"
            aid = gen_acc_id()
            acc = {
                'id': aid,
                'name': me.first_name or 'User',
                'phone': f"+{phone}" if not str(phone).startswith('+') else phone,
                'user_id': user.id,
                'api_id': API_ID or DEFAULT_API_ID,
                'api_hash': API_HASH or DEFAULT_API_HASH,
                'session': session_str,
                'is_backup': False,
                'created_at': datetime.now().isoformat(),
                'last_active': datetime.now().isoformat()
            }
            add_account_data(acc)
            active_accounts.append(acc)
            account_clients[aid] = client
            
            context.user_data['await'] = None
            await update.message.reply_text(
                f"✅ **Account Added via Session!**\n\n"
                f"👤 Name: {me.first_name}\n"
                f"🆔 ID: {aid}\n\n"
                f"🟢 Account is now active.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Accounts", callback_data="m_acc")]])
            )
        except Exception as e:
            await update.message.reply_text(f"❌ **Error:** `{str(e)[:200]}`", parse_mode='Markdown')
        
        return
    
    # ====== HARDENING TEXT INPUTS ======
    elif await_state == 'harden_name':
        if text.lower() == 'clear':
            set_setting('new_account_name', '')
        else:
            set_setting('new_account_name', text)
        context.user_data['await'] = None
        await update.message.reply_text(f"✅ **Name set to:** `{text if text.lower() != 'clear' else '(reset)'}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))
        return
    
    elif await_state == 'harden_bio':
        if text.lower() == 'clear':
            set_setting('new_account_bio', '')
        else:
            set_setting('new_account_bio', text)
        context.user_data['await'] = None
        await update.message.reply_text(f"✅ **Bio set to:** `{text if text.lower() != 'clear' else '(reset)'}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_harden")]]))
        return
    
    elif await_state == 'harden_ad_time':
        try:
            seconds = int(text.strip())
            seconds = max(1, min(seconds, 2592000))  # 1s to 30 days
            set_setting('auto_delete_seconds', seconds)
            time_str = f"{seconds//86400}d" if seconds >= 86400 else f"{seconds//3600}h" if seconds >= 3600 else f"{seconds}s"
            context.user_data['await'] = None
            await update.message.reply_text(f"✅ **Auto-delete timer set to:** `{seconds}s` ({time_str})", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_config")]]))
        except ValueError:
            await update.message.reply_text("❌ **Invalid number!** Enter seconds (e.g., 86400)", parse_mode='Markdown')
        return
    
    elif await_state == 'harden_link_add':
        links = load_autojoin_links()
        links.append(text.strip())
        save_autojoin_links(links)
        context.user_data['await'] = None
        await update.message.reply_text(f"✅ **Link added!**\n\n📌 Total links: {len(links)}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_links")]]))
        return
    
    elif await_state == 'set_proxy':
        aid = context.user_data.get('proxy_account_id')
        if not aid:
            await update.message.reply_text("❌ **Session expired.**", parse_mode='Markdown')
            context.user_data['await'] = None
            return
        
        if text.strip().lower() == 'remove':
            remove_account_proxy(aid)
            context.user_data['await'] = None
            await update.message.reply_text(f"🗑️ **Proxy removed for account!**\n✅ Will use default proxy settings.", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_proxy")]]))
            return
        
        # Parse proxy string: type://user:pass@host:port
        try:
            parsed = urlparse(text.strip())
            proxy_type = parsed.scheme or 'socks5'
            host = parsed.hostname or '127.0.0.1'
            port = parsed.port or 9050
            username = parsed.username
            password = parsed.password
            
            proxy_config = {
                'proxy_type': proxy_type,
                'addr': host,
                'port': port,
                'username': username,
                'password': password
            }
            save_account_proxy(aid, proxy_config)
            context.user_data['await'] = None
            await update.message.reply_text(f"✅ **Proxy set!**\n\n`{proxy_type}://{username or 'none'}@{host}:{port}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_proxy")]]))
        except Exception as e:
            await update.message.reply_text(f"❌ **Invalid proxy format!**\n\n📌 Use: `type://user:pass@host:port`\n\nError: `{str(e)[:50]}`", parse_mode='Markdown')
        return
    
    # ====== AUTO REPLY TEXT INPUTS ======
    elif await_state == 'ar_welcome':
        if text.lower() == 'clear':
            set_setting('welcome_message', '')
            await update.message.reply_text("🗑️ **Welcome message cleared!**", parse_mode='Markdown')
        else:
            set_setting('welcome_message', text)
            await update.message.reply_text(f"✅ **Welcome message set!**\n\n`{text[:100]}`", parse_mode='Markdown')
        context.user_data['await'] = None
        await update.message.reply_text("🔙 Back to Auto Reply", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    elif await_state == 'ar_welcome2':
        if text.lower() == 'clear':
            set_setting('welcome_message_2', '')
            await update.message.reply_text("🗑️ **Second message cleared!**", parse_mode='Markdown')
        else:
            set_setting('welcome_message_2', text)
            await update.message.reply_text(f"✅ **Second message set!**\n\n`{text[:100]}`", parse_mode='Markdown')
        context.user_data['await'] = None
        await update.message.reply_text("🔙 Back to Auto Reply", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        return
    
    elif await_state == 'ar_wait':
        try:
            wait = int(text.strip())
            wait = max(1, min(wait, 30))
            set_setting('wait_time', wait)
            context.user_data['await'] = None
            await update.message.reply_text(f"✅ **Wait time set to:** `{wait}s`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        except ValueError:
            await update.message.reply_text("❌ **Invalid number!** Enter seconds (1-30)", parse_mode='Markdown')
        return
    
    elif await_state == 'ar_typing':
        try:
            dur = int(text.strip())
            dur = max(1, min(dur, 8))
            set_setting('typing_duration', dur)
            context.user_data['await'] = None
            await update.message.reply_text(f"✅ **Typing duration set to:** `{dur}s`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]]))
        except ValueError:
            await update.message.reply_text("❌ **Invalid number!** Enter seconds (1-8)", parse_mode='Markdown')
        return
    
    elif await_state == 'ar_kw_add':
        if '|' in text:
            parts = text.split('|', 1)
            keyword = parts[0].strip()
            reply = parts[1].strip()
            replies = load_replies()
            replies.append({'keyword': keyword, 'reply': reply})
            save_replies(replies)
            context.user_data['await'] = None
            await update.message.reply_text(f"✅ **Keyword added!**\n\n`{keyword}` → `{reply[:50]}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_keywords")]]))
        else:
            await update.message.reply_text("❌ **Format error!** Use: `keyword | reply text`", parse_mode='Markdown')
        return
    
    elif await_state == 'ar_kw_del':
        try:
            idx = int(text.strip()) - 1
            replies = load_replies()
            if 0 <= idx < len(replies):
                removed = replies.pop(idx)
                save_replies(replies)
                context.user_data['await'] = None
                await update.message.reply_text(f"🗑️ **Removed:** `{removed.get('keyword','?')}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ar_keywords")]]))
            else:
                await update.message.reply_text(f"❌ **Invalid number!** Enter 1-{len(replies)}", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ **Enter a valid number!**", parse_mode='Markdown')
        return
    
    # ====== GROUP SPAM TEXT INPUTS ======
    elif await_state == 'gs_msg_add':
        add_spam_message(text)
        context.user_data['await'] = None
        msgs = load_spam_messages()
        await update.message.reply_text(f"✅ **Message added!**\n📊 Total messages: {len(msgs)}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="gs_messages")]]))
        return
    
    # ====== CHANNEL BACKUP TEXT INPUTS ======
    elif await_state == 'ch_main_add':
        ch_input = text.strip()
        cb = load_channel_backup()
        if 'main_channels' not in cb:
            cb['main_channels'] = []
        cb['main_channels'].append({'id': ch_input, 'name': ch_input})
        save_channel_backup(cb)
        context.user_data['await'] = None
        await update.message.reply_text(f"✅ **Main channel added:** `{ch_input}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ch_main")]]))
        return
    
    elif await_state == 'ch_main_rm':
        try:
            idx = int(text.strip()) - 1
            cb = load_channel_backup()
            channels = cb.get('main_channels', [])
            if 0 <= idx < len(channels):
                removed = channels.pop(idx)
                cb['main_channels'] = channels
                save_channel_backup(cb)
                context.user_data['await'] = None
                await update.message.reply_text(f"🗑️ **Removed:** `{removed.get('id','?')}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ch_main")]]))
            else:
                await update.message.reply_text(f"❌ **Invalid number!**", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ **Enter a valid number!**", parse_mode='Markdown')
        return
    
    elif await_state == 'ch_bk_add':
        ch_input = text.strip()
        cb = load_channel_backup()
        if 'backup_channels' not in cb:
            cb['backup_channels'] = []
        cb['backup_channels'].append({'id': ch_input, 'name': ch_input})
        save_channel_backup(cb)
        context.user_data['await'] = None
        await update.message.reply_text(f"✅ **Backup channel added:** `{ch_input}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ch_backup")]]))
        return
    
    elif await_state == 'ch_bk_rm':
        try:
            idx = int(text.strip()) - 1
            cb = load_channel_backup()
            channels = cb.get('backup_channels', [])
            if 0 <= idx < len(channels):
                removed = channels.pop(idx)
                cb['backup_channels'] = channels
                save_channel_backup(cb)
                context.user_data['await'] = None
                await update.message.reply_text(f"🗑️ **Removed:** `{removed.get('id','?')}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ch_backup")]]))
            else:
                await update.message.reply_text(f"❌ **Invalid number!**", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ **Enter a valid number!**", parse_mode='Markdown')
        return
    
    # ====== SETTINGS TEXT INPUTS ======
    elif await_state == 'set_ad_time':
        try:
            seconds = int(text.strip())
            seconds = max(1, min(seconds, 2592000))
            ad_data = load_auto_delete_data()
            ad_data['seconds'] = seconds
            save_auto_delete_data(ad_data)
            context.user_data['await'] = None
            time_str = f"{seconds//86400}d" if seconds >= 86400 else f"{seconds//3600}h" if seconds >= 3600 else f"{seconds}s"
            await update.message.reply_text(f"✅ **Auto-delete timer set to:** `{seconds}s` ({time_str})", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))
        except ValueError:
            await update.message.reply_text("❌ **Invalid number!**", parse_mode='Markdown')
        return
    
    elif await_state == 'set_ignored':
        if text.lower() == 'clear':
            set_setting('ignored_messages', '')
            await update.message.reply_text("🗑️ **Ignored messages cleared!**", parse_mode='Markdown')
        else:
            set_setting('ignored_messages', text)
            await update.message.reply_text(f"✅ **Ignored messages updated!**", parse_mode='Markdown')
        context.user_data['await'] = None
        await update.message.reply_text("🔙 Back to Settings", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_set")]]))
        return
    
    # ====== ADMIN PANEL (OWNER ONLY) ======
    elif await_state == 'admin_add':
        if user.id != OWNER_ID:
            return
        try:
            new_admin_id = int(text.strip())
            if new_admin_id == OWNER_ID:
                await update.message.reply_text("❌ **You are already the owner!**", parse_mode='Markdown')
                return
            if new_admin_id in ADMIN_IDS:
                await update.message.reply_text(f"❌ **{new_admin_id} is already an admin!**", parse_mode='Markdown')
                return
            ADMIN_IDS.append(new_admin_id)
            set_setting('admin_ids', ADMIN_IDS)
            context.user_data['await'] = None
            await update.message.reply_text(f"✅ **Admin added:** `{new_admin_id}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_adm")]]))
        except ValueError:
            await update.message.reply_text("❌ **Invalid User ID!**", parse_mode='Markdown')
        return
        async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads for profile pic and welcome image."""
    await_state = context.user_data.get('await', None)
    
    if await_state == 'harden_photo_upload':
        photo_file = await update.message.photo[-1].get_file()
        file_path = USER_DATA_DIR / 'new_profile_pic.jpg'
        await photo_file.download_to_drive(str(file_path))
        context.user_data['await'] = None
        await update.message.reply_text(
            "✅ **New profile photo saved!**\n\n"
            "📌 It will be applied during **1-click hardening**.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="harden_photo")]])
        )
    
    elif await_state == 'ar_upload_img':
        photo_file = await update.message.photo[-1].get_file()
        file_path = USER_DATA_DIR / 'welcome_image.png'
        await photo_file.download_to_drive(str(file_path))
        context.user_data['await'] = None
        await update.message.reply_text(
            "✅ **Welcome image saved!**\n\n"
            "📌 It will be sent before auto-reply messages.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_ar")]])
        )
        async def post_init(application: Application):
    """Setup after bot initializes."""
    # Load admin IDs from settings
    global ADMIN_IDS
    saved_admins = get_setting('admin_ids', [])
    if saved_admins and isinstance(saved_admins, list):
        ADMIN_IDS = saved_admins
    if OWNER_ID not in ADMIN_IDS:
        ADMIN_IDS.insert(0, OWNER_ID)
    
    # Load customer count
    global customer_count
    saved = load_customers()
    if saved:
        customer_count = set(saved)
    
    # Start background tasks
    application.create_task(auto_delete_messages_loop())
    application.create_task(keepalive_loop())
    application.create_task(account_health_loop())
    
    # Set up commands
    commands = [
        BotCommand("start", "🏠 Main Menu"),
        BotCommand("menu", "📋 Show Menu"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except:
        pass
    
    application.bot_data.start_time = datetime.now()
    logger.info("Bot initialized successfully!")

async def main():
    """Main entry point."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    if not API_ID or not API_HASH:
        logger.warning("Using default API_ID/API_HASH. May have rate limits.")
    
    # Build application
    builder = Application.builder()
    builder.token(BOT_TOKEN)
    builder.post_init(post_init)
    builder.connect_timeout(30.0)
    builder.read_timeout(30.0)
    builder.write_timeout(30.0)
    builder.pool_timeout(30.0)
    
    app = builder.build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text_input))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    # Start polling
    logger.info("Starting bot polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=1.0,
        timeout=30
    )
    
    logger.info("Bot is running! Press Ctrl+C to stop.")
    
    # Keep running
    stop_signal = asyncio.Future()
    
    try:
        await stop_signal
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

# ====== FLASK WEB SERVER (for Render health checks) ======
if FLASK_AVAILABLE:
    flask_app = Flask(__name__)
    flask_app.secret_key = WEBHOOK_SECRET
    
    @flask_app.route('/')
    def home():
        return jsonify({
            "status": "running",
            "bot": "SecureBot",
            "version": "1.0",
            "active_accounts": len(active_accounts),
            "timestamp": datetime.now().isoformat()
        })
    
    @flask_app.route('/health')
    def health():
        return jsonify({"status": "healthy", "time": datetime.now().isoformat()}), 200
    
    def run_flask():
        port = int(os.environ.get('PORT', 8080))
        flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
else:
    def run_flask():
        pass

# ====== ENTRY POINT ======
if __name__ == '__main__':
    # Start Flask in a separate thread (needed for Render)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
        

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
        return "❌ অ্যাকাউন্ট পাওয়া যায়নি!"
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
        txt = f"📱 **ডিভাইস তালিকা** - {acc.get('name','?')}\n\n"
        for a in auths.authorizations:
            txt += f"▫️ **{a.device_model}** | {a.app_name} v{a.app_version}\n"
            txt += f"  🌐 IP: {a.ip} | {a.country}\n"
            txt += f"  📅 তারিখ: {a.date_created}\n"
            if a.current:
                txt += "  ✅ **বর্তমান ডিভাইস**\n"
            txt += "\n"
        await client.disconnect()
        return txt or "❌ কোনো ডিভাইস পাওয়া যায়নি!"
    except Exception as e:
        return f"❌ ত্রুটি: {str(e)[:100]}"

async def harden_account_one_click(acc):
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
            return "❌ অনুমোদিত নয় (Not Authorized)"
        
        results.append(f"🔄 **হার্ডেনিং শুরু** - {acc.get('name','?')}")
        
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
            results.append(f"✅ {revoked}টি পুরনো সেশন রিভোক করা হয়েছে")
        except Exception as e:
            results.append(f"⚠️ সেশন রিভোক: {str(e)[:50]}")
        
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
            results.append("✅ প্রাইভেসি সেটিংস শক্তিশালী করা হয়েছে")
        except Exception as e:
            results.append(f"⚠️ প্রাইভেসি: {str(e)[:50]}")
        
        # 3. Change profile name and bio
        new_name = get_setting('new_account_name', '')
        new_bio = get_setting('new_account_bio', '')
        try:
            if new_name:
                await client(functions.account.UpdateProfileRequest(first_name=new_name))
                results.append(f"✅ নাম পরিবর্তন: {new_name}")
            if new_bio:
                await client(functions.account.UpdateProfileRequest(about=new_bio))
                results.append("✅ বায়ো আপডেট করা হয়েছে")
        except Exception as e:
            results.append(f"⚠️ প্রোফাইল আপডেট: {str(e)[:50]}")
        
        # 4. Delete profile photo if requested
        if get_setting('delete_dp_enabled', False):
            try:
                photos = await client(functions.photos.GetUserPhotosRequest(user_id=me.id, offset=0, max_id=0, limit=100))
                if photos and photos.photos:
                    await client(functions.photos.DeletePhotosRequest(id=photos.photos))
                    results.append(f"✅ {len(photos.photos)}টি প্রোফাইল ছবি মুছে ফেলা হয়েছে")
                else:
                    results.append("ℹ️ মুছে ফেলার মতো কোনো প্রোফাইল ছবি নেই")
            except Exception as e:
                results.append(f"⚠️ ডিপি মুছে ফেলা: {str(e)[:50]}")
        
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
                results.append(f"✅ {left_count}টি গ্রুপ/চ্যানেল ছেড়ে দেওয়া হয়েছে")
            except Exception as e:
                results.append(f"⚠️ গ্রুপ ছাড়া: {str(e)[:50]}")
        
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
                results.append(f"✅ {deleted_count}টি চ্যাট হিস্ট্রি মুছে ফেলা হয়েছে")
            except Exception as e:
                results.append(f"⚠️ চ্যাট মুছা: {str(e)[:50]}")
        
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
                    results.append(f"✅ {joined}টি গ্রুপে যোগ দেওয়া হয়েছে")
            except Exception as e:
                results.append(f"⚠️ অটো-জয়েন: {str(e)[:50]}")
        
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
                
                time_str = f"{seconds//86400} দিন" if seconds >= 86400 else f"{seconds//3600} ঘণ্টা" if seconds >= 3600 else f"{seconds} সেকেন্ড"
                results.append(f"✅ অটো-ডিলিট টাইমার সেট ({time_str}) - {registered_count}টি চ্যাট রেজিস্টার")
            except Exception as e:
                results.append(f"⚠️ অটো-ডিলিট: {str(e)[:30]}")
        
        # 9. Set new profile photo if file exists
        profile_pic_path = USER_DATA_DIR / 'new_profile_pic.jpg'
        if profile_pic_path.exists():
            try:
                await client(functions.photos.UploadProfilePhotoRequest(
                    file=await client.upload_file(str(profile_pic_path))
                ))
                results.append("✅ নতুন প্রোফাইল ছবি সেট করা হয়েছে")
            except Exception as e:
                results.append(f"⚠️ প্রোফাইল ছবি আপলোড: {str(e)[:50]}")
        
        await client.disconnect()
        
        results.append(f"\n🎉 **হার্ডেনিং সম্পন্ন!** ✅")
        
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
        return f"❌ হার্ডেনিং ব্যর্থ হয়েছে: {str(e)[:200]}"

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
            
            reply_text = welcome_msg or "👋 হ্যালো! আমি কিভাবে আপনাকে সাহায্য করতে পারি?"
            
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
    for aid, client in account_clients.items():
        try:
            await setup_auto_reply_for_account(aid, client)
        except Exception as e:
            logger.error(f"Failed to setup auto reply for {aid}: {e}")

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
        messages = [{"text": "👋 হ্যালো! এটি একটি অটোমেটেড মেসেজ।"}]
    
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
    global group_spam_enabled, spam_worker_tasks
    
    group_spam_enabled = True
    
    for aid, client in account_clients.items():
        if aid not in spam_worker_tasks or spam_worker_tasks[aid].done():
            task = asyncio.create_task(spam_worker(aid, client))
            spam_worker_tasks[aid] = task
            await asyncio.sleep(1)
    
    logger.info(f"Started spam for {len(spam_worker_tasks)} accounts")

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
    logger.info("All spam workers stopped")

# ====== AUTO DELETE TIMER - FAST SETUP ======
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
            logger.info(f"Auto-delete: {acc_registered} chats for {acc.get('name','?')}")
            
        except Exception as e:
            logger.error(f"Auto-delete fast setup for {aid}: {e}")
    
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
                                logger.info(f"Reconnected {aid}")
                        except:
                            pass
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Keepalive loop: {e}")
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
    await update.message.reply_text(
        f"🎉 **স্বাগতম, {user.first_name}!** 🎉\n\n"
        f"🤖 বোটটি প্রস্তুত!\n"
        f"📌 অপশন দেখতে /menu ব্যবহার করুন।\n\n"
        f"**পাওয়ারফুল টেলিগ্রাম অটোমেশন বট** 🚀",
        parse_mode='Markdown'
    )
    await show_main_menu(update, context)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👥 অ্যাকাউন্ট ম্যানেজমেন্ট", callback_data='m_acc')],
        [InlineKeyboardButton("🛡️ অ্যাকাউন্ট হার্ডেনিং", callback_data='m_harden')],
        [InlineKeyboardButton("🤖 অটো রিপ্লাই", callback_data='m_ar')],
        [InlineKeyboardButton("📨 গ্রুপ স্প্যাম", callback_data='m_gs')],
        [InlineKeyboardButton("💾 চ্যানেল ব্যাকআপ", callback_data='m_channel')],
        [InlineKeyboardButton("📊 স্ট্যাটাস ও পরিসংখ্যান", callback_data='m_stat')],
        [InlineKeyboardButton("⚙️ সেটিংস", callback_data='m_set')],
        [InlineKeyboardButton("🔐 অ্যাডমিন প্যানেল", callback_data='m_adm')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "🏠 **মেইন মেনু**\n\n"
        "➖➖➖➖➖➖➖➖➖➖➖\n"
        "নিচের অপশন থেকে বাছাই করুন:\n"
        "➖➖➖➖➖➖➖➖➖➖➖"
    )
    
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
        await query.edit_message_text("❌ **আপনি অনুমোদিত নন!** এই বট ব্যবহার করার অনুমতি নেই।")
        return

    # ====== MAIN MENU ======
    if data == "main" or data == "back_to_menu":
        await show_main_menu(update, context)

    # ====== ACCOUNT HARDENING ======
    elif data == "m_harden":
        txt = (
            "🛡️ **অ্যাকাউন্ট হার্ডেনিং**\n\n"
            "═══════════════════════\n"
            "📌 উপলব্ধ ফিচারসমূহ:\n"
            "═══════════════════════\n\n"
            "▫️ নাম ও বায়ো পরিবর্তন\n"
            "▫️ সব পুরনো ডিভাইস সরানো\n"
            "▫️ প্রাইভেসি সেটিংস শক্তিশালীকরণ\n"
            "▫️ প্রোফাইল ছবি মুছে নতুন সেট\n"
            "▫️ সব গ্রুপ/চ্যানেল ছেড়ে দেওয়া\n"
            "▫️ সব চ্যাট হিস্ট্রি মুছে ফেলা\n"
            "▫️ গ্রুপে অটো জয়েন\n"
            "▫️ অটো-ডিলিট টাইমার (1সে - 30 দিন)\n"
            "▫️ প্রক্সি কনফিগারেশন\n\n"
            "═══════════════════════\n"
            "⚡ **সবকিছু ১ ক্লিকেই!**\n"
            "═══════════════════════"
        )
        kb = [
            [InlineKeyboardButton("⚡ 1 ক্লিক ফুল হার্ডেনিং", callback_data="harden_all")],
            [InlineKeyboardButton("⚙️ হার্ডেনিং অপশন কনফিগার", callback_data="harden_config")],
            [InlineKeyboardButton("📝 নতুন নাম সেট", callback_data="harden_name")],
            [InlineKeyboardButton("📝 নতুন বায়ো সেট", callback_data="harden_bio")],
            [InlineKeyboardButton("🖼️ প্রোফাইল ছবি ম্যানেজ", callback_data="harden_photo")],
            [InlineKeyboardButton("📱 ডিভাইস তালিকা দেখুন", callback_data="harden_devices")],
            [InlineKeyboardButton("🔗 অটো জয়েন লিংক", callback_data="harden_links")],
            [InlineKeyboardButton("🌐 অ্যাকাউন্ট প্রক্সি", callback_data="harden_proxy")],
            [InlineKeyboardButton("📜 হার্ডেনিং হিস্ট্রি", callback_data="harden_history")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_config":
        dp_del = "✅" if get_setting('delete_dp_enabled', False) else "❌"
        leave_all = "✅" if get_setting('leave_all_enabled', False) else "❌"
        del_chats = "✅" if get_setting('delete_all_chats_enabled', False) else "❌"
        join_en = "✅" if get_setting('auto_join_enabled', False) else "❌"
        ad_en = "✅" if get_setting('auto_delete_harden_enabled', False) else "❌"
        ad_sec = int(get_setting('auto_delete_seconds', 86400))
        ad_time = f"{ad_sec//86400} দিন" if ad_sec >= 86400 else f"{ad_sec//3600} ঘণ্টা" if ad_sec >= 3600 else f"{ad_sec} সেকেন্ড"
        
        txt = (
            "⚙️ **হার্ডেনিং অপশন কনফিগারেশন**\n\n"
            "নিচে থেকে বাছাই করুন কী কী ফিচার\n"
            "১ ক্লিক হার্ডেনিং-এ অন্তর্ভুক্ত হবে:\n\n"
            f"🖼️ প্রোফাইল ছবি মুছুন: {dp_del}\n"
            f"🚪 সব গ্রুপ ছাড়ুন: {leave_all}\n"
            f"🗑️ সব চ্যাট মুছুন: {del_chats}\n"
            f"🔗 অটো জয়েন গ্রুপ: {join_en}\n"
            f"⏰ অটো-ডিলিট টাইমার: {ad_en} ({ad_time})\n"
        )
        kb = [
            [InlineKeyboardButton(f"{'✅' if get_setting('delete_dp_enabled', False) else '❌'} প্রোফাইল ছবি মুছুন", callback_data="hcfg_dp")],
            [InlineKeyboardButton(f"{'✅' if get_setting('leave_all_enabled', False) else '❌'} সব গ্রুপ/চ্যানেল ছাড়ুন", callback_data="hcfg_leave")],
            [InlineKeyboardButton(f"{'✅' if get_setting('delete_all_chats_enabled', False) else '❌'} সব চ্যাট হিস্ট্রি মুছুন", callback_data="hcfg_delchat")],
            [InlineKeyboardButton(f"{'✅' if get_setting('auto_join_enabled', False) else '❌'} অটো জয়েন গ্রুপ", callback_data="hcfg_join")],
            [InlineKeyboardButton(f"{'✅' if get_setting('auto_delete_harden_enabled', False) else '❌'} অটো-ডিলিট টাইমার", callback_data="hcfg_ad")],
            [InlineKeyboardButton("⏱️ অটো-ডিলিট সময় সেট", callback_data="hcfg_ad_time")],
            [InlineKeyboardButton("🔙 হার্ডেনিং মেনু", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "hcfg_dp":
        cur = get_setting('delete_dp_enabled', False)
        set_setting('delete_dp_enabled', not cur)
        await query.edit_message_text(
            f"{'✅ চালু' if not cur else '❌ বন্ধ'} করা হয়েছে - হার্ডেনিং-এ প্রোফাইল ছবি মুছে ফেলা", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_config")]])
        )
    elif data == "hcfg_leave":
        cur = get_setting('leave_all_enabled', False)
        set_setting('leave_all_enabled', not cur)
        await query.edit_message_text(
            f"{'✅ চালু' if not cur else '❌ বন্ধ'} করা হয়েছে - হার্ডেনিং-এ সব গ্রুপ ছেড়ে দেওয়া", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_config")]])
        )
    elif data == "hcfg_delchat":
        cur = get_setting('delete_all_chats_enabled', False)
        set_setting('delete_all_chats_enabled', not cur)
        await query.edit_message_text(
            f"{'✅ চালু' if not cur else '❌ বন্ধ'} করা হয়েছে - হার্ডেনিং-এ সব চ্যাট মুছে ফেলা", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_config")]])
        )
    elif data == "hcfg_join":
        cur = get_setting('auto_join_enabled', False)
        set_setting('auto_join_enabled', not cur)
        await query.edit_message_text(
            f"{'✅ চালু' if not cur else '❌ বন্ধ'} করা হয়েছে - হার্ডেনিং-এ গ্রুপে অটো জয়েন", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_config")]])
        )
    elif data == "hcfg_ad":
        cur = get_setting('auto_delete_harden_enabled', False)
        set_setting('auto_delete_harden_enabled', not cur)
        await query.edit_message_text(
            f"{'✅ চালু' if not cur else '❌ বন্ধ'} করা হয়েছে - হার্ডেনিং-এ অটো-ডিলিট টাইমার", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_config")]])
        )

    elif data == "hcfg_ad_time":
        context.user_data['await'] = 'harden_ad_time'
        seconds = int(get_setting('auto_delete_seconds', 86400))
        await query.edit_message_text(
            "⏱️ **অটো-ডিলিট টাইমার সময় সেট করুন**\n\n"
            "সেকেন্ডে সময় লিখুন:\n\n"
            "📌 উদাহরণ:\n"
            "1 = ১ সেকেন্ড\n"
            "60 = ১ মিনিট\n"
            "3600 = ১ ঘণ্টা\n"
            "86400 = ১ দিন (ডিফল্ট)\n"
            "2592000 = ৩০ দিন\n\n"
            f"বর্তমান: {seconds} সেকেন্ড",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_config")]])
        )

    elif data == "harden_all":
        all_accs = get_all_accounts()
        main_accs = [a for a in all_accs if not a.get('is_backup')]
        
        if not main_accs:
            await query.edit_message_text(
                "❌ **কোনো অ্যাকাউন্ট পাওয়া যায়নি!**\n\n"
                "প্রথমে একটি অ্যাকাউন্ট যোগ করুন:\n"
                "👥 অ্যাকাউন্ট ম্যানেজমেন্ট → 📱 ফোন + OTP অথবা 🔑 সেশন স্ট্রিং",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])
            )
            return
        
        # FIXED: Check both active_accounts and all accounts from disk
        kb = []
        for a in main_accs:
            name = a.get('name', 'অজানা')[:15]
            phone = a.get('phone', 'N/A')
            # Check if this account is active (connected)
            is_active = any(x['id'] == a['id'] for x in active_accounts)
            status_icon = "🟢" if is_active else "🟡"
            btn_text = f"{status_icon} {name} | {phone[-4:]}"
            kb.append([InlineKeyboardButton(btn_text, callback_data=f"hdn_{a['id']}")])
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")])
        await query.edit_message_text(
            "⚡ **হার্ডেনিং করার জন্য অ্যাকাউন্ট নির্বাচন করুন**\n\n"
            "🟢 = সক্রিয় (চালু আছে)\n"
            "🟡 = নিষ্ক্রিয় (তবুও কাজ করবে)\n\n"
            "সকল কনফিগার করা অপশন ১ ক্লিকেই প্রয়োগ হবে!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("hdn_"):
        aid = data.split('_')[1]
        # FIXED: First check active_accounts, then fallback to find_account from disk
        acc = None
        for a in active_accounts:
            if a['id'] == aid:
                acc = a
                break
        if not acc:
            acc = find_account(aid)
        if not acc:
            await query.edit_message_text(
                "❌ **অ্যাকাউন্ট পাওয়া যায়নি!**\n\n"
                "সম্ভাব্য কারণ:\n"
                "1️⃣ অ্যাকাউন্টটি ডিলিট হয়ে গেছে\n"
                "2️⃣ ডাটা ফাইল নষ্ট হয়ে গেছে\n\n"
                "➡️ দয়া করে নতুন করে অ্যাকাউন্ট যোগ করুন।",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])
            )
            return
        await query.edit_message_text(
            f"⏳ **হার্ডেনিং শুরু হচ্ছে...**\n\n"
            f"👤 অ্যাকাউন্ট: {acc.get('name', 'অজানা')}\n"
            f"📱 ফোন: {acc.get('phone', 'N/A')}\n\n"
            f"⚙️ চলমান... দয়া করে অপেক্ষা করুন।\n"
            f"এতে কয়েক মিনিট সময় লাগতে পারে।",
            parse_mode='Markdown'
        )
        result = await harden_account_one_click(acc)
        await query.edit_message_text(
            f"📋 **হার্ডেনিং ফলাফল:**\n\n{result}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])
        )

    elif data == "harden_name":
        context.user_data['await'] = 'harden_name'
        cur = get_setting('new_account_name', '')
        await query.edit_message_text(
            f"📝 **নতুন নাম লিখুন:**\n\nবর্তমান: {cur or 'সেট করা হয়নি'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])
        )

    elif data == "harden_bio":
        context.user_data['await'] = 'harden_bio'
        cur = get_setting('new_account_bio', '')
        await query.edit_message_text(
            f"📝 **নতুন বায়ো লিখুন:**\n\nবর্তমান: {cur or 'সেট করা হয়নি'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])
        )

    elif data == "harden_photo":
        txt = "🖼️ **প্রোফাইল ছবি ম্যানেজমেন্ট**\n\n"
        if (USER_DATA_DIR / 'new_profile_pic.jpg').exists():
            txt += "✅ নতুন ছবি আপলোডের জন্য প্রস্তুত (new_profile_pic.jpg)\n"
        else:
            txt += "❌ কোনো নতুন ছবি সেট করা নেই। একটি ছবি পাঠান।\n"
        txt += "\n**অপশন:**"
        kb = [
            [InlineKeyboardButton("🗑️ বর্তমান ডিপি মুছুন (হার্ডেনিং-এ)", callback_data="hcfg_dp")],
            [InlineKeyboardButton("📤 নতুন প্রোফাইল ছবি আপলোড", callback_data="harden_upload_photo")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_upload_photo":
        context.user_data['await'] = 'harden_photo_upload'
        await query.edit_message_text(
            "📤 **নতুন প্রোফাইল ছবি পাঠান**\n\n"
            "যে ছবিটি প্রোফাইল পিকচার হিসেবে সেট করতে চান, সেটি পাঠান।\n\n"
            "ছবিটি সেভ করা হবে এবং ১-ক্লিক হার্ডেনিং-এর সময়\n"
            "স্বয়ংক্রিয়ভাবে সেট করা হবে।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_photo")]])
        )

    elif data == "harden_devices":
        if not active_accounts:
            await query.edit_message_text(
                "❌ **কোনো সক্রিয় অ্যাকাউন্ট নেই!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])
            )
            return
        kb = [[InlineKeyboardButton(f"📱 {a.get('name','?')[:15]}", callback_data=f"hdv_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")])
        await query.edit_message_text(
            "📱 **ডিভাইস দেখার জন্য অ্যাকাউন্ট নির্বাচন করুন:**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("hdv_"):
        aid = data.split('_')[1]
        info = await get_device_login_info(aid)
        await query.edit_message_text(
            f"📋 **ডিভাইস তথ্য:**\n\n{info[:3500]}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 পিছনে", callback_data="harden_devices"), InlineKeyboardButton("🔄 রিফ্রেশ", callback_data=f"hdv_{aid}")]
            ])
        )

    elif data == "harden_links":
        links = load_autojoin_links()
        txt = "🔗 **অটো জয়েন লিংক**\n\nহার্ডেনিং-এর সময়\nঅ্যাকাউন্ট যেসব গ্রুপে অটো জয়িন হবে:\n\n"
        if links:
            for i, link in enumerate(links, 1):
                txt += f"{i}. {link[:40]}...\n"
        else:
            txt += "❌ কোনো লিংক সেট করা নেই। নিচে যোগ করুন।\n"
        kb = [
            [InlineKeyboardButton("➕ লিংক যোগ করুন", callback_data="harden_link_add")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]
        ]
        await query.edit_message_text(txt[:4000], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "harden_link_add":
        context.user_data['await'] = 'harden_link_add'
        await query.edit_message_text(
            "🔗 **গ্রুপ/চ্যানেলের ইনভাইট লিংক পাঠান:**\n\n"
            "উদাহরণ: https://t.me/yourgroup",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]])
        )

    elif data == "harden_proxy":
        txt = "🌐 **অ্যাকাউন্ট প্রক্সি সেটিংস**\n\n"
        txt += "প্রত্যেক অ্যাকাউন্টের জন্য আলাদা প্রক্সি সেট করুন।\n\n"
        txt += "ফরম্যাট: type://user:pass@host:port\n"
        txt += "উদাহরণ: socks5://user:pass@127.0.0.1:9050\n\n"
        if not active_accounts:
            txt += "❌ কোনো সক্রিয় অ্যাকাউন্ট নেই।"
        else:
            txt += "প্রক্সি কনফিগার করতে অ্যাকাউন্ট নির্বাচন করুন:"
        
        kb = []
        for a in active_accounts[:10]:
            name = a.get('name', '?')[:15]
            proxy_info = get_account_proxy(a['id'])
            status = "✅" if proxy_info else "❌"
            kb.append([InlineKeyboardButton(f"{status} {name}", callback_data=f"proxy_set_{a['id']}")])
        kb.append([InlineKeyboardButton("🗑️ সব প্রক্সি সরান", callback_data="proxy_remove_all")])
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")])
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("proxy_set_"):
        aid = data.split('_', 2)[2]
        context.user_data['proxy_account_id'] = aid
        context.user_data['await'] = 'set_proxy'
        current = get_account_proxy(aid)
        txt = f"🌐 **অ্যাকাউন্টের জন্য প্রক্সি লিখুন:**\n\n"
        if current:
            txt += f"বর্তমান: {current.get('proxy_type','?')}://{current.get('username','') or 'none'}@{current.get('addr','?')}:{current.get('port','?')}\n\n"
        txt += "ফরম্যাট: type://username:password@host:port\n"
        txt += "উদাহরণ: socks5://user:pass@127.0.0.1:9050\n\n"
        txt += "প্রক্সি সরাতে 'remove' লিখুন।"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_proxy")]]))

    elif data == "proxy_remove_all":
        save_json(ACCOUNT_PROXIES_FILE, {})
        await query.edit_message_text("✅ **সব প্রক্সি সরানো হয়েছে!**", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_proxy")]]))

    elif data == "harden_history":
        txt = "📜 **হার্ডেনিং হিস্ট্রি**\n\n"
        has_data = False
        all_accs = get_all_accounts()
        for acc in all_accs:
            tasks = load_harden_tasks().get(acc['id'], [])
            if tasks:
                has_data = True
                txt += f"👤 **{acc.get('name','?')}**\n"
                for t in tasks[-5:]:
                    status = "✅" if t['status'] == 'completed' else "⏳"
                    txt += f"  {status} {t['type']} - {t['created_at'][:16]}\n"
                txt += "\n"
        if not has_data:
            txt += "❌ কোনো হিস্ট্রি নেই। ১ ক্লিক হার্ডেনিং ব্যবহার করুন।"
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    # ====== ACCOUNT MANAGEMENT ======
    elif data == "m_acc":
        ma = len(get_main_accounts())
        ba = len(get_backup_accounts())
        act = len(active_accounts)
        txt = (
            "👥 **অ্যাকাউন্ট ম্যানেজমেন্ট**\n\n"
            f"📊 মূল অ্যাকাউন্ট: {ma}\n"
            f"💾 ব্যাকআপ: {ba}\n"
            f"🟢 সক্রিয়: {act}\n\n"
            "নিচের অপশন থেকে বাছাই করুন:"
        )
        kb = [
            [InlineKeyboardButton("📱 ফোন + OTP যোগ করুন", callback_data="ac_ph")],
            [InlineKeyboardButton("🔑 সেশন স্ট্রিং যোগ করুন", callback_data="ac_ss")],
            [InlineKeyboardButton("🗑️ অ্যাকাউন্ট ডিলিট", callback_data="ac_del")],
            [InlineKeyboardButton("💾 ব্যাকআপ ম্যানেজমেন্ট", callback_data="ac_bk")],
            [InlineKeyboardButton("📋 সব অ্যাকাউন্ট তালিকা", callback_data="ac_ls")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_ph":
        context.user_data['await'] = 'ac_ph'
        await query.edit_message_text(
            "📱 **ফোন নম্বর লিখুন:**\n\n"
            "ফরম্যাট: +৮৮০১XXXXXXXXX\n\n"
            "উদাহরণ: +৮৮০১৭১২৩৪৫৬৭৮",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
        )

    elif data == "ac_ss":
        context.user_data['await'] = 'ac_ss'
        await query.edit_message_text(
            "🔑 **সেশন স্ট্রিং পেস্ট করুন:**\n\n"
            "Telegram থেকে প্রাপ্ত সেশন স্ট্রিং পাঠান।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
        )

    elif data == "ac_del":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text(
                "❌ **কোনো অ্যাকাউন্ট নেই!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
            )
            return
        kb = []
        for a in all_a:
            is_owner = a.get('user_id') == OWNER_ID
            if user_id == OWNER_ID or not is_owner:
                btn_text = f"🗑️ {a.get('name','?')} | {a.get('phone','N/A')}"
                if is_owner:
                    btn_text += " 👑"
                kb.append([InlineKeyboardButton(btn_text, callback_data=f"acd_{a['id']}")])
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")])
        await query.edit_message_text(
            "🗑️ **ডিলিট করার জন্য অ্যাকাউন্ট নির্বাচন করুন:**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("acd_"):
        aid = data.split('_', 1)[1]
        a = find_account(aid)
        name = a.get('name', '?') if a else '?'
        
        if a and a.get('user_id') == OWNER_ID and user_id != OWNER_ID:
            await query.edit_message_text(
                "❌ **অ্যাডমিনরা ওনার অ্যাকাউন্ট ডিলিট করতে পারবেন না!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
            )
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
        await query.edit_message_text(
            f"✅ **{name}** স্থায়ীভাবে ডিলিট করা হয়েছে!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
        )

    elif data == "ac_bk":
        ba = get_backup_accounts()
        txt = f"💾 **ব্যাকআপ অ্যাকাউন্ট**\n\nমোট: {len(ba)}\n\n"
        for i, a in enumerate(ba, 1):
            txt += f"{i}. **{a.get('name', '?')}** ({a.get('phone', 'N/A')})\n"
        kb = [
            [InlineKeyboardButton("➕ ব্যাকআপ সেশন যোগ করুন", callback_data="ac_bk_add")],
            [InlineKeyboardButton("🗑️ ব্যাকআপ সরান", callback_data="ac_bk_del")],
            [InlineKeyboardButton("➡️ ব্যাকআপ → সক্রিয় (১ ক্লিক)", callback_data="ac_bk_to_run")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ac_bk_add":
        context.user_data['await'] = 'ac_bk_ss'
        await query.edit_message_text(
            "🔑 **ব্যাকআপ সেশন স্ট্রিং পেস্ট করুন:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])
        )

    elif data == "ac_bk_del":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text(
                "❌ **কোনো ব্যাকআপ অ্যাকাউন্ট নেই!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])
            )
            return
        kb = [[InlineKeyboardButton(f"🗑️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")])
        await query.edit_message_text(
            "🗑️ **সরানোর জন্য ব্যাকআপ নির্বাচন করুন:**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "ac_bk_to_run":
        ba = get_backup_accounts()
        if not ba:
            await query.edit_message_text(
                "❌ **কোনো ব্যাকআপ অ্যাকাউন্ট নেই!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])
            )
            return
        kb = [[InlineKeyboardButton(f"➡️ {a.get('name','?')} ({a.get('phone','N/A')})", callback_data=f"b2r_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")])
        await query.edit_message_text(
            "➡️ **কোন ব্যাকআপ সক্রিয় করতে চান?**\n\n"
            "অটো রিপ্লাই + স্প্যাম চালু হবে!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("b2r_"):
        bid = data.split('_')[1]
        backup_acc = None
        for a in get_backup_accounts():
            if a['id'] == bid:
                backup_acc = a
                break
        if not backup_acc:
            await query.edit_message_text("❌ অ্যাকাউন্ট পাওয়া যায়নি!")
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
                await query.edit_message_text(
                    f"✅ **{backup_acc.get('name','?')}** এখন সক্রিয়!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])
                )
        except Exception as e:
            await query.edit_message_text(
                f"❌ ব্যর্থ হয়েছে: {str(e)[:100]}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])
            )

    elif data.startswith("acbkd_"):
        bid = data.split('_')[1]
        remove_account_data(bid)
        await query.edit_message_text(
            "✅ **ব্যাকআপ সরানো হয়েছে!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])
        )

    elif data == "ac_ls":
        all_a = get_all_accounts()
        if not all_a:
            await query.edit_message_text(
                "❌ **কোনো অ্যাকাউন্ট নেই!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
            )
            return
        txt = f"📋 **সব অ্যাকাউন্ট ({len(all_a)})**\n\n"
        for i, a in enumerate(all_a, 1):
            n = a.get('name', '?')
            p = a.get('phone', 'N/A')
            tp = "🔵 মূল" if not a.get('is_backup') else "🟣 ব্যাকআপ"
            st = "🟢" if any(x['id'] == a['id'] for x in active_accounts) else "🔴"
            txt += f"{st} {tp} {i}. **{n}** 📱{p}\n"
        await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]]))
        # ====== CHANNEL BACKUP ======
    elif data == "m_channel":
        ch_data = load_channel_backup()
        main_chs = ch_data.get('main_channels', [])
        bk_chs = ch_data.get('backup_channels', [])
        active_ch = ch_data.get('active_channel', None)
        
        txt = (
            f"💾 **চ্যানেল ব্যাকআপ সিস্টেম**\n\n"
            f"═══════════════════════\n"
            f"📌 মেইন চ্যানেল: {len(main_chs)}টি\n"
            f"📌 ব্যাকআপ চ্যানেল: {len(bk_chs)}টি\n"
            f"✅ সক্রিয়: {active_ch.get('title','❌ নেই') if active_ch else '❌ নেই'}\n"
            f"═══════════════════════\n\n"
            f"যখন মেইন চ্যানেল থেকে কিক/ব্যান করা হবে,\n"
            f"অটোমেটিক ব্যাকআপ চ্যানেলে জয়েন হবে\n"
            f"এবং স্প্যাম চালু থাকবে!\n"
            f"আপনার কাস্টমাররা কখনো হারিয়ে যাবে না! 🚀"
        )
        
        kb = [
            [InlineKeyboardButton("➕ মেইন চ্যানেল যোগ করুন", callback_data="ch_add_main")],
            [InlineKeyboardButton("➕ ব্যাকআপ চ্যানেল যোগ করুন", callback_data="ch_add_backup")],
            [InlineKeyboardButton("📋 তালিকা দেখুন", callback_data="ch_list")],
            [InlineKeyboardButton("🗑️ চ্যানেল সরান", callback_data="ch_remove")],
            [InlineKeyboardButton(f"{'✅ চালু' if get_setting('channel_backup_enabled', True) else '❌ বন্ধ'} চ্যানেল ব্যাকআপ", callback_data="ch_toggle")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ch_add_main":
        context.user_data['await'] = 'ch_add_main'
        await query.edit_message_text(
            "📢 **মেইন চ্যানেলের আইডি বা ইউজারনেম পাঠান:**\n\n"
            "উদাহরণ: @yourchannel অথবা -1001234567890\n\n"
            "⚠️ অ্যাকাউন্টটি অবশ্যই চ্যানেলের মেম্বার হতে হবে!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
        )

    elif data == "ch_add_backup":
        context.user_data['await'] = 'ch_add_backup'
        await query.edit_message_text(
            "📢 **ব্যাকআপ চ্যানেলের আইডি বা ইউজারনেম পাঠান:**\n\n"
            "উদাহরণ: @backupchannel অথবা -1001234567890\n\n"
            "যখন মেইন চ্যানেল থেকে কিক করা হবে,\n"
            "অটোমেটিক এই চ্যানেলে জয়েন হবে!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
        )

    elif data == "ch_list":
        ch_data = load_channel_backup()
        txt = "📋 **চ্যানেল তালিকা:**\n\n"
        txt += "═══ 📌 মেইন চ্যানেল: ═══\n"
        if ch_data['main_channels']:
            for i, ch in enumerate(ch_data['main_channels'], 1):
                txt += f"{i}. **{ch.get('title','?')}** ({ch.get('id','?')})\n"
        else:
            txt += "❌ কোনো মেইন চ্যানেল নেই\n"
        txt += "\n═══ 💾 ব্যাকআপ চ্যানেল: ═══\n"
        if ch_data['backup_channels']:
            for i, ch in enumerate(ch_data['backup_channels'], 1):
                txt += f"{i}. **{ch.get('title','?')}** ({ch.get('id','?')})\n"
        else:
            txt += "❌ কোনো ব্যাকআপ চ্যানেল নেই\n"
        txt += f"\n✅ সক্রিয় চ্যানেল: {ch_data['active_channel'].get('title','❌ নেই') if ch_data['active_channel'] else '❌ নেই'}"
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif data == "ch_remove":
        ch_data = load_channel_backup()
        all_chs = ch_data['main_channels'] + ch_data['backup_channels']
        if not all_chs:
            await query.edit_message_text(
                "❌ **কোনো চ্যানেল নেই!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
            )
            return
        kb = []
        for ch in all_chs:
            label = f"🗑️ {ch.get('title','?')[:20]}"
            kb.append([InlineKeyboardButton(label, callback_data=f"chrm_{ch['id']}_{ch.get('type','main')}")])
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")])
        await query.edit_message_text(
            "🗑️ **সরানোর জন্য চ্যানেল নির্বাচন করুন:**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )

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
        await query.edit_message_text(
            "✅ **চ্যানেল সরানো হয়েছে!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
        )

    elif data == "ch_toggle":
        cur = get_setting('channel_backup_enabled', True)
        set_setting('channel_backup_enabled', not cur)
        status = "✅ চালু" if not cur else "❌ বন্ধ"
        await query.edit_message_text(
            f"✅ **চ্যানেল ব্যাকআপ এখন {status}!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
        )

    # ====== AUTO REPLY ======
    elif data == "m_ar":
        running = sum(1 for a in active_accounts if a.get('enabled', True))
        total = len(active_accounts)
        status = "🟢 **সক্রিয়**" if auto_reply_enabled else "🔴 **বন্ধ**"
        text = (
            f"🤖 **অটো রিপ্লাই**\n\n"
            f"স্ট্যাটাস: {status}\n"
            f"সক্রিয় অ্যাকাউন্ট: {running}/{total}\n\n"
            f"নিচের অপশন থেকে বাছাই করুন:"
        )
        kb = [
            [InlineKeyboardButton("▶️ সব চালু করুন", callback_data="ar_start")],
            [InlineKeyboardButton("⏹️ সব বন্ধ করুন", callback_data="ar_stop")],
            [InlineKeyboardButton("📝 ওয়েলকাম মেসেজ", callback_data="ar_welcome")],
            [InlineKeyboardButton("🚫 ফটো ব্লক", callback_data="ar_blockphoto")],
            [InlineKeyboardButton("⌨️ টাইপিং সময়", callback_data="ar_typing")],
            [InlineKeyboardButton("⏱️ অপেক্ষার সময়", callback_data="ar_waittime")],
            [InlineKeyboardButton("🚫 ইগনোর মেসেজ", callback_data="ar_ignore")],
            [InlineKeyboardButton("📋 কাস্টম রিপ্লাই", callback_data="ar_replies")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_start":
        auto_reply_enabled = True
        await setup_auto_reply_all()
        await query.edit_message_text(
            "✅ **অটো রিপ্লাই চালু হয়েছে!**\n\n"
            "সমস্ত সক্রিয় অ্যাকাউন্টে অটো রিপ্লাই কাজ করবে।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]])
        )

    elif data == "ar_stop":
        auto_reply_enabled = False
        await remove_auto_reply_all()
        await query.edit_message_text(
            "⏹️ **অটো রিপ্লাই বন্ধ করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]])
        )

    elif data == "ar_welcome":
        enabled = get_setting('welcome_enabled', True)
        status = "✅ চালু" if enabled else "❌ বন্ধ"
        has_img = "✅ আছে" if WELCOME_IMAGE_FILE.exists() else "❌ নেই"
        txt = (
            f"📝 **ওয়েলকাম মেসেজ সেটিংস**\n\n"
            f"স্ট্যাটাস: {status}\n"
            f"ইমেজ: {has_img}\n\n"
            f"প্রথম মেসেজ পাঠানোর পর কাস্টমারকে\n"
            f"স্বয়ংক্রিয়ভাবে ওয়েলকাম মেসেজ যাবে!"
        )
        kb = [
            [InlineKeyboardButton(f"{'✅ চালু' if enabled else '❌ বন্ধ'} টগল", callback_data="ar_welcome_tog")],
            [InlineKeyboardButton("📝 টেক্সট ১ সম্পাদনা", callback_data="ar_welcome_edit")],
            [InlineKeyboardButton("📝 টেক্সট ২ সম্পাদনা", callback_data="ar_welcome_edit2")],
            [InlineKeyboardButton("🖼️ ইমেজ সেট করুন", callback_data="ar_welcome_img")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_welcome_tog":
        cur = get_setting('welcome_enabled', True)
        set_setting('welcome_enabled', not cur)
        enabled = not cur
        status = "✅ চালু" if enabled else "❌ বন্ধ"
        has_img = "✅ আছে" if WELCOME_IMAGE_FILE.exists() else "❌ নেই"
        txt = (
            f"📝 **ওয়েলকাম মেসেজ সেটিংস**\n\n"
            f"স্ট্যাটাস: {status}\n"
            f"ইমেজ: {has_img}\n\n"
            f"প্রথম মেসেজ পাঠানোর পর কাস্টমারকে\n"
            f"স্বয়ংক্রিয়ভাবে ওয়েলকাম মেসেজ যাবে!"
        )
        kb = [
            [InlineKeyboardButton(f"{'✅ চালু' if enabled else '❌ বন্ধ'} টগল", callback_data="ar_welcome_tog")],
            [InlineKeyboardButton("📝 টেক্সট ১ সম্পাদনা", callback_data="ar_welcome_edit")],
            [InlineKeyboardButton("📝 টেক্সট ২ সম্পাদনা", callback_data="ar_welcome_edit2")],
            [InlineKeyboardButton("🖼️ ইমেজ সেট করুন", callback_data="ar_welcome_img")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_welcome_edit":
        context.user_data['await'] = 'welcome_text'
        cur = get_setting('welcome_message', '')
        await query.edit_message_text(
            f"📝 **নতুন ওয়েলকাম টেক্সট ১ লিখুন:**\n\nবর্তমান:\n{cur or 'সেট করা হয়নি'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]])
        )

    elif data == "ar_welcome_edit2":
        context.user_data['await'] = 'welcome_text_2'
        cur = get_setting('welcome_message_2', '')
        await query.edit_message_text(
            f"📝 **নতুন ওয়েলকাম টেক্সট ২ লিখুন (৩০সে পর পাঠাবে):**\n\nবর্তমান:\n{cur or 'সেট করা হয়নি'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]])
        )

    elif data == "ar_welcome_img":
        context.user_data['await'] = 'welcome_image'
        await query.edit_message_text(
            "🖼️ **ওয়েলকাম ইমেজ পাঠান:**\n\n"
            "যে ছবিটি ওয়েলকাম মেসেজের সাথে\n"
            "পাঠাতে চান, সেটি পাঠান।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]])
        )

    elif data == "ar_blockphoto":
        enabled = get_setting('block_photo_enabled', True)
        txt = f"🚫 **ফটো ব্লক:** {'✅ চালু' if enabled else '❌ বন্ধ'}\n\nফটো সহ মেসেজ ইগনোর করবে কিনা।"
        kb = [
            [InlineKeyboardButton(f"{'✅ চালু' if enabled else '❌ বন্ধ'} টগল", callback_data="ar_blockphoto_tog")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_blockphoto_tog":
        cur = get_setting('block_photo_enabled', True)
        set_setting('block_photo_enabled', not cur)
        enabled = not cur
        txt = f"🚫 **ফটো ব্লক:** {'✅ চালু' if enabled else '❌ বন্ধ'}"
        kb = [
            [InlineKeyboardButton(f"{'✅ চালু' if enabled else '❌ বন্ধ'} টগল", callback_data="ar_blockphoto_tog")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_typing":
        enabled = get_setting('typing_enabled', True)
        duration = int(get_setting('typing_duration', 240))
        txt = f"⌨️ **টাইপিং ইফেক্ট:** {'✅ চালু' if enabled else '❌ বন্ধ'} | সময়: {duration}সে\n\nকাস্টমারকে টাইপিং ইফেক্ট দেখাবে।"
        kb = [
            [InlineKeyboardButton(f"{'✅ চালু' if enabled else '❌ বন্ধ'} টগল", callback_data="ar_typing_tog")],
            [InlineKeyboardButton("⏱️ সময় সেট করুন", callback_data="ar_typing_time")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_typing_tog":
        cur = get_setting('typing_enabled', True)
        set_setting('typing_enabled', not cur)
        enabled = not cur
        duration = int(get_setting('typing_duration', 240))
        txt = f"⌨️ **টাইপিং ইফেক্ট:** {'✅ চালু' if enabled else '❌ বন্ধ'} | সময়: {duration}সে"
        kb = [
            [InlineKeyboardButton(f"{'✅ চালু' if enabled else '❌ বন্ধ'} টগল", callback_data="ar_typing_tog")],
            [InlineKeyboardButton("⏱️ সময় সেট করুন", callback_data="ar_typing_time")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ar_typing_time":
        context.user_data['await'] = 'typing_time'
        await query.edit_message_text(
            f"⏱️ **টাইপিং সময় লিখুন (০-৩০০ সেকেন্ড):**\n\nবর্তমান: {get_setting('typing_duration', 240)} সেকেন্ড",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_typing")]])
        )

    elif data == "ar_waittime":
        current = int(get_setting('wait_time', 300))
        txt = f"⏱️ **অপেক্ষার সময়:** {current}সে ({current//60}মি)\n\nমেসেজ পড়ার পর কত সেকেন্ড অপেক্ষা করে রিপ্লাই দেবে।"
        kb = [
            [InlineKeyboardButton("০ সে", callback_data="wt_0"), InlineKeyboardButton("৬০ সে", callback_data="wt_60")],
            [InlineKeyboardButton("১২০ সে", callback_data="wt_120"), InlineKeyboardButton("৩০০ সে", callback_data="wt_300")],
            [InlineKeyboardButton("কাস্টম", callback_data="wt_custom")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("wt_"):
        val = data.split("_")[1]
        if val == "custom":
            context.user_data['await'] = 'wait_time'
            await query.edit_message_text(
                f"⏱️ **সেকেন্ড লিখুন (০-৬০০):**\n\nবর্তমান: {get_setting('wait_time', 300)} সে",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]])
            )
        else:
            set_setting('wait_time', int(val))
            await query.edit_message_text(
                f"✅ **অপেক্ষার সময় {val} সেকেন্ড সেট করা হয়েছে!**",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]])
            )

    elif data == "ar_ignore":
        context.user_data['await'] = 'ignore'
        cur = get_setting('ignored_messages', '')
        txt = "🚫 **ইগনোর মেসেজ:**\n\nযেসব মেসেজ অটো রিপ্লাই দেবে না।\nপ্রতি লাইনে একটি করে কীওয়ার্ড লিখুন।\n\n"
        if cur:
            txt += f"বর্তমান:\n{cur}"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    elif data == "ar_replies":
        replies = load_json(REPLIES_FILE, [])
        txt = "📋 **কাস্টম রিপ্লাই:**\n\nকীওয়ার্ড যুক্ত মেসেজ পেলে\nস্বয়ংক্রিয়ভাবে নির্দিষ্ট রিপ্লাই দেবে।\n\n"
        if replies:
            for r in replies[-10:]:
                txt += f"🔑 {r['keyword'][:12]} → 💬 {r['reply'][:20]}...\n"
        else:
            txt += "❌ কোনো কাস্টম রিপ্লাই নেই।\n\n/add_reply কীওয়ার্ড রিপ্লাই_টেক্সট\nএই কমান্ড ব্যবহার করে যোগ করুন।"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    # ====== GROUP SPAM ======
    elif data == "m_gs":
        run = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        st = "🟢 **সক্রিয়**" if group_spam_enabled else "🔴 **বন্ধ**"
        sent = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        txt = (
            f"📨 **গ্রুপ স্প্যাম**\n\n"
            f"স্ট্যাটাস: {st}\n"
            f"চলমান: {run}/{len(active_accounts)}\n"
            f"মোট পাঠানো: {sent}টি\n\n"
            f"গ্রুপ/চ্যানেলে অটোমেটিক মেসেজ পাঠাবে!"
        )
        kb = [
            [InlineKeyboardButton("▶️ সব চালু করুন", callback_data="gs_start"), InlineKeyboardButton("⏹️ সব বন্ধ করুন", callback_data="gs_stop")],
            [InlineKeyboardButton("⚡ স্পিড", callback_data="gs_spd")],
            [InlineKeyboardButton("💬 মেসেজ", callback_data="gs_msg")],
            [InlineKeyboardButton("📊 পরিসংখ্যান", callback_data="gs_st")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "gs_start":
        group_spam_enabled = True
        await start_spam_all()
        await query.edit_message_text(
            "✅ **স্প্যাম চালু হয়েছে!**\n\n"
            "সমস্ত সক্রিয় অ্যাকাউন্টে গ্রুপ স্প্যাম শুরু হয়েছে!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]])
        )

    elif data == "gs_stop":
        group_spam_enabled = False
        await stop_spam_all()
        await query.edit_message_text(
            "⏹️ **স্প্যাম বন্ধ করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]])
        )

    elif data == "gs_spd":
        cur = get_setting('spam_speed', 'medium')
        speed_names = {'super_fast': '⚡ সুপার ফাস্ট', 'fast': '🚀 ফাস্ট', 'medium': '🚗 মিডিয়াম', 'slow': '🐢 স্লো'}
        txt = f"⚡ **স্প্যাম স্পিড:** {speed_names.get(cur, cur)}"
        kb = [
            [InlineKeyboardButton(f"{'✅' if cur=='super_fast' else ''} ⚡ সুপার ফাস্ট", callback_data="gs_sf")],
            [InlineKeyboardButton(f"{'✅' if cur=='fast' else ''} 🚀 ফাস্ট", callback_data="gs_fa")],
            [InlineKeyboardButton(f"{'✅' if cur=='medium' else ''} 🚗 মিডিয়াম", callback_data="gs_me")],
            [InlineKeyboardButton(f"{'✅' if cur=='slow' else ''} 🐢 স্লো", callback_data="gs_sl")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data in ["gs_sf", "gs_fa", "gs_me", "gs_sl"]:
        m = {'gs_sf': 'super_fast', 'gs_fa': 'fast', 'gs_me': 'medium', 'gs_sl': 'slow'}
        speed_names = {'super_fast': 'সুপার ফাস্ট', 'fast': 'ফাস্ট', 'medium': 'মিডিয়াম', 'slow': 'স্লো'}
        set_setting('spam_speed', m[data])
        await query.edit_message_text(
            f"✅ **স্পিড সেট করা হয়েছে: {speed_names[m[data]]}**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]])
        )

    elif data == "gs_msg":
        msgs = load_spam_messages()
        txt = "💬 **স্প্যাম মেসেজ:**\n\n"
        if msgs:
            for i, m in enumerate(msgs[:5], 1):
                txt += f"{i}. 📝 {m['text'][:40]}...\n"
        else:
            txt += "📝 ডিফল্ট মেসেজ ব্যবহার করা হবে।\n"
        kb = [
            [InlineKeyboardButton("➕ মেসেজ যোগ করুন", callback_data="gs_msg_add")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "gs_msg_add":
        context.user_data['await'] = 'gs_msg_add'
        await query.edit_message_text(
            "📝 **স্প্যাম মেসেজ টেক্সট পাঠান:**\n\n"
            "যে মেসেজটি গ্রুপে পাঠাতে চান, সেটি লিখুন।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]])
        )

    elif data == "gs_st":
        txt = "📊 **পরিসংখ্যান:**\n\n"
        for a in active_accounts:
            s = account_stats.get(a['id'], {}).get('spam_sent', 0)
            r = "▶️" if account_stats.get(a['id'], {}).get('spam_running', False) else "⏹️"
            txt += f"{r} **{a.get('name','?')[:10]}**: {s}টি মেসেজ\n"
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))

    # ====== SETTINGS ======
    elif data == "m_set":
        bp = "✅ চালু" if get_setting('block_photo_enabled', True) else "❌ বন্ধ"
        fs = "✅ চালু" if get_setting('flood_slow_mode', True) else "❌ বন্ধ"
        ln = "✅ চালু" if logout_notification_enabled else "❌ বন্ধ"
        has_qr = "✅ আছে" if QR_CODE_FILE.exists() else "❌ নেই"
        txt = (
            f"⚙️ **সেটিংস**\n\n"
            f"🚫 ফটো ব্লক: {bp}\n"
            f"🐢 ফ্লাড স্লো: {fs}\n"
            f"🔔 লগআউট এলার্ট: {ln}\n"
            f"📱 কিউআর কোড: {has_qr}\n\n"
            f"নিচের অপশন থেকে বাছাই করুন:"
        )
        kb = [
            [InlineKeyboardButton(f"🚫 ফটো ব্লক: {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"🐢 ফ্লাড স্লো: {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"🔔 লগআউট এলার্ট: {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("💰 পেমেন্ট সেটিংস", callback_data="st_pay")],
            [InlineKeyboardButton(f"📱 কিউআর কোড {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_bp":
        cur = get_setting('block_photo_enabled', True)
        set_setting('block_photo_enabled', not cur)
        bp = "✅ চালু" if not cur else "❌ বন্ধ"
        fs = "✅ চালু" if get_setting('flood_slow_mode', True) else "❌ বন্ধ"
        ln = "✅ চালু" if logout_notification_enabled else "❌ বন্ধ"
        has_qr = "✅ আছে" if QR_CODE_FILE.exists() else "❌ নেই"
        txt = (
            f"⚙️ **সেটিংস**\n\n"
            f"🚫 ফটো ব্লক: {bp}\n"
            f"🐢 ফ্লাড স্লো: {fs}\n"
            f"🔔 লগআউট এলার্ট: {ln}\n"
            f"📱 কিউআর কোড: {has_qr}"
        )
        kb = [
            [InlineKeyboardButton(f"🚫 ফটো ব্লক: {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"🐢 ফ্লাড স্লো: {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"🔔 লগআউট এলার্ট: {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("💰 পেমেন্ট সেটিংস", callback_data="st_pay")],
            [InlineKeyboardButton(f"📱 কিউআর কোড {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_fs":
        cur = get_setting('flood_slow_mode', True)
        set_setting('flood_slow_mode', not cur)
        bp = "✅ চালু" if get_setting('block_photo_enabled', True) else "❌ বন্ধ"
        fs = "✅ চালু" if not cur else "❌ বন্ধ"
        ln = "✅ চালু" if logout_notification_enabled else "❌ বন্ধ"
        has_qr = "✅ আছে" if QR_CODE_FILE.exists() else "❌ নেই"
        txt = (
            f"⚙️ **সেটিংস**\n\n"
            f"🚫 ফটো ব্লক: {bp}\n"
            f"🐢 ফ্লাড স্লো: {fs}\n"
            f"🔔 লগআউট এলার্ট: {ln}\n"
            f"📱 কিউআর কোড: {has_qr}"
        )
        kb = [
            [InlineKeyboardButton(f"🚫 ফটো ব্লক: {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"🐢 ফ্লাড স্লো: {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"🔔 লগআউট এলার্ট: {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("💰 পেমেন্ট সেটিংস", callback_data="st_pay")],
            [InlineKeyboardButton(f"📱 কিউআর কোড {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_ln":
        logout_notification_enabled = not logout_notification_enabled
        bp = "✅ চালু" if get_setting('block_photo_enabled', True) else "❌ বন্ধ"
        fs = "✅ চালু" if get_setting('flood_slow_mode', True) else "❌ বন্ধ"
        ln = "✅ চালু" if logout_notification_enabled else "❌ বন্ধ"
        has_qr = "✅ আছে" if QR_CODE_FILE.exists() else "❌ নেই"
        txt = (
            f"⚙️ **সেটিংস**\n\n"
            f"🚫 ফটো ব্লক: {bp}\n"
            f"🐢 ফ্লাড স্লো: {fs}\n"
            f"🔔 লগআউট এলার্ট: {ln}\n"
            f"📱 কিউআর কোড: {has_qr}"
        )
        kb = [
            [InlineKeyboardButton(f"🚫 ফটো ব্লক: {bp}", callback_data="st_bp")],
            [InlineKeyboardButton(f"🐢 ফ্লাড স্লো: {fs}", callback_data="st_fs")],
            [InlineKeyboardButton(f"🔔 লগআউট এলার্ট: {ln}", callback_data="st_ln")],
            [InlineKeyboardButton("💰 পেমেন্ট সেটিংস", callback_data="st_pay")],
            [InlineKeyboardButton(f"📱 কিউআর কোড {has_qr}", callback_data="st_qr")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_pay":
        upi = get_setting('upi_id', '')
        paytm = get_setting('paytm_num', '')
        txt = (
            f"💰 **পেমেন্ট সেটিংস**\n\n"
            f"🏦 UPI: {upi or '❌ সেট করা হয়নি'}\n"
            f"📱 PayTm: {paytm or '❌ সেট করা হয়নি'}"
        )
        kb = [
            [InlineKeyboardButton("🏦 UPI সেট করুন", callback_data="st_upi")],
            [InlineKeyboardButton("📱 PayTm সেট করুন", callback_data="st_paytm")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "st_upi":
        context.user_data['await'] = 'upi'
        await query.edit_message_text(
            "🏦 **UPI আইডি লিখুন:**\n\nউদাহরণ: user@upi",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]])
        )

    elif data == "st_paytm":
        context.user_data['await'] = 'paytm'
        await query.edit_message_text(
            "📱 **PayTm নম্বর লিখুন:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]])
        )

    elif data == "st_qr":
        context.user_data['await'] = 'qr_code'
        await query.edit_message_text(
            "📱 **কিউআর কোড ইমেজ পাঠান:**\n\n"
            "পেমেন্টের জন্য কিউআর কোড সেট করুন।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]])
        )

    # ====== STATUS ======
    elif data == "m_stat":
        ar = "✅ চালু" if auto_reply_enabled else "❌ বন্ধ"
        gs = "✅ চালু" if group_spam_enabled else "❌ বন্ধ"
        ttl_auto = sum(account_stats.get(a['id'], {}).get('auto_sent', 0) for a in active_accounts)
        ttl_spam = sum(account_stats.get(a['id'], {}).get('spam_sent', 0) for a in active_accounts)
        spm_act = sum(1 for a in active_accounts if account_stats.get(a['id'], {}).get('spam_running', False))
        ad_data = load_auto_delete_data()
        deleted = ad_data.get('deleted_count', 0)
        txt = (
            f"📊 **স্ট্যাটাস ও পরিসংখ্যান**\n\n"
            f"═══════════════════════\n"
            f"🤖 অটো রিপ্লাই: {ar}\n"
            f"📨 গ্রুপ স্প্যাম: {gs}\n"
            f"═══════════════════════\n"
            f"👤 সক্রিয় অ্যাকাউন্ট: {len(active_accounts)}\n"
            f"📨 স্প্যাম চলছে: {spm_act}\n"
            f"═══════════════════════\n"
            f"💬 অটো পাঠানো: {ttl_auto}টি\n"
            f"📤 স্প্যাম পাঠানো: {ttl_spam}টি\n"
            f"👥 কাস্টমার: {len(customer_count)}জন\n"
            f"🗑️ অটো ডিলিট: {deleted}টি মেসেজ\n"
            f"═══════════════════════"
        )
        await query.edit_message_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 রিফ্রেশ", callback_data="m_stat"), InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
            ])
        )

    # ====== ADMIN PANEL ======
    elif data == "m_adm":
        txt = (
            "🔐 **অ্যাডমিন প্যানেল**\n\n"
            "শুধুমাত্র ওনার ও অ্যাডমিনদের জন্য।"
        )
        kb = [
            [InlineKeyboardButton("📢 ব্রডকাস্ট", callback_data="ad_bc")],
            [InlineKeyboardButton("📋 লগ দেখুন", callback_data="ad_lg")],
            [InlineKeyboardButton("🔄 বট রিস্টার্ট", callback_data="ad_rt")],
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]
        ]
        await query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ad_bc":
        context.user_data['await'] = 'broadcast'
        await query.edit_message_text(
            "📢 **ব্রডকাস্ট মেসেজ পাঠান:**\n\n"
            "সব কাস্টমারকে পাঠানোর জন্য মেসেজ লিখুন।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]])
        )

    elif data == "ad_lg":
        log_path = Path('bot.log')
        if log_path.exists():
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-20:]
            txt = "📋 **শেষ ২০টি লগ**\n\n" + "".join(lines[-500:])
        else:
            txt = "❌ কোনো লগ ফাইল পাওয়া যায়নি।"
        await query.edit_message_text(txt[:4000], parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]]))

    elif data == "ad_rt":
        await query.edit_message_text(
            "🔄 **বট রিস্টার্ট হচ্ছে...**\n\n"
            "কয়েক সেকেন্ড অপেক্ষা করুন।",
            parse_mode='Markdown'
        )
        os.execv(sys.executable, [sys.executable] + sys.argv)

    else:
        await query.edit_message_text(
            f"❌ **অজানা অপশন:** {data}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])
        )
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
                await update.message.reply_text(
                    f"✅ **কাস্টম রিপ্লাই যোগ করা হয়েছে!**\n\n🔑 {parts[1]} → 💬 {parts[2][:30]}",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "❌ **ভুল ফরম্যাট!**\n\nসঠিক ব্যবহার:\n`/add_reply কীওয়ার্ড রিপ্লাই_টেক্সট`",
                    parse_mode='Markdown'
                )
        elif text == '/new_join_link':
            context.user_data['await'] = 'harden_link_add'
            await update.message.reply_text(
                "🔗 **গ্রুপ ইনভাইট লিংক পাঠান:**",
                parse_mode='Markdown'
            )
        elif text == '/restart' and user_id == OWNER_ID:
            await update.message.reply_text("🔄 **বট রিস্টার্ট হচ্ছে...**")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            await update.message.reply_text(
                "❌ **অজানা কমান্ড!**\n\n📌 /menu ব্যবহার করুন।",
                parse_mode='Markdown'
            )
        return

    # Handle all await states
    if await_state == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **ওয়েলকাম টেক্সট ১ আপডেট করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]])
        )

    elif await_state == 'welcome_text_2':
        set_setting('welcome_message_2', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **ওয়েলকাম টেক্সট ২ আপডেট করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]])
        )

    elif await_state == 'wait_time':
        try:
            val = max(0, min(600, int(text)))
            set_setting('wait_time', val)
            context.user_data.pop('await', None)
            await update.message.reply_text(
                f"✅ **অপেক্ষার সময়:** {val} সেকেন্ড সেট করা হয়েছে!",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_waittime")]])
            )
        except:
            await update.message.reply_text("❌ **দয়া করে একটি সংখ্যা লিখুন (০-৬০০)!**")

    elif await_state == 'typing_time':
        try:
            val = int(text)
            if 0 <= val <= 300:
                set_setting('typing_duration', val)
                context.user_data.pop('await', None)
                await update.message.reply_text(
                    f"✅ **টাইপিং সময়:** {val} সেকেন্ড সেট করা হয়েছে!",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_typing")]])
                )
            else:
                await update.message.reply_text("❌ **দয়া করে ০-৩০০ এর মধ্যে একটি সংখ্যা লিখুন!**")
        except:
            await update.message.reply_text("❌ **দয়া করে একটি সংখ্যা লিখুন!**")

    elif await_state == 'ignore':
        set_setting('ignored_messages', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **ইগনোর মেসেজ আপডেট করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]])
        )

    elif await_state == 'harden_name':
        set_setting('new_account_name', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            f"✅ **নাম সেট করা হয়েছে:** {text}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])
        )

    elif await_state == 'harden_bio':
        set_setting('new_account_bio', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **বায়ো সেট করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])
        )

    elif await_state == 'harden_link_add':
        links = load_autojoin_links()
        links.append(text)
        save_autojoin_links(links)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **লিংক যোগ করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]])
        )

    elif await_state == 'harden_ad_time':
        try:
            val = int(text)
            if 1 <= val <= 2592000:
                set_setting('auto_delete_seconds', val)
                context.user_data.pop('await', None)
                time_str = f"{val//86400} দিন" if val >= 86400 else f"{val//3600} ঘণ্টা" if val >= 3600 else f"{val} সেকেন্ড"
                await update.message.reply_text(
                    f"✅ **অটো-ডিলিট টাইমার:** {val} সেকেন্ড ({time_str})",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_config")]])
                )
            else:
                await update.message.reply_text("❌ **দয়া করে ১-২৫৯২০০০ সেকেন্ডের মধ্যে লিখুন (১সে - ৩০ দিন)!**")
        except:
            await update.message.reply_text("❌ **দয়া করে একটি সংখ্যা লিখুন!**")

    elif await_state == 'set_proxy':
        aid = context.user_data.get('proxy_account_id', '')
        if text.lower() == 'remove':
            remove_account_proxy(aid)
            context.user_data.pop('await', None)
            context.user_data.pop('proxy_account_id', None)
            await update.message.reply_text(
                "✅ **প্রক্সি সরানো হয়েছে!** অ্যাকাউন্ট ডিফল্ট প্রক্সি ব্যবহার করবে।",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_proxy")]])
            )
        else:
            try:
                proto_part = text.split('://')
                if len(proto_part) != 2:
                    raise ValueError("ভুল ফরম্যাট")
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
                await update.message.reply_text(
                    f"✅ **প্রক্সি সেট করা হয়েছে!**\n\n{proxy_type}://{user or 'none'}@{host}:{port}",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_proxy")]])
                )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ **ভুল প্রক্সি ফরম্যাট:** {str(e)[:50]}\n\n"
                    f"সঠিক ফরম্যাট: type://user:pass@host:port\n"
                    f"উদাহরণ: socks5://user:pass@127.0.0.1:9050",
                    parse_mode='Markdown'
                )

    elif await_state == 'ch_add_main':
        ch_data = load_channel_backup()
        ch_data['main_channels'].append({'id': text, 'title': text, 'type': 'main'})
        save_channel_backup(ch_data)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **মেইন চ্যানেল যোগ করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
        )

    elif await_state == 'ch_add_backup':
        ch_data = load_channel_backup()
        ch_data['backup_channels'].append({'id': text, 'title': text, 'type': 'backup'})
        save_channel_backup(ch_data)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **ব্যাকআপ চ্যানেল যোগ করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])
        )

    elif await_state == 'upi':
        set_setting('upi_id', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **UPI আইডি সেট করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]])
        )

    elif await_state == 'paytm':
        set_setting('paytm_num', text)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **PayTm নম্বর সেট করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="st_pay")]])
        )

    elif await_state == 'broadcast':
        context.user_data.pop('await', None)
        msg = f"📢 **ব্রডকাস্ট বার্তা**\n\n{text}"
        sent = 0
        for uid in customer_count:
            try:
                await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode='Markdown')
                sent += 1
                await asyncio.sleep(0.1)
            except:
                pass
        await update.message.reply_text(
            f"✅ **ব্রডকাস্ট সম্পন্ন!**\n\n{sent} জন কাস্টমারকে পাঠানো হয়েছে।",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_adm")]])
        )

    elif await_state == 'gs_msg_add':
        add_spam_message(text)
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "✅ **স্প্যাম মেসেজ যোগ করা হয়েছে!**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msg")]])
        )

    elif await_state == 'ac_ph':
        context.user_data['phone'] = text
        context.user_data['await'] = 'ac_otp'
        try:
            ac_api_id = int(os.environ.get('API_ID', str(DEFAULT_API_ID)))
            ac_api_hash = os.environ.get('API_HASH', DEFAULT_API_HASH)
            if not ac_api_id or not ac_api_hash:
                await update.message.reply_text(
                    "❌ **API_ID বা API_HASH সেট করা নেই!**\n\n"
                    "এনভায়রনমেন্ট ভেরিয়েবলে সেট করুন:\n"
                    "API_ID = আপনার আইডি\n"
                    "API_HASH = আপনার হ্যাশ",
                    parse_mode='Markdown'
                )
                context.user_data.pop('await', None)
                return
            client = TelegramClient(StringSession(), ac_api_id, ac_api_hash)
            await client.connect()
            send_code = await client.send_code_request(text)
            context.user_data['ac_client'] = client
            context.user_data['ac_phone_code_hash'] = send_code.phone_code_hash
            await update.message.reply_text(
                f"✅ **OTP পাঠানো হয়েছে** {text} এ!\n\n"
                f"📱 আপনার ফোনে প্রাপ্ত OTP কোডটি লিখুন:",
                parse_mode='Markdown'
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ **ব্যর্থ হয়েছে:** {str(e)[:100]}",
                parse_mode='Markdown'
            )
            context.user_data.pop('await', None)

    elif await_state == 'ac_otp':
        otp = text.replace(' ', '')
        client = context.user_data.get('ac_client')
        phone = context.user_data.get('phone', '')
        pch = context.user_data.get('ac_phone_code_hash', '')
        if not client:
            await update.message.reply_text(
                "❌ **সেশন শেষ হয়ে গেছে!** আবার শুরু করুন।",
                parse_mode='Markdown'
            )
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
            await update.message.reply_text(
                f"✅ **অ্যাকাউন্ট যোগ করা হয়েছে!** 🎉\n\n"
                f"👤 নাম: {name}\n"
                f"📱 ফোন: {phone}",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
            )
            try:
                n_client = await start_account(acc)
                if n_client:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = n_client
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    if auto_reply_enabled:
                        await setup_auto_reply_for_account(acc['id'], n_client)
                    await update.message.reply_text(
                        f"🟢 **অ্যাকাউন্ট সক্রিয় করা হয়েছে!**\n\n"
                        f"এখন {name} ব্যবহারের জন্য প্রস্তুত!",
                        parse_mode='Markdown'
                    )
            except:
                pass
        except SessionPasswordNeededError:
            context.user_data['await'] = 'ac_2fa'
            await update.message.reply_text(
                "🔐 **২-ফ্যাক্টর পাসওয়ার্ড প্রয়োজন!**\n\n"
                "আপনার Telegram অ্যাকাউন্টের ২FA পাসওয়ার্ড লিখুন:",
                parse_mode='Markdown'
            )
        except PhoneCodeInvalidError:
            await update.message.reply_text(
                "❌ **ভুল OTP!** আবার চেষ্টা করুন:",
                parse_mode='Markdown'
            )
        except PhoneCodeExpiredError:
            await update.message.reply_text(
                "❌ **OTP মেয়াদ শেষ!** আবার শুরু করুন /menu",
                parse_mode='Markdown'
            )
            context.user_data.pop('await', None)

    elif await_state == 'ac_2fa':
        client = context.user_data.get('ac_client')
        phone = context.user_data.get('phone', '')
        if not client:
            await update.message.reply_text(
                "❌ **সেশন শেষ!** আবার শুরু করুন।",
                parse_mode='Markdown'
            )
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
            await update.message.reply_text(
                f"✅ **অ্যাকাউন্ট যোগ করা হয়েছে (২FA সহ)!** 🎉\n\n"
                f"👤 নাম: {name}\n"
                f"📱 ফোন: {phone}",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
            )
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
            await update.message.reply_text(
                f"❌ **২FA ব্যর্থ হয়েছে:** {str(e)[:100]}",
                parse_mode='Markdown'
            )
            context.user_data.pop('await', None)

    elif await_state == 'ac_ss':
        if len(text) < 10:
            await update.message.reply_text(
                "❌ **ভুল সেশন স্ট্রিং!** স্ট্রিংটি খুব ছোট।",
                parse_mode='Markdown'
            )
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
                await update.message.reply_text(
                    f"✅ **অ্যাকাউন্ট যোগ করা হয়েছে!** 🎉\n\n"
                    f"👤 নাম: {name}\n"
                    f"📱 ফোন: {phone}",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])
                )
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
                await update.message.reply_text(
                    "❌ **ব্যবহারকারীর তথ্য পাওয়া যায়নি!**",
                    parse_mode='Markdown'
                )
        except Exception as e:
            await update.message.reply_text(
                f"❌ **ভুল সেশন স্ট্রিং:** {str(e)[:100]}",
                parse_mode='Markdown'
            )
        finally:
            if 'await' in context.user_data:
                context.user_data.pop('await', None)

    elif await_state == 'ac_bk_ss':
        if len(text) < 10:
            await update.message.reply_text(
                "❌ **ভুল সেশন স্ট্রিং!** স্ট্রিংটি খুব ছোট।",
                parse_mode='Markdown'
            )
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
                await update.message.reply_text(
                    f"✅ **ব্যাকআপ অ্যাকাউন্ট যোগ করা হয়েছে!** 💾\n\n"
                    f"👤 নাম: {name}\n"
                    f"📱 ফোন: {phone}",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])
                )
            else:
                await update.message.reply_text(
                    "❌ **ব্যবহারকারীর তথ্য পাওয়া যায়নি!**",
                    parse_mode='Markdown'
                )
        except Exception as e:
            await update.message.reply_text(
                f"❌ **ভুল সেশন স্ট্রিং:** {str(e)[:100]}",
                parse_mode='Markdown'
            )
        finally:
            if 'await' in context.user_data:
                context.user_data.pop('await', None)

    else:
        context.user_data.pop('await', None)
        await update.message.reply_text(
            "❌ **অজানা ইনপুট!** /menu ব্যবহার করুন।",
            parse_mode='Markdown'
        )


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
            await update.message.reply_text(
                "✅ **ওয়েলকাম ইমেজ সেট করা হয়েছে!** 🖼️",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_welcome")]])
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ **ব্যর্থ হয়েছে:** {str(e)[:80]}",
                parse_mode='Markdown'
            )

    elif await_state == 'qr_code':
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(QR_CODE_FILE)
            context.user_data.pop('await', None)
            await update.message.reply_text(
                "✅ **কিউআর কোড সেট করা হয়েছে!** 📱",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_set")]])
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ **ব্যর্থ হয়েছে:** {str(e)[:80]}",
                parse_mode='Markdown'
            )

    elif await_state == 'harden_photo_upload':
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(USER_DATA_DIR / 'new_profile_pic.jpg')
            context.user_data.pop('await', None)
            await update.message.reply_text(
                "✅ **নতুন প্রোফাইল ছবি সেভ করা হয়েছে!**\n\n"
                "পরবর্তী হার্ডেনিং-এ স্বয়ংক্রিয়ভাবে সেট হবে।",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_photo")]])
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ **ব্যর্থ হয়েছে:** {str(e)[:80]}",
                parse_mode='Markdown'
            )

    else:
        await update.message.reply_text(
            "❌ **অপ্রত্যাশিত ফটো!**",
            parse_mode='Markdown'
        )


# ====== ERROR HANDLER ======
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                f"❌ **ত্রুটি:** {str(context.error)[:100]}",
                parse_mode='Markdown'
            )
    except:
        pass


# ====== MAIN FUNCTION ======
async def main():
    """Main entry point."""
    logger.info("🤖 বট শুরু হচ্ছে...")

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN সেট করা নেই!")
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
    loaded_count = 0
    for acc in all_accs:
        if not acc.get('is_backup'):
            try:
                nc = await start_account(acc)
                if nc:
                    active_accounts.append(acc)
                    account_clients[acc['id']] = nc
                    account_stats[acc['id']] = {'auto_sent': 0, 'spam_sent': 0, 'running': False, 'spam_running': False}
                    account_stop_flags[acc['id']] = False
                    loaded_count += 1
                    logger.info(f"✅ অ্যাকাউন্ট লোড: {acc.get('name')} ({acc.get('phone')})")
            except Exception as e:
                logger.error(f"❌ অ্যাকাউন্ট লোড ব্যর্থ {acc.get('name')}: {e}")

    logger.info(f"✅ মোট {loaded_count}টি অ্যাকাউন্ট লোড করা হয়েছে")

    # Auto setup auto-reply handlers if enabled
    if auto_reply_enabled:
        await setup_auto_reply_all()

    # Auto setup auto-delete timer
    try:
        logger.info("⏰ অটো-ডিলিট টাইমার সেটআপ...")
        ad_data = load_auto_delete_data()
        if ad_data.get("enabled", False):
            registered = await setup_auto_delete_fast(ad_data.get("seconds", 86400))
            logger.info(f"✅ অটো-ডিলিট টাইমার: {registered}টি চ্যাট রেজিস্টার")
    except Exception as e:
        logger.error(f"❌ অটো-ডিলিট টাইমার ব্যর্থ: {e}")

    # Start background tasks
    asyncio.create_task(auto_delete_messages_loop(app))
    asyncio.create_task(keepalive_loop())
    asyncio.create_task(account_health_loop())

    await app.updater.start_polling(drop_pending_updates=True)

    logger.info(f"🚀 বট চালু! {len(active_accounts)}টি অ্যাকাউন্ট সক্রিয়।")

    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("⏹️ বট বন্ধ হচ্ছে...")
    except asyncio.CancelledError:
        logger.info("⏹️ টাস্ক ক্যানসেল, বন্ধ হচ্ছে...")
    finally:
        logger.info("⏹️ বট বন্ধ হচ্ছে...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        for aid, client in list(account_clients.items()):
            try:
                await client.disconnect()
            except:
                pass
        logger.info("✅ বট বন্ধ হয়েছে।")


# ====== FLASK WEBHOOK (optional) ======
if FLASK_AVAILABLE:
    flask_app = Flask(__name__)
    flask_app.secret_key = WEBHOOK_SECRET

    @flask_app.route('/')
    def home():
        return jsonify({
            "status": "running",
            "accounts": len(active_accounts),
            "customers": len(customer_count),
            "auto_reply": auto_reply_enabled,
            "group_spam": group_spam_enabled
        })

    @flask_app.route('/health')
    def health():
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "accounts_active": len(active_accounts)
        })

    def run_flask():
        flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)


# ====== ENTRY POINT ======
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🚀 টেলিগ্রাম অটোমেশন বট")
    logger.info(f"🐍 Python: {sys.version}")
    logger.info(f"🤖 PTB Available: {PTB_AVAILABLE}")
    logger.info(f"📱 Telethon Available: {TELETHON_AVAILABLE}")
    logger.info(f"🌐 Flask Available: {FLASK_AVAILABLE}")
    logger.info(f"📁 Accounts file: {ACCOUNTS_FILE}")
    logger.info(f"⏰ Auto-delete file: {AUTO_DELETE_FILE}")
    logger.info("=" * 50)

    # Start Flask in a thread if available (for Render web service)
    if FLASK_AVAILABLE and os.environ.get('RENDER', ''):
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info("🌐 Flask web server background thread-এ চালু হয়েছে")

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("⏹️ ব্যবহারকারী দ্বারা বট বন্ধ করা হয়েছে")
    except Exception as e:
        logger.error(f"❌ মারাত্মক ত্রুটি: {e}")
        traceback.print_exc()
        sys.exit(1)

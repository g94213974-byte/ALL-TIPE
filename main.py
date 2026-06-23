import os, sys, json, asyncio, logging, time, hashlib, base64, re, secrets, threading, uuid, random, string, shutil, requests, html, math, ipaddress, traceback
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse, urljoin, quote, unquote

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('bot.log', encoding='utf-8'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# TELEGRAM IMPORTS
PTB_AVAILABLE = TELETHON_AVAILABLE = STRING_SESSION_AVAILABLE = FLASK_AVAILABLE = False
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
    PTB_AVAILABLE = True
except Exception as e:
    logger.error(f"PTB import failed: {e}")

try:
    from telethon import TelegramClient, events, functions, types, errors
    from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest, SetPrivacyRequest, UpdateProfileRequest
    from telethon.tl.functions.photos import GetUserPhotosRequest, DeletePhotosRequest, UploadProfilePhotoRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest, DeleteHistoryRequest
    from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
    from telethon.tl.types import InputPrivacyKeyStatusTimestamp, InputPrivacyKeyProfilePhoto, InputPrivacyKeyForwards
    from telethon.tl.types import InputPrivacyKeyChatInvite, InputPrivacyKeyPhoneNumber, InputPrivacyKeyAddedByPhone
    from telethon.tl.types import InputPrivacyKeyPhoneCall, InputPrivacyKeyPhoneP2P, InputPrivacyKeyAbout
    from telethon.tl.types import InputPrivacyValueAllowAll, InputPrivacyValueAllowContacts, InputPrivacyValueDisallowAll
    from telethon.errors import FloodWaitError, SessionPasswordNeededError
    from telethon.sessions import StringSession
    TELETHON_AVAILABLE = STRING_SESSION_AVAILABLE = True
except Exception as e:
    logger.error(f"Telethon import failed: {e}")

# ====== CONFIG ======
API_HASH = os.environ.get('API_HASH', '')
API_ID = int(os.environ.get('API_ID', '0'))
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_IDS = list(map(int, filter(None, os.environ.get('ADMIN_IDS', '').split(','))))
OWNER_ID = int(os.environ.get('OWNER_ID', ADMIN_IDS[0] if ADMIN_IDS else '0'))
CRYPTO_KEY = hashlib.sha256(os.environ.get('CRYPTO_KEY', 'default_key').encode()).digest()

PROXY_CONFIG = None
if os.environ.get('USE_PROXY', 'false').lower() == 'true':
    PROXY_CONFIG = {
        'proxy_type': os.environ.get('PROXY_TYPE', 'socks5'),
        'addr': os.environ.get('PROXY_ADDR', '127.0.0.1'),
        'port': int(os.environ.get('PROXY_PORT', '9050')),
        'username': os.environ.get('PROXY_USER', '') or None,
        'password': os.environ.get('PROXY_PASS', '') or None
    }

USER_DATA_DIR = Path('user_data')
USER_DATA_DIR.mkdir(exist_ok=True)

_JSON_FILES = ['accounts', 'tasks', 'config', 'settings', 'auto_delete', 'spam_messages', 'replies', 'customers',
               'channel_backup', 'autojoin_links', 'harden_tasks', 'account_proxies']

def _p(name):
    return USER_DATA_DIR / f'{name}.json'

def jload(name, default=None):
    p = _p(name)
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except:
        pass
    return default if default is not None else {}

def jsave(name, data):
    try:
        f = _p(name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
        return True
    except Exception as e:
        logger.error(f"Save failed {name}: {e}")
        return False

# ====== CORE DATA ======
active_accounts = []
account_clients = {}
account_stats = {}
account_stop_flags = {}
auto_reply_handlers = {}
spam_worker_tasks = {}
auto_reply_enabled = False
group_spam_enabled = False
customer_count = set()

def get_accounts():
    return jload('accounts', {})

def save_accounts(d):
    return jsave('accounts', d)

def find_account(aid):
    """First search active_accounts, then fallback to file"""
    for a in active_accounts:
        if a.get('id') == aid:
            return a
    for v in get_accounts().values():
        if v.get('id') == aid:
            return v
    return None

def add_account_data(acc):
    d = get_accounts()
    d[acc['id']] = acc
    return save_accounts(d)

def remove_account_data(aid):
    d = get_accounts()
    if aid in d:
        del d[aid]
        return save_accounts(d)
    return False

def save_account_proxy(account_id, proxy_config):
    data = jload('account_proxies', {})
    data[account_id] = proxy_config
    return jsave('account_proxies', data)

def remove_account_proxy(account_id):
    data = jload('account_proxies', {})
    if account_id in data:
        del data[account_id]
        return jsave('account_proxies', data)
    return False

# ====== CLIENT MANAGEMENT ======
async def start_account(acc):
    try:
        proxy = jload('account_proxies', {}).get(acc['id']) or PROXY_CONFIG
        c = TelegramClient(
            StringSession(acc.get('session', '')),
            acc.get('api_id', API_ID),
            acc.get('api_hash', API_HASH),
            proxy=proxy
        )
        await c.connect()
        me = await c.get_me()
        return c if me else None
    except Exception as e:
        logger.error(f"start_account failed: {e}")
        return None

# ====== HARDEN ONE CLICK ======
async def harden_one_click(acc):
    results = []
    try:
        proxy = jload('account_proxies', {}).get(acc['id']) or PROXY_CONFIG
        c = TelegramClient(
            StringSession(acc.get('session', '')),
            acc.get('api_id', API_ID),
            acc.get('api_hash', API_HASH),
            proxy=proxy
        )
        await c.connect()
        me = await c.get_me()
        if not me:
            return "❌ অনুমোদিত নয়"

        results.append(f"🔄 **হার্ডেনিং শুরু** - {acc.get('name','?')}")

        # 1. Revoke old sessions
        try:
            auths = await c(GetAuthorizationsRequest())
            revoked = 0
            for a in auths.authorizations:
                if not a.current:
                    try:
                        await c(ResetAuthorizationRequest(hash=a.hash))
                        revoked += 1
                        await asyncio.sleep(0.3)
                    except:
                        pass
            results.append(f"✅ {revoked}টি পুরনো সেশন রিভোক")
        except Exception as e:
            results.append(f"⚠️ সেশন: {str(e)[:40]}")

        # 2. Privacy settings
        privacy_map = [
            (InputPrivacyKeyStatusTimestamp(), [InputPrivacyValueAllowAll()]),
            (InputPrivacyKeyProfilePhoto(), [InputPrivacyValueAllowContacts()]),
            (InputPrivacyKeyForwards(), [InputPrivacyValueAllowContacts()]),
            (InputPrivacyKeyChatInvite(), [InputPrivacyValueAllowAll()]),
            (InputPrivacyKeyPhoneNumber(), [InputPrivacyValueDisallowAll()]),
            (InputPrivacyKeyAddedByPhone(), [InputPrivacyValueDisallowAll()]),
            (InputPrivacyKeyPhoneCall(), [InputPrivacyValueAllowContacts()]),
            (InputPrivacyKeyPhoneP2P(), [InputPrivacyValueDisallowAll()]),
            (InputPrivacyKeyAbout(), [InputPrivacyValueAllowContacts()])
        ]
        for k, v in privacy_map:
            try:
                await c(SetPrivacyRequest(key=k, rules=v))
            except:
                pass
        results.append("✅ প্রাইভেসি সেটিংস শক্তিশালী")

        # 3. Profile name & bio
        sets = jload('settings', {})
        nn = sets.get('new_account_name', '')
        nb = sets.get('new_account_bio', '')
        try:
            if nn:
                await c(UpdateProfileRequest(first_name=nn))
                results.append(f"✅ নাম: {nn}")
            if nb:
                await c(UpdateProfileRequest(about=nb))
                results.append("✅ বায়ো আপডেট")
        except Exception as e:
            results.append(f"⚠️ প্রোফাইল: {str(e)[:40]}")

        # 4. Delete profile photo
        if sets.get('delete_dp_enabled', False):
            try:
                photos = await c(GetUserPhotosRequest(user_id=me.id, offset=0, max_id=0, limit=100))
                if photos and photos.photos:
                    await c(DeletePhotosRequest(id=photos.photos))
                    results.append(f"✅ {len(photos.photos)}টি ছবি মুছে ফেলা")
                else:
                    results.append("ℹ️ ডিপি নেই")
            except:
                results.append("⚠️ ডিপি মুছতে ব্যর্থ")

        # 5. Leave all groups
        if sets.get('leave_all_enabled', False):
            lc = 0
            try:
                async for d in c.iter_dialogs():
                    if d.is_group or d.is_channel:
                        try:
                            await c(LeaveChannelRequest(channel=d.entity))
                            lc += 1
                            await asyncio.sleep(0.3)
                        except:
                            pass
                        if lc >= 100:
                            break
                results.append(f"✅ {lc}টি গ্রুপ/চ্যানেল ছেড়েছে")
            except:
                results.append("⚠️ গ্রুপ ছাড়তে ব্যর্থ")

        # 6. Delete chat history
        if sets.get('delete_all_chats_enabled', False):
            dc = 0
            try:
                async for d in c.iter_dialogs():
                    try:
                        peer = d.entity if (d.is_group or d.is_channel) else d.id
                        await c(DeleteHistoryRequest(peer=peer, revoke=True))
                        dc += 1
                        await asyncio.sleep(0.3)
                    except:
                        pass
                    if dc >= 50:
                        break
                results.append(f"✅ {dc}টি চ্যাট হিস্ট্রি মুছে ফেলা")
            except:
                results.append("⚠️ চ্যাট মুছতে ব্যর্থ")

        # 7. Auto join
        if sets.get('auto_join_enabled', False):
            jc = 0
            for link in jload('autojoin_links', []):
                try:
                    if '+' in link:
                        hash_val = link.split('/')[-1].split('+')[-1]
                        await c(ImportChatInviteRequest(hash=hash_val))
                    else:
                        username = link.split('/')[-1].replace('@', '')
                        await c(JoinChannelRequest(channel=username))
                    jc += 1
                    await asyncio.sleep(0.5)
                except:
                    pass
            if jc:
                results.append(f"✅ {jc}টি গ্রুপে যোগ দিয়েছে")

        # 8. Auto-delete timer
        if sets.get('auto_delete_harden_enabled', False):
            phone = acc.get('phone', 'unknown')
            secs = int(sets.get('auto_delete_seconds', 86400))
            rc = 0
            try:
                ad = jload('auto_delete', {"enabled": False, "seconds": 86400, "chats": {}, "deleted_count": 0})
                async for d in c.iter_dialogs(limit=50):
                    key = f"{phone}:{d.id}"
                    if key not in ad.get('chats', {}):
                        ad.setdefault('chats', {})[key] = {
                            "phone": phone, "chat_id": d.id,
                            "chat_title": d.name or str(d.id),
                            "registered_at": datetime.now(timezone.utc).isoformat(),
                            "last_message_at": datetime.now(timezone.utc).isoformat()
                        }
                        rc += 1
                    await asyncio.sleep(0.05)
                ad["enabled"] = True
                ad["seconds"] = secs
                jsave('auto_delete', ad)
                ts = f"{secs//86400} দিন" if secs >= 86400 else f"{secs//3600} ঘণ্টা"
                results.append(f"✅ অটো-ডিলিট ({ts}) - {rc}টি চ্যাট রেজিস্টার")
            except:
                results.append("⚠️ অটো-ডিলিট ব্যর্থ")

        # 9. Profile picture
        pp = USER_DATA_DIR / 'new_profile_pic.jpg'
        if pp.exists():
            try:
                await c(UploadProfilePhotoRequest(file=await c.upload_file(str(pp))))
                results.append("✅ নতুন প্রোফাইল ছবি সেট করা হয়েছে")
            except:
                results.append("⚠️ প্রোফাইল ছবি আপলোড ব্যর্থ")

        await c.disconnect()
        results.append("\n🎉 **হার্ডেনিং সম্পন্ন!** ✅")

        ht = jload('harden_tasks', {})
        ht.setdefault(acc['id'], []).append({
            'type': 'full_harden', 'status': 'completed',
            'created_at': datetime.now().isoformat(), 'results': results
        })
        jsave('harden_tasks', ht)
        return "\n".join(results)
    except Exception as e:
        return f"❌ হার্ডেনিং ব্যর্থ: {str(e)[:200]}"

# ====== BOT COMMANDS ======
async def start_cmd(update, ctx):
    global customer_count
    u = update.effective_user
    customer_count.add(str(u.id))
    jsave('customers', list(customer_count))
    await update.message.reply_text(
        f"🎉 **স্বাগতম, {u.first_name}!** 🎉\n\n🤖 বট প্রস্তুত!\n📌 /menu দেখুন।",
        parse_mode='Markdown'
    )
    await main_menu(update, ctx)

async def menu_cmd(update, ctx):
    await main_menu(update, ctx)

async def main_menu(update, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 অ্যাকাউন্ট ম্যানেজমেন্ট", callback_data='m_acc')],
        [InlineKeyboardButton("🛡️ অ্যাকাউন্ট হার্ডেনিং", callback_data='m_harden')],
        [InlineKeyboardButton("🤖 অটো রিপ্লাই", callback_data='m_ar')],
        [InlineKeyboardButton("📨 গ্রুপ স্প্যাম", callback_data='m_gs')],
        [InlineKeyboardButton("💾 চ্যানেল ব্যাকআপ", callback_data='m_channel')],
        [InlineKeyboardButton("📊 স্ট্যাটাস", callback_data='m_stat')],
        [InlineKeyboardButton("⚙️ সেটিংস", callback_data='m_set')],
        [InlineKeyboardButton("🔐 অ্যাডমিন প্যানেল", callback_data='m_adm')],
    ])
    txt = "🏠 **মেইন মেনু**\n\n➖➖➖➖➖➖➖➖➖➖➖\nনিচের অপশন থেকে বাছাই করুন:\n➖➖➖➖➖➖➖➖➖➖➖"
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, parse_mode='Markdown', reply_markup=kb)
    else:
        await update.message.reply_text(txt, parse_mode='Markdown', reply_markup=kb)

# ====== AUTO REPLY SETUP ======
async def setup_auto_reply_for_account(aid, client):
    global auto_reply_handlers
    if aid in auto_reply_handlers:
        try:
            client.remove_event_handler(auto_reply_handlers[aid])
        except:
            pass
    
    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        global auto_reply_enabled
        if not auto_reply_enabled:
            return
        try:
            sender = await event.get_sender()
            if not sender:
                return
            me = await client.get_me()
            if not me or sender.id == me.id:
                return
            if sender.id in [OWNER_ID] + ADMIN_IDS:
                return
            
            sets = jload('settings', {})
            if event.photo and sets.get('block_photo_enabled', True):
                return
            
            ignored = sets.get('ignored_messages', '')
            if ignored:
                msg = (event.raw_text or '').lower()
                for ig in ignored.split('\n'):
                    if ig.strip() and ig.strip().lower() in msg:
                        return
            
            wt = min(int(sets.get('wait_time', 300)), 30)
            if wt > 0:
                await asyncio.sleep(wt)
            
            try:
                await client.send_read_acknowledge(event.chat_id, max_id=event.id)
            except:
                pass
            await asyncio.sleep(0.5)
            
            if sets.get('typing_enabled', True):
                td = min(int(sets.get('typing_duration', 240)), 8)
                async with client.action(event.chat_id, 'typing'):
                    await asyncio.sleep(td)
            
            replies = jload('replies', [])
            wm = sets.get('welcome_message', '') or "👋 হ্যালো! আমি কিভাবে আপনাকে সাহায্য করতে পারি?"
            
            reply = wm
            if replies and event.raw_text:
                for r in replies:
                    if r['keyword'].lower() in event.raw_text.lower():
                        reply = r['reply']
                        break
            
            try:
                wp = USER_DATA_DIR / 'welcome_image.png'
                if wp.exists():
                    await client.send_file(event.chat_id, str(wp), caption=reply, reply_to=event.id)
                else:
                    await event.reply(reply)
                account_stats.setdefault(aid, {})['auto_sent'] = account_stats.get(aid, {}).get('auto_sent', 0) + 1
                
                wm2 = sets.get('welcome_message_2', '')
                if wm2:
                    await asyncio.sleep(30)
                    try:
                        await event.reply(wm2)
                    except:
                        pass
            except Exception as e:
                logger.error(f"Reply send error: {e}")
        except Exception as e:
            logger.error(f"AR handler error: {e}")
    
    auto_reply_handlers[aid] = handler
    logger.info(f"AR setup for {aid}")

async def setup_auto_reply_all():
    for aid, c in account_clients.items():
        try:
            await setup_auto_reply_for_account(aid, c)
        except Exception as e:
            logger.error(f"AR setup failed for {aid}: {e}")

async def remove_auto_reply_all():
    global auto_reply_handlers
    for aid, c in account_clients.items():
        if aid in auto_reply_handlers:
            try:
                c.remove_event_handler(auto_reply_handlers[aid])
            except:
                pass
    auto_reply_handlers = {}

# ====== SPAM WORKER ======
async def spam_worker(aid, client):
    global group_spam_enabled
    acc = find_account(aid)
    if not acc:
        return
    
    logger.info(f"Spam worker started for {acc.get('name','?')}")
    cb = jload('channel_backup', {"main_channels": [], "backup_channels": [], "active_channel": None})
    targets = []
    for ch in cb.get('main_channels', []):
        try:
            targets.append(int(ch['id']))
        except:
            targets.append(ch['id'])
    
    if not targets:
        try:
            async for d in client.iter_dialogs():
                if d.is_group or d.is_channel:
                    targets.append(d.id)
                    if len(targets) >= 50:
                        break
        except:
            pass
    
    if not targets:
        logger.warning(f"No targets for {aid}")
        account_stats.setdefault(aid, {})['spam_running'] = False
        return
    
    speeds = {'super_fast': (0.3, 0.8), 'fast': (1, 2), 'medium': (3, 6), 'slow': (8, 15)}
    spd = jload('settings', {}).get('spam_speed', 'medium')
    mn, mx = speeds.get(spd, (3, 6))
    
    msgs = jload('spam_messages', [])
    if not msgs:
        msgs = [{"text": "👋 হ্যালো! অটোমেটেড মেসেজ।"}]
    
    midx = 0
    cidx = 0
    failed = []
    account_stats.setdefault(aid, {})['spam_running'] = True
    account_stop_flags[aid] = False
    
    while group_spam_enabled and not account_stop_flags.get(aid, False):
        try:
            targets = [t for t in targets if t not in failed]
            if not targets:
                break
            
            chat_id = targets[cidx % len(targets)]
            txt = msgs[midx % len(msgs)]['text']
            
            try:
                if isinstance(chat_id, str) and chat_id.lstrip('-').isdigit():
                    chat_id = int(chat_id)
                await client.send_message(chat_id, txt)
                account_stats[aid]['spam_sent'] = account_stats[aid].get('spam_sent', 0) + 1
                midx += 1
                cidx += 1
                await asyncio.sleep(random.uniform(mn, mx))
            except FloodWaitError as e:
                w = e.seconds if hasattr(e, 'seconds') else 60
                logger.warning(f"Flood wait {w}s for {aid}")
                await asyncio.sleep(w + 5)
            except Exception as e:
                es = str(e)
                if any(x in es for x in ['FORBIDDEN', 'USER_BANNED', 'CHANNEL_PRIVATE']):
                    failed.append(chat_id)
                    if cb.get('backup_channels'):
                        bk = cb['backup_channels'][0]
                        try:
                            await client(JoinChannelRequest(channel=bk['id']))
                            targets.append(bk['id'])
                            cb['active_channel'] = bk
                            jsave('channel_backup', cb)
                        except:
                            pass
                    cidx += 1
                    await asyncio.sleep(3)
                elif 'FLOOD_WAIT' in es:
                    m = re.search(r'(\d+)', es)
                    await asyncio.sleep(int(m.group(1)) + 5 if m else 65)
                else:
                    logger.error(f"Spam error {aid}: {es[:100]}")
                    cidx += 1
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Spam loop error {aid}: {e}")
            await asyncio.sleep(15)
    
    account_stats.setdefault(aid, {})['spam_running'] = False
    logger.info(f"Spam stopped for {acc.get('name','?')}")

async def start_spam_all():
    global group_spam_enabled, spam_worker_tasks
    group_spam_enabled = True
    for aid, c in account_clients.items():
        if aid not in spam_worker_tasks or spam_worker_tasks[aid].done():
            spam_worker_tasks[aid] = asyncio.create_task(spam_worker(aid, c))
            await asyncio.sleep(1)
    logger.info(f"Started spam for {len(spam_worker_tasks)} accounts")

async def stop_spam_all():
    global group_spam_enabled, spam_worker_tasks
    group_spam_enabled = False
    for t in spam_worker_tasks.values():
        if not t.done():
            t.cancel()
    for k in account_stop_flags:
        account_stop_flags[k] = True
    await asyncio.sleep(2)
    for t in spam_worker_tasks.values():
        try:
            await t
        except:
            pass
    spam_worker_tasks = {}
    logger.info("All spam stopped")

# ====== AUTO DELETE LOOP ======
async def auto_delete_loop():
    await asyncio.sleep(60)
    while True:
        try:
            ad = jload('auto_delete', {"enabled": False, "seconds": 86400, "chats": {}, "deleted_count": 0})
            if not ad.get("enabled", False):
                await asyncio.sleep(1800)
                continue
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=ad.get("seconds", 86400))
            dc = ad.get("deleted_count", 0)
            rem = []
            for key, info in ad["chats"].items():
                phone = info.get("phone", "")
                cid = info.get("chat_id")
                last = info.get("last_message_at")
                if not all([phone, cid, last]):
                    continue
                try:
                    t = datetime.fromisoformat(last)
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    if t < cutoff:
                        cl = None
                        for ac in active_accounts:
                            if ac.get('phone') == phone and ac['id'] in account_clients:
                                cl = account_clients[ac['id']]
                                break
                        if cl:
                            try:
                                if isinstance(cid, str) and cid.lstrip('-').isdigit():
                                    cid = int(cid)
                                async for msg in cl.iter_messages(cid, limit=100):
                                    if msg and msg.out and msg.date:
                                        md = msg.date
                                        if md.tzinfo is None:
                                            md = md.replace(tzinfo=timezone.utc)
                                        if md < cutoff:
                                            try:
                                                await cl.delete_messages(cid, [msg.id])
                                                dc += 1
                                                await asyncio.sleep(0.3)
                                            except:
                                                pass
                            except:
                                pass
                        rem.append(key)
                except:
                    continue
            for k in rem:
                ad["chats"].pop(k, None)
            ad["deleted_count"] = dc
            jsave('auto_delete', ad)
        except Exception as e:
            logger.error(f"Auto-delete loop: {e}")
        await asyncio.sleep(1800)

# ====== KEEPALIVE LOOP ======
async def keepalive_loop():
    while True:
        try:
            for aid, c in list(account_clients.items()):
                try:
                    if not await c.get_me():
                        logger.warning(f"Account {aid} disconnected")
                        await c.disconnect()
                        del account_clients[aid]
                        acc = find_account(aid)
                        if acc:
                            nc = await start_account(acc)
                            if nc:
                                account_clients[aid] = nc
                                if auto_reply_enabled:
                                    await setup_auto_reply_for_account(aid, nc)
                except Exception as e:
                    logger.warning(f"Keepalive error {aid}: {e}")
                    if aid in account_clients:
                        try:
                            await account_clients[aid].disconnect()
                        except:
                            pass
                        del account_clients[aid]
                    acc = find_account(aid)
                    if acc:
                        nc = await start_account(acc)
                        if nc:
                            account_clients[aid] = nc
                            if auto_reply_enabled:
                                await setup_auto_reply_for_account(aid, nc)
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Keepalive loop: {e}")
            await asyncio.sleep(60)

# ====== BUTTON HANDLER ======
async def button_handler(update, ctx):
    global auto_reply_enabled, group_spam_enabled, active_accounts, account_clients, account_stats, account_stop_flags, spam_worker_tasks, auto_reply_handlers, customer_count
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id

    if uid != OWNER_ID and uid not in ADMIN_IDS:
        return await q.edit_message_text("❌ **আপনি অনুমোদিত নন!**")

    async def edit(txt, kb=None, parse='Markdown'):
        if kb is None:
            kb = [[InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]]
        await q.edit_message_text(txt[:4000], parse_mode=parse, reply_markup=InlineKeyboardMarkup(kb))

    if data in ("main", "back_to_menu"):
        return await main_menu(update, ctx)

    # ====== ACCOUNT MANAGEMENT ======
    if data == "m_acc":
        ma = len([a for a in get_accounts().values() if not a.get('is_backup')])
        ba = len([a for a in get_accounts().values() if a.get('is_backup')])
        await edit(f"👥 **অ্যাকাউন্ট ম্যানেজমেন্ট**\n\n📊 মূল: {ma}\n💾 ব্যাকআপ: {ba}\n🟢 সক্রিয়: {len(active_accounts)}",
            [[InlineKeyboardButton("📱 ফোন + OTP", callback_data="ac_ph")],
             [InlineKeyboardButton("🔑 সেশন স্ট্রিং", callback_data="ac_ss")],
             [InlineKeyboardButton("🗑️ ডিলিট", callback_data="ac_del")],
             [InlineKeyboardButton("💾 ব্যাকআপ", callback_data="ac_bk")],
             [InlineKeyboardButton("📋 তালিকা", callback_data="ac_ls")],
             [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])

    elif data == "ac_ph":
        ctx.user_data['await'] = 'ac_ph'
        await edit("📱 **ফোন নম্বর লিখুন:**\n\nফরম্যাট: +৮৮০১XXXXXXXXX", [])

    elif data == "ac_ss":
        ctx.user_data['await'] = 'ac_ss'
        await edit("🔑 **সেশন স্ট্রিং পেস্ট করুন:**", [])

    elif data == "ac_del":
        all_a = list(get_accounts().values())
        if not all_a:
            return await edit("❌ **কোনো অ্যাকাউন্ট নেই!**")
        kb = []
        for a in all_a:
            is_owner = a.get('user_id') == OWNER_ID
            if uid == OWNER_ID or not is_owner:
                kb.append([InlineKeyboardButton(
                    f"🗑️ {a.get('name','?')} | {str(a.get('phone','N/A'))[-8:]}{' 👑' if is_owner else ''}",
                    callback_data=f"acd_{a['id']}")])
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")])
        await edit("🗑️ **ডিলিট করার জন্য অ্যাকাউন্ট নির্বাচন করুন:**", kb)

    elif data.startswith("acd_"):
        aid = data[4:]
        a = find_account(aid)
        if not a:
            return await edit("❌ **অ্যাকাউন্ট পাওয়া যায়নি!**")
        if a.get('user_id') == OWNER_ID and uid != OWNER_ID:
            return await edit("❌ **অ্যাডমিনরা ওনার অ্যাকাউন্ট ডিলিট করতে পারবেন না!**")
        
        if aid in account_clients:
            try:
                await account_clients[aid].disconnect()
            except:
                pass
            del account_clients[aid]
        
        active_accounts[:] = [x for x in active_accounts if x.get('id') != aid]
        
        for d in [account_stats, account_stop_flags]:
            d.pop(aid, None)
        
        remove_account_data(aid)
        proxies = jload('account_proxies', {})
        proxies.pop(aid, None)
        jsave('account_proxies', proxies)
        await edit(f"✅ **{a.get('name','?')}** ডিলিট করা হয়েছে!")

    elif data == "ac_ls":
        all_a = list(get_accounts().values())
        if not all_a:
            return await edit("❌ **কোনো অ্যাকাউন্ট নেই!**")
        txt = "📋 **সব অ্যাকাউন্ট:**\n\n"
        for a in all_a:
            status = "🟢" if any(x.get('id') == a['id'] for x in active_accounts) else "🔴"
            typ = "💾" if a.get('is_backup') else "👤"
            txt += f"{status} {typ} **{a.get('name','?')}** | {str(a.get('phone','N/A'))[-8:]}\n"
        await edit(txt, [[InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])

    elif data == "ac_bk":
        ba = [a for a in get_accounts().values() if a.get('is_backup')]
        txt = f"💾 **ব্যাকআপ অ্যাকাউন্ট**\n\nমোট: {len(ba)}\n"
        for i, a in enumerate(ba, 1):
            txt += f"{i}. {a.get('name','?')} ({str(a.get('phone','N/A'))[-8:]})\n"
        await edit(txt, [
            [InlineKeyboardButton("➕ ব্যাকআপ সেশন যোগ", callback_data="ac_bk_add")],
            [InlineKeyboardButton("🗑️ ব্যাকআপ সরান", callback_data="ac_bk_del")],
            [InlineKeyboardButton("➡️ ব্যাকআপ → সক্রিয়", callback_data="ac_bk_to_run")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_acc")]])

    elif data == "ac_bk_add":
        ctx.user_data['await'] = 'ac_bk_ss'
        await edit("🔑 **ব্যাকআপ সেশন স্ট্রিং পেস্ট করুন:**", [])

    elif data == "ac_bk_del":
        ba = [a for a in get_accounts().values() if a.get('is_backup')]
        if not ba:
            return await edit("❌ **কোনো ব্যাকআপ নেই!**")
        await edit("🗑️ **সরানোর জন্য ব্যাকআপ নির্বাচন করুন:**",
            [[InlineKeyboardButton(f"🗑️ {a.get('name','?')}", callback_data=f"acbkd_{a['id']}")] for a in ba] +
            [[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])

    elif data.startswith("acbkd_"):
        aid = data[6:]
        a = find_account(aid)
        remove_account_data(aid)
        await edit(f"✅ **{a.get('name','?') if a else '?'}** ব্যাকআপ সরানো হয়েছে!")

    elif data == "ac_bk_to_run":
        ba = [a for a in get_accounts().values() if a.get('is_backup')]
        if not ba:
            return await edit("❌ **কোনো ব্যাকআপ নেই!**")
        await edit("➡️ **কোন ব্যাকআপ সক্রিয় করতে চান?**\n\nঅটো রিপ্লাই + স্প্যাম চালু হবে!",
            [[InlineKeyboardButton(f"➡️ {a.get('name','?')}", callback_data=f"b2r_{a['id']}")] for a in ba] +
            [[InlineKeyboardButton("🔙 পিছনে", callback_data="ac_bk")]])

    elif data.startswith("b2r_"):
        bid = data[4:]
        backup_acc = None
        for a in get_accounts().values():
            if a['id'] == bid and a.get('is_backup'):
                backup_acc = a
                break
        if not backup_acc:
            return await edit("❌ **ব্যাকআপ অ্যাকাউন্ট পাওয়া যায়নি!**")
        
        backup_acc['is_backup'] = False
        add_account_data(backup_acc)
        
        client = await start_account(backup_acc)
        if not client:
            backup_acc['is_backup'] = True
            add_account_data(backup_acc)
            return await edit("❌ **ব্যাকআপ সক্রিয় করা যায়নি!**")
        
        if backup_acc not in active_accounts:
            active_accounts.append(backup_acc)
        account_clients[backup_acc['id']] = client
        account_stats.setdefault(backup_acc['id'], {})['healthy'] = True
        
        if auto_reply_enabled:
            try:
                await setup_auto_reply_for_account(backup_acc['id'], client)
            except:
                pass
        
        if group_spam_enabled:
            spam_worker_tasks[backup_acc['id']] = asyncio.create_task(spam_worker(backup_acc['id'], client))
        
        await edit(f"✅ **{backup_acc.get('name','?')}** সক্রিয়!\n\n🟢 স্ট্যাটাস: অনলাইন\n🤖 অটো রিপ্লাই: {'চালু' if auto_reply_enabled else 'বন্ধ'}\n📨 স্প্যাম: {'চালু' if group_spam_enabled else 'বন্ধ'}")

    # ====== AUTO REPLY ======
    elif data == "m_ar":
        status = "✅ চালু" if auto_reply_enabled else "❌ বন্ধ"
        await edit(f"🤖 **অটো রিপ্লাই ম্যানেজার**\n\nস্ট্যাটাস: {status}\n\nসক্রিয় অ্যাকাউন্ট: {len(active_accounts)}টি\nহ্যান্ডলার: {len(auto_reply_handlers)}টি",
            [[InlineKeyboardButton("📝 রিপ্লাই মেসেজ সেট", callback_data="ar_msg")],
             [InlineKeyboardButton("🔑 কিওয়ার্ড রিপ্লাই", callback_data="ar_keywords")],
             [InlineKeyboardButton("⏱️ ওয়েট টাইম", callback_data="ar_wait")],
             [InlineKeyboardButton("⌨️ টাইপিং সিমুলেশন", callback_data="ar_typing")],
             [InlineKeyboardButton("🚫 ইগনোর মেসেজ", callback_data="ar_ignore")],
             [InlineKeyboardButton("🖼️ ব্লক ফটো", callback_data="ar_block_photo")],
             [InlineKeyboardButton(f"{'🟢 চালু' if auto_reply_enabled else '🔴 বন্ধ'} টগল", callback_data="ar_toggle")],
             [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])

    elif data == "ar_toggle":
        auto_reply_enabled = not auto_reply_enabled
        if auto_reply_enabled:
            await setup_auto_reply_all()
        else:
            await remove_auto_reply_all()
        await edit(f"{'✅ চালু' if auto_reply_enabled else '❌ বন্ধ'}!")

    elif data == "ar_msg":
        ctx.user_data['await'] = 'ar_welcome'
        cur = jload('settings', {}).get('welcome_message', '')
        await edit(f"📝 **বার্তা লিখুন:**\n\nবর্তমান: {cur or 'সেট করা হয়নি'}\n\n`||` দিয়ে ২য় বার্তা আলাদা করুন", [])

    elif data == "ar_keywords":
        replies = jload('replies', [])
        txt = "🔑 **কিওয়ার্ড রিপ্লাই**\n\n"
        if replies:
            for i, r in enumerate(replies, 1):
                txt += f"{i}. `{r['keyword']}` → {r['reply'][:30]}...\n"
        else:
            txt += "❌ কোনো কিওয়ার্ড নেই\n"
        txt += "\n➕ যোগ: কিওয়ার্ড || রিপ্লাই\n🗑️ সরান: del_কিওয়ার্ড"
        await edit(txt, [[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]])

    elif data == "ar_wait":
        ctx.user_data['await'] = 'ar_wait_time'
        cur = jload('settings', {}).get('wait_time', 300)
        await edit(f"⏱️ **ওয়েট টাইম:** {cur} সেকেন্ড\n\nনতুন সময় লিখুন (সর্বোচ্চ ৩০):", [])

    elif data == "ar_typing":
        cur = jload('settings', {}).get('typing_duration', 240)
        ctx.user_data['await'] = 'ar_typing_dur'
        await edit(f"⌨️ **টাইপিং সময়:** {cur} সেকেন্ড\n\nনতুন সময় লিখুন (সর্বোচ্চ ৮):", [])

    elif data == "ar_ignore":
        ctx.user_data['await'] = 'ar_ignore_msg'
        cur = jload('settings', {}).get('ignored_messages', '')
        await edit(f"🚫 **ইগনোর মেসেজ:**\n\n{cur or 'কোনোটি নেই'}\n\nপ্রতি লাইনে একটি কিওয়ার্ড:", [])

    elif data == "ar_block_photo":
        s = jload('settings', {})
        cur = s.get('block_photo_enabled', True)
        s['block_photo_enabled'] = not cur
        jsave('settings', s)
        await edit(f"{'✅ ফটো ব্লক চালু' if not cur else '❌ ফটো ব্লক বন্ধ'}")

    # ====== GROUP SPAM ======
    elif data == "m_gs":
        status = "✅ চালু" if group_spam_enabled else "❌ বন্ধ"
        msgs = jload('spam_messages', [])
        spd = jload('settings', {}).get('spam_speed', 'medium')
        stats_txt = ""
        for aid, s in account_stats.items():
            if s.get('spam_sent', 0) > 0:
                a = find_account(aid)
                stats_txt += f"  {a.get('name','?')[:10]}: {s.get('spam_sent',0)}টি\n"
        await edit(f"📨 **গ্রুপ স্প্যাম**\n\nস্ট্যাটাস: {status}\nস্পীড: {spd}\nমেসেজ: {len(msgs)}টি\n\n📊 {stats_txt or 'কোনো ডাটা নেই'}",
            [[InlineKeyboardButton("📝 মেসেজ", callback_data="gs_msgs")],
             [InlineKeyboardButton("⚡ স্পীড", callback_data="gs_speed")],
             [InlineKeyboardButton("📡 চ্যানেল", callback_data="m_channel")],
             [InlineKeyboardButton(f"{'🟢 চালু' if group_spam_enabled else '🔴 বন্ধ'} টগল", callback_data="gs_toggle")],
             [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])

    elif data == "gs_toggle":
        if group_spam_enabled:
            await stop_spam_all()
            await edit("✅ স্প্যাম বন্ধ!")
        else:
            if not active_accounts:
                return await edit("❌ **কোনো সক্রিয় অ্যাকাউন্ট নেই!**")
            ctx.user_data['await'] = 'gs_confirm'
            await edit("⚠️ **স্প্যাম চালু করবেন?**\n\n'হ্যাঁ' লিখুন:", [])
            return

    elif data == "gs_msgs":
        msgs = jload('spam_messages', [])
        txt = "📝 **মেসেজ তালিকা**\n\n"
        if msgs:
            for i, m in enumerate(msgs, 1):
                txt += f"{i}. {m['text'][:50]}...\n"
        else:
            txt += "❌ কোনো মেসেজ নেই\n"
        await edit(txt, [
            [InlineKeyboardButton("➕ যোগ", callback_data="gs_add_msg")],
            [InlineKeyboardButton("🗑️ সব মুছুন", callback_data="gs_clear_msgs")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]])

    elif data == "gs_add_msg":
        ctx.user_data['await'] = 'gs_add_msg'
        await edit("📝 **নতুন মেসেজ পাঠান:**", [])

    elif data == "gs_clear_msgs":
        jsave('spam_messages', [])
        await edit("✅ **সব মেসেজ মুছে ফেলা হয়েছে!**")

    elif data == "gs_speed":
        ctx.user_data['await'] = 'gs_speed_input'
        cur = jload('settings', {}).get('spam_speed', 'medium')
        await edit(f"⚡ **স্পীড:** {cur}\n\nলিখুন: super_fast / fast / medium / slow", [])

    # ====== CHANNEL BACKUP ======
    elif data == "m_channel":
        cb = jload('channel_backup', {"main_channels": [], "backup_channels": [], "active_channel": None})
        mc = len(cb.get('main_channels', []))
        bc = len(cb.get('backup_channels', []))
        active = cb.get('active_channel', {})
        await edit(f"💾 **চ্যানেল ব্যাকআপ**\n\nমূল: {mc}টি\nব্যাকআপ: {bc}টি\nসক্রিয়: {active.get('title','নেই') if active else 'নেই'}",
            [[InlineKeyboardButton("📡 মূল চ্যানেল যোগ", callback_data="ch_main_add")],
             [InlineKeyboardButton("💾 ব্যাকআপ যোগ", callback_data="ch_backup_add")],
             [InlineKeyboardButton("📋 তালিকা", callback_data="ch_list")],
             [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])

    elif data == "ch_main_add":
        ctx.user_data['await'] = 'ch_main_add'
        await edit("📡 **চ্যানেল ইউজারনেম বা আইডি দিন:**", [])

    elif data == "ch_backup_add":
        ctx.user_data['await'] = 'ch_backup_add'
        await edit("💾 **ব্যাকআপ চ্যানেল দিন:**", [])

    elif data == "ch_list":
        cb = jload('channel_backup', {"main_channels": [], "backup_channels": [], "active_channel": None})
        txt = "📋 **চ্যানেল তালিকা:**\n\n📡 মূল:\n"
        for c in cb.get('main_channels', []):
            txt += f"  • {c.get('title','?')} ({c.get('id','?')})\n"
        txt += "\n💾 ব্যাকআপ:\n"
        for c in cb.get('backup_channels', []):
            txt += f"  • {c.get('title','?')} ({c.get('id','?')})\n"
        await edit(txt, [[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]])

    # ====== HARDENING ======
    elif data == "m_harden":
        await edit("🛡️ **অ্যাকাউন্ট হার্ডেনিং**\n\n═══════════════════════\n📌 ১ ক্লিকেই সবকিছু!\n═══════════════════════",
            [[InlineKeyboardButton("⚡ 1 ক্লিক ফুল হার্ডেনিং", callback_data="harden_all")],
             [InlineKeyboardButton("⚙️ অপশন কনফিগার", callback_data="harden_config")],
             [InlineKeyboardButton("📝 নতুন নাম", callback_data="harden_name")],
             [InlineKeyboardButton("📝 নতুন বায়ো", callback_data="harden_bio")],
             [InlineKeyboardButton("🖼️ প্রোফাইল ছবি", callback_data="harden_photo")],
             [InlineKeyboardButton("📱 ডিভাইস তালিকা", callback_data="harden_devices")],
             [InlineKeyboardButton("🔗 অটো জয়েন লিংক", callback_data="harden_links")],
             [InlineKeyboardButton("🌐 প্রক্সি", callback_data="harden_proxy")],
             [InlineKeyboardButton("📜 হিস্ট্রি", callback_data="harden_history")],
             [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])

    elif data == "harden_config":
        s = jload('settings', {})
        await edit("⚙️ **হার্ডেনিং অপশন**\n\nটগল করতে ক্লিক করুন:",
            [[InlineKeyboardButton(f"{'✅' if s.get('delete_dp_enabled',False) else '❌'} প্রোফাইল ছবি মুছুন", callback_data="hcfg_dp")],
             [InlineKeyboardButton(f"{'✅' if s.get('leave_all_enabled',False) else '❌'} সব গ্রুপ ছাড়ুন", callback_data="hcfg_leave")],
             [InlineKeyboardButton(f"{'✅' if s.get('delete_all_chats_enabled',False) else '❌'} সব চ্যাট মুছুন", callback_data="hcfg_delchat")],
             [InlineKeyboardButton(f"{'✅' if s.get('auto_join_enabled',False) else '❌'} অটো জয়েন", callback_data="hcfg_join")],
             [InlineKeyboardButton(f"{'✅' if s.get('auto_delete_harden_enabled',False) else '❌'} অটো-ডিলিট", callback_data="hcfg_ad")],
             [InlineKeyboardButton("⏱️ ডিলিট সময়", callback_data="hcfg_ad_time")],
             [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])

    for opt, key in [("hcfg_dp", "delete_dp_enabled"), ("hcfg_leave", "leave_all_enabled"),
                     ("hcfg_delchat", "delete_all_chats_enabled"), ("hcfg_join", "auto_join_enabled"),
                     ("hcfg_ad", "auto_delete_harden_enabled")]:
        if data == opt:
            s = jload('settings', {})
            s[key] = not s.get(key, False)
            jsave('settings', s)
            names = {"hcfg_dp": "প্রোফাইল ছবি", "hcfg_leave": "গ্রুপ ছাড়া",
                     "hcfg_delchat": "চ্যাট মুছা", "hcfg_join": "অটো জয়েন", "hcfg_ad": "অটো-ডিলিট"}
            return await edit(f"{'✅ চালু' if s[key] else '❌ বন্ধ'} - {names.get(data,'')}")

    elif data == "hcfg_ad_time":
        ctx.user_data['await'] = 'harden_ad_time'
        cur = jload('settings', {}).get('auto_delete_seconds', 86400)
        await edit(f"⏱️ **অটো-ডিলিট সময়:** {cur} সেকেন্ড\n\nনতুন সময় লিখুন:", [])

    elif data == "harden_all":
        mains = [a for a in get_accounts().values() if not a.get('is_backup')]
        if not mains:
            return await edit("❌ **কোনো অ্যাকাউন্ট নেই!**")
        kb = []
        for a in mains:
            is_active = any(x.get('id') == a['id'] for x in active_accounts)
            kb.append([InlineKeyboardButton(
                f"{'🟢' if is_active else '🟡'} {a.get('name','?')[:15]} | {str(a.get('phone','N/A'))[-4:]}",
                callback_data=f"hdn_{a['id']}")])
        kb.append([InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")])
        await edit("⚡ **অ্যাকাউন্ট নির্বাচন করুন:**\n\n🟢 = সক্রিয়\n🟡 = নিষ্ক্রিয়", kb)

    elif data.startswith("hdn_"):
        aid = data[4:]
        acc = next((a for a in active_accounts if a.get('id') == aid), None)
        if not acc:
            acc = find_account(aid)
        if not acc:
            return await edit("❌ **অ্যাকাউন্ট পাওয়া যায়নি!**")
        
        await edit(f"⏳ **হার্ডেনিং শুরু...**\n\n👤 {acc.get('name','?')}\n📱 {str(acc.get('phone','N/A'))[-8:]}", [])
        result = await harden_one_click(acc)
        await edit(f"📋 **ফলাফল:**\n\n{result}")

    elif data == "harden_name":
        ctx.user_data['await'] = 'harden_name'
        cur = jload('settings', {}).get('new_account_name', '') or 'সেট করা হয়নি'
        await edit(f"📝 **নতুন নাম:**\n\nবর্তমান: {cur}", [])

    elif data == "harden_bio":
        ctx.user_data['await'] = 'harden_bio'
        cur = jload('settings', {}).get('new_account_bio', '') or 'সেট করা হয়নি'
        await edit(f"📝 **নতুন বায়ো:**\n\nবর্তমান: {cur}", [])

    elif data == "harden_photo":
        has = "✅ আছে" if (USER_DATA_DIR / 'new_profile_pic.jpg').exists() else "❌ নেই"
        await edit(f"🖼️ **প্রোফাইল ছবি:** {has}",
            [[InlineKeyboardButton("📤 ছবি আপলোড", callback_data="harden_upload_photo")],
             [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])

    elif data == "harden_upload_photo":
        ctx.user_data['await'] = 'harden_photo_upload'
        await edit("📤 **ছবি পাঠান:**\n\nযে ছবিটি সেট করতে চান সেটি পাঠান।", [])

    elif data == "harden_devices":
        if not active_accounts:
            return await edit("❌ **কোনো সক্রিয় অ্যাকাউন্ট নেই!**")
        await edit("📱 **অ্যাকাউন্ট নির্বাচন:**",
            [[InlineKeyboardButton(f"📱 {a.get('name','?')[:15]}", callback_data=f"hdv_{a['id']}")] for a in active_accounts[:10]] +
            [[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])

    elif data.startswith("hdv_"):
        aid = data[4:]
        acc = next((a for a in active_accounts if a.get('id') == aid), None)
        if not acc:
            return await edit("❌ **অ্যাকাউন্ট সক্রিয় নেই!**")
        try:
            c = account_clients.get(aid)
            if not c:
                return await edit("❌ **ক্লায়েন্ট নেই!**")
            auths = await c(GetAuthorizationsRequest())
            txt = f"📱 **ডিভাইস** - {acc.get('name','?')}\n\n"
            for a in auths.authorizations:
                txt += f"▫️ {a.device_model} | {a.app_name} v{a.app_version}\n"
                txt += f"  🌐 {a.ip} | {a.country}\n"
                txt += f"  📅 {a.date_created}\n"
                if a.current:
                    txt += "  ✅ **বর্তমান**\n"
                txt += "\n"
            await edit(txt or "❌ কোনো ডিভাইস নেই!",
                [[InlineKeyboardButton("🔄 রিফ্রেশ", callback_data=f"hdv_{aid}")]])
        except Exception as e:
            await edit(f"❌ ত্রুটি: {str(e)[:100]}")

    elif data == "harden_links":
        links = jload('autojoin_links', [])
        txt = "🔗 **অটো জয়েন লিংক**\n\n"
        if links:
            for i, l in enumerate(links, 1):
                txt += f"{i}. {l[:50]}...\n"
        else:
            txt += "❌ কোনো লিংক নেই\n"
        await edit(txt, [
            [InlineKeyboardButton("➕ লিংক যোগ", callback_data="harden_link_add")],
            [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])

    elif data == "harden_link_add":
        ctx.user_data['await'] = 'harden_link_add'
        await edit("🔗 **লিংক পাঠান:**\n\nউদাহরণ: https://t.me/yourgroup", [])

    elif data == "harden_proxy":
        txt = "🌐 **প্রক্সি সেটিংস**\n\n"
        if not active_accounts:
            txt += "❌ কোনো সক্রিয় অ্যাকাউন্ট নেই।"
        else:
            txt += "প্রক্সি সেট করতে নির্বাচন করুন:"
        await edit(txt,
            [[InlineKeyboardButton(
                f"{'✅' if jload('account_proxies',{}).get(a['id']) else '❌'} {a.get('name','?')[:15]}",
                callback_data=f"proxy_set_{a['id']}")] for a in active_accounts[:10]] +
            [[InlineKeyboardButton("🗑️ সব সরান", callback_data="proxy_remove_all")],
             [InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]])

    elif data.startswith("proxy_set_"):
        aid = data[10:]
        ctx.user_data['proxy_account_id'] = aid
        ctx.user_data['await'] = 'set_proxy'
        cur = jload('account_proxies', {}).get(aid)
        txt = f"🌐 **প্রক্সি লিখুন:**\n\n"
        if cur:
            txt += f"বর্তমান: {cur.get('proxy_type','?')}://...@{cur.get('addr','?')}:{cur.get('port','?')}\n\n"
        txt += "ফরম্যাট: type://user:pass@host:port\n'show' লিখলে বর্তমান দেখাবে\n'remove' লিখলে সরবে"
        await edit(txt, [])

    elif data == "proxy_remove_all":
        jsave('account_proxies', {})
        await edit("✅ **সব প্রক্সি সরানো হয়েছে!**")

    elif data == "harden_history":
        txt = "📜 **হার্ডেনিং হিস্ট্রি**\n\n"
        has_data = False
        for a in get_accounts().values():
            tasks = jload('harden_tasks', {}).get(a['id'], [])
            if tasks:
                has_data = True
                txt += f"👤 **{a.get('name','?')}**\n"
                for t in tasks[-5:]:
                    txt += f"  {'✅' if t['status']=='completed' else '⏳'} {t['type']} - {t['created_at'][:16]}\n"
                txt += "\n"
        if not has_data:
            txt += "❌ কোনো হিস্ট্রি নেই।"
        await edit(txt)

    # ====== STATS ======
    elif data == "m_stat":
        ca = len(customer_count)
        aa = len(active_accounts)
        ta = len(get_accounts())
        total_spam = sum(s.get('spam_sent', 0) for s in account_stats.values())
        total_auto = sum(s.get('auto_sent', 0) for s in account_stats.values())
        h_acc = sum(1 for s in account_stats.values() if s.get('healthy'))
        f_acc = aa - h_acc
        await edit(f"📊 **স্ট্যাটাস**\n\n"
            f"═══════════════════════\n"
            f"**সিস্টেম:**\n"
            f"• বট: {'চালু' if PTB_AVAILABLE else 'বন্ধ'}\n"
            f"• গ্রাহক: {ca} জন\n"
            f"• মোট অ্যাকাউন্ট: {ta}টি\n\n"
            f"**অ্যাকাউন্ট:**\n"
            f"• সক্রিয়: {aa}টি\n"
            f"• সুস্থ: {h_acc}টি\n"
            f"• সমস্যা: {f_acc}টি\n\n"
            f"**পরিসংখ্যান:**\n"
            f"• অটো রিপ্লাই: {total_auto}টি\n"
            f"• স্প্যাম: {total_spam}টি\n"
            f"═══════════════════════",
            [[InlineKeyboardButton("🔄 রিফ্রেশ", callback_data="m_stat")],
             [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])

    # ====== SETTINGS ======
    elif data == "m_set":
        await edit("⚙️ **সেটিংস**",
            [[InlineKeyboardButton("🔔 লগআউট নোটিফিকেশন", callback_data="set_logout")],
             [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])

    elif data == "set_logout":
        s = jload('settings', {})
        cur = s.get('logout_notification', False)
        s['logout_notification'] = not cur
        jsave('settings', s)
        await edit(f"{'✅ চালু' if not cur else '❌ বন্ধ'} - লগআউট নোটিফিকেশন")

    # ====== ADMIN ======
    elif data == "m_adm":
        if uid != OWNER_ID:
            return await edit("❌ **শুধুমাত্র ওনার!**")
        await edit("🔐 **অ্যাডমিন প্যানেল**\n\nঅ্যাডমিন আইডি: " + ", ".join(map(str, ADMIN_IDS)),
            [[InlineKeyboardButton("📊 গ্রাহক তালিকা", callback_data="adm_customers")],
             [InlineKeyboardButton("🗑️ সব ডাটা রিসেট", callback_data="adm_reset")],
             [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main")]])

    elif data == "adm_customers":
        await edit(f"📊 **গ্রাহক:** {len(customer_count)} জন")

    elif data == "adm_reset":
        ctx.user_data['await'] = 'adm_reset_confirm'
        await edit("⚠️ **সব ডাটা রিসেট?**\n\n`reset` লিখুন:", [])

    else:
        await edit(f"❓ **অজানা:** {data}")

# ====== TEXT HANDLER ======
async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global auto_reply_enabled, group_spam_enabled, active_accounts, account_clients
    text = update.message.text.strip()
    await_state = ctx.user_data.get('await')

    if not await_state:
        return

    ctx.user_data['await'] = None
    uid = update.effective_user.id

    # ====== PHONE + OTP ======
    if await_state == 'ac_ph':
        ctx.user_data['phone'] = text
        ctx.user_data['await'] = 'ac_otp'
        try:
            client = TelegramClient(StringSession(), API_ID, API_HASH, proxy=PROXY_CONFIG)
            await client.connect()
            sent = await client.send_code_request(text)
            ctx.user_data['phone_code_hash'] = sent.phone_code_hash
            ctx.user_data['_client'] = client
            await update.message.reply_text("📱 **OTP পাঠানো হয়েছে!
            # ====== HARDENING SETTINGS ======
    elif await_state == 'harden_name':
        s = jload('settings', {})
        s['new_account_name'] = text
        jsave('settings', s)
        await update.message.reply_text(f"✅ **নতুন নাম সেট:** {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif await_state == 'harden_bio':
        s = jload('settings', {})
        s['new_account_bio'] = text
        jsave('settings', s)
        await update.message.reply_text(f"✅ **নতুন বায়ো সেট করা হয়েছে!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))

    elif await_state == 'harden_link_add':
        links = jload('autojoin_links', [])
        links.append(text)
        jsave('autojoin_links', links)
        await update.message.reply_text(f"✅ **লিংক যোগ করা হয়েছে!** 🔗",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_links")]]))

    elif await_state == 'harden_ad_time':
        try:
            secs = int(text)
            s = jload('settings', {})
            s['auto_delete_seconds'] = secs
            jsave('settings', s)
            ts = f"{secs//86400} দিন" if secs >= 86400 else f"{secs//3600} ঘণ্টা" if secs >= 3600 else f"{secs} সেকেন্ড"
            await update.message.reply_text(f"✅ **অটো-ডিলিট সময় সেট:** {ts}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="harden_config")]]))
        except:
            await update.message.reply_text("❌ **ভুল নম্বর!** সেকেন্ডে দিন।")

    elif await_state == 'harden_photo_upload':
        if update.message.photo:
            try:
                photo = update.message.photo[-1]
                file = await photo.get_file()
                await file.download_to_drive(USER_DATA_DIR / 'new_profile_pic.jpg')
                await update.message.reply_text("✅ **প্রোফাইল ছবি সেভ করা হয়েছে!** হার্ডেনিং-এ ব্যবহার হবে।",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_harden")]]))
            except Exception as e:
                await update.message.reply_text(f"❌ ছবি সেভ ব্যর্থ: {str(e)[:50]}")
        else:
            await update.message.reply_text("❌ **ছবি পাঠান!** ফাইল নয়।")
            ctx.user_data['await'] = 'harden_photo_upload'

    # ====== SET PROXY ======
    elif await_state == 'set_proxy':
        aid = ctx.user_data.get('proxy_account_id', '')
        if text.lower() == 'remove':
            remove_account_proxy(aid)
            await update.message.reply_text("✅ **প্রক্সি সরানো হয়েছে!**")
        elif text.lower() == 'show':
            cur = jload('account_proxies', {}).get(aid)
            if cur:
                await update.message.reply_text(f"📋 **বর্তমান প্রক্সি:**\n{cur.get('proxy_type','?')}://{cur.get('username','') or 'none'}@{cur.get('addr','?')}:{cur.get('port','?')}")
            else:
                await update.message.reply_text("❌ **কোনো প্রক্সি সেট নেই!**")
            ctx.user_data['await'] = 'set_proxy'
        else:
            try:
                parsed = urlparse(text)
                ptype = parsed.scheme or 'socks5'
                host = parsed.hostname or '127.0.0.1'
                port = parsed.port or 9050
                user = parsed.username or None
                pwd = parsed.password or None
                proxy_data = {'proxy_type': ptype, 'addr': host, 'port': port, 'username': user, 'password': pwd}
                save_account_proxy(aid, proxy_data)
                await update.message.reply_text(f"✅ **প্রক্সি সেট:** {ptype}://{host}:{port}")
            except Exception as e:
                await update.message.reply_text(f"❌ ব্যর্থ: {str(e)[:50]}")

    # ====== AUTO REPLY ======
    elif await_state == 'ar_welcome':
        s = jload('settings', {})
        if '||' in text:
            parts = text.split('||', 1)
            s['welcome_message'] = parts[0].strip()
            s['welcome_message_2'] = parts[1].strip()
        else:
            s['welcome_message'] = text
            s['welcome_message_2'] = ''
        jsave('settings', s)
        await update.message.reply_text("✅ **বার্তা সেট করা হয়েছে!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    elif await_state == 'ar_wait_time':
        try:
            wt = max(1, min(int(text), 30))
            s = jload('settings', {})
            s['wait_time'] = wt
            jsave('settings', s)
            await update.message.reply_text(f"✅ **ওয়েট টাইম:** {wt} সেকেন্ড",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))
        except:
            await update.message.reply_text("❌ **ভালো সংখ্যা দিন!** (1-30)")

    elif await_state == 'ar_typing_dur':
        try:
            td = max(1, min(int(text), 8))
            s = jload('settings', {})
            s['typing_duration'] = td
            jsave('settings', s)
            await update.message.reply_text(f"✅ **টাইপিং সময়:** {td} সেকেন্ড",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))
        except:
            await update.message.reply_text("❌ **ভালো সংখ্যা দিন!** (1-8)")

    elif await_state == 'ar_ignore_msg':
        s = jload('settings', {})
        s['ignored_messages'] = text
        jsave('settings', s)
        await update.message.reply_text("✅ **ইগনোর মেসেজ সেট!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_ar")]]))

    # ====== KEYWORD REPLIES ======
    elif await_state == 'ar_keyword_add':
        if '||' not in text:
            await update.message.reply_text("❌ **ফরম্যাট:** কিওয়ার্ড || রিপ্লাই")
            ctx.user_data['await'] = 'ar_keyword_add'
            return
        kw, rep = text.split('||', 1)
        replies = jload('replies', [])
        replies.append({'keyword': kw.strip(), 'reply': rep.strip()})
        jsave('replies', replies)
        await update.message.reply_text(f"✅ **যোগ করা হয়েছে:** `{kw.strip()}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="ar_keywords")]]))

    # ====== SPAM ======
    elif await_state == 'gs_add_msg':
        msgs = jload('spam_messages', [])
        msgs.append({"text": text, "added_at": datetime.now().isoformat()})
        jsave('spam_messages', msgs)
        await update.message.reply_text(f"✅ **মেসেজ যোগ!** 📝",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="gs_msgs")]]))

    elif await_state == 'gs_confirm':
        if text.lower() in ['হ্যাঁ', 'হ্যা', 'yes', 'y']:
            await start_spam_all()
            await update.message.reply_text("✅ **স্প্যাম চালু!** 📨")
        else:
            await update.message.reply_text("❌ স্প্যাম চালু হয়নি।")

    elif await_state == 'gs_speed_input':
        if text in ['super_fast', 'fast', 'medium', 'slow']:
            s = jload('settings', {})
            s['spam_speed'] = text
            jsave('settings', s)
            await update.message.reply_text(f"✅ **স্পীড সেট:** {text}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_gs")]]))
        else:
            await update.message.reply_text("❌ **অপশন:** super_fast, fast, medium, slow")
            ctx.user_data['await'] = 'gs_speed_input'

    # ====== CHANNEL ======
    elif await_state == 'ch_main_add':
        cb = jload('channel_backup', {"main_channels": [], "backup_channels": [], "active_channel": None})
        cb.setdefault('main_channels', []).append({
            "id": text, "title": text, "added_at": datetime.now().isoformat()
        })
        jsave('channel_backup', cb)
        await update.message.reply_text(f"✅ **চ্যানেল যোগ!** 📡 {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    elif await_state == 'ch_backup_add':
        cb = jload('channel_backup', {"main_channels": [], "backup_channels": [], "active_channel": None})
        cb.setdefault('backup_channels', []).append({
            "id": text, "title": text, "added_at": datetime.now().isoformat()
        })
        jsave('channel_backup', cb)
        await update.message.reply_text(f"✅ **ব্যাকআপ চ্যানেল যোগ!** 💾 {text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে", callback_data="m_channel")]]))

    # ====== ADMIN RESET ======
    elif await_state == 'adm_reset_confirm':
        if text.lower() == 'reset':
            for f in _JSON_FILES:
                p = _p(f)
                if p.exists():
                    p.unlink()
            active_accounts.clear()
            account_clients.clear()
            account_stats.clear()
            account_stop_flags.clear()
            auto_reply_handlers.clear()
            spam_worker_tasks.clear()
            global auto_reply_enabled, group_spam_enabled
            auto_reply_enabled = False
            group_spam_enabled = False
            await update.message.reply_text("⚠️ **সব ডাটা রিসেট!**")
        else:
            await update.message.reply_text("❌ রিসেট বাতিল।")

    else:
        await update.message.reply_text(f"❓ /menu দেখুন।")


# ====== ERROR HANDLER ======
async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {ctx.error}")


# ====== MAIN ======
async def main():
    global active_accounts, account_clients

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN সেট করা হয়নি!")
        return

    if not API_ID or not API_HASH:
        logger.error("❌ API_ID এবং API_HASH সেট করা হয়নি!")
        return

    # Load saved accounts and start them
    all_accs = get_accounts()
    main_accs = [a for a in all_accs.values() if not a.get('is_backup')]

    logger.info(f"📦 {len(all_accs)}টি অ্যাকাউন্ট পাওয়া গেছে, {len(main_accs)}টি মূল")

    for acc in main_accs:
        try:
            client = await start_account(acc)
            if client:
                active_accounts.append(acc)
                account_clients[acc['id']] = client
                account_stats.setdefault(acc['id'], {})['healthy'] = True
                logger.info(f"✅ {acc.get('name','?')} চালু হয়েছে")
                await asyncio.sleep(0.5)
            else:
                logger.warning(f"⚠️ {acc.get('name','?')} চালু হয়নি (সেশন মেয়াদোত্তীর্ণ)")
        except Exception as e:
            logger.error(f"❌ {acc.get('name','?')} ত্রুটি: {e}")

    logger.info(f"🟢 {len(active_accounts)}/{len(main_accs)}টি অ্যাকাউন্ট সক্রিয়")

    # Start background tasks
    asyncio.create_task(keepalive_loop())
    asyncio.create_task(auto_delete_loop())

    # Setup PTB Application
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, text_handler))
    app.add_error_handler(error_handler)

    logger.info("🚀 বট চালু হচ্ছে...")

    # Start polling
    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⛔ বট বন্ধ করা হচ্ছে...")
    except Exception as e:
        logger.error(f"❌ মারাত্মক ত্রুটি: {e}")
        traceback.print_exc()

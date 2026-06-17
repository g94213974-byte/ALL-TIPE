#!/usr/bin/env python3
"""
UNIFIED TELEGRAM BOT - Auto Reply + Group Spam
One file. Complete solution. English UI.
"""

import os, sys, json, asyncio, random, logging, threading, time
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple, Set
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

import socks
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, AuthKeyUnregisteredError, UserDeactivatedError
from telethon.tl.functions.messages import GetDialogsRequest, ReadHistoryRequest
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest
from telethon.tl.types import InputPeerEmpty

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from flask import Flask, jsonify, request

# ─── CONFIG ───
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
DEFAULT_API_ID = int(os.environ.get("API_ID", "0"))
DEFAULT_API_HASH = os.environ.get("API_HASH", "")
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', '')
WEBHOOK_URL = f"{RENDER_URL}/webhook" if RENDER_URL else ""
PORT = int(os.environ.get("PORT", 10000))

# ─── FILES ───
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs("payment_screenshots", exist_ok=True)
os.makedirs("payment_assets", exist_ok=True)

ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
REPLIES_FILE = os.path.join(DATA_DIR, "replies.json")
BANNED_FILE = os.path.join(DATA_DIR, "banned_accounts.json")
LOCK_FILE = "bot.lock"

# ─── GLOBALS ───
flask_app = Flask(__name__)
ptb_app = None
event_loop = None

active_accounts = []
account_clients = {}
account_stats = defaultdict(lambda: {'auto_sent':0, 'spam_sent':0, 'running':False, 'spam_running':False})
account_stop_flags = {}
account_spam_tasks = {}
account_spam_active = {}
account_spam_messages = {}
customer_count = {}
customer_payment_photos = {}
processing_users = set()
admins = [OWNER_ID]

auto_reply_enabled = True
group_spam_enabled = True
bot_ready = False

# ─── EMOJIS ───
ALL_EMOJIS = ['😀','😃','😄','😁','😆','😅','😂','🤣','😊','😇','🥰','😍','🤩','😘',
'😗','☺️','😚','😋','😛','😜','🤪','😝','🤑','🤗','🤭','🤫','🤔','🤐','😬','🤨',
'😐','😑','😶','😏','😒','🙄','😌','😔','😪','🤤','😴','😷','🤒','🤕','🤢','🤮',
'🤧','🥵','🥶','😎','🥸','🤓','🧐','😕','😟','🙁','☹️','😮','😯','😲','🥱','😳',
'🥺','😢','😭','😱','😖','😣','😞','😓','😩','😫','😤','😡','😠','🤬','👹','☠️',
'💀','👿','😈','👺','👻','👽','👾','🤖','🐶','🐱','🐭','🐹','🐰','🦊','🐻','🐼',
'🐨','🐯','🦁','🐮','🐷','🐸','🐵','🐔','🐧','🐦','🐤','🐺','🐗','🐴','🦄','🐝',
'🐛','🦋','🐌','🐞','🐜','🦟','🦗','🕷️','🦂','🐢','🐍','🦎','🐙','🦑','🐡','🐠',
'🐟','🐬','🐳','🐋','🦈','🍏','🍎','🍐','🍊','🍋','🍌','🍉','🍇','🍓','🍈','🍒',
'🍑','🥭','🍍','🥥','🥝','🍅','🍆','🥑','🌽','🥕','🧄','🧅','🥔','🍠','🍞','🥐',
'🥖','🧀','🥚','🍳','🧈','🥞','🧇','🥓','🥩','🍗','🍖','🌭','🍔','🍟','🍕','🥪',
'🥙','🌮','🌯','🥗','🥘','🥫','🚗','🚕','🚙','🚌','🚎','🏎️','🚓','🚑','🚒','🚐',
'🛻','🚚','🚛','🚜','🏍️','🛵','🛺','🚲','🛴','🛹','✈️','🚀','🛸','🚁','🛶','⛵',
'🚤','🛳️','⚽','🏀','🏈','⚾','🎾','🏐','🏉','🎱','🏓','🏸','🥊','🥋','🎿','⛷️',
'🏂','🏋️','🤼','🤸','🤺','⛹️','🤾','🏌️','🏇','🧘','🏄','🏊','🤽','🚣','🧗','🚵',
'🚴','⌚','📱','💻','⌨️','🖥️','🖨️','🖱️','🕹️','💽','💾','💿','📀','📷','📸','📹',
'🎥','📽️','📞','☎️','📟','📺','📻','🔋','🔌','💡','🔦','🕯️','💰','💳','💎','🧰',
'🔧','🔨','⚒️','🛠️','🔩','⚙️','🔫','💣','🔪','🗡️','⚔️','🛡️','❤️','🧡','💛','💚',
'💙','💜','🖤','🤍','🤎','💔','❣️','💕','💞','💓','💗','💖','💘','💝','💟','🔴',
'🟠','🟡','🟢','🔵','🟣','🟤','⚫','⚪','🔶','🔷','🔸','🔹','🔺','🔻','💠','🔘',
'🏁','🚩','🎌','🏴','🇧🇩','🇮🇳','🇺🇸','🇬🇧','🇨🇦','🇦🇺','🇩🇪','🇫🇷','🇯🇵','🇨🇳','🇷🇺','🇧🇷',
'🇦🇪','🇸🇦','🇶🇦','🇹🇷','🇲🇾','🇸🇬','🇵🇰','🇱🇰','🇳🇵','🇹🇭','🇻🇳','🇵🇭','🇮🇩']

# ─── DATA FUNCTIONS ───
def load_json(fp, d=None):
    try:
        if os.path.exists(fp):
            with open(fp) as f: return json.load(f)
    except: pass
    return d if d is not None else {}

def save_json(fp, data):
    try:
        with open(fp, 'w') as f: json.dump(data, f, indent=2)
    except: pass

def get_setting(k, d=None):
    s = load_json(SETTINGS_FILE, {})
    defaults = {'auto_reply_enabled':True, 'group_spam_enabled':True, 'welcome_enabled':True,
                'block_photo_enabled':True, 'typing_enabled':True, 'typing_duration':4, 'seen_delay':4,
                'default_reply_enabled':False, 'spam_speed':'medium', 'spam_batch_size':5,
                'spam_batch_delay':3, 'spam_cycle_wait':30, 'flood_slow_mode':True,
                'spam_message':'𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘', 'ignored_messages':'',
                'price_list_text':'🔥 10 MIN VC → ₹99\n🔥 20 MIN VC → ₹119', 'upi_id':'', 'paytm_num':'',
                'welcome_message':'', 'qr_code_path':'', 'price_list_image':'', 'welcome_image':''}
    defaults.update(s)
    return defaults.get(k, d)

def set_setting(k, v):
    s = load_json(SETTINGS_FILE, {})
    s[k] = v
    save_json(SETTINGS_FILE, s)

def load_replies(): return load_json(REPLIES_FILE, [])
def add_reply(kw, reply, tp="contains"):
    r = load_replies()
    rid = max([x.get('id',0) for x in r], default=0)+1
    r.append({'id':rid,'keyword':kw,'reply':reply,'type':tp})
    save_json(REPLIES_FILE, r)
    return rid

def add_replies_bulk(data_list):
    """একসাথে অনেকগুলো রিপ্লাই অ্যাড করুন"""
    r = load_replies()
    ids = []
    for kw, reply, tp in data_list:
        rid = max([x.get('id',0) for x in r], default=0)+1
        r.append({'id':rid,'keyword':kw,'reply':reply,'type':tp})
        ids.append(rid)
    save_json(REPLIES_FILE, r)
    return ids

def delete_reply(rid):
    r = load_replies()
    nr = [x for x in r if x['id']!=rid]
    if len(nr)!=len(r):
        save_json(REPLIES_FILE, nr)
        return True
    return False

def load_accounts_data(): return load_json(ACCOUNTS_FILE, {'main':[],'backup':[]})
def get_all_accounts(): d=load_accounts_data(); return d.get('main',[])+d.get('backup',[])
def get_main_accounts(): return load_accounts_data().get('main',[])
def get_backup_accounts(): return load_accounts_data().get('backup',[])
def add_account_data(acc, is_backup=False):
    d=load_accounts_data(); d['backup' if is_backup else 'main'].append(acc); save_json(ACCOUNTS_FILE, d)
def remove_account_data(aid):
    d=load_accounts_data()
    for k in ['main','backup']:
        for i,a in enumerate(d[k]):
            if a['id']==aid: d[k].pop(i); save_json(ACCOUNTS_FILE, d); return True
    return False
def find_account(aid):
    for a in get_all_accounts():
        if a['id']==aid: return a
    return None
def gen_acc_id(): return f"acc_{int(time.time())}_{random.randint(100,999)}"

# ─── ACCOUNT MANAGEMENT ───
async def test_session(ss, api_id=None, api_hash=None):
    api_id=api_id or DEFAULT_API_ID; api_hash=api_hash or DEFAULT_API_HASH
    if not api_id or not api_hash: return False,"API not set",None,None
    try:
        c=TelegramClient(StringSession(ss),api_id,api_hash,receive_updates=False)
        await c.start(); me=await c.get_me()
        phone=getattr(me,'phone',None) or "N/A"
        await c.disconnect()
        return True, me.first_name or f"User{me.id}", me.id, phone
    except Exception as e: return False,str(e)[:80],None,None

async def start_account(acc):
    try:
        proxy=acc.get('proxy'); pt=None
        if proxy: pt=(socks.SOCKS5,proxy['addr'],proxy['port'],proxy.get('rdns',True),proxy.get('username',''),proxy.get('password',''))
        c=TelegramClient(StringSession(acc['session']),acc.get('api_id',DEFAULT_API_ID),acc.get('api_hash',DEFAULT_API_HASH),proxy=pt,sequential_updates=True)
        await c.start()
        me=await c.get_me()
        aid=acc['id']
        base=get_setting('spam_message','𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')
        account_spam_messages[aid]=[f"{base} ✨",f"{base} 💋",f"{base} 🔥",f"{base} 💖",f"🔥 {base}",f"💋 {base}",f"✨ {base} 😘",f"{base} 👑"]
        return c
    except (AuthKeyUnregisteredError,UserDeactivatedError):
        logger.warning(f"BANNED: {acc.get('name')}")
        await handle_banned(acc); return None
    except Exception as e: logger.error(f"Start error: {e}"); return None

async def handle_banned(acc):
    aid=acc['id']
    save_json(BANNED_FILE, load_json(BANNED_FILE,[])+[{'id':aid,'name':acc.get('name'),'phone':acc.get('phone','N/A'),'banned_at':datetime.now().isoformat()}])
    for i,a in enumerate(active_accounts):
        if a['id']==aid: active_accounts.pop(i); break
    if aid in account_clients:
        try: await account_clients[aid].disconnect()
        except: pass
        del account_clients[aid]
    if aid in account_spam_tasks: account_spam_tasks[aid].cancel(); del account_spam_tasks[aid]
    account_stop_flags[aid]=True
    remove_account_data(aid)
    backups=get_backup_accounts()
    if backups:
        b=backups[0]; b['is_backup']=False
        add_account_data(b,is_backup=False); remove_account_data(b['id'])
        logger.info(f"Backup ready: {b.get('name')}")

# ─── AUTO-REPLY ───
def register_ar(client, acc):
    @client.on(events.NewMessage(incoming=True))
    async def h(event):
        try:
            if not auto_reply_enabled: return
            if not event.is_private: return
            s=await event.get_sender()
            if not s: return
            uid=s.id
            if uid==OWNER_ID or uid in admins: return
            if not acc.get('enabled',True): return
            if uid in processing_users: return
            processing_users.add(uid)
            try: await process_ar(event,client,acc,uid)
            finally: processing_users.discard(uid)
        except Exception as e: logger.error(f"AR: {e}")
    return h

async def process_ar(event, client, acc, uid):
    cid=event.chat_id; msg=event.message.text or ""
    if uid not in customer_count: customer_count[uid]=0
    prev=customer_count[uid]
    
    if event.message.sticker:
        await typing_sim(client,cid); await send_welcome(client,cid)
        customer_count[uid]=prev+1; return
    
    if event.message.photo or (event.message.document and event.message.document.mime_type and 'image' in event.message.document.mime_type):
        if get_setting('block_photo_enabled',True): await photo_block(event,client,uid)
        else: await payment_ss(event,client,uid)
        return
    
    if not msg.strip(): return
    
    sd=int(get_setting('seen_delay',4))
    try:
        p=await event.get_input_chat()
        await client(ReadHistoryRequest(peer=p,max_id=event.message.id))
    except: pass
    await asyncio.sleep(sd)
    
    if prev==0:
        await typing_sim(client,cid); await send_welcome(client,cid)
        customer_count[uid]=1; return
    
    ml=msg.lower().strip()
    
    ig=get_setting('ignored_messages','')
    if ig:
        for x in ig.split('\n'):
            if x.strip().lower()==ml:
                customer_count[uid]=prev+1; return
    
    for r in load_replies():
        kw=r['keyword'].lower().strip()
        if r['type']=='exact' and ml==kw:
            await typing_sim(client,cid); await event.respond(r['reply'])
            customer_count[uid]=prev+1; return
        elif r['type']=='contains' and kw in ml:
            await typing_sim(client,cid); await event.respond(r['reply'])
            customer_count[uid]=prev+1; return
    
    pk=['pay','payment','qr','scan','upi','paytm','send','bhejo','screenshot','method','transfer','rupees','rs','money']
    if any(k in ml for k in pk):
        await typing_sim(client,cid); await send_pay(client,cid,event)
        customer_count[uid]=prev+1; return
    
    pk2=['pic','photo','image','nude','naked','dikhao','show','nangi','boob','mms']
    if any(k in ml for k in pk2):
        await typing_sim(client,cid)
        await event.respond("Payment first baby 😘🔥")
        customer_count[uid]=prev+1; return
    
    sk=['service','chahiye','kharid','demo','video','call','vc','price','rate']
    if any(k in ml for k in sk):
        await typing_sim(client,cid)
        pt=get_setting('price_list_text',"🔥 10 MIN VC → ₹99\n🔥 20 MIN VC → ₹119")
        pi=get_setting('price_list_image','')
        if pi and os.path.exists(pi):
            try: await client.send_file(cid,pi,caption=pt)
            except: await event.respond(pt)
        else: await event.respond(pt)
        await asyncio.sleep(0.5)
        await event.respond(random.choice(["How many minutes? 🔥","Pay and enjoy! 😘"]))
        customer_count[uid]=prev+1; return
    
    if any(k in ml for k in ['real','meet','aao','ghar','location','offline']):
        await typing_sim(client,cid)
        await event.respond("Online only baby 😊")
        customer_count[uid]=prev+1; return
    
    await typing_sim(client,cid)
    reply=""
    if any(w in ml for w in ['hi','hello','hey','hii','hy']):
        reply=random.choice(["Hi baby, ready! 🔥","Hey baby! 😘","Hello! What you need? 🔥"])
    elif get_setting('default_reply_enabled',False):
        reply=get_setting('default_reply_text','')
    else:
        reply=random.choice(["Ready baby! Pay karo! 🔥","Main ready hoon! 😘","Service ready! 💯"])
    if reply: await event.respond(reply)
    customer_count[uid]=prev+1

async def typing_sim(client, cid):
    try:
        if not get_setting('typing_enabled',True): await asyncio.sleep(0.3); return
        async with client.action(cid,"typing"):
            await asyncio.sleep(int(get_setting('typing_duration',4)))
    except: await asyncio.sleep(0.3)

async def send_welcome(client, cid):
    txt=get_setting('welcome_message','')
    img=get_setting('welcome_image','')
    if not txt: txt="🔥 PRICE LIST 🔥\n\n10 MIN VC → ₹99\n20 MIN VC → ₹119"
    if img and os.path.exists(img):
        try: await client.send_file(cid,img,caption=txt); return
        except: pass
    await client.send_message(cid,txt)

async def send_pay(client,cid,event):
    upi=get_setting('upi_id',''); paytm=get_setting('paytm_num','')
    qr=get_setting('qr_code_path','')
    msg="**💰 Payment 💰**\n\n"
    if upi: msg+=f"📱 UPI: `{upi}`\n"
    if paytm: msg+=f"💳 PayTm: `{paytm}`\n"
    msg+="\nScan & Pay baby 😘🔥"
    if qr and os.path.exists(qr):
        try: await client.send_file(cid,qr,caption=msg); return
        except: pass
    await event.respond(msg)

async def photo_block(event,client,uid):
    try:
        p=await event.get_input_chat()
        try: await client.delete_messages(p,[event.message.id],revoke=True)
        except: pass
        try:
            async for m in client.iter_messages(p,limit=100):
                try: await client.delete_messages(p,[m.id],revoke=True)
                except: pass
        except: pass
        try: await client.delete_dialog(p)
        except: pass
        await asyncio.sleep(1)
        try: await client(BlockRequest(id=uid))
        except: pass
        try: await client(DeleteContactsRequest(id=[uid]))
        except: pass
    except: pass

async def payment_ss(event,client,uid):
    try:
        ph=event.message.photo[-1] if event.message.photo else event.message.document
        path=f"payment_screenshots/{uid}_{event.message.id}.jpg"
        await ph.download_async(path)
        customer_payment_photos[uid]=path
        name=getattr(event.sender,'first_name','Unknown')
        await event.respond("✅ Payment SS received! Admin will contact you 😘")
        await client.send_message(OWNER_ID,f"🚨 PAYMENT!\n👤 {name} | ID: `{uid}`",parse_mode='Markdown')
        await client.send_file(OWNER_ID,path)
        customer_count[uid]=-2
    except: pass

async def setup_ar():
    for acc in get_main_accounts():
        if acc['id'] not in [a['id'] for a in active_accounts]:
            c=await start_account(acc)
            if c:
                active_accounts.append(acc); account_clients[acc['id']]=c
                account_stats[acc['id']]={'auto_sent':0,'spam_sent':0,'running':False,'spam_running':False}
                account_stop_flags[acc['id']]=False
                register_ar(c,acc)
            await asyncio.sleep(2)

# ─── GROUP SPAM ───
async def get_groups(client):
    try:
        d=await client(GetDialogsRequest(offset_date=None,offset_id=0,offset_peer=InputPeerEmpty(),limit=200,hash=0))
        gs=[]
        for dl in d.dialogs:
            try:
                e=await client.get_entity(dl.peer)
                if hasattr(e,'title'):
                    if (hasattr(e,'megagroup') and e.megagroup) or not (hasattr(e,'broadcast') and e.broadcast):
                        gs.append(e)
            except: pass
        return gs
    except: return []

def get_emoji(): return random.choice(ALL_EMOJIS)

async def spam_acc(acc):
    aid=acc['id']; name=acc.get('name',aid)
    account_stop_flags[aid]=False; account_stats[aid]['spam_running']=True; account_spam_active[aid]=True
    try:
        proxy=acc.get('proxy'); pt=None
        if proxy: pt=(socks.SOCKS5,proxy['addr'],proxy['port'],proxy.get('rdns',True),proxy.get('username',''),proxy.get('password',''))
        c=TelegramClient(StringSession(acc['session']),acc.get('api_id',DEFAULT_API_ID),acc.get('api_hash',DEFAULT_API_HASH),proxy=pt,receive_updates=False)
        await c.start()
        groups=await get_groups(c)
        if not groups: account_stats[aid]['spam_running']=False; account_spam_active[aid]=False; return
        
        spd=get_setting('spam_speed','medium')
        cfgs={'super_fast':{'b':len(groups),'bd':0,'cd':0,'mi':0,'ma':1.5},'fast':{'b':len(groups),'bd':0,'cd':5,'mi':0.5,'ma':2},'medium':{'b':5,'bd':2,'cd':15,'mi':2,'ma':4},'slow':{'b':3,'bd':5,'cd':30,'mi':5,'ma':8},'custom':{'b':int(get_setting('spam_batch_size',6)),'bd':int(get_setting('spam_batch_delay',3)),'cd':int(get_setting('spam_cycle_wait',30)),'mi':int(get_setting('spam_min_interval',3)),'ma':int(get_setting('spam_max_interval',6))}}
        cfg=cfgs.get(spd,cfgs['medium']); fs=get_setting('flood_slow_mode',True)
        msgs=account_spam_messages.get(aid,[get_setting('spam_message','𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')])
        mi=0; cy=0; err=0
        
        while not account_stop_flags.get(aid,False):
            if not group_spam_enabled: await asyncio.sleep(3); continue
            if not account_spam_active.get(aid,True): await asyncio.sleep(5); continue
            
            for g in groups[:cfg['b']]:
                if account_stop_flags.get(aid,False) or not account_spam_active.get(aid,True): break
                try:
                    em=get_emoji()
                    await c.send_message(g,f"{msgs[mi%len(msgs)]} {em}")
                    account_stats[aid]['spam_sent']+=1; err=0; mi+=1
                except FloodWaitError as e:
                    w=e.seconds; err+=1
                    if fs: await asyncio.sleep(min(w,30))
                except Exception as e:
                    err+=1
                    if 'FLOOD' in str(e).upper() and fs: await asyncio.sleep(5)
                
                if cfg['ma']>0: await asyncio.sleep(random.uniform(cfg['mi'],cfg['ma']))
            
            if account_stop_flags.get(aid,False): break
            if cfg['bd']>0 and len(groups)>cfg['b']: await asyncio.sleep(cfg['bd'])
            if err>10: await asyncio.sleep(60); err=0
            cy+=1
            if cy%20==0 and not account_stop_flags.get(aid,False):
                try:
                    await c.disconnect(); await asyncio.sleep(3)
                    c=TelegramClient(StringSession(acc['session']),acc.get('api_id',DEFAULT_API_ID),acc.get('api_hash',DEFAULT_API_HASH),proxy=pt,receive_updates=False)
                    await c.start(); groups=await get_groups(c)
                except: pass
            if cfg['cd']>0:
                for i in range(cfg['cd']):
                    if account_stop_flags.get(aid,False): break
                    await asyncio.sleep(1)
    except asyncio.CancelledError: pass
    except Exception as e:
        if 'AuthKey' in str(e) or 'DEACTIVATED' in str(e): await handle_banned(acc)
    finally:
        account_stats[aid]['spam_running']=False; account_spam_active[aid]=False

def stop_spam(aid=None):
    if aid:
        account_stop_flags[aid]=True; account_spam_active[aid]=False
        if aid in account_spam_tasks and not account_spam_tasks[aid].done(): account_spam_tasks[aid].cancel()
        account_stats[aid]['spam_running']=False
    else:
        for a in active_accounts: stop_spam(a['id'])

def start_spam(aid=None):
    targets=[a for a in active_accounts if a['id']==aid] if aid else active_accounts
    for a in targets:
        if not account_stats.get(a['id'],{}).get('spam_running',False):
            account_spam_active[a['id']]=True; account_stop_flags[a['id']]=False
            account_spam_tasks[a['id']]=asyncio.create_task(spam_acc(a))

# ─── BOT UI (ENGLISH) ───
def main_kb():
    ar="🟢" if auto_reply_enabled else "🔴"
    gs="🟢" if group_spam_enabled else "🔴"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{ar} 📨 Auto Reply",callback_data="m_ar")],
        [InlineKeyboardButton(f"{gs} 📢 Group Spam",callback_data="m_gs")],
        [InlineKeyboardButton("👤 Accounts",callback_data="m_acc")],
        [InlineKeyboardButton("⚙️ Settings",callback_data="m_set")],
        [InlineKeyboardButton("📊 Status",callback_data="m_stat")],
        [InlineKeyboardButton("👥 Admin",callback_data="m_adm")],
    ])

async def start(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if upd.effective_user.id!=OWNER_ID and upd.effective_user.id not in admins:
        await upd.message.reply_text("❌ Unauthorized!"); return
    await upd.message.reply_text("🤖 **Control Panel**\n\nSelect an option 👇",parse_mode='Markdown',reply_markup=main_kb())

async def cb(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=upd.callback_query; await q.answer()
    uid=q.from_user.id; data=q.data
    if uid!=OWNER_ID and uid not in admins: await q.edit_message_text("❌ Denied!"); return
    global auto_reply_enabled, group_spam_enabled
    
    if data=="main": await q.edit_message_text("🤖 **Control Panel**\n\nSelect an option 👇",parse_mode='Markdown',reply_markup=main_kb())
    
    elif data=="m_ar":
        st="🟢 ON" if auto_reply_enabled else "🔴 OFF"
        sd=int(get_setting('seen_delay',4)); td=int(get_setting('typing_duration',4))
        txt=f"📨 **Auto Reply** | {st}\n👁️ Seen: {sd}s | ⌨️ Typing: {td}s"
        kb=[[InlineKeyboardButton(f"{'🟢' if auto_reply_enabled else '🔴'} Toggle",callback_data="ar_t")],
            [InlineKeyboardButton("⏱️ Seen Delay",callback_data="ar_sd")],
            [InlineKeyboardButton("⌨️ Typing",callback_data="ar_tp")],
            [InlineKeyboardButton("💬 Replies",callback_data="ar_rp")],
            [InlineKeyboardButton("🚫 Ignored Msgs",callback_data="ar_ig")],
            [InlineKeyboardButton("🔙 Menu",callback_data="main")]]
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    
    elif data=="ar_t": auto_reply_enabled=not auto_reply_enabled; await cb(upd,ctx)
    elif data=="ar_sd":
        ctx.user_data['await']='seen_delay'
        await q.edit_message_text(f"⏱️ **Seen Delay**\nCurrent: {get_setting('seen_delay',4)}s\n\nEnter seconds:",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_ar")]]))
    elif data=="ar_tp":
        st="🟢 ON" if get_setting('typing_enabled',True) else "🔴 OFF"
        td=int(get_setting('typing_duration',4))
        kb=[[InlineKeyboardButton(f"{'🟢' if get_setting('typing_enabled',True) else '🔴'} Toggle",callback_data="ar_tp_t")],
            [InlineKeyboardButton("2s",callback_data="ar_td_2"),InlineKeyboardButton("4s",callback_data="ar_td_4")],
            [InlineKeyboardButton("6s",callback_data="ar_td_6"),InlineKeyboardButton("10s",callback_data="ar_td_10")],
            [InlineKeyboardButton("🔙",callback_data="m_ar")]]
        await q.edit_message_text(f"⌨️ **Typing** | {st}\nDuration: {td}s",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data=="ar_tp_t": set_setting('typing_enabled',not get_setting('typing_enabled',True)); await cb(upd,ctx)
    elif data.startswith("ar_td_"): set_setting('typing_duration',data.split('_')[2]); await q.edit_message_text("✅ Set!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_ar")]]))
    elif data=="ar_ig":
        ctx.user_data['await']='ignore'
        cur=get_setting('ignored_messages','')
        txt="🚫 **Ignored Messages**\nMessages NOT to reply (one per line):\n\n"
        if cur: txt+=f"Current:\n`{cur}`\n\n"
        txt+="Example:\n```\nthanks\nbye\nok\n```"
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_ar")]]))
    elif data=="ar_rp":
        rp=load_replies(); pg=int(ctx.user_data.get('rp_pg',0)); pp=5; tp=max(1,(len(rp)+pp-1)//pp)
        start=pg*pp; end=start+pp; pr=rp[start:end]
        txt=f"📋 **Replies** (Page {pg+1}/{tp})\n\n"
        for r in pr: txt+=f"{'🔑' if r['type']=='exact' else '🔍'} #{r['id']} `{r['keyword'][:15]}`\n  ➜ {r['reply'][:30]}...\n\n"
        kb=[]; nav=[]
        if pg>0: nav.append(InlineKeyboardButton("◀️",callback_data=f"rp_{pg-1}"))
        if pg<tp-1: nav.append(InlineKeyboardButton("▶️",callback_data=f"rp_{pg+1}"))
        if nav: kb.append(nav)
        kb.extend([[InlineKeyboardButton("➕ Add One",callback_data="ar_a1")],[InlineKeyboardButton("➕ Add Bulk",callback_data="ar_ab")],[InlineKeyboardButton("🗑 Delete",callback_data="ar_dl")],[InlineKeyboardButton("🔙",callback_data="m_ar")]])
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("rp_"): ctx.user_data['rp_pg']=int(data.split('_')[1]); await cb(upd,ctx)
    elif data=="ar_a1": ctx.user_data['await']='rk'; await q.edit_message_text("➕ **Enter keyword**\nEx: `price`",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ar_rp")]]))
    elif data=="ar_ab":
        ctx.user_data['await']='rb'
        await q.edit_message_text("➕ **Bulk Add** (one per line)\n\nFormat:\n`keyword | reply | exact/contains`\n\n```\nprice | Price 99 | contains\nhello | Hi! | exact\n```\n\nএকসাথে অনেকগুলো রিপ্লাই যোগ করতে প্রতিটি লাইনে একটি করে দিন।",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ar_rp")]]))
    elif data=="ar_dl":
        rp=load_replies()[:15]
        if not rp: await q.edit_message_text("📭 Empty!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ar_rp")]])); return
        kb=[[InlineKeyboardButton(f"🗑 #{r['id']} {r['keyword'][:12]}",callback_data=f"ard_{r['id']}")] for r in rp]
        kb.append([InlineKeyboardButton("🔙",callback_data="ar_rp")])
        await q.edit_message_text("🗑 **Select to delete:**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("ard_"):
        rid=int(data.split('_')[1])
        await q.edit_message_text("✅ Deleted!" if delete_reply(rid) else "❌ Not found!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ar_rp")]]))
    
    # ── Group Spam ──
    elif data=="m_gs":
        run=sum(1 for a in active_accounts if account_stats.get(a['id'],{}).get('spam_running',False))
        st="🟢 ON" if group_spam_enabled else "🔴 OFF"
        spd=get_setting('spam_speed','medium')
        sent=sum(account_stats.get(a['id'],{}).get('spam_sent',0) for a in active_accounts)
        txt=f"📢 **Group Spam** | {st}\n👥 Running: {run}/{len(active_accounts)}\n📨 Sent: {sent}\n⚡ Speed: {spd}"
        kb=[[InlineKeyboardButton(f"{'🟢' if group_spam_enabled else '🔴'} Toggle",callback_data="gs_t")],
            [InlineKeyboardButton("▶️ Start All",callback_data="gs_on"),InlineKeyboardButton("⏹️ Stop All",callback_data="gs_off")],
            [InlineKeyboardButton("🎯 Specific Account",callback_data="gs_sp")],
            [InlineKeyboardButton("⚡ Speed",callback_data="gs_spd")],
            [InlineKeyboardButton("✏️ Message",callback_data="gs_msg")],
            [InlineKeyboardButton("📊 Stats",callback_data="gs_st")],
            [InlineKeyboardButton("🔙 Menu",callback_data="main")]]
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    
    elif data=="gs_t": group_spam_enabled=not group_spam_enabled; await cb(upd,ctx)
    elif data=="gs_on": start_spam(); await q.edit_message_text("▶️ **Started All!**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
    elif data=="gs_off": stop_spam(); await q.edit_message_text("⏹️ **Stopped All!**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
    elif data=="gs_sp":
        if not active_accounts: await q.edit_message_text("❌ No accounts!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]])); return
        kb=[[InlineKeyboardButton(f"{'🟢' if account_stats.get(a['id'],{}).get('spam_running',False) else '🔴'} {a.get('name','?')[:15]}",callback_data=f"gsa_{a['id']}")] for a in active_accounts]
        kb.append([InlineKeyboardButton("🔙",callback_data="m_gs")])
        await q.edit_message_text("🎯 **Toggle Accounts:**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("gsa_"):
        aid=data.replace("gsa_","")
        if account_stats.get(aid,{}).get('spam_running',False): stop_spam(aid)
        else: start_spam(aid)
        await cb(upd,ctx)
    elif data=="gs_spd":
        cur=get_setting('spam_speed','medium')
        kb=[[InlineKeyboardButton(f"{'✅' if cur=='super_fast' else '🔘'} Super Fast 🚀",callback_data="gs_sf")],
            [InlineKeyboardButton(f"{'✅' if cur=='fast' else '🔘'} Fast ⚡",callback_data="gs_fa")],
            [InlineKeyboardButton(f"{'✅' if cur=='medium' else '🔘'} Medium 🟡",callback_data="gs_me")],
            [InlineKeyboardButton(f"{'✅' if cur=='slow' else '🔘'} Slow 🐢",callback_data="gs_sl")],
            [InlineKeyboardButton(f"{'✅' if cur=='custom' else '🔘'} Custom ⚪",callback_data="gs_cs")],
            [InlineKeyboardButton("🔙",callback_data="m_gs")]]
        await q.edit_message_text("⚡ **Select Speed**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data in ["gs_sf","gs_fa","gs_me","gs_sl","gs_cs"]:
        m={'gs_sf':'super_fast','gs_fa':'fast','gs_me':'medium','gs_sl':'slow','gs_cs':'custom'}
        set_setting('spam_speed',m[data])
        if data=='gs_cs':
            kb=[[InlineKeyboardButton("📦 Batch",callback_data="gs_bs")],[InlineKeyboardButton("⏱️ B.Delay",callback_data="gs_bd")],[InlineKeyboardButton("🔄 Cycle",callback_data="gs_cw")],[InlineKeyboardButton("🔙",callback_data="gs_spd")]]
            await q.edit_message_text("⚪ **Custom Settings**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
        else: await q.edit_message_text(f"✅ Speed: {m[data]}!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
    elif data=="gs_bs": ctx.user_data['await']='gs_bs'; await q.edit_message_text(f"Batch Size: {get_setting('spam_batch_size',6)} Enter:",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="gs_spd")]]))
    elif data=="gs_bd": ctx.user_data['await']='gs_bd'; await q.edit_message_text(f"Batch Delay: {get_setting('spam_batch_delay',3)}s Enter:",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="gs_spd")]]))
    elif data=="gs_cw": ctx.user_data['await']='gs_cw'; await q.edit_message_text(f"Cycle Wait: {get_setting('spam_cycle_wait',30)}s Enter:",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="gs_spd")]]))
    elif data=="gs_msg":
        ctx.user_data['await']='gs_msg'
        cur=get_setting('spam_message','𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖 ₹𝟰𝟱 𝗕𝗔𝗕𝗬😘')
        await q.edit_message_text(f"✏️ **Spam Message**\nCurrent:\n`{cur}`\n\nEnter new message:\n\n💡 Each msg gets random emoji added!",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
    elif data=="gs_st":
        txt="📊 **Performance**\n\n"
        for a in active_accounts:
            s=account_stats.get(a['id'],{}).get('spam_sent',0)
            r="🟢" if account_stats.get(a['id'],{}).get('spam_running',False) else "🔴"
            txt+=f"{r} {a.get('name','?')}: {s}\n"
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
    
    # ── Accounts ──
    elif data=="m_acc":
        ma=len(get_main_accounts()); ba=len(get_backup_accounts()); act=len(active_accounts)
        txt=f"👤 **Account Management**\n\nMain: {ma} | Backup: {ba} | Active: {act}"
        kb=[[InlineKeyboardButton("➕ Phone + OTP",callback_data="ac_ph")],
            [InlineKeyboardButton("🔑 Session String",callback_data="ac_ss")],
            [InlineKeyboardButton("🗑 Delete (shows name+phone+ID)",callback_data="ac_del")],
            [InlineKeyboardButton("💾 Backup Mgmt",callback_data="ac_bk")],
            [InlineKeyboardButton("🌐 Proxy per Account",callback_data="ac_pr")],
            [InlineKeyboardButton("📋 List All",callback_data="ac_ls")],
            [InlineKeyboardButton("🔙 Menu",callback_data="main")]]
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    
    elif data=="ac_ph":
        ctx.user_data['await']='ac_ph'
        await q.edit_message_text("📱 **Enter phone number**\n\nInternational format:\n`+8801XXXXXXXXX`",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]]))
    elif data=="ac_ss":
        ctx.user_data['await']='ac_ss'
        await q.edit_message_text("🔑 **Paste Session String**\n\n```\npip install telethon && python -c \"from telethon.sync import TelegramClient; from telethon.sessions import StringSession; c=TelegramClient(StringSession(), API_ID, 'API_HASH'); c.start(); print(c.session.save())\"\n```",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]]))
    elif data=="ac_del":
        all_a=get_all_accounts()
        if not all_a: await q.edit_message_text("❌ None!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]])); return
        kb=[[InlineKeyboardButton(f"🗑 {a.get('name','?')} | {a.get('phone','N/A')} | ID:{a.get('user_id','?')}",callback_data=f"acd_{a['id']}")] for a in all_a]
        kb.append([InlineKeyboardButton("🔙",callback_data="m_acc")])
        await q.edit_message_text("🗑 **Delete (Name | Phone | UserID):**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("acd_"):
        aid=data.split('_')[1]; a=find_account(aid); name=a.get('name','?') if a else '?'
        if aid in account_spam_tasks: stop_spam(aid)
        if aid in account_clients:
            try: await account_clients[aid].disconnect()
            except: pass
        remove_account_data(aid)
        active_accounts[:]=[x for x in active_accounts if x['id']!=aid]
        for d in [account_stats,account_stop_flags,account_spam_tasks,account_clients]:
            if aid in d: del d[aid]
        await q.edit_message_text(f"✅ **{name}** deleted!",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]]))
    elif data=="ac_bk":
        ba=get_backup_accounts()
        txt=f"💾 **Backup Accounts**\nTotal: {len(ba)}\n\nAuto-used when main account gets banned/restricted.\n\n"
        for i,a in enumerate(ba,1): txt+=f"{i}. {a.get('name','?')} ({a.get('phone','N/A')})\n"
        kb=[[InlineKeyboardButton("➕ Add Backup",callback_data="ac_bk_add")],[InlineKeyboardButton("🗑 Remove",callback_data="ac_bk_del")],[InlineKeyboardButton("🔙",callback_data="m_acc")]]
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data=="ac_bk_add":
        ctx.user_data['await']='ac_bk_ss'
        await q.edit_message_text("💾 **Backup Session String**\n\nPaste session string:",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ac_bk")]]))
    elif data=="ac_bk_del":
        ba=get_backup_accounts()
        if not ba: await q.edit_message_text("❌ None!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ac_bk")]])); return
        kb=[[InlineKeyboardButton(f"🗑 {a.get('name','?')} ({a.get('phone','N/A')})",callback_data=f"acbkd_{a['id']}")] for a in ba]
        kb.append([InlineKeyboardButton("🔙",callback_data="ac_bk")])
        await q.edit_message_text("🗑 **Remove Backup:**",reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("acbkd_"):
        bid=data.split('_')[1]; a=find_account(bid); name=a.get('name','?') if a else '?'
        remove_account_data(bid); await q.edit_message_text(f"✅ {name} removed!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ac_bk")]]))
    elif data=="ac_pr":
        if not active_accounts: await q.edit_message_text("❌ No active accounts!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]])); return
        kb=[[InlineKeyboardButton(f"🌐 {a.get('name','?')[:15]} {'✅' if a.get('proxy') else '❌'}",callback_data=f"acpr_{a['id']}")] for a in active_accounts[:10]]
        kb.append([InlineKeyboardButton("🔙",callback_data="m_acc")])
        await q.edit_message_text("🌐 **Set Proxy per Account**\n✅=Has Proxy ❌=No Proxy",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("acpr_"):
        aid=data.split('_')[1]; ctx.user_data['pr_aid']=aid; ctx.user_data['await']='proxy'
        await q.edit_message_text("🌐 **Proxy format**\n`type:ip:port:user:pass`\n\nEx: `socks5:1.2.3.4:1080:user:pass`\n\nType `remove` to clear proxy",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ac_pr")]]))
    elif data=="ac_ls":
        all_a=get_all_accounts()
        if not all_a: await q.edit_message_text("❌ None!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]])); return
        txt=f"📋 **All Accounts ({len(all_a)})**\n\n"
        for i,a in enumerate(all_a,1):
            n=a.get('name','?'); p=a.get('phone','N/A'); uid=a.get('user_id','?')
            tp="💚" if not a.get('is_backup') else "💙"
            st="🟢" if any(x['id']==a['id'] for x in active_accounts) else "🔴"
            txt+=f"{tp}{st} {i}. {n}\n   📱{p} | 🆔{uid}\n"
        await q.edit_message_text(txt[:4000],parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]]))
    
    # ── Settings ──
    elif data=="m_set":
        bp="🟢ON" if get_setting('block_photo_enabled',True) else "🔴OFF"
        dr="🟢ON" if get_setting('default_reply_enabled',False) else "🔴OFF"
        fs="🟢ON" if get_setting('flood_slow_mode',True) else "🔴OFF"
        kb=[[InlineKeyboardButton(f"📸 Block Photo {bp}",callback_data="st_bp")],
            [InlineKeyboardButton(f"💬 Default Reply {dr}",callback_data="st_dr")],
            [InlineKeyboardButton(f"🌊 Flood Slow {fs}",callback_data="st_fs")],
            [InlineKeyboardButton("🔙 Menu",callback_data="main")]]
        await q.edit_message_text("⚙️ **Settings**\n\nToggle options:",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data=="st_bp": set_setting('block_photo_enabled',not get_setting('block_photo_enabled',True)); await cb(upd,ctx)
    elif data=="st_dr":
        cur=get_setting('default_reply_enabled',False)
        set_setting('default_reply_enabled',not cur)
        if not cur: ctx.user_data['await']='dr_txt'; await q.edit_message_text("💬 **Enter default reply text:**",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_set")]]))
        else: await cb(upd,ctx)
    elif data=="st_fs": set_setting('flood_slow_mode',not get_setting('flood_slow_mode',True)); await cb(upd,ctx)
    
    # ── Status ──
    elif data=="m_stat":
        ar="🟢ON" if auto_reply_enabled else "🔴OFF"
        gs="🟢ON" if group_spam_enabled else "🔴OFF"
        txt=f"📊 **Status**\n\n📨 Auto Reply: {ar}\n📢 Group Spam: {gs}\n👤 Total: {len(get_all_accounts())}\n🟢 Active: {len(active_accounts)}\n📢 Spam Running: {sum(1 for a in active_accounts if account_stats.get(a['id'],{}).get('spam_running',False))}\n📨 Spam Sent: {sum(account_stats.get(a['id'],{}).get('spam_sent',0) for a in active_accounts)}\n👥 Customers: {len(customer_count)}\n💾 Backups: {len(get_backup_accounts())}\n⚡ Speed: {get_setting('spam_speed','medium')}"
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh",callback_data="m_stat")],[InlineKeyboardButton("🔙 Menu",callback_data="main")]]))
    
    # ── Admin ──
    elif data=="m_adm":
        txt=f"👥 **Admin Panel**\n\n👑 Owner: `{OWNER_ID}`\n👤 Admins: {len(admins)-1}\n\n"
        for a in admins: txt+=f"{'👑' if a==OWNER_ID else '👤'} `{a}`\n"
        kb=[[InlineKeyboardButton("➕ Add Admin",callback_data="ad_add")],[InlineKeyboardButton("🗑 Delete Admin",callback_data="ad_del")],[InlineKeyboardButton("🔙 Menu",callback_data="main")]]
        if uid!=OWNER_ID: kb=[[InlineKeyboardButton("🔙 Menu",callback_data="main")]]
        await q.edit_message_text(txt,parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data=="ad_add" and uid==OWNER_ID:
        ctx.user_data['await']='ad_add'
        await q.edit_message_text("➕ **Enter user ID:**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_adm")]]))
    elif data=="ad_del" and uid==OWNER_ID:
        if len(admins)<=1: await q.edit_message_text("❌ Only owner left!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_adm")]])); return
        kb=[[InlineKeyboardButton(f"🗑 `{a}`",callback_data=f"addc_{a}")] for a in admins if a!=OWNER_ID]
        kb.append([InlineKeyboardButton("🔙",callback_data="m_adm")])
        await q.edit_message_text("🗑 **Select to remove:**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("addc_") and uid==OWNER_ID:
        aid=int(data.split('_')[1])
        if aid in admins and aid!=OWNER_ID:
            admins.remove(aid); await q.edit_message_text(f"✅ `{aid}` removed!",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_adm")]]))

# ─── TEXT HANDLER ───
async def txt_h(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id
    if uid!=OWNER_ID and uid not in admins: return
    txt=upd.message.text.strip(); aw=ctx.user_data.get('await')
    if not aw: return
    
    if aw=='seen_delay':
        try:
            v=int(txt)
            if 1<=v<=30: set_setting('seen_delay',v); await upd.message.reply_text(f"✅ Seen: {v}s!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_ar")]]))
            else: await upd.message.reply_text("❌ 1-30 only!")
        except: await upd.message.reply_text("❌ Number pls!")
        ctx.user_data['await']=None
    
    elif aw=='ignore':
        set_setting('ignored_messages',txt)
        await upd.message.reply_text("✅ Updated!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_ar")]]))
        ctx.user_data['await']=None
    
    elif aw=='rk':
        ctx.user_data['rk']=txt; ctx.user_data['await']='rt'
        await upd.message.reply_text(f"Keyword: `{txt}`\n\nMatch type:",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔑 Exact",callback_data="rt_exact")],[InlineKeyboardButton("🔍 Contains",callback_data="rt_cont")],[InlineKeyboardButton("🔙 Cancel",callback_data="ar_rp")]]))
    
    elif aw=='rt':
        kw=ctx.user_data.get('rk',''); tp=ctx.user_data.get('rt','contains')
        rid=add_reply(kw,txt,tp)
        await upd.message.reply_text(f"✅ Added! (ID: {rid})",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="ar_rp")]]))
        ctx.user_data['await']=None
    
    elif aw=='rb':
        """একসাথে অনেকগুলি রিপ্লাই যোগ করুন - Bulk Add"""
        lines=txt.strip().split('\n')
        data_list = []
        success = 0
        errors = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts=[p.strip() for p in line.split('|')]
            if len(parts)>=3:
                kw,reply,mt=parts[0],parts[1],parts[2].lower()
                if mt not in ['exact','contains']: mt='contains'
                data_list.append((kw, reply, mt))
                success += 1
            else:
                errors += 1
        
        if data_list:
            ids = add_replies_bulk(data_list)
            msg = f"✅ {len(ids)} টি রিপ্লাই যোগ করা হলো!"
            if errors:
                msg += f"\n⚠️ {errors} টি লাইন ভুল ফরম্যাটে ছিল (স্কিপ করা হয়েছে)"
            msg += "\n\n✅ ফরম্যাট: `keyword | reply | exact/contains`"
        else:
            msg = "❌ কোনো বৈধ রিপ্লাই পাওয়া যায়নি!\n\nফরম্যাট: `keyword | reply | exact/contains`"
            msg += "\n\nউদাহরণ:\n```\nprice | Price 99 টাকা | contains\nhello | Hello baby! | exact\nbye | Bye bye | exact\n```"
        
        await upd.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="ar_rp")]]))
        ctx.user_data['await']=None
    
    elif aw=='gs_bs':
        try:
            v=int(txt)
            if 1<=v<=50: set_setting('spam_batch_size',v); await upd.message.reply_text(f"✅ Batch: {v}!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
            else: await upd.message.reply_text("❌ 1-50!")
        except: await upd.message.reply_text("❌ Number!")
        ctx.user_data['await']=None
    
    elif aw=='gs_bd':
        try:
            v=int(txt)
            if 0<=v<=30: set_setting('spam_batch_delay',v); await upd.message.reply_text(f"✅ B.Delay: {v}s!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
            else: await upd.message.reply_text("❌ 0-30!")
        except: await upd.message.reply_text("❌ Number!")
        ctx.user_data['await']=None
    
    elif aw=='gs_cw':
        try:
            v=int(txt)
            if 0<=v<=300: set_setting('spam_cycle_wait',v); await upd.message.reply_text(f"✅ Cycle: {v}s!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
            else: await upd.message.reply_text("❌ 0-300!")
        except: await upd.message.reply_text("❌ Number!")
        ctx.user_data['await']=None
    
    elif aw=='gs_msg':
        set_setting('spam_message',txt)
        await upd.message.reply_text(f"✅ Message updated!\n\n`{txt}`",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_gs")]]))
        ctx.user_data['await']=None
    
    elif aw=='dr_txt':
        set_setting('default_reply_text',txt)
        await upd.message.reply_text("✅ Default reply set!",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_set")]]))
        ctx.user_data['await']=None
    
    elif aw=='ad_add':
        try:
            aid=int(txt.strip())
            if aid not in admins: admins.append(aid); await upd.message.reply_text(f"✅ `{aid}` added!",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_adm")]]))
            else: await upd.message.reply_text("❌ Already admin!")
        except: await upd.message.reply_text("❌ Valid ID pls!")
        ctx.user_data['await']=None
    
    # ─── ACCOUNT: Phone + OTP ───
    elif aw=='ac_ph':
        phone=txt.strip()
        if not phone.startswith('+'): phone='+'+phone
        ctx.user_data['ac_ph']=phone
        ctx.user_data['await']='ac_otp'
        try:
            from telethon.errors import PhoneNumberInvalidError
            c=TelegramClient(StringSession(),DEFAULT_API_ID,DEFAULT_API_HASH,receive_updates=False)
            await c.connect()
            await c.send_code_request(phone)
            ctx.user_data['ac_cl']=c
            await upd.message.reply_text(f"📱 OTP sent to `{phone}`\n\n**Enter OTP:**",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]]))
        except Exception as e:
            await upd.message.reply_text(f"❌ {str(e)[:80]}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]]))
            ctx.user_data['await']=None
    
    elif aw=='ac_otp':
        code=txt.strip(); phone=ctx.user_data.get('ac_ph',''); client=ctx.user_data.get('ac_cl')
        if not client: await upd.message.reply_text("❌ Session expired! Try again."); ctx.user_data['await']=None; return
        
        if ctx.user_data.get('ac_2fa'):
            try:
                await client.sign_in(password=code)
                me=await client.get_me()
                ss=client.session.save()
                info={'id':gen_acc_id(),'user_id':me.id,'name':me.first_name or f"User{me.id}",'phone':getattr(me,'phone',phone),'session':ss,'api_id':DEFAULT_API_ID,'api_hash':DEFAULT_API_HASH,'enabled':True,'mode':'ai','spam_active':False,'proxy':None,'is_backup':False,'added_at':datetime.now().isoformat()}
                add_account_data(info)
                c2=await start_account(info)
                if c2:
                    active_accounts.append(info); account_clients[info['id']]=c2
                    account_stats[info['id']]={'auto_sent':0,'spam_sent':0,'running':False,'spam_running':False}
                    account_stop_flags[info['id']]=False; register_ar(c2,info)
                await upd.message.reply_text(f"✅ **Added!** 🎉\n👤 {info['name']}\n📱 {info['phone']}",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]]))
                ctx.user_data['await']=None; return
            except Exception as e:
                await upd.message.reply_text(f"❌ {str(e)[:80]}"); ctx.user_data['await']=None; return
        
        try:
            await client.sign_in(phone,code)
            me=await client.get_me()
            ss=client.session.save()
            info={'id':gen_acc_id(),'user_id':me.id,'name':me.first_name or f"User{me.id}",'phone':getattr(me,'phone',phone),'session':ss,'api_id':DEFAULT_API_ID,'api_hash':DEFAULT_API_HASH,'enabled':True,'mode':'ai','spam_active':False,'proxy':None,'is_backup':False,'added_at':datetime.now().isoformat()}
            add_account_data(info)
            c2=await start_account(info)
            if c2:
                active_accounts.append(info); account_clients[info['id']]=c2
                account_stats[info['id']]={'auto_sent':0,'spam_sent':0,'running':False,'spam_running':False}
                account_stop_flags[info['id']]=False; register_ar(c2,info)
            await upd.message.reply_text(f"✅ **Added!** 🎉\n👤 {info['name']}\n📱 {info['phone']}",parse_mode='Markdown',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="m_acc")]]))
            ctx.user_data['await']=None
        except SessionPasswordNeededError:
            ctx.user_data['ac_2fa']=True; ctx.user_data['await']='ac_otp'
            await upd.message.reply_text("🔑 **2FA Password required:**",parse_mode='Markdown')
        except PhoneCodeInvalidError: await upd.message.reply_text("❌ Invalid OTP! Try again:")
        except PhoneCodeExpiredError: await upd.message.reply_text("❌ OTP expired! Start again."); ctx.user_data['await']=None
        except Exception as e: await upd.message.reply_text(f"❌ {str(e)[:80]}"); ctx.user_data['await']=None

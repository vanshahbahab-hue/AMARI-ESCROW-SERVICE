import re
import json
import os
import threading
import qrcode
import random
import string
from io import BytesIO
from datetime import datetime
from flask import Flask
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ============ FLASK FOR RENDER ============
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "ESCROW Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host='0.0.0.0', port=port)

# ============ CONFIG ============
BOT_TOKEN = "8679581798:AAGZtycapDdwpwYR8ro5M4xZNFiIR4QuetI"
OWNER_ID = 8586849798
ADMIN_IDS = [OWNER_ID]

DEALS_FILE = "deals.json"
USERS_FILE = "users.json"
PENDING_FILE = "pending.json"

# ============ FANCY TEXT FUNCTION ============
def to_fancy(text):
    fancy_map = {
        'A': '𝐀', 'B': '𝐁', 'C': '𝐂', 'D': '𝐃', 'E': '𝐄', 'F': '𝐅', 'G': '𝐆', 'H': '𝐇', 'I': '𝐈',
        'J': '𝐉', 'K': '𝐊', 'L': '𝐋', 'M': '𝐌', 'N': '𝐍', 'O': '𝐎', 'P': '𝐏', 'Q': '𝐐', 'R': '𝐑',
        'S': '𝐒', 'T': '𝐓', 'U': '𝐔', 'V': '𝐕', 'W': '𝐖', 'X': '𝐗', 'Y': '𝐘', 'Z': '𝐙',
        'a': '𝐚', 'b': '𝐛', 'c': '𝐜', 'd': '𝐝', 'e': '𝐞', 'f': '𝐟', 'g': '𝐠', 'h': '𝐡', 'i': '𝐢',
        'j': '𝐣', 'k': '𝐤', 'l': '𝐥', 'm': '𝐦', 'n': '𝐧', 'o': '𝐨', 'p': '𝐩', 'q': '𝐪', 'r': '𝐫',
        's': '𝐬', 't': '𝐭', 'u': '𝐮', 'v': '𝐯', 'w': '𝐰', 'x': '𝐱', 'y': '𝐲', 'z': '𝐳',
        '0': '𝟎', '1': '𝟏', '2': '𝟐', '3': '𝟑', '4': '𝟒', '5': '𝟓', '6': '𝟔', '7': '𝟕', '8': '𝟖', '9': '𝟗'
    }
    return ''.join(fancy_map.get(c, c) for c in text)

# ============ FILE FUNCTIONS ============
def load_deals():
    if os.path.exists(DEALS_FILE):
        with open(DEALS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_deals(data):
    with open(DEALS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_users(data):
    with open(USERS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_pending():
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_pending(data):
    with open(PENDING_FILE, 'w') as f:
        json.dump(data, f, indent=2)

deals = load_deals()
users = load_users()
pending_tx = load_pending()

# ============ HELPERS ============
def generate_deal_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def calculate_fee(amount):
    if amount <= 400:
        return 10
    elif amount <= 2000:
        return int(amount * 0.03)
    elif amount <= 5000:
        return int(amount * 0.035)
    else:
        return int(amount * 0.03)

def get_qr_amount(original_amount):
    base_amount = original_amount + calculate_fee(original_amount)
    random_paise = random.randint(1, 99)
    qr_amount = base_amount + (random_paise / 100)
    return round(qr_amount, 2), random_paise

def generate_qr(upi_id, qr_amount, deal_id):
    upi_link = f"upi://pay?pa={upi_id}&pn=ESCROW&am={qr_amount}&cu=INR&tn={deal_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(upi_link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

def extract_amount_from_sms(text):
    patterns = [r'Rs\.?\s*(\d+\.?\d*)', r'₹\s*(\d+\.?\d*)', r'debited\s*Rs\.?\s*(\d+\.?\d*)']
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None

def find_deal_by_qr_amount(qr_amount):
    for deal_id, deal in deals.items():
        if deal.get("qr_amount") == qr_amount and deal["status"] == "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓":
            return deal_id, deal
    return None, None

def register_user(user_id, username, first_name):
    if str(user_id) not in users:
        users[str(user_id)] = {
            "id": user_id,
            "username": username,
            "name": first_name,
            "joined": str(datetime.now()),
            "banned": False
        }
        save_users(users)
        return True
    return False

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_owner(user_id):
    return user_id == OWNER_ID

def is_banned(user_id):
    user = users.get(str(user_id), {})
    return user.get('banned', False)

# ============ MAIN MESSAGE HANDLER ============
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username.lower() if user.username else ""
    text_lower = message_text.lower()
    user_id = user.id
    
    # Register user if new
    is_new = register_user(user_id, user.username or "NoUsername", user.first_name)
    if is_new and user_id != OWNER_ID:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🆕 𝐍𝐄𝐖 𝐔𝐒𝐄𝐑 𝐉𝐎𝐈𝐍𝐄𝐃!\n\n👤 𝐍𝐚𝐦𝐞: {user.first_name}\n🆔 𝐈𝐃: {user_id}\n📛 𝐔𝐬𝐞𝐫𝐧𝐚𝐦𝐞: @{user.username or 'NoUsername'}\n🕐 𝐓𝐢𝐦𝐞: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    if is_banned(user_id):
        await update.message.reply_text("❌ 𝐘𝐨𝐮 𝐚𝐫𝐞 𝐛𝐚𝐧𝐧𝐞𝐝 𝐟𝐫𝐨𝐦 𝐮𝐬𝐢𝐧𝐠 𝐭𝐡𝐢𝐬 𝐛𝐨𝐭.")
        return
    
    # ============ ESCROW FORM DETECTION ============
    if re.search(r'ESCROW\s*DEAL\s*FORM', message_text, re.IGNORECASE):
        amount_match = re.search(r'DEAL\s*AMOUNT\s*:?\s*[-\s]*(\d+)', message_text, re.IGNORECASE)
        buyer_match = re.search(r'BUYERS?\s*:?\s*[-\s]*@?(\w+)', message_text, re.IGNORECASE)
        seller_match = re.search(r'SELLER\s*:?\s*[-\s]*@?(\w+)', message_text, re.IGNORECASE)
        deal_detail_match = re.search(r'DEAL\s*DETAIL\s*:?\s*[-\s]*(.+)', message_text, re.IGNORECASE)
        upi_match = re.search(r'RLS\s*UPI\s*:?\s*[-\s]*(\S+@\S+)', message_text, re.IGNORECASE)
        
        if not amount_match:
            await update.message.reply_text("❌ 𝐌𝐢𝐬𝐬𝐢𝐧𝐠 𝐃𝐄𝐀𝐋 𝐀𝐌𝐎𝐔𝐍𝐓!")
            return
        
        amount = int(amount_match.group(1))
        buyer = buyer_match.group(1) if buyer_match else None
        seller = seller_match.group(1) if seller_match else None
        deal_detail = deal_detail_match.group(1) if deal_detail_match else "𝐍/𝐀"
        upi_id = upi_match.group(1) if upi_match else "venomxpay@naviaxis"
        
        if not buyer or not seller:
            await update.message.reply_text("❌ 𝐍𝐞𝐞𝐝 𝐁𝐔𝐘𝐄𝐑 𝐚𝐧𝐝 𝐒𝐄𝐋𝐋𝐄𝐑!")
            return
        
        fee = calculate_fee(amount)
        total_with_fee = amount + fee
        qr_amount, random_paise = get_qr_amount(amount)
        deal_id = generate_deal_id()
        
        deals[deal_id] = {
            "deal_id": deal_id,
            "amount": amount,
            "fee": fee,
            "total_with_fee": total_with_fee,
            "qr_amount": qr_amount,
            "buyer": buyer,
            "seller": seller,
            "deal_detail": deal_detail,
            "upi_id": upi_id,
            "buyer_agreed": False,
            "seller_agreed": False,
            "status": "𝐏𝐄𝐍𝐃𝐈𝐍𝐆",
            "chat_id": chat_id,
            "created_at": str(datetime.now()),
            "buyer_id": None,
            "seller_id": None,
            "payment_received": False,
            "payment_txid": None,
            "payment_amount": None,
            "seller_upi": None,
            "release_requested": False
        }
        save_deals(deals)
        
        fancy_amount = to_fancy(str(amount))
        fancy_fee = to_fancy(str(fee))
        fancy_total = to_fancy(str(total_with_fee))
        
        await update.message.reply_text(f"""
🔷 𝐄𝐒𝐂𝐑𝐎𝐖 𝐃𝐄𝐀𝐋 𝐂𝐑𝐄𝐀𝐓𝐄𝐃 🔷

📋 𝐃𝐄𝐀𝐋 𝐈𝐃: `{deal_id}`
💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}
📊 𝐅𝐞𝐞: ₹{fancy_fee}
💵 𝐓𝐨𝐭𝐚𝐥 𝐭𝐨 𝐏𝐚𝐲: ₹{fancy_total}

👤 𝐁𝐮𝐲𝐞𝐫: @{buyer}
👥 𝐒𝐞𝐥𝐥𝐞𝐫: @{seller}
📝 𝐃𝐞𝐭𝐚𝐢𝐥𝐬: {deal_detail}
💳 𝐔𝐏𝐈: {upi_id}

━━━━━━━━━━━━━━━━━━
⚠️ 𝐄𝐒𝐂𝐑𝐎𝐖 𝐅𝐄𝐄𝐒 𝐈𝐒 𝐍𝐎𝐍-𝐑𝐄𝐅𝐔𝐍𝐃𝐀𝐁𝐋𝐄
━━━━━━━━━━━━━━━━━━

✅ @{buyer} - 𝐓𝐲𝐩𝐞 `𝐀𝐆𝐑𝐄𝐄` 𝐭𝐨 𝐜𝐨𝐧𝐟𝐢𝐫𝐦
✅ @{seller} - 𝐓𝐲𝐩𝐞 `𝐀𝐆𝐑𝐄𝐄` 𝐭𝐨 𝐜𝐨𝐧𝐟𝐢𝐫𝐦

🕐 𝐁𝐨𝐭𝐡 𝐦𝐮𝐬𝐭 𝐚𝐠𝐫𝐞𝐞 𝐰𝐢𝐭𝐡𝐢𝐧 𝟏𝟎 𝐦𝐢𝐧𝐮𝐭𝐞𝐬!
""", parse_mode="Markdown")
        
        await context.bot.send_message(chat_id=OWNER_ID, text=f"🆕 𝐍𝐄𝐖 𝐃𝐄𝐀𝐋!\n📋 𝐈𝐃: {deal_id}\n💰 ₹{amount}\n@{buyer} → @{seller}")
        return
    
    # ============ AGREE DETECTION ============
    agree_words = ['agree', 'agre', 'argee', 'agr', 'yes', 'done', 'ok', 'y']
    is_agree = any(word == text_lower or text_lower.startswith(word) for word in agree_words)
    
    if is_agree:
        for deal_id, deal in deals.items():
            if deal["status"] != "𝐏𝐄𝐍𝐃𝐈𝐍𝐆":
                continue
            
            if deal["buyer"].lower() == username:
                deal["buyer_agreed"] = True
                deal["buyer_id"] = user.id
                save_deals(deals)
                await update.message.reply_text(f"✅ @{user.username}, 𝐲𝐨𝐮 𝐚𝐠𝐫𝐞𝐞𝐝 𝐚𝐬 𝐁𝐔𝐘𝐄𝐑 𝐟𝐨𝐫 𝐝𝐞𝐚𝐥 `{deal_id}`!")
                
                if deal["seller_agreed"]:
                    await process_both_agreed(context, deal_id, deal)
                return
            
            elif deal["seller"].lower() == username:
                deal["seller_agreed"] = True
                deal["seller_id"] = user.id
                save_deals(deals)
                await update.message.reply_text(f"✅ @{user.username}, 𝐲𝐨𝐮 𝐚𝐠𝐫𝐞𝐞𝐝 𝐚𝐬 𝐒𝐄𝐋𝐋𝐄𝐑 𝐟𝐨𝐫 𝐝𝐞𝐚𝐥 `{deal_id}`!")
                
                if deal["buyer_agreed"]:
                    await process_both_agreed(context, deal_id, deal)
                return
        
        await update.message.reply_text("❌ 𝐘𝐨𝐮 𝐝𝐨𝐧'𝐭 𝐡𝐚𝐯𝐞 𝐚𝐧𝐲 𝐩𝐞𝐧𝐝𝐢𝐧𝐠 𝐝𝐞𝐚𝐥.")
        return

async def process_both_agreed(context, deal_id, deal):
    deal["status"] = "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓"
    save_deals(deals)
    
    qr_amount = deal["qr_amount"]
    img_bytes = generate_qr(deal["upi_id"], qr_amount, deal_id)
    photo = InputFile(img_bytes, filename="qr.png")
    
    fancy_amount = to_fancy(str(deal['amount']))
    fancy_fee = to_fancy(str(deal['fee']))
    fancy_qr = to_fancy(str(qr_amount))
    
    if deal.get("buyer_id"):
        await context.bot.send_photo(
            chat_id=deal["buyer_id"],
            photo=photo,
            caption=f"🔷 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐐𝐑 𝐂𝐎𝐃𝐄 🔷\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐎𝐫𝐢𝐠𝐢𝐧𝐚𝐥: ₹{fancy_amount}\n📊 𝐅𝐞𝐞: ₹{fancy_fee}\n\n💵 𝐏𝐚𝐲 𝐭𝐡𝐢𝐬 𝐞𝐱𝐚𝐜𝐭 𝐚𝐦𝐨𝐮𝐧𝐭: ₹{fancy_qr}\n\n✅ 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐰𝐢𝐥𝐥 𝐛𝐞 𝐀𝐔𝐓𝐎-𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃 𝐰𝐡𝐞𝐧 𝐒𝐌𝐒 𝐢𝐬 𝐫𝐞𝐜𝐞𝐢𝐯𝐞𝐝\n\n❌ 𝐃𝐎𝐍'𝐓 𝐏𝐀𝐘 𝐈𝐍 𝐃𝐌𝐒",
            parse_mode="Markdown"
        )
    
    await context.bot.send_message(
        chat_id=deal["chat_id"],
        text=f"✅ 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n👤 𝐁𝐮𝐲𝐞𝐫 @{deal['buyer']} 𝐡𝐚𝐬 𝐫𝐞𝐜𝐞𝐢𝐯𝐞𝐝 𝐐𝐑 𝐜𝐨𝐝𝐞.\n⚠️ 𝐏𝐚𝐲 𝐄𝐗𝐀𝐂𝐓 ₹{fancy_qr} 𝐟𝐨𝐫 𝐚𝐮𝐭𝐨-𝐯𝐞𝐫𝐢𝐟𝐢𝐜𝐚𝐭𝐢𝐨𝐧!",
        parse_mode="Markdown"
    )
    
    await context.bot.send_message(chat_id=OWNER_ID, text=f"✅ 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄𝐃!\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: {deal_id}\n@{deal['buyer']} 𝐚𝐧𝐝 @{deal['seller']}")

# ============ AUTO VERIFICATION FROM SMS ============
async def sms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    text = update.message.text
    sms_amount = extract_amount_from_sms(text)
    
    if not sms_amount:
        await update.message.reply_text("❌ 𝐂𝐨𝐮𝐥𝐝 𝐧𝐨𝐭 𝐞𝐱𝐭𝐫𝐚𝐜𝐭 𝐚𝐦𝐨𝐮𝐧𝐭 𝐟𝐫𝐨𝐦 𝐒𝐌𝐒.")
        return
    
    deal_id, deal = find_deal_by_qr_amount(sms_amount)
    
    if deal_id and deal:
        deal["payment_received"] = True
        deal["payment_amount"] = sms_amount
        deal["status"] = "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃"
        save_deals(deals)
        
        fancy_amount = to_fancy(str(deal['amount']))
        
        await update.message.reply_text(f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐀𝐔𝐓𝐎-𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}", parse_mode="Markdown")
        
        # Send to GROUP
        await context.bot.send_message(
            chat_id=deal["chat_id"],
            text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐀𝐔𝐓𝐎-𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃! ✅\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 𝐯𝐞𝐫𝐢𝐟𝐢𝐞𝐝.\n👥 𝐒𝐞𝐥𝐥𝐞𝐫 𝐜𝐚𝐧 𝐧𝐨𝐰 𝐝𝐞𝐥𝐢𝐯𝐞𝐫 𝐭𝐡𝐞 𝐩𝐫𝐨𝐝𝐮𝐜𝐭.\n👤 𝐁𝐮𝐲𝐞𝐫 𝐰𝐢𝐥𝐥 𝐫𝐞𝐥𝐞𝐚𝐬𝐞 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 𝐚𝐟𝐭𝐞𝐫 𝐫𝐞𝐜𝐞𝐢𝐯𝐢𝐧𝐠 𝐩𝐫𝐨𝐝𝐮𝐜𝐭.",
            parse_mode="Markdown"
        )
        
        # Send to buyer
        if deal.get("buyer_id"):
            await context.bot.send_message(
                chat_id=deal["buyer_id"],
                text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n📦 𝐀𝐟𝐭𝐞𝐫 𝐫𝐞𝐜𝐞𝐢𝐯𝐢𝐧𝐠 𝐩𝐫𝐨𝐝𝐮𝐜𝐭, 𝐭𝐲𝐩𝐞: `/release {deal_id}`",
                parse_mode="Markdown"
            )
        
        # Send to seller
        if deal.get("seller_id"):
            await context.bot.send_message(
                chat_id=deal["seller_id"],
                text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n🎁 𝐏𝐥𝐞𝐚𝐬𝐞 𝐝𝐞𝐥𝐢𝐯𝐞𝐫 𝐭𝐡𝐞 𝐩𝐫𝐨𝐝𝐮𝐜𝐭 𝐭𝐨 𝐛𝐮𝐲𝐞𝐫.",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(f"⚠️ 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐝𝐞𝐭𝐞𝐜𝐭𝐞𝐝!\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{sms_amount}\n❌ 𝐍𝐨 𝐦𝐚𝐭𝐜𝐡𝐢𝐧𝐠 𝐝𝐞𝐚𝐥 𝐟𝐨𝐮𝐧𝐝!")

# ============ BUYER VERIFY COMMAND (ONLY AFTER REAL PAYMENT) ============
async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buyer can verify ONLY after payment is actually made"""
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/verify 𝐃𝐄𝐀𝐋_𝐈𝐃`\n\n𝐄𝐱𝐚𝐦𝐩𝐥𝐞: `/verify K2P9EJY0`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if user_id != deal.get("buyer_id"):
        await update.message.reply_text("❌ 𝐎𝐧𝐥𝐲 𝐛𝐮𝐲𝐞𝐫 𝐜𝐚𝐧 𝐯𝐞𝐫𝐢𝐟𝐲 𝐭𝐡𝐞 𝐩𝐚𝐲𝐦𝐞𝐧𝐭!")
        return
    
    if deal["status"] != "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓":
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐢𝐬 𝐧𝐨𝐭 𝐚𝐰𝐚𝐢𝐭𝐢𝐧𝐠 𝐩𝐚𝐲𝐦𝐞𝐧𝐭!\n𝐂𝐮𝐫𝐫𝐞𝐧𝐭 𝐬𝐭𝐚𝐭𝐮𝐬: {deal['status']}", parse_mode="Markdown")
        return
    
    # ============ CRITICAL FIX: Check if payment actually happened ============
    # Bot will NOT confirm payment unless SMS has been received
    # Payment can only be confirmed by:
    # 1. SMS auto-verification (owner forwards SMS)
    # 2. Admin manually confirms (/confirmpayment DEAL_ID)
    
    # If payment is not received yet, buyer CANNOT fake verify
    if not deal.get("payment_received"):
        await update.message.reply_text(
            f"❌ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐍𝐎𝐓 𝐑𝐄𝐂𝐄𝐈𝐕𝐄𝐃 𝐘𝐄𝐓! ❌\n\n"
            f"📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n"
            f"💰 𝐀𝐦𝐨𝐮𝐧𝐭 𝐭𝐨 𝐏𝐚𝐲: ₹{deal['qr_amount']}\n\n"
            f"🔷 𝐏𝐥𝐞𝐚𝐬𝐞 𝐦𝐚𝐤𝐞 𝐭𝐡𝐞 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 𝐚𝐧𝐝 𝐭𝐡𝐞𝐧 𝐯𝐞𝐫𝐢𝐟𝐲.\n"
            f"📱 𝐀𝐟𝐭𝐞𝐫 𝐩𝐚𝐲𝐦𝐞𝐧𝐭, 𝐟𝐨𝐫𝐰𝐚𝐫𝐝 𝐭𝐡𝐞 𝐒𝐌𝐒 𝐭𝐨 𝐛𝐨𝐭.\n\n"
            f"⚠️ 𝐃𝐎 𝐍𝐎𝐓 𝐅𝐀𝐊𝐄 𝐕𝐄𝐑𝐈𝐅𝐘!",
            parse_mode="Markdown"
        )
        return
    
    # If payment is received, confirm
    fancy_amount = to_fancy(str(deal['amount']))
    
    await update.message.reply_text(
        f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃! ✅\n\n"
        f"📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n"
        f"💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n"
        f"🎉 𝐂𝐎𝐍𝐓𝐈𝐍𝐔𝐄 𝐘𝐎𝐔𝐑 𝐃𝐄𝐀𝐋 🎉\n\n"
        f"📦 𝐀𝐟𝐭𝐞𝐫 𝐫𝐞𝐜𝐞𝐢𝐯𝐢𝐧𝐠 𝐩𝐫𝐨𝐝𝐮𝐜𝐭, 𝐭𝐲𝐩𝐞: `/release {deal_id}`",
        parse_mode="Markdown"
    )
    
    # Notify group
    await context.bot.send_message(
        chat_id=deal["chat_id"],
        text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃 𝐅𝐎𝐑 𝐃𝐄𝐀𝐋 `{deal_id}`!\n\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n👤 𝐁𝐮𝐲𝐞𝐫: @{deal['buyer']}\n\n👥 𝐒𝐞𝐥𝐥𝐞𝐫 𝐜𝐚𝐧 𝐧𝐨𝐰 𝐝𝐞𝐥𝐢𝐯𝐞𝐫 𝐭𝐡𝐞 𝐩𝐫𝐨𝐝𝐮𝐜𝐭.",
        parse_mode="Markdown"
    )
    
    # Notify seller
    if deal.get("seller_id"):
        await context.bot.send_message(
            chat_id=deal["seller_id"],
            text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n🎁 𝐏𝐥𝐞𝐚𝐬𝐞 𝐝𝐞𝐥𝐢𝐯𝐞𝐫 𝐭𝐡𝐞 𝐩𝐫𝐨𝐝𝐮𝐜𝐭 𝐭𝐨 𝐛𝐮𝐲𝐞𝐫.",
            parse_mode="Markdown"
        )

# ============ ADMIN MANUAL PAYMENT CONFIRMATION (For testing/emergency) ============
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin can manually confirm payment - /confirmpayment DEAL_ID AMOUNT"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/confirmpayment 𝐃𝐄𝐀𝐋_𝐈𝐃 𝐀𝐌𝐎𝐔𝐍𝐓`\n\n𝐄𝐱𝐚𝐦𝐩𝐥𝐞: `/confirmpayment K2P9EJY0 40.08`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    amount = float(context.args[1])
    
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if deal["status"] != "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓":
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐢𝐬 𝐧𝐨𝐭 𝐚𝐰𝐚𝐢𝐭𝐢𝐧𝐠 𝐩𝐚𝐲𝐦𝐞𝐧𝐭!", parse_mode="Markdown")
        return
    
    deal["payment_received"] = True
    deal["payment_amount"] = amount
    deal["status"] = "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃"
    save_deals(deals)
    
    fancy_amount = to_fancy(str(deal['amount']))
    
    await update.message.reply_text(f"✅ 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐦𝐚𝐧𝐮𝐚𝐥𝐥𝐲 𝐜𝐨𝐧𝐟𝐢𝐫𝐦𝐞𝐝 𝐟𝐨𝐫 𝐝𝐞𝐚𝐥 `{deal_id}`!", parse_mode="Markdown")
    
    # Notify buyer
    if deal.get("buyer_id"):
        await context.bot.send_message(
            chat_id=deal["buyer_id"],
            text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n📦 𝐀𝐟𝐭𝐞𝐫 𝐫𝐞𝐜𝐞𝐢𝐯𝐢𝐧𝐠 𝐩𝐫𝐨𝐝𝐮𝐜𝐭, 𝐭𝐲𝐩𝐞: `/release {deal_id}`",
            parse_mode="Markdown"
        )

# ============ BUYER RELEASE COMMAND ============
async def release_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/release 𝐃𝐄𝐀𝐋_𝐈𝐃`\n\n𝐄𝐱𝐚𝐦𝐩𝐥𝐞: `/release K2P9EJY0`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if user_id != deal.get("buyer_id"):
        await update.message.reply_text("❌ 𝐎𝐧𝐥𝐲 𝐛𝐮𝐲𝐞𝐫 𝐜𝐚𝐧 𝐫𝐞𝐥𝐞𝐚𝐬𝐞 𝐭𝐡𝐞 𝐝𝐞𝐚𝐥!")
        return
    
    if deal["status"] != "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃":
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐢𝐬 𝐧𝐨𝐭 𝐫𝐞𝐚𝐝𝐲 𝐟𝐨𝐫 𝐫𝐞𝐥𝐞𝐚𝐬𝐞!", parse_mode="Markdown")
        return
    
    if deal.get("release_requested"):
        await update.message.reply_text("❌ 𝐑𝐞𝐥𝐞𝐚𝐬𝐞 𝐚𝐥𝐫𝐞𝐚𝐝𝐲 𝐫𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝! 𝐖𝐚𝐢𝐭𝐢𝐧𝐠 𝐟𝐨𝐫 𝐬𝐞𝐥𝐥𝐞𝐫'𝐬 𝐔𝐏𝐈.")
        return
    
    deal["release_requested"] = True
    save_deals(deals)
    
    fancy_amount = to_fancy(str(deal['amount']))
    
    await update.message.reply_text(f"✅ 𝐑𝐞𝐥𝐞𝐚𝐬𝐞 𝐫𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝 𝐟𝐨𝐫 𝐝𝐞𝐚𝐥 `{deal_id}`!\n\n👥 𝐒𝐞𝐥𝐥𝐞𝐫 @{deal['seller']} 𝐰𝐢𝐥𝐥 𝐧𝐨𝐰 𝐩𝐫𝐨𝐯𝐢𝐝𝐞 𝐭𝐡𝐞𝐢𝐫 𝐔𝐏𝐈 𝐈𝐃.", parse_mode="Markdown")
    
    if deal.get("seller_id"):
        await context.bot.send_message(
            chat_id=deal["seller_id"],
            text=f"🔷 𝐑𝐄𝐋𝐄𝐀𝐒𝐄 𝐑𝐄𝐐𝐔𝐄𝐒𝐓 𝐑𝐄𝐂𝐄𝐈𝐕𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n👤 𝐁𝐮𝐲𝐞𝐫 @{deal['buyer']} 𝐡𝐚𝐬 𝐜𝐨𝐧𝐟𝐢𝐫𝐦𝐞𝐝 𝐫𝐞𝐜𝐞𝐢𝐯𝐢𝐧𝐠 𝐭𝐡𝐞 𝐩𝐫𝐨𝐝𝐮𝐜𝐭.\n\n📝 𝐏𝐥𝐞𝐚𝐬𝐞 𝐬𝐞𝐧𝐝 𝐲𝐨𝐮𝐫 𝐔𝐏𝐈 𝐈𝐃 𝐭𝐨 𝐫𝐞𝐜𝐞𝐢𝐯𝐞 𝐩𝐚𝐲𝐦𝐞𝐧𝐭:\n`/sendupi {deal_id} 𝐘𝐎𝐔𝐑_𝐔𝐏𝐈_𝐈𝐃`\n\n𝐄𝐱𝐚𝐦𝐩𝐥𝐞: `/sendupi {deal_id} yourname@okhdfcbank`",
            parse_mode="Markdown"
        )

# ============ SELLER SEND UPI COMMAND ============
async def send_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/sendupi 𝐃𝐄𝐀𝐋_𝐈𝐃 𝐔𝐏𝐈_𝐈𝐃`\n\n𝐄𝐱𝐚𝐦𝐩𝐥𝐞: `/sendupi K2P9EJY0 venomxpay@naviaxis`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    upi_id = context.args[1]
    
    if not re.match(r'^[\w\.\-]+@[\w\.\-]+$', upi_id):
        await update.message.reply_text("❌ 𝐈𝐧𝐯𝐚𝐥𝐢𝐝 𝐔𝐏𝐈 𝐈𝐃! 𝐅𝐨𝐫𝐦𝐚𝐭: 𝐧𝐚𝐦𝐞@𝐛𝐚𝐧𝐤")
        return
    
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if user_id != deal.get("seller_id"):
        await update.message.reply_text(f"❌ 𝐎𝐧𝐥𝐲 𝐬𝐞𝐥𝐥𝐞𝐫 @{deal['seller']} 𝐜𝐚𝐧 𝐩𝐫𝐨𝐯𝐢𝐝𝐞 𝐔𝐏𝐈 𝐈𝐃!")
        return
    
    if not deal.get("release_requested"):
        await update.message.reply_text(f"❌ 𝐁𝐮𝐲𝐞𝐫 𝐡𝐚𝐬 𝐧𝐨𝐭 𝐫𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝 𝐫𝐞𝐥𝐞𝐚𝐬𝐞 𝐲𝐞𝐭!")
        return
    
    if deal.get("seller_upi"):
        await update.message.reply_text(f"❌ 𝐔𝐏𝐈 𝐈𝐃 𝐚𝐥𝐫𝐞𝐚𝐝𝐲 𝐩𝐫𝐨𝐯𝐢𝐝𝐞𝐝!")
        return
    
    deal["seller_upi"] = upi_id
    save_deals(deals)
    
    fancy_amount = to_fancy(str(deal['amount']))
    
    await update.message.reply_text(
        f"✅ 𝐔𝐏𝐈 𝐈𝐃 𝐫𝐞𝐜𝐞𝐢𝐯𝐞𝐝 𝐟𝐨𝐫 𝐝𝐞𝐚𝐥 `{deal_id}`!\n\n"
        f"💳 𝐔𝐏𝐈: `{upi_id}`\n\n"
        f"💰 𝐘𝐨𝐮𝐫 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 𝐨𝐟 ₹{fancy_amount} 𝐰𝐢𝐥𝐥 𝐛𝐞 𝐜𝐫𝐞𝐝𝐢𝐭𝐞𝐝 𝐢𝐧 𝟏𝟎-𝟐𝟎 𝐦𝐢𝐧𝐮𝐭𝐞𝐬.\n"
        f"👑 𝐎𝐰𝐧𝐞𝐫 𝐰𝐢𝐥𝐥 𝐩𝐫𝐨𝐜𝐞𝐬𝐬 𝐭𝐡𝐞 𝐭𝐫𝐚𝐧𝐬𝐟𝐞𝐫 𝐬𝐡𝐨𝐫𝐭𝐥𝐲.\n\n"
        f"𝐓𝐡𝐚𝐧𝐤 𝐲𝐨𝐮 𝐟𝐨𝐫 𝐮𝐬𝐢𝐧𝐠 𝐄𝐒𝐂𝐑𝐎𝐖 𝐁𝐎𝐓!",
        parse_mode="Markdown"
    )
    
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"💰 𝐑𝐄𝐋𝐄𝐀𝐒𝐄 𝐑𝐄𝐐𝐔𝐄𝐒𝐓 𝐏𝐄𝐍𝐃𝐈𝐍𝐆!\n\n"
              f"📋 𝐃𝐞𝐚𝐥 𝐈𝐃: {deal_id}\n"
              f"💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{deal['amount']}\n"
              f"👤 𝐁𝐮𝐲𝐞𝐫: @{deal['buyer']}\n"
              f"👥 𝐒𝐞𝐥𝐥𝐞𝐫: @{deal['seller']}\n"
              f"💳 𝐒𝐞𝐥𝐥𝐞𝐫 𝐔𝐏𝐈: {upi_id}\n\n"
              f"✅ 𝐔𝐬𝐞 `/complete {deal_id}` 𝐭𝐨 𝐦𝐚𝐫𝐤 𝐝𝐞𝐚𝐥 𝐚𝐬 𝐜𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝 𝐚𝐟𝐭𝐞𝐫 𝐭𝐫𝐚𝐧𝐬𝐟𝐞𝐫𝐫𝐢𝐧𝐠 𝐦𝐨𝐧𝐞𝐲."
    )

# ============ OWNER COMPLETE DEAL COMMAND ============
async def complete_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ 𝐎𝐧𝐥𝐲 𝐨𝐰𝐧𝐞𝐫 𝐜𝐚𝐧 𝐜𝐨𝐦𝐩𝐥𝐞𝐭𝐞 𝐭𝐡𝐞 𝐝𝐞𝐚𝐥!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/complete 𝐃𝐄𝐀𝐋_𝐈𝐃`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if deal["status"] != "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃":
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 𝐧𝐨𝐭 𝐜𝐨𝐧𝐟𝐢𝐫𝐦𝐞𝐝 𝐲𝐞𝐭!", parse_mode="Markdown")
        return
    
    if not deal.get("release_requested"):
        await update.message.reply_text("❌ 𝐁𝐮𝐲𝐞𝐫 𝐡𝐚𝐬𝐧'𝐭 𝐫𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝 𝐫𝐞𝐥𝐞𝐚𝐬𝐞 𝐲𝐞𝐭!")
        return
    
    if not deal.get("seller_upi"):
        await update.message.reply_text("❌ 𝐒𝐞𝐥𝐥𝐞𝐫 𝐡𝐚𝐬𝐧'𝐭 𝐩𝐫𝐨𝐯𝐢𝐝𝐞𝐝 𝐔𝐏𝐈 𝐈𝐃 𝐲𝐞𝐭!")
        return
    
    deal["status"] = "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"
    save_deals(deals)
    
    fancy_amount = to_fancy(str(deal['amount']))
    
    await context.bot.send_message(
        chat_id=deal["chat_id"],
        text=f"✅ 𝐃𝐄𝐀𝐋 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃! ✅\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n👤 𝐁𝐮𝐲𝐞𝐫: @{deal['buyer']}\n👥 𝐒𝐞𝐥𝐥𝐞𝐫: @{deal['seller']}\n\n🎉 𝐓𝐫𝐚𝐧𝐬𝐚𝐜𝐭𝐢𝐨𝐧 𝐬𝐮𝐜𝐜𝐞𝐬𝐬𝐟𝐮𝐥𝐥𝐲 𝐜𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝!",
        parse_mode="Markdown"
    )
    
    if deal.get("seller_id"):
        await context.bot.send_message(
            chat_id=deal["seller_id"],
            text=f"✅ 𝐃𝐄𝐀𝐋 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n💳 𝐅𝐮𝐧𝐝𝐬 𝐡𝐚𝐯𝐞 𝐛𝐞𝐞𝐧 𝐭𝐫𝐚𝐧𝐬𝐟𝐞𝐫𝐫𝐞𝐝 𝐭𝐨 𝐲𝐨𝐮𝐫 𝐔𝐏𝐈: {deal['seller_upi']}\n\n𝐓𝐡𝐚𝐧𝐤 𝐲𝐨𝐮!",
            parse_mode="Markdown"
        )
    
    if deal.get("buyer_id"):
        await context.bot.send_message(
            chat_id=deal["buyer_id"],
            text=f"✅ 𝐃𝐄𝐀𝐋 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃!\n\n📋 𝐃𝐞𝐚𝐥 𝐈𝐃: `{deal_id}`\n💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n\n𝐓𝐡𝐚𝐧𝐤 𝐲𝐨𝐮 𝐟𝐨𝐫 𝐮𝐬𝐢𝐧𝐠 𝐄𝐒𝐂𝐑𝐎𝐖 𝐁𝐎𝐓!",
            parse_mode="Markdown"
        )
    
    await update.message.reply_text(f"✅ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐦𝐚𝐫𝐤𝐞𝐝 𝐚𝐬 𝐜𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝!", parse_mode="Markdown")

# ============ OWNER PANEL COMMANDS ============
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ 𝐎𝐧𝐥𝐲 𝐨𝐰𝐧𝐞𝐫 𝐜𝐚𝐧 𝐮𝐬𝐞 𝐭𝐡𝐢𝐬!")
        return
    
    total_users = len(users)
    active_deals = len([d for d in deals.values() if d["status"] not in ["𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃", "𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃"]])
    completed_deals = len([d for d in deals.values() if d["status"] == "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"])
    total_volume = sum([d["amount"] for d in deals.values() if d["status"] == "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"])
    
    await update.message.reply_text(
        f"👑 𝐎𝐖𝐍𝐄𝐑 𝐏𝐀𝐍𝐄𝐋 👑\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 𝐒𝐓𝐀𝐓𝐈𝐒𝐓𝐈𝐂𝐒\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 𝐓𝐨𝐭𝐚𝐥 𝐔𝐬𝐞𝐫𝐬: {total_users}\n"
        f"📋 𝐀𝐜𝐭𝐢𝐯𝐞 𝐃𝐞𝐚𝐥𝐬: {active_deals}\n"
        f"✅ 𝐂𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝 𝐃𝐞𝐚𝐥𝐬: {completed_deals}\n"
        f"💰 𝐓𝐨𝐭𝐚𝐥 𝐕𝐨𝐥𝐮𝐦𝐞: ₹{total_volume}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👑 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 `/users` - 𝐋𝐢𝐬𝐭 𝐚𝐥𝐥 𝐮𝐬𝐞𝐫𝐬\n"
        f"📋 `/deals` - 𝐋𝐢𝐬𝐭 𝐚𝐥𝐥 𝐝𝐞𝐚𝐥𝐬\n"
        f"🚫 `/ban 𝐔𝐒𝐄𝐑_𝐈𝐃` - 𝐁𝐚𝐧 𝐮𝐬𝐞𝐫\n"
        f"✅ `/unban 𝐔𝐒𝐄𝐑_𝐈𝐃` - 𝐔𝐧𝐛𝐚𝐧 𝐮𝐬𝐞𝐫\n"
        f"💰 `/complete 𝐃𝐄𝐀𝐋_𝐈𝐃` - 𝐂𝐨𝐦𝐩𝐥𝐞𝐭𝐞 𝐝𝐞𝐚𝐥\n"
        f"➕ `/addadmin 𝐔𝐒𝐄𝐑_𝐈𝐃` - 𝐀𝐝𝐝 𝐚𝐝𝐦𝐢𝐧\n"
        f"🔧 `/confirmpayment 𝐃𝐄𝐀𝐋_𝐈𝐃 𝐀𝐌𝐎𝐔𝐍𝐓` - 𝐌𝐚𝐧𝐮𝐚𝐥 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 𝐜𝐨𝐧𝐟𝐢𝐫𝐦",
        parse_mode="Markdown"
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if not users:
        await update.message.reply_text("📭 𝐍𝐨 𝐮𝐬𝐞𝐫𝐬 𝐟𝐨𝐮𝐧𝐝.")
        return
    
    msg = "👥 𝐔𝐒𝐄𝐑𝐒 𝐋𝐈𝐒𝐓 👥\n━━━━━━━━━━━━━━━━━━\n\n"
    for uid, u in users.items():
        status = "🚫 𝐁𝐀𝐍𝐍𝐄𝐃" if u.get('banned') else "✅ 𝐀𝐂𝐓𝐈𝐕𝐄"
        msg += f"🆔 𝐈𝐃: `{uid}`\n📛 𝐔𝐬𝐞𝐫𝐧𝐚𝐦𝐞: @{u.get('username', '𝐍𝐨𝐧𝐞')}\n📌 𝐒𝐭𝐚𝐭𝐮𝐬: {status}\n━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if not deals:
        await update.message.reply_text("📭 𝐍𝐨 𝐝𝐞𝐚𝐥𝐬 𝐟𝐨𝐮𝐧𝐝.")
        return
    
    msg = "📋 𝐃𝐄𝐀𝐋𝐒 𝐋𝐈𝐒𝐓 📋\n━━━━━━━━━━━━━━━━━━\n\n"
    for deal_id, deal in list(deals.items())[-10:]:
        msg += f"🔖 𝐈𝐃: `{deal_id}`\n💰 ₹{deal['amount']}\n📌 𝐒𝐭𝐚𝐭𝐮𝐬: {deal['status']}\n👤 @{deal['buyer']} → @{deal['seller']}\n━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/ban 𝐔𝐒𝐄𝐑_𝐈𝐃`", parse_mode="Markdown")
        return
    
    user_id = context.args[0]
    if user_id in users:
        users[user_id]['banned'] = True
        save_users(users)
        await update.message.reply_text(f"✅ 𝐔𝐬𝐞𝐫 `{user_id}` 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 𝐛𝐚𝐧𝐧𝐞𝐝!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ 𝐔𝐬𝐞𝐫 `{user_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/unban 𝐔𝐒𝐄𝐑_𝐈𝐃`", parse_mode="Markdown")
        return
    
    user_id = context.args[0]
    if user_id in users:
        users[user_id]['banned'] = False
        save_users(users)
        await update.message.reply_text(f"✅ 𝐔𝐬𝐞𝐫 `{user_id}` 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 𝐮𝐧𝐛𝐚𝐧𝐧𝐞𝐝!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ 𝐔𝐬𝐞𝐫 `{user_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ 𝐎𝐧𝐥𝐲 𝐨𝐰𝐧𝐞𝐫 𝐜𝐚𝐧 𝐚𝐝𝐝 𝐚𝐝𝐦𝐢𝐧𝐬!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/addadmin 𝐔𝐒𝐄𝐑_𝐈𝐃`", parse_mode="Markdown")
        return
    
    try:
        new_admin = int(context.args[0])
        if new_admin not in ADMIN_IDS:
            ADMIN_IDS.append(new_admin)
            await update.message.reply_text(f"✅ 𝐔𝐬𝐞𝐫 `{new_admin}` 𝐢𝐬 𝐧𝐨𝐰 𝐚𝐧 𝐚𝐝𝐦𝐢𝐧!", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ 𝐈𝐧𝐯𝐚𝐥𝐢𝐝 𝐔𝐒𝐄𝐑_𝐈𝐃!", parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/status 𝐃𝐄𝐀𝐋_𝐈𝐃`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    status_map = {
        "𝐏𝐄𝐍𝐃𝐈𝐍𝐆": "⏳ 𝐖𝐚𝐢𝐭𝐢𝐧𝐠 𝐟𝐨𝐫 𝐚𝐠𝐫𝐞𝐞𝐦𝐞𝐧𝐭",
        "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓": "💳 𝐖𝐚𝐢𝐭𝐢𝐧𝐠 𝐟𝐨𝐫 𝐩𝐚𝐲𝐦𝐞𝐧𝐭",
        "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃": "✅ 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐜𝐨𝐧𝐟𝐢𝐫𝐦𝐞𝐝",
        "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃": "🎉 𝐃𝐞𝐚𝐥 𝐜𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝",
        "𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃": "❌ 𝐃𝐞𝐚𝐥 𝐜𝐚𝐧𝐜𝐞𝐥𝐥𝐞𝐝"
    }
    
    fancy_amount = to_fancy(str(deal['amount']))
    
    await update.message.reply_text(
        f"📋 𝐃𝐄𝐀𝐋 𝐒𝐓𝐀𝐓𝐔𝐒\n━━━━━━━━━━━━━━━━━━\n"
        f"🔖 𝐈𝐃: `{deal_id}`\n"
        f"📊 𝐒𝐭𝐚𝐭𝐮𝐬: {status_map.get(deal['status'], deal['status'])}\n"
        f"💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{fancy_amount}\n"
        f"👤 𝐁𝐮𝐲𝐞𝐫: @{deal['buyer']}\n"
        f"👥 𝐒𝐞𝐥𝐥𝐞𝐫: @{deal['seller']}",
        parse_mode="Markdown"
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 𝐔𝐬𝐚𝐠𝐞: `/cancel 𝐃𝐄𝐀𝐋_𝐈𝐃`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if user_id not in ADMIN_IDS and user_id != deal.get("buyer_id") and user_id != deal.get("seller_id"):
        await update.message.reply_text("❌ 𝐍𝐨𝐭 𝐚𝐮𝐭𝐡𝐨𝐫𝐢𝐳𝐞𝐝!")
        return
    
    if deal["status"] in ["𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃", "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃"]:
        await update.message.reply_text("❌ 𝐂𝐚𝐧𝐧𝐨𝐭 𝐜𝐚𝐧𝐜𝐞𝐥 𝐧𝐨𝐰!")
        return
    
    deal["status"] = "𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃"
    save_deals(deals)
    
    await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐜𝐚𝐧𝐜𝐞𝐥𝐥𝐞𝐝!", parse_mode="Markdown")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🔷 𝐄𝐒𝐂𝐑𝐎𝐖 𝐁𝐎𝐓 🔷\n\n"
        f"👋 𝐖𝐞𝐥𝐜𝐨𝐦𝐞 𝐭𝐨 𝐄𝐒𝐂𝐑𝐎𝐖 𝐁𝐎𝐓, {user.first_name}!\n\n"
        f"📝 𝐓𝐨 𝐜𝐫𝐞𝐚𝐭𝐞 𝐚 𝐝𝐞𝐚𝐥, 𝐭𝐲𝐩𝐞 𝐢𝐧 𝐚𝐧𝐲 𝐠𝐫𝐨𝐮𝐩:\n\n"
        f"`ESCROW DEAL FORM !!!\n\nDEAL AMOUNT : 1000\nBUYER : @username\nSELLER : @username\nDEAL DETAIL : Product\nRLS UPI : your@upi\nCONDITION : After payment\nESCROW TILL : 2024-12-31`\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬:\n"
        f"• `/status 𝐃𝐄𝐀𝐋_𝐈𝐃` - 𝐂𝐡𝐞𝐜𝐤 𝐝𝐞𝐚𝐥 𝐬𝐭𝐚𝐭𝐮𝐬\n"
        f"• `/cancel 𝐃𝐄𝐀𝐋_𝐈𝐃` - 𝐂𝐚𝐧𝐜𝐞𝐥 𝐝𝐞𝐚𝐥\n"
        f"• `/verify 𝐃𝐄𝐀𝐋_𝐈𝐃` - 𝐕𝐞𝐫𝐢𝐟𝐲 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 (𝐎𝐧𝐥𝐲 𝐚𝐟𝐭𝐞𝐫 𝐩𝐚𝐲𝐢𝐧𝐠)\n"
        f"• `/release 𝐃𝐄𝐀𝐋_𝐈𝐃` - 𝐑𝐞𝐥𝐞𝐚𝐬𝐞 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 (𝐀𝐟𝐭𝐞𝐫 𝐫𝐞𝐜𝐞𝐢𝐯𝐢𝐧𝐠 𝐩𝐫𝐨𝐝𝐮𝐜𝐭)\n\n"
        f"👑 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫: @iflexvenom",
        parse_mode="Markdown"
    )

# ============ MAIN ============
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # User commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("verify", verify_command))
    application.add_handler(CommandHandler("release", release_command))
    application.add_handler(CommandHandler("sendupi", send_upi))
    
    # Admin commands
    application.add_handler(CommandHandler("owner", owner_panel))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(CommandHandler("deals", list_deals))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("complete", complete_deal))
    application.add_handler(CommandHandler("addadmin", add_admin))
    application.add_handler(CommandHandler("confirmpayment", confirm_payment))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sms_handler))
    
    print("=" * 50)
    print("🔷 ESCROW BOT STARTED - FULLY FIXED")
    print(f"👑 Owner: {OWNER_ID}")
    print(f"📋 Admins: {ADMIN_IDS}")
    print("✅ Deal ID - Normal characters (easy copy)")
    print("✅ Everything else - Fancy characters")
    print("✅ Auto payment verify via SMS")
    print("✅ Buyer can /verify ONLY after REAL payment")
    print("=" * 50)
    
    application.run_polling()

if __name__ == "__main__":
    main()

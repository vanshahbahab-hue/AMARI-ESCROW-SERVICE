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

# GLOBAL STORE FOR SMS TRANSACTIONS
sms_transactions = {}

# ============ FANCY TEXT ============
def to_fancy(text):
    fancy_map = {
        'A': '𝐀', 'B': '𝐁', 'C': '𝐂', 'D': '𝐃', 'E': '𝐄', 'F': '𝐅', 'G': '𝐆', 'H': '𝐇', 'I': '𝐈',
        'J': '𝐉', 'K': '𝐊', 'L': '𝐋', 'M': '𝐌', 'N': '𝐍', 'O': '𝐎', 'P': '𝐏', 'Q': '𝐐', 'R': '𝐑',
        'S': '𝐒', 'T': '𝐓', 'U': '𝐔', 'V': '𝐕', 'W': '𝐖', 'X': '𝐗', 'Y': '𝐘', 'Z': '𝐙',
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

deals = load_deals()
users = load_users()

# ============ HELPERS ============
def generate_deal_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def generate_qr(upi_id, amount, deal_id):
    upi_link = f"upi://pay?pa={upi_id}&pn=ESCROW&am={amount}&cu=INR&tn={deal_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(upi_link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

def extract_tx_id_from_sms(text):
    patterns = [r'Txn ID[:\s]*(\d+)', r'Transaction ID[:\s]*(\d+)', r'TX[:\s]*(\d+)', r'ID[:\s]*(\d+)', r'(\d{10,15})']
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def extract_amount_from_sms(text):
    patterns = [r'Rs\.?\s*(\d+\.?\d*)', r'₹\s*(\d+\.?\d*)', r'debited\s*Rs\.?\s*(\d+\.?\d*)']
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None

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

# ============ SMS HANDLER (Stores transaction first) ============
async def sms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SMS aate hi store ho jayega - Ye hai sabse important part"""
    text = update.message.text
    tx_id = extract_tx_id_from_sms(text)
    amount = extract_amount_from_sms(text)
    
    if not tx_id or not amount:
        # Ye error ab sirf SMS forward karne par aayega, form par nahi
        await update.message.reply_text("❌ Could not extract TXN ID or Amount from this message. Make sure it's a payment SMS.")
        return
    
    # Store in global memory
    sms_transactions[tx_id] = {
        "tx_id": tx_id,
        "amount": amount,
        "raw_sms": text[:300],
        "timestamp": str(datetime.now())
    }
    
    await update.message.reply_text(f"✅ 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐒𝐌𝐒 𝐑𝐄𝐂𝐎𝐑𝐃𝐄𝐃!\n🔖 𝐓𝐗𝐍: `{tx_id}`\n💰 ₹{amount}\n\n📌 𝐍𝐨𝐰 𝐲𝐨𝐮 𝐜𝐚𝐧 𝐯𝐞𝐫𝐢𝐟𝐲 𝐭𝐡𝐞 𝐝𝐞𝐚𝐥.", parse_mode="Markdown")
    
    # Auto-verify any pending deal waiting for this amount
    for deal_id, deal in deals.items():
        if deal["status"] == "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓" and not deal.get("payment_received"):
            if abs(amount - deal["amount"]) < 0.01:
                deal["payment_received"] = True
                deal["payment_txid"] = tx_id
                deal["payment_amount"] = amount
                deal["status"] = "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃"
                save_deals(deals)
                
                await context.bot.send_message(
                    chat_id=deal["chat_id"],
                    text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐀𝐔𝐓𝐎-𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐯𝐞𝐫𝐢𝐟𝐢𝐞𝐝!",
                    parse_mode="Markdown"
                )
                
                if deal.get("buyer_id"):
                    await context.bot.send_message(
                        chat_id=deal["buyer_id"],
                        text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n📦 `/release {deal_id}`",
                        parse_mode="Markdown"
                    )
                
                if deal.get("seller_id"):
                    await context.bot.send_message(
                        chat_id=deal["seller_id"],
                        text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n🎁 𝐏𝐥𝐞𝐚𝐬𝐞 𝐝𝐞𝐥𝐢𝐯𝐞𝐫.",
                        parse_mode="Markdown"
                    )
                
                await update.message.reply_text(f"✅ Auto-verified deal `{deal_id}`!", parse_mode="Markdown")
                break

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
            text=f"🆕 𝐍𝐄𝐖 𝐔𝐒𝐄𝐑!\n👤 {user.first_name}\n🆔 {user_id}\n📛 @{user.username or 'NoUsername'}"
        )
    
    if is_banned(user_id):
        await update.message.reply_text("❌ 𝐘𝐨𝐮 𝐚𝐫𝐞 𝐛𝐚𝐧𝐧𝐞𝐝.")
        return
    
    # ============ ESCROW FORM DETECTION ============
    if re.search(r'ESCROW\s*DEAL\s*FORM', message_text, re.IGNORECASE):
        amount_match = re.search(r'DEAL\s*AMOUNT\s*:?\s*[-\s]*(\d+)', message_text, re.IGNORECASE)
        buyer_match = re.search(r'BUYERS?\s*:?\s*[-\s]*@?(\w+)', message_text, re.IGNORECASE)
        seller_match = re.search(r'SELLER\s*:?\s*[-\s]*@?(\w+)', message_text, re.IGNORECASE)
        deal_detail_match = re.search(r'DEAL\s*DETAIL\s*:?\s*[-\s]*(.+)', message_text, re.IGNORECASE)
        upi_match = re.search(r'RLS\s*UPI\s*:?\s*[-\s]*(\S+@\S+)', message_text, re.IGNORECASE)
        
        if not amount_match:
            await update.message.reply_text("❌ 𝐌𝐢𝐬𝐬𝐢𝐧𝐠 𝐀𝐌𝐎𝐔𝐍𝐓!")
            return
        
        amount = int(amount_match.group(1))
        buyer = buyer_match.group(1) if buyer_match else None
        seller = seller_match.group(1) if seller_match else None
        deal_detail = deal_detail_match.group(1) if deal_detail_match else "𝐍/𝐀"
        upi_id = upi_match.group(1) if upi_match else "venomxpay@naviaxis"
        
        if not buyer or not seller:
            await update.message.reply_text("❌ 𝐍𝐞𝐞𝐝 𝐁𝐔𝐘𝐄𝐑 & 𝐒𝐄𝐋𝐋𝐄𝐑!")
            return
        
        deal_id = generate_deal_id()
        
        deals[deal_id] = {
            "deal_id": deal_id, "amount": amount,
            "buyer": buyer, "seller": seller, "deal_detail": deal_detail,
            "upi_id": upi_id, "buyer_agreed": False, "seller_agreed": False,
            "status": "𝐏𝐄𝐍𝐃𝐈𝐍𝐆", "chat_id": chat_id,
            "created_at": str(datetime.now()), "buyer_id": None, "seller_id": None,
            "payment_received": False, "payment_txid": None, "payment_amount": None,
            "seller_upi": None, "release_requested": False
        }
        save_deals(deals)
        
        await update.message.reply_text(f"""
🔷 𝐄𝐒𝐂𝐑𝐎𝐖 𝐃𝐄𝐀𝐋 𝐂𝐑𝐄𝐀𝐓𝐄𝐃 🔷

📋 𝐃𝐄𝐀𝐋 𝐈𝐃: `{deal_id}`
💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{amount}

👤 𝐁𝐮𝐲𝐞𝐫: @{buyer}
👥 𝐒𝐞𝐥𝐥𝐞𝐫: @{seller}
📝 {deal_detail}
💳 {upi_id}

✅ @{buyer} - 𝐓𝐲𝐩𝐞 `𝐀𝐆𝐑𝐄𝐄`
✅ @{seller} - 𝐓𝐲𝐩𝐞 `𝐀𝐆𝐑𝐄𝐄`

🕐 𝟏𝟎 𝐦𝐢𝐧𝐮𝐭𝐞𝐬!
""", parse_mode="Markdown")
        
        await context.bot.send_message(chat_id=OWNER_ID, text=f"🆕 𝐍𝐄𝐖 𝐃𝐄𝐀𝐋!\n📋 {deal_id}\n💰 ₹{amount}\n@{buyer} → @{seller}")
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
                await update.message.reply_text(f"✅ @{user.username}, 𝐚𝐠𝐫𝐞𝐞𝐝 𝐚𝐬 𝐁𝐔𝐘𝐄𝐑 𝐟𝐨𝐫 `{deal_id}`!")
                if deal["seller_agreed"]:
                    await process_both_agreed(context, deal_id, deal)
                return
            
            elif deal["seller"].lower() == username:
                deal["seller_agreed"] = True
                deal["seller_id"] = user.id
                save_deals(deals)
                await update.message.reply_text(f"✅ @{user.username}, 𝐚𝐠𝐫𝐞𝐞𝐝 𝐚𝐬 𝐒𝐄𝐋𝐋𝐄𝐑 𝐟𝐨𝐫 `{deal_id}`!")
                if deal["buyer_agreed"]:
                    await process_both_agreed(context, deal_id, deal)
                return
        
        await update.message.reply_text("❌ 𝐍𝐨 𝐩𝐞𝐧𝐝𝐢𝐧𝐠 𝐝𝐞𝐚𝐥.")
        return

async def process_both_agreed(context, deal_id, deal):
    deal["status"] = "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓"
    save_deals(deals)
    
    img_bytes = generate_qr(deal["upi_id"], deal["amount"], deal_id)
    photo = InputFile(img_bytes, filename="qr.png")
    
    if deal.get("buyer_id"):
        await context.bot.send_photo(
            chat_id=deal["buyer_id"],
            photo=photo,
            caption=f"🔷 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐐𝐑 🔷\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n📝 `/verify {deal_id} 𝐘𝐎𝐔𝐑_𝐓𝐗𝐍_𝐈𝐃`\n\n❌ 𝐃𝐎𝐍'𝐓 𝐏𝐀𝐘 𝐈𝐍 𝐃𝐌𝐒",
            parse_mode="Markdown"
        )
    
    await context.bot.send_message(
        chat_id=deal["chat_id"],
        text=f"✅ 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄𝐃!\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n👤 𝐁𝐮𝐲𝐞𝐫 𝐠𝐨𝐭 𝐐𝐑.",
        parse_mode="Markdown"
    )

# ============ VERIFY COMMAND (Checks SMS transactions) ============
async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buyer: /verify DEAL_ID TRANSACTION_ID"""
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "📝 `/verify 𝐃𝐄𝐀𝐋_𝐈𝐃 𝐓𝐑𝐀𝐍𝐒𝐀𝐂𝐓𝐈𝐎𝐍_𝐈𝐃`\n\n𝐄𝐱𝐚𝐦𝐩𝐥𝐞: `/verify ONP9G2US 616397012871`",
            parse_mode="Markdown"
        )
        return
    
    deal_id = context.args[0].upper()
    tx_id = context.args[1]
    
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if user_id != deal.get("buyer_id"):
        await update.message.reply_text("❌ 𝐎𝐧𝐥𝐲 𝐛𝐮𝐲𝐞𝐫!", parse_mode="Markdown")
        return
    
    if deal["status"] != "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓":
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐚𝐰𝐚𝐢𝐭𝐢𝐧𝐠!", parse_mode="Markdown")
        return
    
    if deal.get("payment_received"):
        await update.message.reply_text(f"✅ 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐚𝐥𝐫𝐞𝐚𝐝𝐲 𝐯𝐞𝐫𝐢𝐟𝐢𝐞𝐝!", parse_mode="Markdown")
        return
    
    # Check if SMS transaction exists in global store
    if tx_id in sms_transactions:
        txn_data = sms_transactions[tx_id]
        amount = txn_data.get('amount')
        
        if amount and abs(amount - deal["amount"]) < 0.01:
            deal["payment_received"] = True
            deal["payment_txid"] = tx_id
            deal["payment_amount"] = amount
            deal["status"] = "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃"
            save_deals(deals)
            
            await update.message.reply_text(
                f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃! ✅\n\n"
                f"📋 `{deal_id}`\n💰 ₹{deal['amount']}\n🔖 `{tx_id}`\n\n🎉 𝐂𝐎𝐍𝐓𝐈𝐍𝐔𝐄!\n\n📦 `/release {deal_id}`",
                parse_mode="Markdown"
            )
            
            await context.bot.send_message(
                chat_id=deal["chat_id"],
                text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n👤 @{deal['buyer']}",
                parse_mode="Markdown"
            )
            
            if deal.get("seller_id"):
                await context.bot.send_message(
                    chat_id=deal["seller_id"],
                    text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n🎁 𝐏𝐥𝐞𝐚𝐬𝐞 𝐝𝐞𝐥𝐢𝐯𝐞𝐫.",
                    parse_mode="Markdown"
                )
            
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"💰 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃!\n📋 {deal_id}\n💰 ₹{deal['amount']}\n🔖 {tx_id}"
            )
        else:
            await update.message.reply_text(
                f"❌ 𝐀𝐦𝐨𝐮𝐧𝐭 𝐦𝐢𝐬𝐦𝐚𝐭𝐜𝐡!\n\n𝐄𝐱𝐩𝐞𝐜𝐭𝐞𝐝: ₹{deal['amount']}\n𝐑𝐞𝐜𝐞𝐢𝐯𝐞𝐝: ₹{amount}",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            f"❌ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐍𝐎𝐓 𝐑𝐄𝐂𝐄𝐈𝐕𝐄𝐃! ❌\n\n"
            f"📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n"
            f"⚠️ 𝐓𝐗𝐍 `{tx_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝 𝐢𝐧 𝐨𝐮𝐫 𝐫𝐞𝐜𝐨𝐫𝐝𝐬.\n\n"
            f"📱 𝐏𝐥𝐞𝐚𝐬𝐞 𝐦𝐚𝐤𝐞 𝐭𝐡𝐞 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 𝐟𝐢𝐫𝐬𝐭.\n"
            f"🔖 𝐓𝐡𝐞 𝐭𝐫𝐚𝐧𝐬𝐚𝐜𝐭𝐢𝐨𝐧 𝐈𝐃 𝐰𝐢𝐥𝐥 𝐛𝐞 𝐚𝐮𝐭𝐨-𝐝𝐞𝐭𝐞𝐜𝐭𝐞𝐝 𝐰𝐡𝐞𝐧 𝐭𝐡𝐞 𝐩𝐚𝐲𝐦𝐞𝐧𝐭 𝐒𝐌𝐒 𝐢𝐬 𝐫𝐞𝐜𝐞𝐢𝐯𝐞𝐝.\n\n"
            f"❌ 𝐃𝐎 𝐍𝐎𝐓 𝐅𝐀𝐊𝐄 𝐕𝐄𝐑𝐈𝐅𝐘!",
            parse_mode="Markdown"
        )

# ============ OTHER COMMANDS ============
async def release_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/release 𝐃𝐄𝐀𝐋_𝐈𝐃`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if user_id != deal.get("buyer_id"):
        await update.message.reply_text("❌ 𝐎𝐧𝐥𝐲 𝐛𝐮𝐲𝐞𝐫!", parse_mode="Markdown")
        return
    
    if deal["status"] != "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃":
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐫𝐞𝐚𝐝𝐲!", parse_mode="Markdown")
        return
    
    if deal.get("release_requested"):
        await update.message.reply_text("❌ Already requested!", parse_mode="Markdown")
        return
    
    deal["release_requested"] = True
    save_deals(deals)
    
    await update.message.reply_text(f"✅ 𝐑𝐞𝐥𝐞𝐚𝐬𝐞 𝐫𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝!\n👥 @{deal['seller']} - 𝐒𝐞𝐧𝐝 𝐔𝐏𝐈:", parse_mode="Markdown")
    
    if deal.get("seller_id"):
        await context.bot.send_message(
            chat_id=deal["seller_id"],
            text=f"🔷 𝐑𝐄𝐋𝐄𝐀𝐒𝐄 𝐑𝐄𝐐𝐔𝐄𝐒𝐓!\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n📝 `/sendupi {deal_id} 𝐘𝐎𝐔𝐑_𝐔𝐏𝐈`",
            parse_mode="Markdown"
        )

async def send_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text("📝 `/sendupi 𝐃𝐄𝐀𝐋_𝐈𝐃 𝐔𝐏𝐈_𝐈𝐃`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    upi_id = context.args[1]
    
    if not re.match(r'^[\w\.\-]+@[\w\.\-]+$', upi_id):
        await update.message.reply_text("❌ 𝐈𝐧𝐯𝐚𝐥𝐢𝐝 𝐔𝐏𝐈! 𝐧𝐚𝐦𝐞@𝐛𝐚𝐧𝐤", parse_mode="Markdown")
        return
    
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if user_id != deal.get("seller_id"):
        await update.message.reply_text(f"❌ 𝐎𝐧𝐥𝐲 @{deal['seller']}!", parse_mode="Markdown")
        return
    
    if not deal.get("release_requested"):
        await update.message.reply_text("❌ 𝐍𝐨 𝐫𝐞𝐥𝐞𝐚𝐬𝐞!", parse_mode="Markdown")
        return
    
    if deal.get("seller_upi"):
        await update.message.reply_text("❌ 𝐔𝐏𝐈 𝐚𝐥𝐫𝐞𝐚𝐝𝐲!", parse_mode="Markdown")
        return
    
    deal["seller_upi"] = upi_id
    save_deals(deals)
    
    await update.message.reply_text(f"✅ 𝐔𝐏𝐈 𝐫𝐞𝐜𝐞𝐢𝐯𝐞𝐝!\n💳 `{upi_id}`\n\n💰 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐢𝐧 𝟏𝟎-𝟐𝟎 𝐦𝐢𝐧.", parse_mode="Markdown")
    
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"💰 𝐑𝐄𝐋𝐄𝐀𝐒𝐄!\n📋 {deal_id}\n💰 ₹{deal['amount']}\n💳 {upi_id}\n\n✅ `/complete {deal_id}`"
    )

async def complete_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ 𝐎𝐰𝐧𝐞𝐫 𝐨𝐧𝐥𝐲!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/complete 𝐃𝐄𝐀𝐋_𝐈𝐃`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    if deal["status"] != "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃":
        await update.message.reply_text(f"❌ 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐧𝐨𝐭 𝐜𝐨𝐧𝐟𝐢𝐫𝐦𝐞𝐝!", parse_mode="Markdown")
        return
    
    if not deal.get("release_requested"):
        await update.message.reply_text("❌ 𝐍𝐨 𝐫𝐞𝐥𝐞𝐚𝐬𝐞!", parse_mode="Markdown")
        return
    
    if not deal.get("seller_upi"):
        await update.message.reply_text("❌ 𝐍𝐨 𝐔𝐏𝐈!", parse_mode="Markdown")
        return
    
    deal["status"] = "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"
    save_deals(deals)
    
    await context.bot.send_message(
        chat_id=deal["chat_id"],
        text=f"✅ 𝐃𝐄𝐀𝐋 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃! ✅\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n👤 @{deal['buyer']} ↔ @{deal['seller']}\n\n🎉 𝐃𝐨𝐧𝐞!",
        parse_mode="Markdown"
    )
    
    if deal.get("seller_id"):
        await context.bot.send_message(
            chat_id=deal["seller_id"],
            text=f"✅ 𝐃𝐄𝐀𝐋 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n💳 {deal['seller_upi']}",
            parse_mode="Markdown"
        )
    
    await update.message.reply_text(f"✅ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐜𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝!", parse_mode="Markdown")

# ============ OWNER PANEL ============
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ 𝐎𝐰𝐧𝐞𝐫 𝐨𝐧𝐥𝐲!")
        return
    
    total_users = len(users)
    active_deals = len([d for d in deals.values() if d["status"] not in ["𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃", "𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃"]])
    completed_deals = len([d for d in deals.values() if d["status"] == "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"])
    total_volume = sum([d["amount"] for d in deals.values() if d["status"] == "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"])
    
    await update.message.reply_text(
        f"👑 𝐎𝐖𝐍𝐄𝐑 𝐏𝐀𝐍𝐄𝐋 👑\n\n"
        f"👥 𝐔𝐬𝐞𝐫𝐬: {total_users}\n"
        f"📋 𝐀𝐜𝐭𝐢𝐯𝐞: {active_deals}\n"
        f"✅ 𝐂𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝: {completed_deals}\n"
        f"💰 𝐕𝐨𝐥𝐮𝐦𝐞: ₹{total_volume}\n\n"
        f"📋 `/users`\n📋 `/deals`\n🚫 `/ban`\n✅ `/unban`\n💰 `/complete`",
        parse_mode="Markdown"
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if not users:
        await update.message.reply_text("📭 𝐍𝐨 𝐮𝐬𝐞𝐫𝐬.")
        return
    
    msg = "👥 𝐔𝐒𝐄𝐑𝐒 👥\n━━━━━━━━━━━━━━━━━━\n"
    for uid, u in users.items():
        status = "🚫 𝐁𝐀𝐍𝐍𝐄𝐃" if u.get('banned') else "✅ 𝐀𝐂𝐓𝐈𝐕𝐄"
        msg += f"🆔 `{uid}`\n📛 @{u.get('username', '𝐍𝐨𝐧𝐞')}\n📌 {status}\n━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if not deals:
        await update.message.reply_text("📭 𝐍𝐨 𝐝𝐞𝐚𝐥𝐬.")
        return
    
    msg = "📋 𝐃𝐄𝐀𝐋𝐒 📋\n━━━━━━━━━━━━━━━━━━\n"
    for deal_id, deal in list(deals.items())[-10:]:
        msg += f"🔖 `{deal_id}`\n💰 ₹{deal['amount']}\n📌 {deal['status']}\n👤 @{deal['buyer']} → @{deal['seller']}\n━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/ban 𝐔𝐒𝐄𝐑_𝐈𝐃`", parse_mode="Markdown")
        return
    
    user_id = context.args[0]
    if user_id in users:
        users[user_id]['banned'] = True
        save_users(users)
        await update.message.reply_text(f"✅ 𝐔𝐬𝐞𝐫 `{user_id}` 𝐛𝐚𝐧𝐧𝐞𝐝!", parse_mode="Markdown")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ 𝐀𝐝𝐦𝐢𝐧 𝐨𝐧𝐥𝐲!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/unban 𝐔𝐒𝐄𝐑_𝐈𝐃`", parse_mode="Markdown")
        return
    
    user_id = context.args[0]
    if user_id in users:
        users[user_id]['banned'] = False
        save_users(users)
        await update.message.reply_text(f"✅ 𝐔𝐬𝐞𝐫 `{user_id}` 𝐮𝐧𝐛𝐚𝐧𝐧𝐞𝐝!", parse_mode="Markdown")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ 𝐎𝐰𝐧𝐞𝐫 𝐨𝐧𝐥𝐲!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/addadmin 𝐔𝐒𝐄𝐑_𝐈𝐃`", parse_mode="Markdown")
        return
    
    try:
        new_admin = int(context.args[0])
        if new_admin not in ADMIN_IDS:
            ADMIN_IDS.append(new_admin)
            await update.message.reply_text(f"✅ `{new_admin}` 𝐢𝐬 𝐧𝐨𝐰 𝐚𝐝𝐦𝐢𝐧!", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ 𝐈𝐧𝐯𝐚𝐥𝐢𝐝 𝐈𝐃!")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/status 𝐃𝐄𝐀𝐋_𝐈𝐃`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ 𝐃𝐞𝐚𝐥 `{deal_id}` 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝!", parse_mode="Markdown")
        return
    
    status_map = {
        "𝐏𝐄𝐍𝐃𝐈𝐍𝐆": "⏳ 𝐖𝐚𝐢𝐭𝐢𝐧𝐠",
        "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓": "💳 𝐖𝐚𝐢𝐭𝐢𝐧𝐠",
        "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃": "✅ 𝐂𝐨𝐧𝐟𝐢𝐫𝐦𝐞𝐝",
        "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃": "🎉 𝐂𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝",
        "𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃": "❌ 𝐂𝐚𝐧𝐜𝐞𝐥𝐥𝐞𝐝"
    }
    
    await update.message.reply_text(
        f"📋 𝐃𝐄𝐀𝐋 𝐒𝐓𝐀𝐓𝐔𝐒\n━━━━━━━━━━━━━━━━━━\n"
        f"🔖 `{deal_id}`\n"
        f"📊 {status_map.get(deal['status'], deal['status'])}\n"
        f"💰 ₹{deal['amount']}\n"
        f"👤 @{deal['buyer']} → @{deal['seller']}",
        parse_mode="Markdown"
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/cancel 𝐃𝐄𝐀𝐋_𝐈𝐃`", parse_mode="Markdown")
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
        f"👋 𝐖𝐞𝐥𝐜𝐨𝐦𝐞, {user.first_name}!\n\n"
        f"📝 𝐂𝐫𝐞𝐚𝐭𝐞 𝐝𝐞𝐚𝐥 𝐢𝐧 𝐠𝐫𝐨𝐮𝐩:\n\n"
        f"`ESCROW DEAL FORM !!!\n\nDEAL AMOUNT : 1000\nBUYER : @buyer\nSELLER : @seller\nDEAL DETAIL : Product\nRLS UPI : your@upi`\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬:\n"
        f"• `/status 𝐈𝐃`\n"
        f"• `/cancel 𝐈𝐃`\n"
        f"• `/verify 𝐈𝐃 𝐓𝐗𝐍`\n"
        f"• `/release 𝐈𝐃`\n\n"
        f"👑 @iflexvenom",
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
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sms_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("=" * 50)
    print("🔷 ESCROW BOT STARTED - SMS FIRST THEN VERIFY")
    print(f"👑 Owner: {OWNER_ID}")
    print("=" * 50)
    
    application.run_polling()

if __name__ == "__main__":
    main()

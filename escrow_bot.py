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
    flask_app.run(host='0.0.0.0', port=port, debug=False)

# ============ CONFIG ============
BOT_TOKEN = "8679581798:AAGZtycapDdwpwYR8ro5M4xZNFiIR4QuetI"
OWNER_ID = 8586849798
ADMIN_IDS = [OWNER_ID]

DEALS_FILE = "deals.json"
USERS_FILE = "users.json"

# GLOBAL STORE FOR SMS TRANSACTIONS
sms_transactions = {}

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
    patterns = [
        r'Txn[:\s]*[Ii][Dd][:\s]*(\d+)',
        r'Transaction[:\s]*[Ii][Dd][:\s]*(\d+)',
        r'TX[:\s]*(\d+)',
        r'[Ii][Dd][:\s]*(\d{10,})',
        r'ref[:\s]*([A-Za-z0-9]{10,})',
        r'reference[:\s]*([A-Za-z0-9]{10,})',
        r'(\d{12,16})'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def extract_amount_from_sms(text):
    patterns = [
        r'Rs\.?\s*(\d+\.?\d*)',
        r'₹\s*(\d+\.?\d*)',
        r'debited\s*Rs\.?\s*(\d+\.?\d*)',
        r'credited\s*Rs\.?\s*(\d+\.?\d*)',
        r'(\d+\.?\d*)\s*credited',
        r'(\d+\.?\d*)\s*debited',
        r'amt[:\s]*(\d+\.?\d*)',
        r'amount[:\s]*(\d+\.?\d*)'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None

def register_user(user_id, username, first_name):
    if str(user_id) not in users:
        users[str(user_id)] = {
            "id": user_id,
            "username": username or "NoUsername",
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

# ============ SMS HANDLER - Auto detects payment SMS ============
async def sms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    This handles SMS that are auto-forwarded to the bot.
    It extracts TXN ID and amount, then auto-verifies matching deals.
    """
    user_id = update.effective_user.id
    text = update.message.text
    
    # Only process if it looks like a payment SMS
    has_amount = extract_amount_from_sms(text) is not None
    has_tx_id = extract_tx_id_from_sms(text) is not None
    
    if not has_amount and not has_tx_id:
        # This doesn't look like a payment SMS, ignore
        return
    
    tx_id = extract_tx_id_from_sms(text)
    amount = extract_amount_from_sms(text)
    
    if not tx_id or not amount:
        return
    
    # Store the transaction
    sms_transactions[tx_id] = {
        "tx_id": tx_id,
        "amount": amount,
        "raw_sms": text[:500],
        "timestamp": str(datetime.now()),
        "verified": False,
        "from_user": user_id
    }
    
    # Log to owner
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"📱 𝐏𝐚𝐲𝐦𝐞𝐧𝐭 𝐒𝐌𝐒 𝐃𝐞𝐭𝐞𝐜𝐭𝐞𝐝!\n🔖 TXN: `{tx_id}`\n💰 Amount: ₹{amount}\n\n🔍 Checking for matching deals...",
        parse_mode="Markdown"
    )
    
    # ============ AUTO-VERIFY: Check all pending deals ============
    auto_verified = False
    for deal_id, deal in deals.items():
        if deal["status"] == "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓" and not deal.get("payment_received"):
            # Check if amount matches (within 0.01 tolerance for decimal amounts like 11.02)
            if abs(amount - deal["amount"]) < 0.01:
                # Amount matches! Auto-verify this deal
                deal["payment_received"] = True
                deal["payment_txid"] = tx_id
                deal["payment_amount"] = amount
                deal["status"] = "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃"
                sms_transactions[tx_id]["verified"] = True
                sms_transactions[tx_id]["deal_id"] = deal_id
                save_deals(deals)
                
                # Notify the GROUP
                await context.bot.send_message(
                    chat_id=deal["chat_id"],
                    text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐀𝐔𝐓𝐎-𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃! ✅\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n🔖 TXN: `{tx_id}`\n\n🎉 Payment detected and auto-verified!\n👤 @{deal['buyer']} - Type `/release {deal_id}` after receiving item.",
                    parse_mode="Markdown"
                )
                
                # Notify BUYER privately
                if deal.get("buyer_id"):
                    await context.bot.send_message(
                        chat_id=deal["buyer_id"],
                        text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐀𝐔𝐓𝐎-𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃! ✅\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n🔖 TXN: `{tx_id}`\n\n📦 After receiving item from @{deal['seller']}, type:\n`/release {deal_id}`",
                        parse_mode="Markdown"
                    )
                
                # Notify SELLER privately
                if deal.get("seller_id"):
                    await context.bot.send_message(
                        chat_id=deal["seller_id"],
                        text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃! ✅\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']}\n\n🎁 Payment confirmed! Please deliver the item to @{deal['buyer']}.",
                        parse_mode="Markdown"
                    )
                
                auto_verified = True
                await context.bot.send_message(
                    chat_id=OWNER_ID,
                    text=f"✅ 𝐀𝐔𝐓𝐎-𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃!\n📋 {deal_id}\n💰 ₹{deal['amount']}\n🔖 {tx_id}\n👤 @{deal['buyer']} → @{deal['seller']}",
                    parse_mode="Markdown"
                )
                break
    
    if not auto_verified:
        # Check if amount matches any pending deal (maybe amount slightly off)
        partial_match = False
        for deal_id, deal in deals.items():
            if deal["status"] == "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓" and not deal.get("payment_received"):
                if abs(amount - deal["amount"]) < 100:
                    partial_match = True
                    await context.bot.send_message(
                        chat_id=OWNER_ID,
                        text=f"⚠️ 𝐏𝐚𝐫𝐭𝐢𝐚𝐥 𝐌𝐚𝐭𝐜𝐡!\n📋 {deal_id}\n💰 Expected: ₹{deal['amount']}\n💰 Received SMS: ₹{amount}\n🔖 TXN: {tx_id}\n\nAmount mismatch! Deal requires ₹{deal['amount']} but SMS shows ₹{amount}.",
                        parse_mode="Markdown"
                    )
                    break
        
        if not partial_match:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"📦 𝐒𝐌𝐒 𝐒𝐭𝐨𝐫𝐞𝐝 (No matching deal)\n🔖 TXN: `{tx_id}`\n💰 Amount: ₹{amount}\n\nBuyer can verify manually with:\n`/verify DEAL_ID {tx_id}`",
                parse_mode="Markdown"
            )

# ============ MAIN MESSAGE HANDLER ============
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username.lower() if user.username else ""
    text_lower = message_text.lower().strip()
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
        amount_match = re.search(r'DEAL\s*AMOUNT\s*:?\s*[-\s]*(\d+\.?\d*)', message_text, re.IGNORECASE)
        buyer_match = re.search(r'BUYERS?\s*:?\s*[-\s]*@?(\w+)', message_text, re.IGNORECASE)
        seller_match = re.search(r'SELLER\s*:?\s*[-\s]*@?(\w+)', message_text, re.IGNORECASE)
        deal_detail_match = re.search(r'DEAL\s*DETAIL\s*:?\s*[-\s]*(.+)', message_text, re.IGNORECASE)
        upi_match = re.search(r'RLS\s*UPI\s*:?\s*[-\s]*(\S+@\S+)', message_text, re.IGNORECASE)
        
        if not amount_match:
            await update.message.reply_text("❌ 𝐌𝐢𝐬𝐬𝐢𝐧𝐠 𝐀𝐌𝐎𝐔𝐍𝐓! Use: DEAL AMOUNT : 1000")
            return
        
        amount = float(amount_match.group(1))
        buyer = buyer_match.group(1) if buyer_match else None
        seller = seller_match.group(1) if seller_match else None
        deal_detail = deal_detail_match.group(1) if deal_detail_match else "𝐍/𝐀"
        upi_id = upi_match.group(1) if upi_match else "venomxpay@naviaxis"
        
        if not buyer or not seller:
            await update.message.reply_text("❌ 𝐍𝐞𝐞𝐝 𝐁𝐔𝐘𝐄𝐑 & 𝐒𝐄𝐋𝐋𝐄𝐑!")
            return
        
        deal_id = generate_deal_id()
        
        deals[deal_id] = {
            "deal_id": deal_id, 
            "amount": amount,
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
        
        await update.message.reply_text(f"""
🔷 𝐄𝐒𝐂𝐑𝐎𝐖 𝐃𝐄𝐀𝐋 𝐂𝐑𝐄𝐀𝐓𝐄𝐃 🔷

📋 𝐃𝐄𝐀𝐋 𝐈𝐃: `{deal_id}`
💰 𝐀𝐦𝐨𝐮𝐧𝐭: ₹{amount:.2f}

👤 𝐁𝐮𝐲𝐞𝐫: @{buyer}
👥 𝐒𝐞𝐥𝐥𝐞𝐫: @{seller}
📝 {deal_detail}
💳 {upi_id}

✅ @{buyer} - Type "agree" to accept
✅ @{seller} - Type "agree" to accept

🕐 10 minutes timeout!
""", parse_mode="Markdown")
        
        await context.bot.send_message(
            chat_id=OWNER_ID, 
            text=f"🆕 𝐍𝐄𝐖 𝐃𝐄𝐀𝐋!\n📋 {deal_id}\n💰 ₹{amount:.2f}\n@{buyer} → @{seller}"
        )
        return
    
    # ============ AGREE DETECTION - FIXED FOR ALL USERS ============
    agree_words = ['agree', 'agre', 'argee', 'agr']
    clean_text = text_lower.strip()
    
    # Check if message is exactly an agree word
    is_agree = clean_text in agree_words or clean_text in ['yes', 'done', 'ok', 'y']
    
    if is_agree:
        agreed_to_deal = False
        
        # Loop through ALL pending deals
        for deal_id, deal in deals.items():
            if deal["status"] != "𝐏𝐄𝐍𝐃𝐈𝐍𝐆":
                continue
            
            buyer_username = deal["buyer"].lower()
            seller_username = deal["seller"].lower()
            
            # Check if this user is the BUYER
            if username == buyer_username:
                if deal["buyer_agreed"]:
                    await update.message.reply_text(f"✅ @{user.username}, you already agreed as BUYER for `{deal_id}`!", parse_mode="Markdown")
                    return
                
                deal["buyer_agreed"] = True
                deal["buyer_id"] = user.id
                save_deals(deals)
                await update.message.reply_text(
                    f"✅ @{user.username}, you agreed as BUYER for `{deal_id}`!",
                    parse_mode="Markdown"
                )
                agreed_to_deal = True
                
                if deal["seller_agreed"]:
                    await process_both_agreed(context, deal_id, deal)
                else:
                    # Tell them to wait for seller
                    await update.message.reply_text(f"⏳ Waiting for @{deal['seller']} to agree...", parse_mode="Markdown")
                return
            
            # Check if this user is the SELLER
            elif username == seller_username:
                if deal["seller_agreed"]:
                    await update.message.reply_text(f"✅ @{user.username}, you already agreed as SELLER for `{deal_id}`!", parse_mode="Markdown")
                    return
                
                deal["seller_agreed"] = True
                deal["seller_id"] = user.id
                save_deals(deals)
                await update.message.reply_text(
                    f"✅ @{user.username}, you agreed as SELLER for `{deal_id}`!",
                    parse_mode="Markdown"
                )
                agreed_to_deal = True
                
                if deal["buyer_agreed"]:
                    await process_both_agreed(context, deal_id, deal)
                else:
                    await update.message.reply_text(f"⏳ Waiting for @{deal['buyer']} to agree...", parse_mode="Markdown")
                return
        
        if not agreed_to_deal:
            await update.message.reply_text(
                "❌ No pending deal found for you.\n\n"
                "Make sure:\n"
                "1️⃣ A deal was created with your username\n"
                "2️⃣ You're typing in the same group where the deal was created\n"
                "3️⃣ Your Telegram username (@username) matches the deal",
                parse_mode="Markdown"
            )
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
            caption=f"🔷 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐐𝐑 🔷\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n💳 {deal['upi_id']}\n\n📌 After payment:\nThe payment SMS will be auto-detected!\n\nIf auto-verify doesn't work:\n`/verify {deal_id} YOUR_TXN_ID`\n\n❌ DON'T PAY IN DMS!",
            parse_mode="Markdown"
        )
    
    await context.bot.send_message(
        chat_id=deal["chat_id"],
        text=f"✅ 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄𝐃!\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n\n👤 @{deal['buyer']} ← → @{deal['seller']}\n💳 QR sent to buyer.\n\n📌 Payment SMS will be auto-verified when received!\n📱 @{deal['buyer']} - Please make the payment using the QR code.",
        parse_mode="Markdown"
    )

# ============ VERIFY COMMAND - Manual verify by buyer ============
async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buyer: /verify DEAL_ID TRANSACTION_ID"""
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "📝 `/verify DEAL_ID TXN_ID`\n\n"
            "Example: `/verify ONP9G2US 616397012871`\n\n"
            "📌 Make payment first, then check your SMS for the transaction ID.",
            parse_mode="Markdown"
        )
        return
    
    deal_id = context.args[0].upper()
    tx_id = context.args[1]
    
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ Deal `{deal_id}` not found!", parse_mode="Markdown")
        return
    
    if user_id != deal.get("buyer_id"):
        await update.message.reply_text("❌ Only the buyer can verify payment!", parse_mode="Markdown")
        return
    
    if deal["status"] != "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓":
        await update.message.reply_text(f"❌ Deal `{deal_id}` is not awaiting payment! Current status: {deal['status']}", parse_mode="Markdown")
        return
    
    if deal.get("payment_received"):
        await update.message.reply_text(f"✅ Payment already verified for `{deal_id}`!", parse_mode="Markdown")
        return
    
    # ============ CHECK IF SMS EXISTS IN OWNER'S BOT ============
    if tx_id in sms_transactions:
        txn_data = sms_transactions[tx_id]
        sms_amount = txn_data.get('amount')
        
        if sms_amount and abs(sms_amount - deal["amount"]) < 0.01:
            # ✅ AMOUNT MATCHES - VERIFY!
            deal["payment_received"] = True
            deal["payment_txid"] = tx_id
            deal["payment_amount"] = sms_amount
            deal["status"] = "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃"
            sms_transactions[tx_id]["verified"] = True
            sms_transactions[tx_id]["deal_id"] = deal_id
            save_deals(deals)
            
            # Confirm to buyer
            await update.message.reply_text(
                f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃! ✅\n\n"
                f"📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n🔖 `{tx_id}`\n\n"
                f"📦 After receiving item from @{deal['seller']}, type:\n`/release {deal_id}`",
                parse_mode="Markdown"
            )
            
            # Notify GROUP
            await context.bot.send_message(
                chat_id=deal["chat_id"],
                text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n👤 @{deal['buyer']} confirmed payment.\n🔖 TXN: `{tx_id}`",
                parse_mode="Markdown"
            )
            
            # Notify SELLER
            if deal.get("seller_id"):
                await context.bot.send_message(
                    chat_id=deal["seller_id"],
                    text=f"✅ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n\n🎁 Payment confirmed by buyer! Please deliver item to @{deal['buyer']}.",
                    parse_mode="Markdown"
                )
            
            # Notify OWNER
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"💰 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐕𝐄𝐑𝐈𝐅𝐈𝐄𝐃 𝐁𝐘 𝐁𝐔𝐘𝐄𝐑!\n📋 {deal_id}\n💰 ₹{deal['amount']:.2f}\n🔖 {tx_id}\n✅ SMS stored in bot - MATCHED!",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ 𝐀𝐦𝐨𝐮𝐧𝐭 𝐦𝐢𝐬𝐦𝐚𝐭𝐜𝐡!\n\n"
                f"Expected: ₹{deal['amount']:.2f}\n"
                f"Received in SMS: ₹{sms_amount}\n\n"
                f"Please check and try again with correct TXN ID.",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            f"❌ 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐍𝐎𝐓 𝐅𝐎𝐔𝐍𝐃 𝐈𝐍 𝐒𝐘𝐒𝐓𝐄𝐌! ❌\n\n"
            f"📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n\n"
            f"⚠️ TXN `{tx_id}` not found in our records.\n\n"
            f"📌 Possible reasons:\n"
            f"1️⃣ Payment SMS hasn't arrived at the bot yet (wait 1-2 min)\n"
            f"2️⃣ You entered the wrong transaction ID\n"
            f"3️⃣ Payment is still processing\n\n"
            f"📱 Once the SMS arrives, it will auto-verify OR you can try `/verify` again.\n\n"
            f"❌ DO NOT FAKE VERIFY!",
            parse_mode="Markdown"
        )

# ============ RELEASE COMMAND - Buyer releases payment ============
async def release_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buyer releases payment after receiving item"""
    user_id = update.effective_user.id
    username = update.effective_user.username.lower() if update.effective_user.username else ""
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/release DEAL_ID`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ Deal `{deal_id}` not found!", parse_mode="Markdown")
        return
    
    # Check if user is buyer or owner/admin
    is_buyer = user_id == deal.get("buyer_id")
    is_admin_user = is_admin(user_id)
    
    if not is_buyer and not is_admin_user:
        await update.message.reply_text("❌ Only the buyer or admin can release payment!", parse_mode="Markdown")
        return
    
    if deal["status"] != "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃":
        await update.message.reply_text(f"❌ Deal `{deal_id}` is not ready for release! Current status: {deal['status']}", parse_mode="Markdown")
        return
    
    if deal.get("release_requested"):
        await update.message.reply_text("❌ Release already requested! Waiting for seller's UPI.", parse_mode="Markdown")
        return
    
    deal["release_requested"] = True
    save_deals(deals)
    
    await update.message.reply_text(
        f"✅ Release requested for `{deal_id}`!\n\n"
        f"👥 @{deal['seller']} - Please send your UPI ID:\n"
        f"`/sendupi {deal_id} YOUR_UPI_ID`",
        parse_mode="Markdown"
    )
    
    if deal.get("seller_id"):
        await context.bot.send_message(
            chat_id=deal["seller_id"],
            text=f"🔷 𝐑𝐄𝐋𝐄𝐀𝐒𝐄 𝐑𝐄𝐐𝐔𝐄𝐒𝐓!\n📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n\nBuyer wants to release payment.\n📝 Send: `/sendupi {deal_id} your@upi`",
            parse_mode="Markdown"
        )

# ============ SEND UPI COMMAND - Seller sends UPI ============
async def send_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seller sends their UPI for payment release"""
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text("📝 `/sendupi DEAL_ID UPI_ID`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    upi_id = context.args[1]
    
    if not re.match(r'^[\w\.\-]+@[\w\.\-]+$', upi_id):
        await update.message.reply_text("❌ Invalid UPI! Format: name@bank", parse_mode="Markdown")
        return
    
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ Deal `{deal_id}` not found!", parse_mode="Markdown")
        return
    
    # Check if user is seller or admin
    is_seller = user_id == deal.get("seller_id")
    is_admin_user = is_admin(user_id)
    
    if not is_seller and not is_admin_user:
        await update.message.reply_text(f"❌ Only @{deal['seller']} or admin can send UPI!", parse_mode="Markdown")
        return
    
    if not deal.get("release_requested"):
        await update.message.reply_text("❌ No release request! Buyer must use `/release` first.", parse_mode="Markdown")
        return
    
    if deal.get("seller_upi"):
        await update.message.reply_text("❌ UPI already submitted!", parse_mode="Markdown")
        return
    
    deal["seller_upi"] = upi_id
    save_deals(deals)
    
    await update.message.reply_text(
        f"✅ UPI received!\n💳 `{upi_id}`\n\n💰 Owner will process payment within 10-20 minutes.",
        parse_mode="Markdown"
    )
    
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"💰 𝐑𝐄𝐋𝐄𝐀𝐒𝐄 𝐑𝐄𝐀𝐃𝐘!\n📋 {deal_id}\n💰 ₹{deal['amount']:.2f}\n💳 {upi_id}\n👤 Seller: @{deal['seller']}\n\n✅ `/complete {deal_id}` to mark done.",
        parse_mode="Markdown"
    )

# ============ COMPLETE DEAL - Owner only ============
async def complete_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner marks deal as complete and sends payment to seller"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/complete DEAL_ID`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ Deal `{deal_id}` not found!", parse_mode="Markdown")
        return
    
    if deal["status"] != "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃":
        await update.message.reply_text(f"❌ Payment not confirmed! Status: {deal['status']}", parse_mode="Markdown")
        return
    
    if not deal.get("release_requested"):
        await update.message.reply_text("❌ No release requested yet!", parse_mode="Markdown")
        return
    
    if not deal.get("seller_upi"):
        await update.message.reply_text("❌ Seller hasn't provided UPI yet!", parse_mode="Markdown")
        return
    
    deal["status"] = "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"
    save_deals(deals)
    
    await context.bot.send_message(
        chat_id=deal["chat_id"],
        text=f"✅ 𝐃𝐄𝐀𝐋 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃! ✅\n\n📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n👤 @{deal['buyer']} ↔ @{deal['seller']}\n\n🎉 Deal completed successfully!",
        parse_mode="Markdown"
    )
    
    if deal.get("seller_id"):
        await context.bot.send_message(
            chat_id=deal["seller_id"],
            text=f"✅ 𝐃𝐄𝐀𝐋 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n💳 {deal['seller_upi']}\n\n🎉 Payment has been sent to your UPI!",
            parse_mode="Markdown"
        )
    
    await update.message.reply_text(f"✅ Deal `{deal_id}` completed! Payment sent to {deal['seller_upi']}", parse_mode="Markdown")

# ============ OWNER PANEL ============
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only!")
        return
    
    total_users = len(users)
    active_deals = len([d for d in deals.values() if d["status"] not in ["𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃", "𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃"]])
    completed_deals = len([d for d in deals.values() if d["status"] == "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"])
    total_volume = sum([d["amount"] for d in deals.values() if d["status"] == "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃"])
    stored_sms = len(sms_transactions)
    
    await update.message.reply_text(
        f"👑 𝐎𝐖𝐍𝐄𝐑 𝐏𝐀𝐍𝐄𝐋 👑\n\n"
        f"👥 𝐔𝐬𝐞𝐫𝐬: {total_users}\n"
        f"📋 𝐀𝐜𝐭𝐢𝐯𝐞: {active_deals}\n"
        f"✅ 𝐂𝐨𝐦𝐩𝐥𝐞𝐭𝐞𝐝: {completed_deals}\n"
        f"💰 𝐕𝐨𝐥𝐮𝐦𝐞: ₹{total_volume:.2f}\n"
        f"📱 𝐒𝐌𝐒 𝐑𝐞𝐜𝐨𝐫𝐝𝐞𝐝: {stored_sms}\n\n"
        f"📋 `/users` - List users\n"
        f"📋 `/deals` - List deals\n"
        f"📱 `/sms` - View stored SMS\n"
        f"🚫 `/ban ID` - Ban user\n"
        f"✅ `/unban ID` - Unban user\n"
        f"💰 `/complete ID` - Complete deal\n"
        f"👑 `/addadmin ID` - Add admin",
        parse_mode="Markdown"
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only!")
        return
    
    if not users:
        await update.message.reply_text("📭 No users yet.")
        return
    
    msg = "👥 𝐔𝐒𝐄𝐑𝐒 👥\n━━━━━━━━━━━━━━━━━━\n"
    for uid, u in users.items():
        status = "🚫 𝐁𝐀𝐍𝐍𝐄𝐃" if u.get('banned') else "✅ 𝐀𝐂𝐓𝐈𝐕𝐄"
        msg += f"🆔 `{uid}`\n📛 @{u.get('username', 'None')}\n📌 {status}\n━━━━━━━━━━━━━━━━━━\n"
    
    if len(msg) > 4096:
        for i in range(0, len(msg), 4000):
            await update.message.reply_text(msg[i:i+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

async def list_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only!")
        return
    
    if not deals:
        await update.message.reply_text("📭 No deals yet.")
        return
    
    msg = "📋 𝐃𝐄𝐀𝐋𝐒 📋\n━━━━━━━━━━━━━━━━━━\n"
    for deal_id, deal in list(deals.items())[-10:]:
        msg += f"🔖 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n📌 {deal['status']}\n👤 @{deal['buyer']} → @{deal['seller']}\n━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_sms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only!")
        return
    
    if not sms_transactions:
        await update.message.reply_text("📭 No SMS transactions stored.")
        return
    
    msg = "📱 𝐒𝐓𝐎𝐑𝐄𝐃 𝐒𝐌𝐒 📱\n━━━━━━━━━━━━━━━━━━\n"
    for tx_id, data in list(sms_transactions.items())[-10:]:
        verified = "✅" if data.get('verified') else "⏳"
        deal_id = data.get('deal_id', 'N/A')
        msg += f"{verified} 🔖 `{tx_id}`\n💰 ₹{data['amount']}\n📋 Deal: {deal_id}\n━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/ban USER_ID`", parse_mode="Markdown")
        return
    
    user_id = context.args[0]
    if user_id in users:
        users[user_id]['banned'] = True
        save_users(users)
        await update.message.reply_text(f"✅ User `{user_id}` banned!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ User `{user_id}` not found!", parse_mode="Markdown")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/unban USER_ID`", parse_mode="Markdown")
        return
    
    user_id = context.args[0]
    if user_id in users:
        users[user_id]['banned'] = False
        save_users(users)
        await update.message.reply_text(f"✅ User `{user_id}` unbanned!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ User `{user_id}` not found!", parse_mode="Markdown")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/addadmin USER_ID`", parse_mode="Markdown")
        return
    
    try:
        new_admin = int(context.args[0])
        if new_admin not in ADMIN_IDS:
            ADMIN_IDS.append(new_admin)
            await update.message.reply_text(f"✅ `{new_admin}` is now admin!", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"✅ `{new_admin}` is already admin!", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid ID! Use numeric user ID.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/status DEAL_ID`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ Deal `{deal_id}` not found!", parse_mode="Markdown")
        return
    
    status_map = {
        "𝐏𝐄𝐍𝐃𝐈𝐍𝐆": "⏳ Waiting for both to agree",
        "𝐀𝐖𝐀𝐈𝐓𝐈𝐍𝐆 𝐏𝐀𝐘𝐌𝐄𝐍𝐓": "💳 Awaiting payment from buyer",
        "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃": "✅ Payment confirmed",
        "𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃": "🎉 Completed",
        "𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃": "❌ Cancelled"
    }
    
    payment_info = ""
    if deal.get("payment_received"):
        payment_info += f"🔖 TXN: `{deal.get('payment_txid', 'N/A')}`\n"
    if deal.get("release_requested"):
        payment_info += "📦 Release requested\n"
    if deal.get("seller_upi"):
        payment_info += f"💳 Seller UPI: `{deal['seller_upi']}`\n"
    
    await update.message.reply_text(
        f"📋 𝐃𝐄𝐀𝐋 𝐒𝐓𝐀𝐓𝐔𝐒\n━━━━━━━━━━━━━━━━━━\n"
        f"🔖 `{deal_id}`\n"
        f"📊 {status_map.get(deal['status'], deal['status'])}\n"
        f"💰 ₹{deal['amount']:.2f}\n"
        f"👤 @{deal['buyer']} → @{deal['seller']}\n"
        f"📝 {deal['deal_detail']}\n"
        f"{payment_info}"
        f"━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown"
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text("📝 `/cancel DEAL_ID`", parse_mode="Markdown")
        return
    
    deal_id = context.args[0].upper()
    deal = deals.get(deal_id)
    
    if not deal:
        await update.message.reply_text(f"❌ Deal `{deal_id}` not found!", parse_mode="Markdown")
        return
    
    if user_id not in ADMIN_IDS and user_id != deal.get("buyer_id") and user_id != deal.get("seller_id"):
        await update.message.reply_text("❌ Not authorized!")
        return
    
    if deal["status"] in ["𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃", "𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐄𝐃"]:
        await update.message.reply_text("❌ Cannot cancel now! Payment already confirmed/completed.")
        return
    
    deal["status"] = "𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃"
    save_deals(deals)
    
    await context.bot.send_message(
        chat_id=deal["chat_id"],
        text=f"❌ 𝐃𝐄𝐀𝐋 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃!\n📋 `{deal_id}`\n💰 ₹{deal['amount']:.2f}\n👤 @{deal['buyer']} ↔ @{deal['seller']}",
        parse_mode="Markdown"
    )
    
    await update.message.reply_text(f"❌ Deal `{deal_id}` cancelled!", parse_mode="Markdown")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🔷 𝐄𝐒𝐂𝐑𝐎𝐖 𝐁𝐎𝐓 🔷\n\n"
        f"👋 Welcome, {user.first_name}!\n\n"
        f"📝 **To create a deal in a group, send:**\n\n"
        f"`ESCROW DEAL FORM !!!`\n"
        f"`DEAL AMOUNT : 1000`\n"
        f"`BUYER : @buyer`\n"
        f"`SELLER : @seller`\n"
        f"`DEAL DETAIL : Product name`\n"
        f"`RLS UPI : your@upi`\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 **How Payment Works:**\n"
        f"1️⃣ Both agree → QR sent to buyer\n"
        f"2️⃣ Buyer pays → SMS auto-forwarded to bot\n"
        f"3️⃣ Bot auto-verifies payment ✓\n"
        f"4️⃣ Buyer gets item → types `/release`\n"
        f"5️⃣ Owner sends payment to seller\n\n"
        f"📌 **User Commands:**\n"
        f"• `/status ID` - Check deal status\n"
        f"• `/cancel ID` - Cancel deal\n"
        f"• `/verify ID TXN` - Manually verify\n"
        f"• `/release ID` - Release payment\n\n"
        f"👑 **Owner:** @iflexvenom",
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
    application.add_handler(CommandHandler("sms", list_sms))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("complete", complete_deal))
    application.add_handler(CommandHandler("addadmin", add_admin))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sms_handler))
    
    print("=" * 60)
    print("🔷 ESCROW BOT STARTED")
    print(f"👑 Owner: {OWNER_ID}")
    print(f"📁 Deals loaded: {len(deals)}")
    print(f"👥 Users loaded: {len(users)}")
    print("=" * 60)
    print("📱 SMS Auto-Verify: ACTIVE")
    print("✅ All users can use commands!")
    print("=" * 60)
    
    application.run_polling()

if __name__ == "__main__":
    main()

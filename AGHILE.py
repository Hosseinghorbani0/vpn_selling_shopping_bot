
BOT_TOKEN = '8830302132:AAGDvIKdbG3WmSjqBbA-ls1UFTz1HsiJVik'  # توکن ربات خود را اینجا قرار دهید
import telebot
from telebot import types
import sqlite3
import json
import os
from datetime import datetime, timedelta


ADMIN_PASSWORD = '123'             # رمز عبور ورود به پنل مدیریت

bot = telebot.TeleBot(BOT_TOKEN)

# متغیر برای مدیریت وضعیت کاربران (Steps)
user_steps = {}
user_data = {}
admin_steps = {}
admin_data = {}

# ==========================================
# دیتابیس
# ==========================================
def init_db():
    conn = sqlite3.connect('v2ray_shop.db')
    c = conn.cursor()
    # جدول تنظیمات
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    # جدول پرداختی ها و اشتراک ها
    c.execute('''CREATE TABLE IF NOT EXISTS payments 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  plan_details TEXT, sub_name TEXT, photo_id TEXT, 
                  status TEXT, config TEXT)''')
                  
    # افزودن ستون های تاریخ در صورتی که دیتابیس از قبل وجود داشته باشد
    try:
        c.execute("ALTER TABLE payments ADD COLUMN purchase_date TEXT")
        c.execute("ALTER TABLE payments ADD COLUMN expire_date TEXT")
        c.execute("ALTER TABLE payments ADD COLUMN plan_days INTEGER")
    except Exception:
        pass # اگر ستون ها باشند ارور میدهد که آن را نادیده میگیریم
    
    # مقادیر پیش فرض تنظیمات
    default_settings = {
        'card_number': '1234567812345678',
        'card_name': 'نام صاحب حساب',
        'channels': '[]', # لیست آیدی کانال ها
        'plans': json.dumps([
            {"id": 1, "name": "30 گیگ 1 ماهه", "price": "50000", "days": 30},
            {"id": 2, "name": "50 گیگ 1 ماهه", "price": "80000", "days": 30}
        ])
    }
    for k, v in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    conn.commit()
    conn.close()

init_db()

def get_setting(key):
    conn = sqlite3.connect('v2ray_shop.db')
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def update_setting(key, value):
    conn = sqlite3.connect('v2ray_shop.db')
    c = conn.cursor()
    c.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
    conn.commit()
    conn.close()

# ==========================================
# توابع کمکی
# ==========================================
def check_force_join(user_id):
    channels = json.loads(get_setting('channels'))
    if not channels:
        return True
    
    for ch in channels:
        try:
            member = bot.get_chat_member(ch, user_id)
            if member.status in ['left', 'kicked']:
                return False
        except:
            pass # در صورتی که ربات در کانال ادمین نباشد
    return True

def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🛍 خرید اشتراک"),
        types.KeyboardButton("📦 اشتراک های من"),
        types.KeyboardButton("📚 آموزش استفاده"),
        types.KeyboardButton("👨‍💻 پشتیبانی")
    )
    return markup

def admin_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🧾 بررسی پرداختی ها (صف)"),
        types.KeyboardButton("💳 تنظیمات کارت"),
        types.KeyboardButton("📢 تنظیم کانال های جوین"),
        types.KeyboardButton("⚙️ تنظیم پلن ها"),
        types.KeyboardButton("🔙 خروج از پنل")
    )
    return markup

# ==========================================
# بخش کاربری (User Side)
# ==========================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    if not check_force_join(message.chat.id):
        channels = json.loads(get_setting('channels'))
        markup = types.InlineKeyboardMarkup()
        for i, ch in enumerate(channels):
            markup.add(types.InlineKeyboardButton(f"عضویت در کانال {i+1}", url=f"https://t.me/{ch.replace('@','')}"))
        bot.send_message(message.chat.id, "برای استفاده از ربات باید در کانال های زیر عضو شوید:", reply_markup=markup)
        return
    
    bot.send_message(message.chat.id, 
                     "سلام! به ربات فروش فیلترشکن خوش آمدید. لطفا یکی از گزینه های زیر را انتخاب کنید:", 
                     reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda m: m.text == "🛍 خرید اشتراک")
def buy_subscription(message):
    if not check_force_join(message.chat.id): return start_cmd(message)
    
    plans = json.loads(get_setting('plans'))
    if not plans:
        bot.send_message(message.chat.id, "در حال حاضر پلنی برای فروش موجود نیست.")
        return
        
    markup = types.InlineKeyboardMarkup(row_width=1)
    for p in plans:
        btn_text = f"{p['name']} | 💳 {p['price']} تومان"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"plan_{p['id']}"))
        
    bot.send_message(message.chat.id, "لطفا یکی از پلن های زیر را انتخاب کنید:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('plan_'))
def handle_plan_selection(call):
    plan_id = int(call.data.split('_')[1])
    plans = json.loads(get_setting('plans'))
    selected_plan = next((p for p in plans if p['id'] == plan_id), None)
    
    if selected_plan:
        user_steps[call.from_user.id] = 'wait_for_sub_name'
        user_data[call.from_user.id] = {'plan': selected_plan}
        
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"شما پلن **{selected_plan['name']}** را انتخاب کردید.\n\n"
                                   "لطفاً در صورت تایید، یک **نام دلخواه (انگلیسی)** برای اشتراک خود بفرستید (مثلا NICOT):",
                              parse_mode='Markdown')

@bot.message_handler(func=lambda m: user_steps.get(m.chat.id) == 'wait_for_sub_name')
def handle_sub_name(message):
    sub_name = message.text
    user_data[message.chat.id]['sub_name'] = sub_name
    user_steps[message.chat.id] = None # reset step
    
    plan = user_data[message.chat.id]['plan']
    card_number = get_setting('card_number')
    card_name = get_setting('card_name')
    
    text = (f"صورتحساب شما آماده شد:\n\n"
            f"📦 نام اشتراک: `{sub_name}`\n"
            f"🛒 جزییات: {plan['name']}\n"
            f"💵 مبلغ قابل پرداخت: <code>{plan['price']}</code> تومان\n\n"
            f"💳 شماره کارت جهت واریز:\n"
            f"<code>{card_number}</code>\n"
            f"👤 به نام: {card_name}\n\n"
            f"💡 برای کپی کردن روی شماره کارت یا مبلغ ضربه بزنید.\n"
            f"پس از پرداخت، روی دکمه زیر کلیک کنید.")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 ارسال فیش پرداخت", callback_data="send_receipt"))
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "send_receipt")
def ask_for_receipt(call):
    user_steps[call.from_user.id] = 'wait_for_receipt_photo'
    bot.send_message(call.message.chat.id, "لطفاً عکس رسید پرداختی خود را همینجا ارسال کنید:")

@bot.message_handler(content_types=['photo'], func=lambda m: user_steps.get(m.chat.id) == 'wait_for_receipt_photo')
def receive_receipt(message):
    photo_id = message.photo[-1].file_id
    plan = user_data[message.chat.id]['plan']
    sub_name = user_data[message.chat.id]['sub_name']
    days = plan.get('days', 30)
    
    conn = sqlite3.connect('v2ray_shop.db')
    c = conn.cursor()
    c.execute("INSERT INTO payments (user_id, plan_details, sub_name, photo_id, status, plan_days) VALUES (?, ?, ?, ?, ?, ?)",
              (message.chat.id, plan['name'], sub_name, photo_id, 'pending', days))
    conn.commit()
    conn.close()
    
    user_steps[message.chat.id] = None
    bot.send_message(message.chat.id, "✅ رسید شما با موفقیت دریافت شد و در صف بررسی توسط ادمین قرار گرفت.\nبه محض تایید، کانفیگ شما ارسال خواهد شد.")

@bot.message_handler(func=lambda m: m.text == "📦 اشتراک های من")
def my_subscriptions(message):
    conn = sqlite3.connect('v2ray_shop.db')
    c = conn.cursor()
    c.execute("SELECT sub_name, plan_details, config, purchase_date, expire_date FROM payments WHERE user_id=? AND status='approved'", (message.chat.id,))
    subs = c.fetchall()
    conn.close()
    
    if not subs:
        bot.send_message(message.chat.id, "شما هنوز هیچ اشتراک تایید شده ای ندارید.")
        return
        
    for sub in subs:
        p_date = sub[3] if sub[3] else "نامشخص"
        e_date = sub[4] if sub[4] else "نامشخص"
        text = f"📦 نام: {sub[0]}\n🛒 پلن: {sub[1]}\n📅 تاریخ خرید: {p_date}\n⏳ تاریخ انقضا: {e_date}\n\nکانفیگ شما:\n<code>{sub[2]}</code>"
        bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text in ["📚 آموزش استفاده", "👨‍💻 پشتیبانی"])
def info_sections(message):
    if message.text == "📚 آموزش استفاده":
        bot.send_message(message.chat.id, "نرم افزار v2rayNG را دانلود کرده و کانفیگ خریداری شده را در آن کپی کنید.")
    else:
        bot.send_message(message.chat.id, "برای ارتباط با پشتیبانی به آیدی @Support مراجعه کنید.")

# ==========================================
# بخش مدیریت (Admin Side)
# ==========================================
@bot.message_handler(commands=['admin'])
def admin_login(message):
    admin_steps[message.chat.id] = 'wait_for_password'
    bot.send_message(message.chat.id, "لطفا رمز عبور پنل مدیریت را وارد کنید:")

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_password')
def check_admin_password(message):
    if message.text == ADMIN_PASSWORD:
        admin_steps[message.chat.id] = 'admin_panel'
        bot.send_message(message.chat.id, "✅ با موفقیت وارد پنل مدیریت شدید.", reply_markup=admin_menu_keyboard())
    else:
        bot.send_message(message.chat.id, "❌ رمز عبور اشتباه است.")
        admin_steps[message.chat.id] = None

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'admin_panel')
def admin_panel_handler(message):
    if message.text == "🔙 خروج از پنل":
        admin_steps[message.chat.id] = None
        bot.send_message(message.chat.id, "از پنل مدیریت خارج شدید.", reply_markup=main_menu_keyboard())
        
    elif message.text == "🧾 بررسی پرداختی ها (صف)":
        show_next_pending_receipt(message.chat.id)
        
    elif message.text == "💳 تنظیمات کارت":
        admin_steps[message.chat.id] = 'wait_for_new_card'
        bot.send_message(message.chat.id, "لطفا شماره کارت جدید و نام صاحب حساب را با یک خط فاصله بفرستید.\nمثال:\n1234123412341234\nعلی احمدی")

    elif message.text == "📢 تنظیم کانال های جوین":
        admin_steps[message.chat.id] = 'wait_for_channels'
        bot.send_message(message.chat.id, "آیدی کانال‌ها را با @ وارد کنید (هر خط یک کانال، حداکثر ۴ تا).\nبرای غیرفعال کردن جوین اجباری، عدد 0 را بفرستید.\n\nمثال:\n@ChannelOne\n@ChannelTwo")

    elif message.text == "⚙️ تنظیم پلن ها":
        admin_steps[message.chat.id] = 'wait_for_plans'
        bot.send_message(message.chat.id, "پلن‌ها را به شکل زیر بفرستید (هر خط یک پلن، حداکثر 4 تا):\nنام پلن | قیمت (تومان) | تعداد روز اعتبار\n\nمثال:\n30 گیگ یک ماهه | 50000 | 30\n50 گیگ دو ماهه | 80000 | 60")

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_new_card')
def update_card_info(message):
    try:
        card, name = message.text.split('\n')
        update_setting('card_number', card.strip())
        update_setting('card_name', name.strip())
        bot.send_message(message.chat.id, "✅ اطلاعات کارت با موفقیت بروزرسانی شد.")
    except:
        bot.send_message(message.chat.id, "فرمت اشتباه است. تغییر کارت لغو شد.")
    admin_steps[message.chat.id] = 'admin_panel'

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_channels')
def update_channels(message):
    if message.text.strip() == '0':
        update_setting('channels', '[]')
        bot.send_message(message.chat.id, "✅ عضویت اجباری با موفقیت غیرفعال شد.")
    else:
        lines = [ch.strip() for ch in message.text.split('\n') if ch.strip().startswith('@')][:4]
        update_setting('channels', json.dumps(lines))
        bot.send_message(message.chat.id, f"✅ تعداد {len(lines)} کانال برای جوین اجباری ثبت شد.")
    admin_steps[message.chat.id] = 'admin_panel'

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_plans')
def update_plans(message):
    lines = message.text.split('\n')[:4]
    plans = []
    for i, line in enumerate(lines):
        try:
            # فرمت: نام | قیمت | روز
            name, price, days = [x.strip() for x in line.split('|')]
            plans.append({"id": i+1, "name": name, "price": price, "days": int(days)})
        except:
            pass
    
    if plans:
        update_setting('plans', json.dumps(plans))
        bot.send_message(message.chat.id, f"✅ تعداد {len(plans)} پلن با موفقیت ثبت شد.")
    else:
        bot.send_message(message.chat.id, "❌ فرمت ارسال اشتباه بود. تغییری ایجاد نشد.")
        
    admin_steps[message.chat.id] = 'admin_panel'

def show_next_pending_receipt(admin_chat_id):
    conn = sqlite3.connect('v2ray_shop.db')
    c = conn.cursor()
    # قدیمی ترین فیش (ORDER BY id ASC LIMIT 1)
    c.execute("SELECT id, user_id, plan_details, sub_name, photo_id FROM payments WHERE status='pending' ORDER BY id ASC LIMIT 1")
    row = c.fetchone()
    conn.close()
    
    if not row:
        bot.send_message(admin_chat_id, "✅ صفی وجود ندارد. هیچ پرداختی در انتظار بررسی نیست.")
        return
        
    p_id, u_id, plan, sub, photo = row
    text = (f"🧾 فیش جدید برای بررسی:\n\n"
            f"👤 آیدی کاربر: {u_id}\n"
            f"📦 نام انتخابی: {sub}\n"
            f"🛒 پلن درخواستی: {plan}")
            
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ تایید", callback_data=f"approve_{p_id}"),
        types.InlineKeyboardButton("❌ رد", callback_data=f"reject_{p_id}")
    )
    
    bot.send_photo(admin_chat_id, photo, caption=text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_receipt_action(call):
    action, p_id = call.data.split('_')
    
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    
    if action == 'reject':
        conn = sqlite3.connect('v2ray_shop.db')
        c = conn.cursor()
        c.execute("UPDATE payments SET status='rejected' WHERE id=?", (p_id,))
        c.execute("SELECT user_id FROM payments WHERE id=?", (p_id,))
        u_id = c.fetchone()[0]
        conn.commit()
        conn.close()
        
        bot.send_message(u_id, "❌ متاسفانه فیش پرداختی شما توسط مدیریت رد شد.")
        bot.send_message(call.message.chat.id, "فیش رد شد. رفتن به فیش بعدی...")
        show_next_pending_receipt(call.message.chat.id)
        
    elif action == 'approve':
        admin_steps[call.from_user.id] = f'wait_for_v2ray_config_{p_id}'
        bot.send_message(call.message.chat.id, "لطفاً کانفیگ (V2RAY String) را برای این کاربر بفرستید:")

@bot.message_handler(func=lambda m: str(admin_steps.get(m.chat.id)).startswith('wait_for_v2ray_config_'))
def receive_v2ray_config(message):
    p_id = admin_steps[message.chat.id].split('_')[-1]
    config_string = message.text
    
    now = datetime.now()
    
    conn = sqlite3.connect('v2ray_shop.db')
    c = conn.cursor()
    
    # دریافت تعداد روزهای پلن
    c.execute("SELECT plan_days FROM payments WHERE id=?", (p_id,))
    row = c.fetchone()
    days = row[0] if row and row[0] else 30
    
    purchase_date = now.strftime('%Y-%m-%d')
    expire_date = (now + timedelta(days=days)).strftime('%Y-%m-%d')
    
    c.execute("UPDATE payments SET status='approved', config=?, purchase_date=?, expire_date=? WHERE id=?", 
              (config_string, purchase_date, expire_date, p_id))
    c.execute("SELECT user_id, sub_name, plan_details FROM payments WHERE id=?", (p_id,))
    row_user = c.fetchone()
    conn.commit()
    conn.close()
    
    if row_user:
        u_id, sub_name, plan = row_user
        user_text = (f"✅ پرداخت شما تایید شد!\n\n"
                     f"📦 اشتراک: {sub_name}\n"
                     f"🛒 پلن: {plan}\n"
                     f"📅 تاریخ خرید: {purchase_date}\n"
                     f"⏳ تاریخ انقضا: {expire_date}\n\n"
                     f"کانفیگ شما:\n<code>{config_string}</code>")
        try:
            bot.send_message(u_id, user_text, parse_mode='HTML')
        except:
            pass # کاربر ربات را بلاک کرده است
            
    bot.send_message(message.chat.id, "✅ کانفیگ ارسال شد و وضعیت ثبت گردید. رفتن به فیش بعدی...")
    admin_steps[message.chat.id] = 'admin_panel'
    show_next_pending_receipt(message.chat.id)

# ==========================================
# اجرای ربات
# ==========================================
print("Bot is running...")
bot.infinity_polling()
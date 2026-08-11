# ==============================================================================
# V2Ray Shop Telegram Bot
# Developed by: Hossein Ghorbani
# GitHub: https://github.com/Hosseinghorbani0
# ==============================================================================

import os
import json
import sqlite3
import logging
import time
from datetime import datetime, timedelta
import telebot
from telebot import types

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_VERSION = "1.3.0"
BOT_TOKEN = os.getenv('BOT_TOKEN', 'bot-token')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '123')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'v2ray_shop.db')

bot = telebot.TeleBot(BOT_TOKEN)

# User and Admin Session States
user_steps = {}
user_data = {}
admin_steps = {}
admin_sessions = set()  # Keeps track of authenticated admin chat IDs

MAX_JOIN_CHANNELS = 6
MAX_PLANS = 12

# ------------------------------------------------------------------------------
# Core Database & System Settings Logic
# Created by Hossein Ghorbani (https://github.com/Hosseinghorbani0)
# ------------------------------------------------------------------------------

def db_connect():
    """Establishes connection to the SQLite database with dict row formatting."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes database schema and populates default settings if missing."""
    with db_connect() as conn:
        c = conn.cursor()
        
        # System settings key-value store
        c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        
        # Payments table
        c.execute('''CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_details TEXT,
            sub_name TEXT,
            photo_id TEXT,
            status TEXT,
            config TEXT,
            purchase_date TEXT,
            expire_date TEXT,
            plan_days INTEGER
        )''')
        
        # Users registry table
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT
        )''')

        default_settings = {
            'card_number': '6037997900000000',
            'card_name': 'نام صاحب حساب',
            'support_username': '@Support',
            'channels': '[]',
            'plans': json.dumps([
                {"id": 1, "name": "30 گیگ 1 ماهه", "price": "50000", "days": 30},
                {"id": 2, "name": "50 گیگ 1 ماهه", "price": "80000", "days": 30},
                {"id": 3, "name": "100 گیگ 2 ماهه", "price": "140000", "days": 60}
            ])
        }

        for key, value in default_settings.items():
            c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()

init_db()

def get_setting(key):
    """Fetch setting value by key."""
    with db_connect() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None

def update_setting(key, value):
    """Update setting key with a new value."""
    with db_connect() as conn:
        conn.execute('UPDATE settings SET value=? WHERE key=?', (value, key))
        conn.commit()

def register_user(user):
    """Register or update user details in the database."""
    with db_connect() as conn:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute('''
            INSERT INTO users (user_id, username, first_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=?, first_name=?
        ''', (user.id, user.username, user.first_name, now, user.username, user.first_name))
        conn.commit()

def check_force_join(user_id):
    """Checks whether user has joined all required Telegram channels."""
    raw_channels = get_setting('channels') or '[]'
    try:
        channels = json.loads(raw_channels)
    except Exception:
        channels = []

    if not channels:
        return True

    for channel in channels:
        if not channel:
            continue
        try:
            member = bot.get_chat_member(channel, user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.warning(f"Failed to check membership for {channel}: {e}")
            return False

    return True

def main_menu_keyboard():
    """Generates reply markup for user main menu."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('🛍 خرید اشتراک'),
        types.KeyboardButton('🏷 نرخ و تعرفه‌ها'),
        types.KeyboardButton('📦 اشتراک های من'),
        types.KeyboardButton('🎫 وضعیت سفارش'),
        types.KeyboardButton('📚 آموزش استفاده'),
        types.KeyboardButton('👨‍💻 پشتیبانی')
    )
    return markup

def admin_menu_keyboard():
    """Generates reply markup for admin panel."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('🧾 بررسی پرداختی ها (صف)'),
        types.KeyboardButton('📊 آمار ربات'),
        types.KeyboardButton('💳 تنظیمات کارت'),
        types.KeyboardButton('📢 تنظیم کانال های جوین'),
        types.KeyboardButton('⚙️ تنظیم پلن ها'),
        types.KeyboardButton('🔙 خروج از پنل')
    )
    return markup

def format_order_status(order):
    """Format single order database row into human-readable Persian text."""
    status_map = {
        'pending': '⏳ در انتظار بررسی',
        'approved': '✅ تایید شده',
        'rejected': '❌ رد شده'
    }
    status_text = status_map.get(order["status"], order["status"])
    return (
        f'📦 **سفارش #{order["id"]}**: {order["sub_name"]} ({order["plan_details"]})\n'
        f'وضعیت: {status_text}\n'
        f'تاریخ خرید: `{order["purchase_date"] or "نامشخص"}`\n'
        f'تاریخ انقضا: `{order["expire_date"] or "نامشخص"}`'
    )

# ==========================================
# بخش کاربری (User Side)
# Created by Hossein Ghorbani (https://github.com/Hosseinghorbani0)
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def start_cmd(message):
    register_user(message.from_user)


@bot.message_handler(commands=['start', 'help'])
def start_cmd(message):
    register_user(message.from_user)
    
    if not check_force_join(message.chat.id):
        channels = json.loads(get_setting('channels') or '[]')
        markup = types.InlineKeyboardMarkup()
        for index, channel in enumerate(channels, start=1):
            clean_ch = channel.replace("@", "")
            markup.add(types.InlineKeyboardButton(f'📢 عضویت در کانال {index}', url=f'https://t.me/{clean_ch}'))
        
        markup.add(types.InlineKeyboardButton('✅ عضو شدم / بررسی مجدد', callback_data='check_join'))

        bot.send_message(
            message.chat.id, 
            '⚠️ **جهت استفاده از خدمات ربات، لطفا ابتدا در کانال‌های زیر عضو شوید:**', 
            reply_markup=markup,
            parse_mode='Markdown'
        )
        return

    bot.send_message(
        message.chat.id,
        '👋 سلام! به ربات فروش فیلترشکن خوش آمدید.\nلطفاً یکی از گزینه های زیر را انتخاب کنید:',
        reply_markup=main_menu_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == 'check_join')
def handle_join_check_callback(call):
    if check_force_join(call.from_user.id):
        bot.answer_callback_query(call.id, '✅ عضویت شما تایید شد!')
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(
            call.message.chat.id,
            'خوش آمدید! لطفاً از منوی زیر استفاده کنید:',
            reply_markup=main_menu_keyboard()
        )
    else:
        bot.answer_callback_query(call.id, '❌ شما هنوز در تمام کانال‌ها عضو نشده‌اید!', show_alert=True)

@bot.message_handler(func=lambda m: m.text == '🛍 خرید اشتراک')
def buy_subscription(message):
    if not check_force_join(message.chat.id):
        return start_cmd(message)

    plans = json.loads(get_setting('plans') or '[]')
    if not plans:
        bot.send_message(message.chat.id, '⚠️ در حال حاضر پلنی برای فروش تعریف نشده است.')
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for plan in plans:
        btn_text = f"💎 {plan['name']} | 💳 {plan['price']} تومان"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"plan_{plan['id']}"))

    bot.send_message(message.chat.id, '📋 **لطفا یکی از پلن های زیر را برای خرید انتخاب کنید:**', reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('plan_'))
def handle_plan_selection(call):
    plan_id = int(call.data.split('_')[1])
    plans = json.loads(get_setting('plans') or '[]')
    selected_plan = next((plan for plan in plans if plan['id'] == plan_id), None)

    if not selected_plan:
        bot.answer_callback_query(call.id, '❌ پلن انتخاب شده معتبر نیست.')
        return

    user_steps[call.from_user.id] = 'wait_for_sub_name'
    user_data[call.from_user.id] = {'plan': selected_plan}

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f'شما پلن **{selected_plan["name"]}** را انتخاب کردید.\n\n'
            '✍️ لطفاً یک **نام انگلیسی** دلخواه برای اشتراک خود بفرستید (مثلا `user123`):'
        ),
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda m: user_steps.get(m.chat.id) == 'wait_for_sub_name')
def handle_sub_name(message):
    sub_name = message.text.strip()
    if not sub_name or len(sub_name) < 2:
        bot.send_message(message.chat.id, '⚠️ لطفاً یک نام معتبر و حداقل ۲ کاراکتری وارد کنید.')
        return

    user_data[message.chat.id]['sub_name'] = sub_name
    user_steps.pop(message.chat.id, None)

    plan = user_data[message.chat.id]['plan']
    card_number = get_setting('card_number') or 'ثبت نشده'
    card_name = get_setting('card_name') or 'ثبت نشده'

    reply_text = (
        f'🧾 **صورتحساب خرید:**\n\n'
        f'👤 نام اشتراک: `{sub_name}`\n'
        f'📦 جزییات پلن: {plan["name"]}\n'
        f'💵 مبلغ قابل پرداخت: <code>{plan["price"]}</code> تومان\n\n'
        f'💳 **شماره کارت جهت واریز:**\n<code>{card_number}</code>\n'
        f'👤 به نام: **{card_name}**\n\n'
        '📌 *جهت کپی روی شماره کارت یا مبلغ کلیک کنید.*\n'
        'پس از واریز، روی دکمه زیر کلیک کرده و عکس رسید را بفرستید.'
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📤 ارسال فیش پرداخت', callback_data='send_receipt'))

    bot.send_message(message.chat.id, reply_text, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == 'send_receipt')
def ask_for_receipt(call):
    user_steps[call.from_user.id] = 'wait_for_receipt_photo'
    bot.send_message(call.message.chat.id, '📸 لطفاً تصویر رسید پرداختی خود را ارسال کنید:')

@bot.message_handler(content_types=['photo'], func=lambda m: user_steps.get(m.chat.id) == 'wait_for_receipt_photo')
def receive_receipt(message):
    photo_id = message.photo[-1].file_id
    plan = user_data.get(message.chat.id, {}).get('plan')
    sub_name = user_data.get(message.chat.id, {}).get('sub_name')

    if not plan or not sub_name:
        bot.send_message(message.chat.id, '❌ خطایی در ثبت اطلاعات رخ داد. لطفاً مجدداً خرید را آغاز کنید.')
        user_steps.pop(message.chat.id, None)
        user_data.pop(message.chat.id, None)
        return

    with db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO payments (user_id, plan_details, sub_name, photo_id, status, plan_days) VALUES (?, ?, ?, ?, ?, ?)',
            (message.chat.id, plan['name'], sub_name, photo_id, 'pending', plan.get('days', 30))
        )
        payment_id = cursor.lastrowid
        conn.commit()

    user_steps.pop(message.chat.id, None)
    user_data.pop(message.chat.id, None)

    bot.send_message(
        message.chat.id, 
        '✅ **رسید شما با موفقیت ثبت شد.**\nسفارش شما در صف بررسی توسط پشتیبانی قرار گرفت و به محض تایید، کانفیگ ارسال می‌شود.'
    )

    for admin_id in admin_sessions:
        try:
            bot.send_message(admin_id, f"🔔 **فیش جدید دریافت شد!** (سفارش #{payment_id})\nبرای بررسی به بخش صف پرداختی‌ها بروید.")
        except Exception:
            pass

@bot.message_handler(func=lambda m: m.text == '📦 اشتراک های من')
def my_subscriptions(message):
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT sub_name, plan_details, config, purchase_date, expire_date FROM payments WHERE user_id=? AND status='approved'",
            (message.chat.id,)
        ).fetchall()

    if not rows:
        bot.send_message(message.chat.id, '⚠️ شما هیچ اشتراک فعال یا تایید شده‌ای ندارید.')
        return

    for row in rows:
        text = (
            f'📦 **نام اشتراک:** `{row["sub_name"]}`\n'
            f'💎 **پلن:** {row["plan_details"]}\n'
            f'📅 **تاریخ خرید:** `{row["purchase_date"] or "نامشخص"}`\n'
            f'⏳ **تاریخ انقضا:** `{row["expire_date"] or "نامشخص"}`\n\n'
            f'🔑 **کانفیگ شما:**\n<code>{row["config"]}</code>'
        )
        bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == '🎫 وضعیت سفارش')
def order_status(message):
    with db_connect() as conn:
        rows = conn.execute(
            'SELECT id, status, plan_details, sub_name, purchase_date, expire_date FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 5',
            (message.chat.id,)
        ).fetchall()

    if not rows:
        bot.send_message(message.chat.id, '⚠️ شما هنوز هیچ سفارشی ثبت نکرده‌اید.')
        return

    statuses = '\n\n------------------\n\n'.join([format_order_status(row) for row in rows])
    bot.send_message(message.chat.id, '📋 **آخرین وضعیت سفارش‌های شما:**\n\n' + statuses, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == '📚 آموزش استفاده')
def usage_guide(message):
    guide_text = (
        '📚 **راهنمای جامع اتصال و دانلود برنامه‌ها:**\n\n'
        '1️⃣ **دانلود نرم‌افزار:**\n\n'
        '🤖 **اندروید (Android):**\n'
        '• ⭐ [v2rayNG (پیشنهادی - ریلیس رسمی)](https://github.com/2dust/v2rayNG/releases)\n'
        '• [NekoBox (گیت‌هاب)](https://github.com/MatsuriDayo/NekoBoxForAndroid/releases)\n\n'
        '🍎 **آیفون (iOS):**\n'
        '• ⭐ [v2Box (پیشنهادی - اپ استور)](https://apps.apple.com/app/v2box-v2ray-client/id6446814190)\n'
        '• [Streisand (اپ استور)](https://apps.apple.com/app/streisand/id6450534064)\n\n'
        '💻 **ویندوز (Windows):**\n'
        '• ⭐ [v2rayN (پیشنهادی - ریلیس رسمی)](https://github.com/2dust/v2rayN/releases)\n\n'
        '2️⃣ **روش اتصال:**\n'
        '• ابتدا کد کانفیگ دریافتی را کپی (Copy) کنید.\n'
        '• وارد برنامه شده و علامت **+** یا گزینه‌ی **Import from Clipboard** را انتخاب کنید.\n'
        '• کانفیگ اضافه شده را انتخاب کرده و دکمه اتصال را بزنید!'
    )
    bot.send_message(
        message.chat.id,
        guide_text,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

@bot.message_handler(func=lambda m: m.text in ['🏷 نرخ و تعرفه‌ها', '📋 لیست قیمت‌ها'])
def show_price_list(message):
    """Displays all subscription plans and prices in a single unified message."""
    if not check_force_join(message.chat.id):
        return start_cmd(message)

    try:
        plans = json.loads(get_setting('plans') or '[]')
    except Exception:
        plans = []

    if not plans:
        bot.send_message(message.chat.id, '⚠️ در حال حاضر هیچ پلن یا تعرفه‌ای ثبت نشده است.')
        return

    price_list = "📊 **لیست قیمت و نرخ اشتراک‌ها:**\n\n"
    for plan in plans:
        price_val = str(plan.get('price', '0'))
        price_formatted = f"{int(price_val):,}" if price_val.isdigit() else price_val
        days = plan.get('days', 30)

        price_list += (
            f"💎 **{plan.get('name', 'اشتراک')}**\n"
            f"💳 **قیمت:** `{price_formatted}` تومان\n"
            f"⏳ **مدت اعتبار:** {days} روز\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
        )

    price_list += "\n🛒 جهت خرید هرکدام، می‌توانید روی دکمه **🛍 خرید اشتراک** کلیک کنید."
    bot.send_message(message.chat.id, price_list, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == '👨‍💻 پشتیبانی')
def support_info(message):
    """Displays customer support contact information."""
    support_username = get_setting('support_username') or '@Support'
    bot.send_message(
        message.chat.id,
        f'👨‍💻 **پشتیبانی ربات:**\n\n'
        f'جهت ارتباط با پشتیبانی، پاسخگویی به سوالات و یا پیگیری مشکلات، با آیدی زیر در تماس باشید:\n\n'
        f'💬 {support_username}',
        parse_mode='Markdown'
    )

# ==========================================
# بخش مدیریت (Admin Side - دکمه‌های شیشه‌ای)
# Created by Hossein Ghorbani (https://github.com/Hosseinghorbani0)
# ==========================================

@bot.message_handler(commands=['admin'])
def admin_login(message):
    """Prompts the user for the admin password."""


@bot.message_handler(commands=['admin'])
def admin_login(message):
    """Prompts the user for the admin password."""
    admin_steps[message.chat.id] = 'wait_for_password'
    bot.send_message(message.chat.id, '🔐 لطفا رمز عبور پنل مدیریت را وارد کنید:')

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_password')
def check_admin_password(message):
    """Verifies the admin password and unlocks admin privileges."""
    if message.text == ADMIN_PASSWORD:
        admin_steps[message.chat.id] = 'admin_panel'
        admin_sessions.add(message.chat.id)
        bot.send_message(
            message.chat.id,
            '✅ با موفقیت وارد پنل مدیریت شدید.',
            reply_markup=admin_menu_keyboard()
        )
    else:
        bot.send_message(message.chat.id, '❌ رمز عبور اشتباه است.')
        admin_steps.pop(message.chat.id, None)

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'admin_panel')
def admin_panel_handler(message):
    """Handles admin menu navigation."""
    if message.text == '🔙 خروج از پنل':
        admin_steps.pop(message.chat.id, None)
        admin_sessions.discard(message.chat.id)
        bot.send_message(
            message.chat.id,
            'از پنل مدیریت خارج شدید.',
            reply_markup=main_menu_keyboard()
        )
        return

    if message.text == '🧾 بررسی پرداختی ها (صف)':
        show_next_pending_receipt(message.chat.id)
        return

    if message.text == '📊 آمار ربات':
        show_bot_stats(message.chat.id)
        return

    if message.text == '💳 تنظیمات کارت':
        admin_steps[message.chat.id] = 'wait_for_new_card'
        bot.send_message(
            message.chat.id,
            'لطفا شماره کارت جدید و نام صاحب حساب را در دو خط بفرستید.\n\nمثال:\n6037997900000000\nعلی احمدی'
        )
        return

    if message.text == '📢 تنظیم کانال های جوین':
        show_admin_channels_menu(message.chat.id)
        return

    if message.text == '⚙️ تنظیم پلن ها':
        show_admin_plans_menu(message.chat.id)
        return

def show_admin_channels_menu(chat_id, message_id=None):
    """Displays channels management interface using interactive inline buttons."""
    channels = json.loads(get_setting('channels') or '[]')
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if channels:
        text = "📢 **لیست کانال‌های جوین اجباری فعلی:**\nبرای حذف هر کانال روی دکمه آن کلیک کنید:\n"
        for idx, ch in enumerate(channels):
            markup.add(types.InlineKeyboardButton(f"❌ حذف {ch}", callback_data=f"adm_del_ch_{idx}"))
    else:
        text = "📢 **هیچ کانالی برای جوین اجباری تنظیم نشده است.**"

    if len(channels) < MAX_JOIN_CHANNELS:
        markup.add(types.InlineKeyboardButton("➕ افزودن کانال جدید", callback_data="adm_add_ch"))
        
    if channels:
        markup.add(types.InlineKeyboardButton("🗑 غیرفعال‌سازی / پاک‌سازی همه", callback_data="adm_clear_ch"))

    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

def show_admin_plans_menu(chat_id, message_id=None):
    """Displays subscription plans management interface using interactive inline buttons."""
    plans = json.loads(get_setting('plans') or '[]')
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if plans:
        text = "⚙️ **لیست پلن‌های فعال فروش:**\nبرای حذف هر پلن روی آن کلیک کنید:\n"
        for plan in plans:
            price_formatted = f"{int(plan['price']):,}" if plan['price'].isdigit() else plan['price']
            btn_text = f"❌ {plan['name']} | {price_formatted} تومان ({plan['days']} روز)"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"adm_del_plan_{plan['id']}"))
    else:
        text = "⚙️ **هیچ پلن فروشی تعریف نشده است.**"

    if len(plans) < MAX_PLANS:
        markup.add(types.InlineKeyboardButton("➕ افزودن پلن جدید", callback_data="adm_add_plan"))
        
    if plans:
        markup.add(types.InlineKeyboardButton("🗑 پاک‌سازی تمام پلن‌ها", callback_data="adm_clear_plans"))

    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
def handle_admin_inline_callbacks(call):
    """Handles admin inline keyboard button clicks for channels and plans."""
    if call.from_user.id not in admin_sessions:
        bot.answer_callback_query(call.id, '❌ دسترسی غیرمجاز. ابتدا وارد پنل شوید.', show_alert=True)
        return

    data = call.data

    # Channel Management Callbacks
    if data.startswith('adm_del_ch_'):
        idx = int(data.split('_')[-1])
        channels = json.loads(get_setting('channels') or '[]')
        if 0 <= idx < len(channels):
            removed = channels.pop(idx)
            update_setting('channels', json.dumps(channels))
            bot.answer_callback_query(call.id, f"✅ کانال {removed} حذف شد.")
            show_admin_channels_menu(call.message.chat.id, call.message.message_id)

    elif data == 'adm_add_ch':
        channels = json.loads(get_setting('channels') or '[]')
        if len(channels) >= MAX_JOIN_CHANNELS:
            bot.answer_callback_query(call.id, f"⚠️ حداکثر {MAX_JOIN_CHANNELS} کانال می‌توانید بگذارید.", show_alert=True)
            return
        admin_steps[call.from_user.id] = 'wait_add_single_channel'
        bot.send_message(call.message.chat.id, "✍️ لطفاً آیدی کانال جدید را با **@** بفرستید (مثلا `@MyChannel`):", parse_mode='Markdown')
        bot.answer_callback_query(call.id)

    elif data == 'adm_clear_ch':
        update_setting('channels', '[]')
        bot.answer_callback_query(call.id, "✅ تمامی کانال‌ها غیرفعال شدند.")
        show_admin_channels_menu(call.message.chat.id, call.message.message_id)

    # Plan Management Callbacks
    elif data.startswith('adm_del_plan_'):
        plan_id = int(data.split('_')[-1])
        plans = json.loads(get_setting('plans') or '[]')
        plans = [p for p in plans if p['id'] != plan_id]
        update_setting('plans', json.dumps(plans))
        bot.answer_callback_query(call.id, "✅ پلن با موفقیت حذف شد.")
        show_admin_plans_menu(call.message.chat.id, call.message.message_id)

    elif data == 'adm_add_plan':
        plans = json.loads(get_setting('plans') or '[]')
        if len(plans) >= MAX_PLANS:
            bot.answer_callback_query(call.id, f"⚠️ حداکثر {MAX_PLANS} پلن می‌توانید تعریف کنید.", show_alert=True)
            return
        admin_steps[call.from_user.id] = 'wait_add_single_plan'
        guide = (
            "✍️ لطفاً مشخصات پلن جدید را در **یک خط** به شکل زیر ارسال کنید:\n\n"
            "`نام پلن | قیمت (تومان) | تعداد روز اعتبار`\n\n"
            "مثال:\n"
            "`30 گیگ یک ماهه | 50000 | 30`"
        )
        bot.send_message(call.message.chat.id, guide, parse_mode='Markdown')
        bot.answer_callback_query(call.id)

    elif data == 'adm_clear_plans':
        update_setting('plans', '[]')
        bot.answer_callback_query(call.id, "✅ تمامی پلن‌ها حذف شدند.")
        show_admin_plans_menu(call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_add_single_channel')
def add_single_channel_handler(message):
    ch_text = message.text.strip()
    if not ch_text.startswith('@'):
        bot.send_message(message.chat.id, "❌ آیدی کانال باید با `@` شروع شود. دوباره تلاش کنید:")
        return

    channels = json.loads(get_setting('channels') or '[]')
    if ch_text in channels:
        bot.send_message(message.chat.id, "⚠️ این کانال قبلاً اضافه شده است.")
    else:
        channels.append(ch_text)
        update_setting('channels', json.dumps(channels))
        bot.send_message(message.chat.id, f"✅ کانال {ch_text} با موفقیت اضافه شد.")

    admin_steps[message.chat.id] = 'admin_panel'
    show_admin_channels_menu(message.chat.id)

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_add_single_plan')
def add_single_plan_handler(message):
    try:
        parts = [part.strip() for part in message.text.strip().split('|')]
        if len(parts) < 3:
            raise ValueError("ورودی ناقص است.")
        
        name, price, days = parts[0], parts[1], int(parts[2])
        plans = json.loads(get_setting('plans') or '[]')
        
        new_id = max([p['id'] for p in plans], default=0) + 1
        plans.append({'id': new_id, 'name': name, 'price': price, 'days': days})
        
        update_setting('plans', json.dumps(plans))
        bot.send_message(message.chat.id, f"✅ پلن **{name}** با موفقیت اضافه شد.", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ فرمت ارسال اشتباه است. مثال صحیح:\n`30 گیگ یک ماهه | 50000 | 30`", parse_mode='Markdown')

    admin_steps[message.chat.id] = 'admin_panel'
    show_admin_plans_menu(message.chat.id)

def show_bot_stats(admin_chat_id):
    """Displays general bot usage and payment statistics."""
    with db_connect() as conn:
        total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        pending_count = conn.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
        approved_count = conn.execute("SELECT COUNT(*) FROM payments WHERE status='approved'").fetchone()[0]
        rejected_count = conn.execute("SELECT COUNT(*) FROM payments WHERE status='rejected'").fetchone()[0]

    stats_text = (
        '📊 **آمار کلی ربات:**\n\n'
        f'👤 تعداد کل کاربران: `{total_users}`\n'
        f'⏳ پرداخت‌های در انتظار بررسی: `{pending_count}`\n'
        f'✅ پرداخت‌های تایید شده: `{approved_count}`\n'
        f'❌ پرداخت‌های رد شده: `{rejected_count}`'
    )
    bot.send_message(admin_chat_id, stats_text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_new_card')
def update_card_info(message):
    """Updates card details in the database."""
    try:
        parts = message.text.strip().split('\n', 1)
        if len(parts) < 2:
            raise ValueError("فرمت ورودی نادرست است.")
        
        card, name = parts[0].strip(), parts[1].strip()
        update_setting('card_number', card)
        update_setting('card_name', name)
        bot.send_message(message.chat.id, '✅ اطلاعات کارت با موفقیت بروزرسانی شد.')
    except Exception as e:
        bot.send_message(message.chat.id, f'❌ فرمت اشتباه است. تغییر کارت لغو شد: {e}')

    admin_steps[message.chat.id] = 'admin_panel'

def show_next_pending_receipt(admin_chat_id):
    """Fetches and displays the next pending user payment for admin review."""
    with db_connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, plan_details, sub_name, photo_id FROM payments WHERE status='pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()

    if not row:
        bot.send_message(admin_chat_id, '✅ صفی وجود ندارد. هیچ پرداختی در انتظار بررسی نیست.')
        return

    caption = (
        f'🧾 **فیش جدید برای بررسی (سفارش #{row["id"]}):**\n\n'
        f'👤 آیدی عددی کاربر: `{row["user_id"]}`\n'
        f'📦 نام انتخابی: `{row["sub_name"]}`\n'
        f'💎 پلن درخواستی: {row["plan_details"]}'
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('✅ تایید و ارسال کانفیگ', callback_data=f'approve_{row["id"]}'),
        types.InlineKeyboardButton('❌ رد درخواست', callback_data=f'reject_{row["id"]}')
    )

    bot.send_photo(admin_chat_id, row['photo_id'], caption=caption, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_receipt_action(call):
    """Processes approval or rejection of user payment receipts."""
    action, payment_id = call.data.split('_', 1)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    if action == 'reject':
        with db_connect() as conn:
            conn.execute('UPDATE payments SET status=? WHERE id=?', ('rejected', payment_id))
            row = conn.execute('SELECT user_id FROM payments WHERE id=?', (payment_id,)).fetchone()

        if row:
            try:
                bot.send_message(row['user_id'], '❌ متاسفانه فیش پرداختی شما توسط مدیریت رد شد.')
            except Exception:
                pass

        bot.send_message(call.message.chat.id, '❌ فیش رد شد. رفتن به فیش بعدی...')
        show_next_pending_receipt(call.message.chat.id)
        return

    admin_steps[call.from_user.id] = f'wait_for_v2ray_config_{payment_id}'
    bot.send_message(call.message.chat.id, '🔑 لطفاً کانفیگ (V2Ray String) را برای این کاربر بفرستید:')

@bot.message_handler(func=lambda m: str(admin_steps.get(m.chat.id)).startswith('wait_for_v2ray_config_'))
def receive_v2ray_config(message):
    """Receives V2Ray config string from admin and sends it to the user."""
    payment_id = admin_steps[message.chat.id].split('_')[-1]
    config_string = message.text.strip()

    with db_connect() as conn:
        row = conn.execute('SELECT plan_days, user_id, sub_name, plan_details FROM payments WHERE id=?', (payment_id,)).fetchone()
        if not row:
            bot.send_message(message.chat.id, '⚠️ پرداخت یافت نشد.')
            admin_steps[message.chat.id] = 'admin_panel'
            return

        days = row['plan_days'] or 30
        purchase_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        expire_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

        conn.execute(
            'UPDATE payments SET status=?, config=?, purchase_date=?, expire_date=? WHERE id=?',
            ('approved', config_string, purchase_date, expire_date, payment_id)
        )

    try:
        bot.send_message(
            row['user_id'],
            ('🎉 **پرداخت شما تایید شد!**\n\n'
             f'👤 **نام اشتراک:** `{row["sub_name"]}`\n'
             f'💎 **پلن:** {row["plan_details"]}\n'
             f'📅 **تاریخ خرید:** `{purchase_date}`\n'
             f'⏳ **تاریخ انقضا:** `{expire_date}`\n\n'
             f'🔑 **کانفیگ شما:**\n<code>{config_string}</code>'),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.warning(f"Failed to send config to user {row['user_id']}: {e}")

    bot.send_message(message.chat.id, '✅ کانفیگ ارسال و سفارش تکمیل گردید. رفتن به فیش بعدی...')
    admin_steps[message.chat.id] = 'admin_panel'
    show_next_pending_receipt(message.chat.id)

def run_bot():
    """Starts the Telegram bot polling loop with automatic error recovery."""
    logger.info(f"V2Ray Shop Bot v{BOT_VERSION} running...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as error:
            logger.error(f"Polling error encountered: {error}")
            time.sleep(5)

# ==============================================================================
# V2Ray Shop Telegram Bot - Built by Hossein Ghorbani
# GitHub: https://github.com/Hosseinghorbani0
# All Rights Reserved
# ==============================================================================

if __name__ == '__main__':
    run_bot()

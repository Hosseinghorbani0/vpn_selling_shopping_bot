import os
import json
import sqlite3
import telebot
from telebot import types
from datetime import datetime, timedelta
import time

BOT_VERSION = "1.0.1"
BOT_TOKEN = os.getenv('BOT_TOKEN', '8830302132:AAGDvIKdbG3WmSjqBbA-ls1UFTz1HsiJVik')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '123')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'v2ray_shop.db')

bot = telebot.TeleBot(BOT_TOKEN)

user_steps = {}
user_data = {}
admin_steps = {}

MAX_JOIN_CHANNELS = 4
MAX_PLANS = 8

# ==========================================
# دیتابیس
# ==========================================

def db_connect():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
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

        default_settings = {
            'card_number': '1234567812345678',
            'card_name': 'نام صاحب حساب',
            'support_username': '@Support',
            'channels': '[]',
            'plans': json.dumps([
                {"id": 1, "name": "30 گیگ 1 ماهه", "price": "50000", "days": 30},
                {"id": 2, "name": "50 گیگ 1 ماهه", "price": "80000", "days": 30}
            ])
        }

        for key, value in default_settings.items():
            c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))


init_db()


def get_setting(key):
    with db_connect() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None


def update_setting(key, value):
    with db_connect() as conn:
        conn.execute('UPDATE settings SET value=? WHERE key=?', (value, key))
        conn.commit()

# ==========================================
# توابع کمکی
# ==========================================

def check_force_join(user_id):
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
        except Exception:
            return False

    return True


def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('🛍 خرید اشتراک'),
        types.KeyboardButton('📦 اشتراک های من'),
        types.KeyboardButton('🎫 وضعیت سفارش'),
        types.KeyboardButton('📚 آموزش استفاده'),
        types.KeyboardButton('👨‍💻 پشتیبانی')
    )
    return markup


def admin_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('🧾 بررسی پرداختی ها (صف)'),
        types.KeyboardButton('💳 تنظیمات کارت'),
        types.KeyboardButton('📢 تنظیم کانال های جوین'),
        types.KeyboardButton('⚙️ تنظیم پلن ها'),
        types.KeyboardButton('🔙 خروج از پنل')
    )
    return markup


def format_order_status(order):
    return (
        f'📦 سفارش #{order["id"]}: {order["sub_name"]} | {order["plan_details"]}\n'
        f'وضعیت: {order["status"]}\n'
        f'تاریخ خرید: {order["purchase_date"] or "نامشخص"}\n'
        f'تاریخ انقضا: {order["expire_date"] or "نامشخص"}'
    )

# ==========================================
# بخش کاربری (User Side)
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def start_cmd(message):
    if not check_force_join(message.chat.id):
        channels = json.loads(get_setting('channels') or '[]')
        markup = types.InlineKeyboardMarkup()
        for index, channel in enumerate(channels, start=1):
            markup.add(types.InlineKeyboardButton(f'عضویت در کانال {index}', url=f'https://t.me/{channel.replace("@", "")}'))

        bot.send_message(message.chat.id, 'برای استفاده از ربات باید در کانال های زیر عضو شوید:', reply_markup=markup)
        return

    bot.send_message(
        message.chat.id,
        'سلام! به ربات فروش فیلترشکن خوش آمدید. لطفا یکی از گزینه های زیر را انتخاب کنید:',
        reply_markup=main_menu_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == '🛍 خرید اشتراک')
def buy_subscription(message):
    if not check_force_join(message.chat.id):
        return start_cmd(message)

    plans = json.loads(get_setting('plans') or '[]')
    if not plans:
        bot.send_message(message.chat.id, 'در حال حاضر پلنی برای فروش موجود نیست.')
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for plan in plans:
        btn_text = f"{plan['name']} | 💳 {plan['price']} تومان"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"plan_{plan['id']}"))

    bot.send_message(message.chat.id, 'لطفا یکی از پلن های زیر را انتخاب کنید:', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('plan_'))
def handle_plan_selection(call):
    plan_id = int(call.data.split('_')[1])
    plans = json.loads(get_setting('plans') or '[]')
    selected_plan = next((plan for plan in plans if plan['id'] == plan_id), None)

    if not selected_plan:
        bot.answer_callback_query(call.id, 'پلن نامعتبر است.')
        return

    user_steps[call.from_user.id] = 'wait_for_sub_name'
    user_data[call.from_user.id] = {'plan': selected_plan}

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f'شما پلن **{selected_plan["name"]}** را انتخاب کردید.\n\n'
            'لطفاً در صورت تایید، یک **نام دلخواه (انگلیسی)** برای اشتراک خود بفرستید (مثلا NICOT):'
        ),
        parse_mode='Markdown'
    )


@bot.message_handler(func=lambda m: user_steps.get(m.chat.id) == 'wait_for_sub_name')
def handle_sub_name(message):
    sub_name = message.text.strip()
    if not sub_name:
        bot.send_message(message.chat.id, 'لطفا یک نام معتبر برای اشتراک وارد کنید.')
        return

    user_data[message.chat.id]['sub_name'] = sub_name
    user_steps.pop(message.chat.id, None)

    plan = user_data[message.chat.id]['plan']
    card_number = get_setting('card_number') or 'نامشخص'
    card_name = get_setting('card_name') or 'نامشخص'

    reply_text = (
        f'صورتحساب شما آماده شد:\n\n'
        f'📦 نام اشتراک: `{sub_name}`\n'
        f'🛒 جزییات: {plan["name"]}\n'
        f'💵 مبلغ قابل پرداخت: <code>{plan["price"]}</code> تومان\n\n'
        f'💳 شماره کارت جهت واریز:\n<code>{card_number}</code>\n'
        f'👤 به نام: {card_name}\n\n'
        '💡 برای کپی کردن روی شماره کارت یا مبلغ ضربه بزنید.\n'
        'پس از پرداخت، روی دکمه زیر کلیک کنید.'
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📤 ارسال فیش پرداخت', callback_data='send_receipt'))

    bot.send_message(message.chat.id, reply_text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data == 'send_receipt')
def ask_for_receipt(call):
    user_steps[call.from_user.id] = 'wait_for_receipt_photo'
    bot.send_message(call.message.chat.id, 'لطفاً عکس رسید پرداختی خود را همینجا ارسال کنید:')


@bot.message_handler(content_types=['photo'], func=lambda m: user_steps.get(m.chat.id) == 'wait_for_receipt_photo')
def receive_receipt(message):
    photo_id = message.photo[-1].file_id
    plan = user_data.get(message.chat.id, {}).get('plan')
    sub_name = user_data.get(message.chat.id, {}).get('sub_name')

    if not plan or not sub_name:
        bot.send_message(message.chat.id, 'خطایی رخ داد. لطفا دوباره خرید اشتراک را آغاز کنید.')
        user_steps.pop(message.chat.id, None)
        user_data.pop(message.chat.id, None)
        return

    with db_connect() as conn:
        conn.execute(
            'INSERT INTO payments (user_id, plan_details, sub_name, photo_id, status, plan_days) VALUES (?, ?, ?, ?, ?, ?)',
            (message.chat.id, plan['name'], sub_name, photo_id, 'pending', plan.get('days', 30))
        )

    user_steps.pop(message.chat.id, None)
    user_data.pop(message.chat.id, None)
    bot.send_message(message.chat.id, '✅ رسید شما با موفقیت دریافت شد و در صف بررسی توسط ادمین قرار گرفت.\nبه محض تایید، کانفیگ شما ارسال خواهد شد.')


@bot.message_handler(func=lambda m: m.text == '📦 اشتراک های من')
def my_subscriptions(message):
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT sub_name, plan_details, config, purchase_date, expire_date FROM payments WHERE user_id=? AND status='approved'",
            (message.chat.id,)
        ).fetchall()

    if not rows:
        bot.send_message(message.chat.id, 'شما هنوز هیچ اشتراک تایید شده ای ندارید.')
        return

    for row in rows:
        text = (
            f'📦 نام: {row["sub_name"]}\n'
            f'🛒 پلن: {row["plan_details"]}\n'
            f'📅 تاریخ خرید: {row["purchase_date"] or "نامشخص"}\n'
            f'⏳ تاریخ انقضا: {row["expire_date"] or "نامشخص"}\n\n'
            f'کانفیگ شما:\n<code>{row["config"]}</code>'
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
        bot.send_message(message.chat.id, 'شما هنوز سفارشی ثبت نکرده‌اید.')
        return

    statuses = '\n\n'.join([format_order_status(row) for row in rows])
    bot.send_message(message.chat.id, 'آخرین وضعیت سفارش‌های شما:\n\n' + statuses)


@bot.message_handler(func=lambda m: m.text == '📚 آموزش استفاده')
def usage_guide(message):
    bot.send_message(message.chat.id, 'نرم افزار v2rayNG را دانلود کرده و کانفیگ خریداری شده را در آن کپی کنید.')


@bot.message_handler(func=lambda m: m.text == '👨‍💻 پشتیبانی')
def support_info(message):
    support_username = get_setting('support_username') or '@Support'
    bot.send_message(message.chat.id, f'برای ارتباط با پشتیبانی به آیدی {support_username} مراجعه کنید.')


# ==========================================
# بخش مدیریت (Admin Side)
# ==========================================

@bot.message_handler(commands=['admin'])
def admin_login(message):
    admin_steps[message.chat.id] = 'wait_for_password'
    bot.send_message(message.chat.id, 'لطفا رمز عبور پنل مدیریت را وارد کنید:')


@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_password')
def check_admin_password(message):
    if message.text == ADMIN_PASSWORD:
        admin_steps[message.chat.id] = 'admin_panel'
        bot.send_message(message.chat.id, '✅ با موفقیت وارد پنل مدیریت شدید.', reply_markup=admin_menu_keyboard())
    else:
        bot.send_message(message.chat.id, '❌ رمز عبور اشتباه است.')
        admin_steps.pop(message.chat.id, None)


@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'admin_panel')
def admin_panel_handler(message):
    if message.text == '🔙 خروج از پنل':
        admin_steps.pop(message.chat.id, None)
        bot.send_message(message.chat.id, 'از پنل مدیریت خارج شدید.', reply_markup=main_menu_keyboard())
        return

    if message.text == '🧾 بررسی پرداختی ها (صف)':
        show_next_pending_receipt(message.chat.id)
        return

    if message.text == '💳 تنظیمات کارت':
        admin_steps[message.chat.id] = 'wait_for_new_card'
        bot.send_message(
            message.chat.id,
            'لطفا شماره کارت جدید و نام صاحب حساب را با یک خط فاصله بفرستید.\nمثال:\n1234123412341234\nعلی احمدی'
        )
        return

    if message.text == '📢 تنظیم کانال های جوین':
        admin_steps[message.chat.id] = 'wait_for_channels'
        bot.send_message(
            message.chat.id,
            'آیدی کانال‌ها را با @ وارد کنید (هر خط یک کانال، حداکثر ۴ تا).\n'
            'برای غیرفعال کردن جوین اجباری، عدد 0 را بفرستید.\n\n'
            'مثال:\n@ChannelOne\n@ChannelTwo'
        )
        return

    if message.text == '⚙️ تنظیم پلن ها':
        admin_steps[message.chat.id] = 'wait_for_plans'
        bot.send_message(
            message.chat.id,
            'پلن‌ها را به شکل زیر بفرستید (هر خط یک پلن، حداکثر 4 تا):\n'
            'نام پلن | قیمت (تومان) | تعداد روز اعتبار\n\n'
            'مثال:\n30 گیگ یک ماهه | 50000 | 30\n50 گیگ دو ماهه | 80000 | 60'
        )
        return


@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_new_card')
def update_card_info(message):
    try:
        card, name = message.text.split('\n', 1)
        update_setting('card_number', card.strip())
        update_setting('card_name', name.strip())
        bot.send_message(message.chat.id, '✅ اطلاعات کارت با موفقیت بروزرسانی شد.')
    except Exception:
        bot.send_message(message.chat.id, 'فرمت اشتباه است. تغییر کارت لغو شد.')

    admin_steps[message.chat.id] = 'admin_panel'


@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_channels')
def update_channels(message):
    if message.text.strip() == '0':
        update_setting('channels', '[]')
        bot.send_message(message.chat.id, '✅ عضویت اجباری با موفقیت غیرفعال شد.')
    else:
        lines = [line.strip() for line in message.text.split('\n') if line.strip().startswith('@')][:MAX_JOIN_CHANNELS]
        update_setting('channels', json.dumps(lines))
        bot.send_message(message.chat.id, f'✅ تعداد {len(lines)} کانال برای جوین اجباری ثبت شد.')

    admin_steps[message.chat.id] = 'admin_panel'


@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_plans')
def update_plans(message):
    lines = [line.strip() for line in message.text.split('\n') if line.strip()][:MAX_PLANS]
    plans = []

    for index, line in enumerate(lines, start=1):
        try:
            name, price, days = [part.strip() for part in line.split('|')]
            plans.append({'id': index, 'name': name, 'price': price, 'days': int(days)})
        except Exception:
            continue

    if plans:
        update_setting('plans', json.dumps(plans))
        bot.send_message(message.chat.id, f'✅ تعداد {len(plans)} پلن با موفقیت ثبت شد.')
    else:
        bot.send_message(message.chat.id, '❌ فرمت ارسال اشتباه بود. تغییری ایجاد نشد.')

    admin_steps[message.chat.id] = 'admin_panel'


def show_next_pending_receipt(admin_chat_id):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, plan_details, sub_name, photo_id FROM payments WHERE status='pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()

    if not row:
        bot.send_message(admin_chat_id, '✅ صفی وجود ندارد. هیچ پرداختی در انتظار بررسی نیست.')
        return

    caption = (
        f'🧾 فیش جدید برای بررسی:\n\n'
        f'👤 آیدی کاربر: {row["user_id"]}\n'
        f'📦 نام انتخابی: {row["sub_name"]}\n'
        f'🛒 پلن درخواستی: {row["plan_details"]}'
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('✅ تایید', callback_data=f'approve_{row["id"]}'),
        types.InlineKeyboardButton('❌ رد', callback_data=f'reject_{row["id"]}')
    )

    bot.send_photo(admin_chat_id, row['photo_id'], caption=caption, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_receipt_action(call):
    action, payment_id = call.data.split('_', 1)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    if action == 'reject':
        with db_connect() as conn:
            conn.execute('UPDATE payments SET status=? WHERE id=?', ('rejected', payment_id))
            row = conn.execute('SELECT user_id FROM payments WHERE id=?', (payment_id,)).fetchone()

        if row:
            bot.send_message(row['user_id'], '❌ متاسفانه فیش پرداختی شما توسط مدیریت رد شد.')

        bot.send_message(call.message.chat.id, 'فیش رد شد. رفتن به فیش بعدی...')
        show_next_pending_receipt(call.message.chat.id)
        return

    admin_steps[call.from_user.id] = f'wait_for_v2ray_config_{payment_id}'
    bot.send_message(call.message.chat.id, 'لطفاً کانفیگ (V2RAY String) را برای این کاربر بفرستید:')


@bot.message_handler(func=lambda m: str(admin_steps.get(m.chat.id)).startswith('wait_for_v2ray_config_'))
def receive_v2ray_config(message):
    payment_id = admin_steps[message.chat.id].split('_')[-1]
    config_string = message.text.strip()

    with db_connect() as conn:
        row = conn.execute('SELECT plan_days, user_id, sub_name, plan_details FROM payments WHERE id=?', (payment_id,)).fetchone()
        if not row:
            bot.send_message(message.chat.id, 'پرداخت یافت نشد. لطفا مجددا تلاش کنید.')
            admin_steps[message.chat.id] = 'admin_panel'
            return

        days = row['plan_days'] or 30
        purchase_date = datetime.now().strftime('%Y-%m-%d')
        expire_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')

        conn.execute(
            'UPDATE payments SET status=?, config=?, purchase_date=?, expire_date=? WHERE id=?',
            ('approved', config_string, purchase_date, expire_date, payment_id)
        )

    try:
        bot.send_message(
            row['user_id'],
            ('✅ پرداخت شما تایید شد!\n\n'
             f'📦 اشتراک: {row["sub_name"]}\n'
             f'🛒 پلن: {row["plan_details"]}\n'
             f'📅 تاریخ خرید: {purchase_date}\n'
             f'⏳ تاریخ انقضا: {expire_date}\n\n'
             f'کانفیگ شما:\n<code>{config_string}</code>'),
            parse_mode='HTML'
        )
    except Exception:
        pass

    bot.send_message(message.chat.id, '✅ کانفیگ ارسال شد و وضعیت ثبت گردید. رفتن به فیش بعدی...')
    admin_steps[message.chat.id] = 'admin_panel'
    show_next_pending_receipt(message.chat.id)


def run_bot():
    print(f'Bot version {BOT_VERSION} is running...')
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as error:
            print('Polling stopped with error:', error)
            time.sleep(5)


if __name__ == '__main__':
    run_bot()

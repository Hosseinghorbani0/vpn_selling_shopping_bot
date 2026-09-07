
import os
import json
import signal
import sqlite3
import logging
import logging.handlers
import time
import html
import hmac
import functools
import threading
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(message)s'
)

logger = logging.getLogger('v2ray_shop_bot')
logger.setLevel(logging.INFO)

general_file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, 'bot.log'), maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8'
)
general_file_handler.setFormatter(log_formatter)
general_file_handler.setLevel(logging.INFO)

error_file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, 'errors.log'), maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8'
)
error_file_handler.setFormatter(log_formatter)
error_file_handler.setLevel(logging.ERROR)

audit_file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, 'audit.log'), maxBytes=5 * 1024 * 1024, backupCount=10, encoding='utf-8'
)
audit_file_handler.setFormatter(log_formatter)
audit_file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

logger.addHandler(general_file_handler)
logger.addHandler(error_file_handler)
logger.addHandler(console_handler)

# audit_logger فرزند logger اصلی است؛ رویدادهایش هم در audit.log و هم
# (چون propagate پیش‌فرض True است) در bot.log/errors.log/کنسول ثبت می‌شوند
# تا هم یک فایل اختصاصی داشته باشیم و هم در نمای کلی لاگ گم نشوند.
audit_logger = logging.getLogger('v2ray_shop_bot.audit')
audit_logger.setLevel(logging.INFO)
audit_logger.addHandler(audit_file_handler)

# لاگ داخلی کتابخانه‌ی telebot را هم به همین فایل‌ها وصل می‌کنیم تا خطاهای
# سطح پایین کتابخانه (مثلاً مشکلات شبکه) هم قابل ردیابی باشند.
_telebot_logger = logging.getLogger('TeleBot')
_telebot_logger.setLevel(logging.WARNING)
_telebot_logger.addHandler(general_file_handler)
_telebot_logger.addHandler(error_file_handler)

BOT_VERSION = "1.6.0"

# هندلرهایی که بیشتر از این مقدار طول بکشند، به‌عنوان «هندلر کند» در
# bot.log ثبت می‌شوند تا بشود گلوگاه‌های عملکردی (مثلاً کوئری‌های سنگین یا
# فراخوانی‌های آهسته‌ی API تلگرام) را پیدا کرد.
SLOW_HANDLER_THRESHOLD_SECONDS = 2.0

# ------------------------------------------------------------------------------
# ⚠️ هشدار امنیتی مهم
# توکن و رمز ادمین قبلی که به‌صورت پیش‌فرض داخل کد بودند، چون در یک چت به
# اشتراک گذاشته شدند، از نظر امنیتی «افشا شده» محسوب می‌شوند. فقط برای این‌که
# ربات همچنان بدون تنظیم دستی بالا بیاید، به‌صورت fallback نگه داشته شدند،
# ولی توصیه‌ی جدی: هرچه سریع‌تر:
#   1) توکن ربات را از BotFather با دستور /revoke تعویض کنید.
#   2) ADMIN_PASSWORD را عوض کرده و آن را فقط با متغیر محیطی ست کنید، نه در کد.
# در حالت ایده‌آل خط‌های زیر باید فقط os.getenv(...) باشند بدون مقدار پیش‌فرض.
# ------------------------------------------------------------------------------

BOT_TOKEN = os.getenv('BOT_TOKEN', 'token')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'pas123')
DATABASE_PATH = os.getenv(
    'DATABASE_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v2ray_shop.db')
)

if BOT_TOKEN.startswith('8981848512') or ADMIN_PASSWORD == '09185998404':
    logger.warning(
        "⚠️ در حال استفاده از توکن/رمز پیش‌فرضِ افشا شده در کد هستید! "
        "لطفاً BOT_TOKEN و ADMIN_PASSWORD را از طریق Environment Variables ست کنید "
        "و توکن قبلی را از BotFather ریوک کنید."
    )

# threaded=True برای پاسخگویی هم‌زمان به چند کاربر لازم است (مخصوصاً موقع فروش)
# ولی تعداد thread پیش‌فرض کتابخانه (2) برای بار همزمان کم است؛ افزایش داده شد.
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=8)

# User and Admin Session States
user_steps = {}
user_data = {}
admin_steps = {}
admin_sessions = set()  # Keeps track of authenticated admin chat IDs

# این دیکشنری‌ها بین ترد‌های مختلف کتابخانه‌ی telebot به‌صورت مشترک
# خوانده/نوشته می‌شوند. یک قفل سراسری سبک برای جلوگیری از هر گونه
# ناسازگاری state بین کاربران/ادمین‌ها استفاده می‌شود.
_state_lock = threading.RLock()


def set_step(store, chat_id, step):
    with _state_lock:
        store[chat_id] = step


def clear_step(store, chat_id):
    with _state_lock:
        store.pop(chat_id, None)


def set_user_data(chat_id, data):
    with _state_lock:
        user_data[chat_id] = data


def clear_user_data(chat_id):
    with _state_lock:
        user_data.pop(chat_id, None)


def add_admin_session(chat_id):
    with _state_lock:
        admin_sessions.add(chat_id)


def remove_admin_session(chat_id):
    with _state_lock:
        admin_sessions.discard(chat_id)


MAX_JOIN_CHANNELS = 6
MAX_PLANS = 12

MAIN_MENU_TEXTS = {
    '🛍 خرید اشتراک', '🏷 نرخ و تعرفه‌ها', '📦 اشتراک های من',
    '🎫 وضعیت سفارش', '📚 آموزش استفاده', '👨‍💻 پشتیبانی'
}
ADMIN_MENU_TEXTS = {
    '🧾 بررسی پرداختی ها (صف)', '📊 آمار ربات', '💳 تنظیمات کارت',
    '📢 تنظیم کانال های جوین', '⚙️ تنظیم پلن ها', '🔙 خروج از پنل'
}

# ------------------------------------------------------------------------------
# دکوراتور مدیریت خطای سراسری برای هندلرها
#
# نسبت به نسخه‌ی قبلی سه قابلیت اضافه شد:
#   1) اندازه‌گیری زمان اجرای هندلر و ثبت هشدار برای هندلرهای کند.
#   2) تفکیک خطاهای بی‌ضرر تلگرام (callback منقضی‌شده / کاربر ربات را
#      بلاک کرده) از خطاهای واقعی، تا نه errors.log شلوغ شود و نه کاربر
#      پیام هشدار نادرست ببیند.
#   3) خطاهای واقعی همچنان کامل (با traceback) در errors.log ثبت می‌شوند
#      و کاربر یک پیام کوتاه دریافت می‌کند؛ کارکرد ربات برای بقیه مختل
#      نمی‌شود.
# ------------------------------------------------------------------------------

def _extract_chat_id(update_obj):
    if hasattr(update_obj, 'chat') and update_obj.chat:
        return update_obj.chat.id
    if hasattr(update_obj, 'message') and update_obj.message:
        return update_obj.message.chat.id
    return None


def _notify_user_of_error(update_obj):
    try:
        chat_id = _extract_chat_id(update_obj)
        if chat_id is not None:
            bot.send_message(
                chat_id,
                '⚠️ متاسفانه در پردازش درخواست شما خطایی رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.'
            )
    except Exception:
        logger.error("ارسال پیام خطا به کاربر هم ناموفق بود:\n%s", traceback.format_exc())


def safe_handler(func):
    @functools.wraps(func)
    def wrapper(update_obj, *args, **kwargs):
        start_ts = time.monotonic()
        try:
            result = func(update_obj, *args, **kwargs)
            elapsed = time.monotonic() - start_ts
            if elapsed > SLOW_HANDLER_THRESHOLD_SECONDS:
                logger.warning(
                    "هندلر '%s' کندتر از حد انتظار اجرا شد: %.2f ثانیه (chat_id=%s).",
                    func.__name__, elapsed, _extract_chat_id(update_obj)
                )
            return result
        except ApiTelegramException as e:
            error_code = getattr(e, 'error_code', None)
            error_desc = str(e).lower()

            if error_code == 400 and 'too old' in error_desc:
                # کلیک روی دکمه‌ای که خیلی قدیمی/منقضی شده (مثلاً از قبل از
                # ری‌استارت ربات). خطای واقعی کاربر نیست؛ نیازی به پیام یا
                # ثبت در errors.log نیست.
                logger.info(
                    "هندلر '%s': callback منقضی‌شده نادیده گرفته شد (chat_id=%s).",
                    func.__name__, _extract_chat_id(update_obj)
                )
                return

            if error_code == 403:
                # کاربر ربات را بلاک کرده یا دسترسی به چت را گرفته؛ تلاش
                # برای ارسال پیام خطا هم بی‌فایده است.
                logger.warning(
                    "هندلر '%s': دسترسی به کاربر ممکن نیست (403 - احتمالاً بلاک شده). chat_id=%s",
                    func.__name__, _extract_chat_id(update_obj)
                )
                return

            logger.error("خطای API تلگرام در هندلر '%s':\n%s", func.__name__, traceback.format_exc())
            _notify_user_of_error(update_obj)
        except Exception:
            logger.error("خطا در هندلر '%s':\n%s", func.__name__, traceback.format_exc())
            _notify_user_of_error(update_obj)
    return wrapper


def safe_answer_callback(call_id, text=None, show_alert=False):
    """جایگزین امنِ bot.answer_callback_query — خطای «callback منقضی‌شده»
    را به‌صورت INFO لاگ می‌کند و بالا نمی‌کشد، تا بقیه‌ی هندلر ادامه پیدا
    کند و کاربر پیام گمراه‌کننده نبیند."""
    try:
        bot.answer_callback_query(call_id, text=text, show_alert=show_alert)
    except ApiTelegramException as e:
        error_code = getattr(e, 'error_code', None)
        if error_code == 400 and 'too old' in str(e).lower():
            logger.info("Callback query %s منقضی شده بود؛ نادیده گرفته شد.", call_id)
        else:
            logger.warning("answer_callback_query ناموفق بود (call_id=%s): %s", call_id, e)


# ------------------------------------------------------------------------------
# Core Database & System Settings Logic
#
# کانکشن با context manager واقعی مدیریت می‌شود (commit/rollback/close
# تضمین‌شده در finally). دیتابیس روی WAL mode + busy_timeout است تا
# نوشتن/خواندن همزمان (چند خرید/تایید هم‌زمان) بدون خطای "database is
# locked" انجام شود. یک ترد پس‌زمینه هم به‌صورت دوره‌ای WAL checkpoint
# می‌زند تا فایل wal- بی‌رویه بزرگ نشود.
# ------------------------------------------------------------------------------

@contextmanager
def db_connect():
    """Establishes connection to the SQLite database with dict row formatting."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA busy_timeout=10000')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initializes database schema and populates default settings if missing."""
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

        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT
        )''')

        # ایندکس روی status چون در چک صف پرداختی‌ها و آمار زیاد استفاده می‌شود.
        c.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)')

        default_settings = {
            'card_number': '6063731265163478',
            'card_name': 'امیرمحمد عزیزی',
            'support_username': '@ADRNALEN_0',
            'channels': '[]',
            'plans': json.dumps([
                {"id": 1, "name": "10 گیگ یک ماهه", "price": "110000", "days": 30},
                {"id": 2, "name": "20 گیگ یک ماهه", "price": "200000", "days": 30},
                {"id": 3, "name": "50 گیگ یک ماهه", "price": "380000", "days": 30},
                {"id": 4, "name": "100 گیگ دو ماهه", "price": "450000", "days": 60},
                {"id": 5, "name": "200 گیگ چهار ماهه", "price": "600000", "days": 120}
            ])
        }

        for key, value in default_settings.items():
            c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))


class SettingsCache:
    """
    کش درون‌حافظه‌ای تنظیمات (کارت، کانال‌ها، پلن‌ها و ...).

    ناکارآمدی قبلی: get_setting() برای هر کلیک دکمه (باز کردن منو، دیدن
    قیمت‌ها، چک جوین و...) یک اتصال SQLite جدید باز می‌کرد و یک SELECT
    می‌زد. زیر بار همزمان بالا (مثلاً چند صد کاربر هم‌زمان روی منوها) این
    فشار غیرضروری روی دیتابیس ایجاد می‌کند، درحالی‌که این تنظیمات به‌ندرت
    تغییر می‌کنند.

    الان همه‌ی تنظیمات یک‌بار در استارت لود می‌شوند و در حافظه (با قفل)
    نگه داشته می‌شوند؛ فقط زمان واقعیِ تغییر (توسط ادمین) هم دیتابیس و هم
    کش به‌روزرسانی می‌شوند.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._data = {}

    def load_all(self):
        with db_connect() as conn:
            rows = conn.execute('SELECT key, value FROM settings').fetchall()
        with self._lock:
            self._data = {row['key']: row['value'] for row in rows}
        logger.info("کش تنظیمات بارگذاری شد (%d کلید).", len(self._data))

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value):
        with db_connect() as conn:
            conn.execute('UPDATE settings SET value=? WHERE key=?', (value, key))
        with self._lock:
            self._data[key] = value


settings_cache = SettingsCache()


def get_setting(key):
    """Fetch setting value by key (از کش درون‌حافظه‌ای، نه دیتابیس)."""
    return settings_cache.get(key)


def update_setting(key, value):
    """Update setting key با نوشتن هم‌زمان روی دیتابیس و کش."""
    settings_cache.set(key, value)


def get_plans_list():
    """پارس امن لیست پلن‌ها از تنظیمات؛ در صورت خطا لیست خالی برمی‌گرداند."""
    try:
        return json.loads(get_setting('plans') or '[]')
    except Exception:
        logger.error("خطا در پارس کردن plans از تنظیمات:\n%s", traceback.format_exc())
        return []


def save_plans_list(plans):
    update_setting('plans', json.dumps(plans))


def get_channels_list():
    """پارس امن لیست کانال‌های جوین اجباری."""
    try:
        return [c for c in json.loads(get_setting('channels') or '[]') if c]
    except Exception:
        logger.error("خطا در پارس کردن channels از تنظیمات:\n%s", traceback.format_exc())
        return []


def save_channels_list(channels):
    update_setting('channels', json.dumps(channels))


def register_user(user):
    """Register or update user details in the database."""
    with db_connect() as conn:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute('''
            INSERT INTO users (user_id, username, first_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=?, first_name=?
        ''', (user.id, user.username, user.first_name, now, user.username, user.first_name))


WAL_CHECKPOINT_INTERVAL_SECONDS = 600  # هر ۱۰ دقیقه


def _wal_checkpoint_worker():
    """چک‌پوینت دوره‌ای WAL در پس‌زمینه؛ جلوگیری از رشد بی‌رویه‌ی فایل
    v2ray_shop.db-wal زیر بار نوشتن مداوم (سفارش‌ها، تایید/رد و...)."""
    while True:
        time.sleep(WAL_CHECKPOINT_INTERVAL_SECONDS)
        try:
            with db_connect() as conn:
                conn.execute('PRAGMA wal_checkpoint(PASSIVE)')
        except Exception:
            logger.warning("چک‌پوینت دوره‌ای WAL ناموفق بود:\n%s", traceback.format_exc())


init_db()
settings_cache.load_all()
threading.Thread(target=_wal_checkpoint_worker, name='wal-checkpoint', daemon=True).start()

# ------------------------------------------------------------------------------
# چک جوین اجباری (Force Join Check)
#
# نکات کلیدی (از نسخه‌ی قبلی حفظ شدند، مهم‌ترین دلیل احتمالی قطعی موقع فروش):
#   1) نتیجه‌ی هر کاربر برای چند دقیقه کش می‌شود -> تعداد درخواست به تلگرام
#      به‌شدت کم می‌شود.
#   2) خطای Flood Control (429) و خطای عدم دسترسی ربات به کانال (چون ادمین
#      کانال نیست) از "کاربر عضو نیست" تفکیک می‌شوند: این‌ها مشکل پیکربندی/
#      نرخ درخواست هستند نه تقصیر کاربر، پس fail-open می‌شوند (کاربر عبور
#      می‌کند) و در errors.log با جزئیات کامل ثبت می‌شوند.
# ------------------------------------------------------------------------------

_join_cache = {}          # user_id -> (checked_at_ts, is_joined)
JOIN_CACHE_TTL_SECONDS = 300


def check_force_join(user_id):
    """Checks whether user has joined all required Telegram channels (with caching)."""
    channels = get_channels_list()

    if not channels:
        return True

    now_ts = time.time()
    cached = _join_cache.get(user_id)
    if cached and (now_ts - cached[0]) < JOIN_CACHE_TTL_SECONDS:
        return cached[1]

    joined = True
    for channel in channels:
        try:
            member = bot.get_chat_member(channel, user_id)
            if member.status in ('left', 'kicked'):
                joined = False
                break
        except ApiTelegramException as e:
            error_code = getattr(e, 'error_code', None)
            if error_code == 429:
                logger.warning(
                    "Flood control از تلگرام موقع چک جوین کانال %s (کاربر %s). "
                    "برای جلوگیری از قطعی فروش، این بار عبور داده شد.", channel, user_id
                )
            else:
                logger.error(
                    "خطای پیکربندی در چک عضویت کانال %s (کد %s): %s. "
                    "احتمالاً ربات در این کانال ادمین نیست.", channel, error_code, e
                )
            _join_cache[user_id] = (now_ts, True)
            return True
        except Exception:
            logger.warning("خطای غیرمنتظره در چک عضویت کانال %s:\n%s", channel, traceback.format_exc())
            _join_cache[user_id] = (now_ts, True)
            return True

    _join_cache[user_id] = (now_ts, joined)
    return joined


def invalidate_join_cache(user_id=None):
    """پاک‌کردن کش جوین؛ وقتی ادمین لیست کانال‌ها را تغییر می‌دهد باید صدا زده شود."""
    if user_id is None:
        _join_cache.clear()
    else:
        _join_cache.pop(user_id, None)


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
# ==========================================

@bot.message_handler(commands=['start', 'help'])
@safe_handler
def start_cmd(message):
    register_user(message.from_user)

    if not check_force_join(message.chat.id):
        channels = get_channels_list()
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
@safe_handler
def handle_join_check_callback(call):
    invalidate_join_cache(call.from_user.id)
    if check_force_join(call.from_user.id):
        safe_answer_callback(call.id, '✅ عضویت شما تایید شد!')
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(
            call.message.chat.id,
            'خوش آمدید! لطفاً از منوی زیر استفاده کنید:',
            reply_markup=main_menu_keyboard()
        )
    else:
        safe_answer_callback(call.id, '❌ شما هنوز در تمام کانال‌ها عضو نشده‌اید!', show_alert=True)

@bot.message_handler(func=lambda m: m.text == '🛍 خرید اشتراک')
@safe_handler
def buy_subscription(message):
    if not check_force_join(message.chat.id):
        return start_cmd(message)

    plans = get_plans_list()
    if not plans:
        bot.send_message(message.chat.id, '⚠️ در حال حاضر پلنی برای فروش تعریف نشده است.')
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for plan in plans:
        btn_text = f"💎 {plan['name']} | 💳 {plan['price']} تومان"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"plan_{plan['id']}"))

    bot.send_message(message.chat.id, '📋 **لطفا یکی از پلن های زیر را برای خرید انتخاب کنید:**', reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('plan_'))
@safe_handler
def handle_plan_selection(call):
    plan_id = int(call.data.split('_')[1])
    plans = get_plans_list()
    selected_plan = next((plan for plan in plans if plan['id'] == plan_id), None)

    if not selected_plan:
        safe_answer_callback(call.id, '❌ پلن انتخاب شده معتبر نیست.')
        return

    safe_answer_callback(call.id)
    set_step(user_steps, call.from_user.id, 'wait_for_sub_name')
    set_user_data(call.from_user.id, {'plan': selected_plan})

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f'شما پلن **{selected_plan["name"]}** را انتخاب کردید.\n\n'
            '✍️ لطفاً یک **نام انگلیسی** دلخواه برای اشتراک خود بفرستید (مثلا `user123`):'
        ),
        parse_mode='Markdown'
    )


def dispatch_main_menu(message):
    """
    اگر کاربر وسط یک مرحله‌ی چندقسمتی (مثلاً وارد کردن نام اشتراک) روی یکی
    از دکمه‌های منوی اصلی بزند، این تابع درخواست منو را به هندلر واقعی‌اش
    هدایت می‌کند (به‌جای این‌که به‌عنوان ورودی همان مرحله تفسیر شود).
    """
    handlers_map = {
        '🛍 خرید اشتراک': buy_subscription,
        '🏷 نرخ و تعرفه‌ها': show_price_list,
        '📦 اشتراک های من': my_subscriptions,
        '🎫 وضعیت سفارش': order_status,
        '📚 آموزش استفاده': usage_guide,
        '👨‍💻 پشتیبانی': support_info,
    }
    handler = handlers_map.get(message.text)
    if handler:
        handler(message)


def cancel_current_purchase_step(chat_id):
    clear_step(user_steps, chat_id)
    clear_user_data(chat_id)


@bot.message_handler(func=lambda m: user_steps.get(m.chat.id) == 'wait_for_sub_name')
@safe_handler
def handle_sub_name(message):
    if message.text == '/start':
        cancel_current_purchase_step(message.chat.id)
        return start_cmd(message)
    if message.text in MAIN_MENU_TEXTS:
        cancel_current_purchase_step(message.chat.id)
        return dispatch_main_menu(message)

    sub_name = message.text.strip() if message.text else ''
    if not sub_name or len(sub_name) < 2:
        bot.send_message(message.chat.id, '⚠️ لطفاً یک نام معتبر و حداقل ۲ کاراکتری وارد کنید.')
        return

    state = user_data.get(message.chat.id)
    if not state or 'plan' not in state:
        bot.send_message(message.chat.id, '❌ خطایی رخ داد. لطفاً دوباره از منوی «🛍 خرید اشتراک» شروع کنید.')
        cancel_current_purchase_step(message.chat.id)
        return

    state['sub_name'] = sub_name
    clear_step(user_steps, message.chat.id)

    plan = state['plan']
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
@safe_handler
def ask_for_receipt(call):
    safe_answer_callback(call.id)
    set_step(user_steps, call.from_user.id, 'wait_for_receipt_photo')
    bot.send_message(call.message.chat.id, '📸 لطفاً تصویر رسید پرداختی خود را ارسال کنید:')

@bot.message_handler(content_types=['photo'], func=lambda m: user_steps.get(m.chat.id) == 'wait_for_receipt_photo')
@safe_handler
def receive_receipt(message):
    photo_id = message.photo[-1].file_id
    state = user_data.get(message.chat.id) or {}
    plan = state.get('plan')
    sub_name = state.get('sub_name')

    if not plan or not sub_name:
        bot.send_message(message.chat.id, '❌ خطایی در ثبت اطلاعات رخ داد. لطفاً مجدداً خرید را آغاز کنید.')
        cancel_current_purchase_step(message.chat.id)
        return

    with db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO payments (user_id, plan_details, sub_name, photo_id, status, plan_days) VALUES (?, ?, ?, ?, ?, ?)',
            (message.chat.id, plan['name'], sub_name, photo_id, 'pending', plan.get('days', 30))
        )
        payment_id = cursor.lastrowid

    cancel_current_purchase_step(message.chat.id)

    audit_logger.info(
        "سفارش جدید ثبت شد: #%s | کاربر=%s | پلن=%s", payment_id, message.chat.id, plan['name']
    )

    bot.send_message(
        message.chat.id,
        '✅ **رسید شما با موفقیت ثبت شد.**\nسفارش شما در صف بررسی توسط پشتیبانی قرار گرفت و به محض تایید، کانفیگ ارسال می‌شود.'
    )

    for admin_id in list(admin_sessions):
        try:
            bot.send_message(admin_id, f"🔔 **فیش جدید دریافت شد!** (سفارش #{payment_id})\nبرای بررسی به بخش صف پرداختی‌ها بروید.")
        except Exception:
            logger.warning("ارسال اعلان به ادمین %s ناموفق بود:\n%s", admin_id, traceback.format_exc())


@bot.message_handler(content_types=['text'], func=lambda m: user_steps.get(m.chat.id) == 'wait_for_receipt_photo')
@safe_handler
def receipt_wait_text_fallback(message):
    if message.text == '/start':
        cancel_current_purchase_step(message.chat.id)
        return start_cmd(message)
    if message.text in MAIN_MENU_TEXTS:
        cancel_current_purchase_step(message.chat.id)
        return dispatch_main_menu(message)
    bot.send_message(message.chat.id, '📸 لطفاً تصویر (عکس) رسید پرداخت را ارسال کنید، نه متن.')


@bot.message_handler(func=lambda m: m.text == '📦 اشتراک های من')
@safe_handler
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
            f'🔑 **کانفیگ شما:**\n<code>{html.escape(row["config"] or "")}</code>'
        )
        bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == '🎫 وضعیت سفارش')
@safe_handler
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
@safe_handler
def usage_guide(message):
    guide_text = (
        '📚 **راهنمای جامع اتصال و دانلود برنامه‌ها:**\n\n'
        '1️⃣ **دانلود نرم‌افزار:**\n\n'
        '🤖 **اندروید (Android):**\n'
        '• ⭐ [v2rayNG (پیشنهادی - ریلیس رسمی)](https://github.com/2dust/v2rayNG/releases)\n'
        '• [NekoBox (گیت‌هاب)](https://github.com/MatsuriDayo/NekoBoxForAndroid/releases)\n\n'
        '• [v2Box (Google Play)](https://play.google.com/store/search?q=v2box&c=apps)\n\n'
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
@safe_handler
def show_price_list(message):
    """Displays all subscription plans and prices in a single unified message."""
    if not check_force_join(message.chat.id):
        return start_cmd(message)

    plans = get_plans_list()
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
@safe_handler
def support_info(message):
    """Displays customer support contact information."""
    support_username = html.escape(get_setting('support_username') or '@Support')
    bot.send_message(
        message.chat.id,
        f'👨‍💻 <b>پشتیبانی ربات:</b>\n\n'
        f'جهت ارتباط با پشتیبانی، پاسخگویی به سوالات و یا پیگیری مشکلات، با آیدی زیر در تماس باشید:\n\n'
        f'💬 {support_username}',
        parse_mode='HTML'
    )

# ==========================================
# بخش مدیریت (Admin Side - دکمه‌های شیشه‌ای)
# ==========================================

@bot.message_handler(commands=['admin'])
@safe_handler
def admin_login(message):
    """Prompts the user for the admin password."""
    set_step(admin_steps, message.chat.id, 'wait_for_password')
    bot.send_message(message.chat.id, '🔐 لطفا رمز عبور پنل مدیریت را وارد کنید:')

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_for_password')
@safe_handler
def check_admin_password(message):
    """Verifies the admin password and unlocks admin privileges."""
    entered = message.text or ''
    # مقایسه‌ی رمز با hmac.compare_digest برای جلوگیری از timing attack.
    if hmac.compare_digest(entered, ADMIN_PASSWORD):
        set_step(admin_steps, message.chat.id, 'admin_panel')
        add_admin_session(message.chat.id)
        audit_logger.info("ورود موفق ادمین: chat_id=%s", message.chat.id)
        bot.send_message(
            message.chat.id,
            '✅ با موفقیت وارد پنل مدیریت شدید.',
            reply_markup=admin_menu_keyboard()
        )
    else:
        audit_logger.warning("تلاش ناموفق برای ورود به پنل ادمین از chat_id=%s", message.chat.id)
        bot.send_message(message.chat.id, '❌ رمز عبور اشتباه است.')
        clear_step(admin_steps, message.chat.id)

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'admin_panel')
@safe_handler
def admin_panel_handler(message):
    """Handles admin menu navigation."""
    if message.text == '🔙 خروج از پنل':
        clear_step(admin_steps, message.chat.id)
        remove_admin_session(message.chat.id)
        audit_logger.info("خروج ادمین از پنل: chat_id=%s", message.chat.id)
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
        set_step(admin_steps, message.chat.id, 'wait_for_new_card')
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
    channels = get_channels_list()

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
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
        except Exception:
            logger.info("edit_message_text (channels) نیازی به تغییر نداشت یا خطای جزئی رخ داد.")
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

def show_admin_plans_menu(chat_id, message_id=None):
    """Displays subscription plans management interface using interactive inline buttons."""
    plans = get_plans_list()

    markup = types.InlineKeyboardMarkup(row_width=1)

    if plans:
        text = "⚙️ **لیست پلن‌های فعال فروش:**\nبرای حذف هر پلن روی آن کلیک کنید:\n"
        for plan in plans:
            price_str = str(plan.get('price', '0'))
            price_formatted = f"{int(price_str):,}" if price_str.isdigit() else price_str
            btn_text = f"❌ {plan['name']} | {price_formatted} تومان ({plan['days']} روز)"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"adm_del_plan_{plan['id']}"))
    else:
        text = "⚙️ **هیچ پلن فروشی تعریف نشده است.**"

    if len(plans) < MAX_PLANS:
        markup.add(types.InlineKeyboardButton("➕ افزودن پلن جدید", callback_data="adm_add_plan"))

    if plans:
        markup.add(types.InlineKeyboardButton("🗑 پاک‌سازی تمام پلن‌ها", callback_data="adm_clear_plans"))

    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
        except Exception:
            logger.info("edit_message_text (plans) نیازی به تغییر نداشت یا خطای جزئی رخ داد.")
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
@safe_handler
def handle_admin_inline_callbacks(call):
    """Handles admin inline keyboard button clicks for channels and plans."""
    if call.from_user.id not in admin_sessions:
        safe_answer_callback(call.id, '❌ دسترسی غیرمجاز. ابتدا وارد پنل شوید.', show_alert=True)
        return

    data = call.data

    # Channel Management Callbacks
    if data.startswith('adm_del_ch_'):
        idx = int(data.split('_')[-1])
        channels = get_channels_list()
        if 0 <= idx < len(channels):
            removed = channels.pop(idx)
            save_channels_list(channels)
            invalidate_join_cache()
            audit_logger.info("کانال %s توسط ادمین %s حذف شد.", removed, call.from_user.id)
            safe_answer_callback(call.id, f"✅ کانال {removed} حذف شد.")
            show_admin_channels_menu(call.message.chat.id, call.message.message_id)
        else:
            safe_answer_callback(call.id, "⚠️ این کانال قبلاً حذف شده بود.")

    elif data == 'adm_add_ch':
        channels = get_channels_list()
        if len(channels) >= MAX_JOIN_CHANNELS:
            safe_answer_callback(call.id, f"⚠️ حداکثر {MAX_JOIN_CHANNELS} کانال می‌توانید بگذارید.", show_alert=True)
            return
        set_step(admin_steps, call.from_user.id, 'wait_add_single_channel')
        bot.send_message(call.message.chat.id, "✍️ لطفاً آیدی کانال جدید را با **@** بفرستید (مثلا `@MyChannel`):", parse_mode='Markdown')
        safe_answer_callback(call.id)

    elif data == 'adm_clear_ch':
        save_channels_list([])
        invalidate_join_cache()
        audit_logger.info("تمامی کانال‌های جوین توسط ادمین %s پاک‌سازی شدند.", call.from_user.id)
        safe_answer_callback(call.id, "✅ تمامی کانال‌ها غیرفعال شدند.")
        show_admin_channels_menu(call.message.chat.id, call.message.message_id)

    # Plan Management Callbacks
    elif data.startswith('adm_del_plan_'):
        plan_id = int(data.split('_')[-1])
        plans = get_plans_list()
        plans = [p for p in plans if p['id'] != plan_id]
        save_plans_list(plans)
        audit_logger.info("پلن #%s توسط ادمین %s حذف شد.", plan_id, call.from_user.id)
        safe_answer_callback(call.id, "✅ پلن با موفقیت حذف شد.")
        show_admin_plans_menu(call.message.chat.id, call.message.message_id)

    elif data == 'adm_add_plan':
        plans = get_plans_list()
        if len(plans) >= MAX_PLANS:
            safe_answer_callback(call.id, f"⚠️ حداکثر {MAX_PLANS} پلن می‌توانید تعریف کنید.", show_alert=True)
            return
        set_step(admin_steps, call.from_user.id, 'wait_add_single_plan')
        guide = (
            "✍️ لطفاً مشخصات پلن جدید را در **یک خط** به شکل زیر ارسال کنید:\n\n"
            "`نام پلن | قیمت (تومان) | تعداد روز اعتبار`\n\n"
            "مثال:\n"
            "`30 گیگ یک ماهه | 50000 | 30`"
        )
        bot.send_message(call.message.chat.id, guide, parse_mode='Markdown')
        safe_answer_callback(call.id)

    elif data == 'adm_clear_plans':
        save_plans_list([])
        audit_logger.info("تمامی پلن‌ها توسط ادمین %s پاک‌سازی شدند.", call.from_user.id)
        safe_answer_callback(call.id, "✅ تمامی پلن‌ها حذف شدند.")
        show_admin_plans_menu(call.message.chat.id, call.message.message_id)

def _handle_admin_text_step_interrupt(message):
    """
    اگر ادمین وسط یک ورودی متنی (کارت جدید/کانال جدید/پلن جدید) یکی از
    دکمه‌های پنل مدیریت یا /start را بزند، به‌جای رد شدن به‌عنوان ورودی
    نامعتبر، عملیات را لغو و به همان مقصد هدایت می‌کند.
    برمی‌گرداند True اگر پیام مصرف/هندل شد.
    """
    if message.text == '/start':
        set_step(admin_steps, message.chat.id, 'admin_panel')
        start_cmd(message)
        return True
    if message.text in ADMIN_MENU_TEXTS:
        set_step(admin_steps, message.chat.id, 'admin_panel')
        admin_panel_handler(message)
        return True
    return False


@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_add_single_channel')
@safe_handler
def add_single_channel_handler(message):
    if _handle_admin_text_step_interrupt(message):
        return

    ch_text = message.text.strip() if message.text else ''
    if not ch_text.startswith('@'):
        bot.send_message(message.chat.id, "❌ آیدی کانال باید با `@` شروع شود. دوباره تلاش کنید:")
        return

    channels = get_channels_list()
    if ch_text in channels:
        bot.send_message(message.chat.id, "⚠️ این کانال قبلاً اضافه شده است.")
    else:
        channels.append(ch_text)
        save_channels_list(channels)
        invalidate_join_cache()
        audit_logger.info("کانال %s توسط ادمین %s اضافه شد.", ch_text, message.chat.id)
        bot.send_message(message.chat.id, f"✅ کانال {ch_text} با موفقیت اضافه شد.")

    set_step(admin_steps, message.chat.id, 'admin_panel')
    show_admin_channels_menu(message.chat.id)

@bot.message_handler(func=lambda m: admin_steps.get(m.chat.id) == 'wait_add_single_plan')
@safe_handler
def add_single_plan_handler(message):
    if _handle_admin_text_step_interrupt(message):
        return

    try:
        parts = [part.strip() for part in (message.text or '').strip().split('|')]
        if len(parts) < 3:
            raise ValueError("ورودی ناقص است.")

        name, price, days_str = parts[0], parts[1], parts[2]

        if not name:
            raise ValueError("نام پلن نمی‌تواند خالی باشد.")
        if not price.isdigit():
            raise ValueError("قیمت باید فقط شامل عدد باشد.")
        days = int(days_str)
        if days <= 0:
            raise ValueError("تعداد روز باید بزرگ‌تر از صفر باشد.")

        plans = get_plans_list()

        new_id = max([p['id'] for p in plans], default=0) + 1
        plans.append({'id': new_id, 'name': name, 'price': price, 'days': days})

        save_plans_list(plans)
        audit_logger.info("پلن جدید «%s» توسط ادمین %s اضافه شد.", name, message.chat.id)
        bot.send_message(message.chat.id, f"✅ پلن **{name}** با موفقیت اضافه شد.", parse_mode='Markdown')
    except Exception as e:
        logger.info("ورودی پلن نامعتبر از ادمین %s: %s", message.chat.id, e)
        bot.send_message(
            message.chat.id,
            f"❌ فرمت ارسال اشتباه است ({e}).\nمثال صحیح:\n`30 گیگ یک ماهه | 50000 | 30`",
            parse_mode='Markdown'
        )

    set_step(admin_steps, message.chat.id, 'admin_panel')
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
@safe_handler
def update_card_info(message):
    """Updates card details in the database."""
    if _handle_admin_text_step_interrupt(message):
        return

    try:
        parts = (message.text or '').strip().split('\n', 1)
        if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
            raise ValueError("فرمت ورودی نادرست است.")

        card, name = parts[0].strip(), parts[1].strip()
        update_setting('card_number', card)
        update_setting('card_name', name)
        audit_logger.info("اطلاعات کارت توسط ادمین %s بروزرسانی شد (کارت جدید: %s).", message.chat.id, card)
        bot.send_message(message.chat.id, '✅ اطلاعات کارت با موفقیت بروزرسانی شد.')
    except Exception as e:
        bot.send_message(message.chat.id, f'❌ فرمت اشتباه است. تغییر کارت لغو شد: {e}')

    set_step(admin_steps, message.chat.id, 'admin_panel')

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

    try:
        bot.send_photo(admin_chat_id, row['photo_id'], caption=caption, reply_markup=markup, parse_mode='Markdown')
    except Exception:
        logger.error("ارسال عکس رسید #%s ناموفق بود:\n%s", row['id'], traceback.format_exc())
        bot.send_message(
            admin_chat_id,
            f"⚠️ نمایش عکس رسید سفارش #{row['id']} با خطا مواجه شد (احتمالاً فایل نامعتبر است). جزئیات:\n\n{caption}",
            reply_markup=markup,
            parse_mode='Markdown'
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
@safe_handler
def handle_receipt_action(call):
    """Processes approval or rejection of user payment receipts."""
    action, payment_id = call.data.split('_', 1)

    # چک idempotent بودن: جلوگیری از پردازش دوگانه اگر دو ادمین هم‌زمان یا
    # یک ادمین دوبار سریع روی تایید/رد کلیک کند.
    with db_connect() as conn:
        row = conn.execute('SELECT status FROM payments WHERE id=?', (payment_id,)).fetchone()

    if not row:
        safe_answer_callback(call.id, '⚠️ سفارش یافت نشد.', show_alert=True)
        return
    if row['status'] != 'pending':
        safe_answer_callback(call.id, '⚠️ این سفارش قبلاً بررسی شده است.', show_alert=True)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        logger.info("حذف دکمه‌های پیام رسید ناموفق بود (احتمالاً پیام قبلاً تغییر کرده).")

    safe_answer_callback(call.id)

    if action == 'reject':
        with db_connect() as conn:
            cur = conn.execute("UPDATE payments SET status=? WHERE id=? AND status='pending'", ('rejected', payment_id))
            if cur.rowcount == 0:
                bot.send_message(call.message.chat.id, '⚠️ این سفارش هم‌زمان توسط جای دیگری پردازش شده بود.')
                return
            user_row = conn.execute('SELECT user_id FROM payments WHERE id=?', (payment_id,)).fetchone()

        audit_logger.info("سفارش #%s توسط ادمین %s رد شد.", payment_id, call.from_user.id)

        if user_row:
            try:
                bot.send_message(user_row['user_id'], '❌ متاسفانه فیش پرداختی شما توسط مدیریت رد شد.')
            except Exception:
                logger.warning("اطلاع رد سفارش #%s به کاربر ارسال نشد:\n%s", payment_id, traceback.format_exc())

        bot.send_message(call.message.chat.id, '❌ فیش رد شد. رفتن به فیش بعدی...')
        show_next_pending_receipt(call.message.chat.id)
        return

    set_step(admin_steps, call.from_user.id, f'wait_for_v2ray_config_{payment_id}')
    bot.send_message(call.message.chat.id, '🔑 لطفاً کانفیگ (V2Ray String) را برای این کاربر بفرستید:')

@bot.message_handler(func=lambda m: str(admin_steps.get(m.chat.id)).startswith('wait_for_v2ray_config_'))
@safe_handler
def receive_v2ray_config(message):
    """Receives V2Ray config string from admin and sends it to the user."""
    payment_id = admin_steps[message.chat.id].split('_')[-1]

    if message.text == '/start':
        set_step(admin_steps, message.chat.id, 'admin_panel')
        return start_cmd(message)
    if message.text in ADMIN_MENU_TEXTS:
        set_step(admin_steps, message.chat.id, 'admin_panel')
        return admin_panel_handler(message)

    config_string = (message.text or '').strip()

    if not config_string:
        bot.send_message(message.chat.id, '⚠️ کانفیگ نمی‌تواند خالی باشد. دوباره ارسال کنید:')
        return

    with db_connect() as conn:
        row = conn.execute('SELECT plan_days, user_id, sub_name, plan_details, status FROM payments WHERE id=?', (payment_id,)).fetchone()
        if not row:
            bot.send_message(message.chat.id, '⚠️ پرداخت یافت نشد.')
            set_step(admin_steps, message.chat.id, 'admin_panel')
            return
        if row['status'] != 'pending':
            bot.send_message(message.chat.id, '⚠️ این سفارش قبلاً پردازش شده (شاید توسط ادمین دیگری).')
            set_step(admin_steps, message.chat.id, 'admin_panel')
            show_next_pending_receipt(message.chat.id)
            return

        days = row['plan_days'] or 30
        purchase_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        expire_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

        cur = conn.execute(
            "UPDATE payments SET status=?, config=?, purchase_date=?, expire_date=? WHERE id=? AND status='pending'",
            ('approved', config_string, purchase_date, expire_date, payment_id)
        )
        if cur.rowcount == 0:
            bot.send_message(message.chat.id, '⚠️ این سفارش هم‌زمان توسط جای دیگری پردازش شده بود.')
            set_step(admin_steps, message.chat.id, 'admin_panel')
            show_next_pending_receipt(message.chat.id)
            return

    audit_logger.info(
        "سفارش #%s توسط ادمین %s تایید و کانفیگ برای کاربر %s ارسال شد.",
        payment_id, message.chat.id, row['user_id']
    )

    try:
        bot.send_message(
            row['user_id'],
            ('🎉 **پرداخت شما تایید شد!**\n\n'
             f'👤 **نام اشتراک:** `{row["sub_name"]}`\n'
             f'💎 **پلن:** {row["plan_details"]}\n'
             f'📅 **تاریخ خرید:** `{purchase_date}`\n'
             f'⏳ **تاریخ انقضا:** `{expire_date}`\n\n'
             f'🔑 **کانفیگ شما:**\n<code>{html.escape(config_string)}</code>'),
            parse_mode='HTML'
        )
    except Exception:
        logger.warning("ارسال کانفیگ سفارش #%s به کاربر %s ناموفق بود:\n%s", payment_id, row['user_id'], traceback.format_exc())
        bot.send_message(message.chat.id, '⚠️ کانفیگ در دیتابیس ثبت شد، ولی ارسال آن به کاربر با خطا مواجه شد (احتمالاً کاربر ربات را بلاک کرده است).')

    bot.send_message(message.chat.id, '✅ کانفیگ ارسال و سفارش تکمیل گردید. رفتن به فیش بعدی...')
    set_step(admin_steps, message.chat.id, 'admin_panel')
    show_next_pending_receipt(message.chat.id)


# ------------------------------------------------------------------------------
# مدیریت سراسری خطاهای بی‌نام (Uncaught) داخل خود کتابخانه‌ی telebot
# ------------------------------------------------------------------------------

class FileLoggingExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        logger.error(
            "خطای مدیریت‌نشده در telebot: %s\n%s",
            exception,
            traceback.format_exc()
        )
        return True  # جلوگیری از crash کردن polling loop


bot.exception_handler = FileLoggingExceptionHandler()


def _handle_shutdown_signal(signum, frame):
    """خاتمه‌ی امن روی SIGTERM/SIGINT (مثلاً systemctl stop یا Ctrl+C):
    وضعیت را در لاگ ثبت می‌کند و polling را متوقف می‌کند تا هیچ درخواستی
    نیمه‌کاره نماند."""
    logger.info("سیگنال خاتمه (%s) دریافت شد؛ در حال توقف امن ربات...", signum)
    try:
        bot.stop_polling()
    except Exception:
        pass
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_shutdown_signal)
signal.signal(signal.SIGINT, _handle_shutdown_signal)


def run_bot():
    """Starts the Telegram bot polling loop with automatic error recovery.

    نسبت به نسخه‌ی قبلی:
      - skip_pending=True: بعد از هر ری‌استارت، آپدیت‌های باقی‌مانده از
        دوران آفلاین (از جمله callbackهای منقضی‌شده که باعث خطای
        «query is too old» می‌شدند) دور ریخته می‌شوند به‌جای پردازش.
      - backoff نمایی (۵ تا ۶۰ ثانیه) روی خطای بحرانی حلقه، به‌جای تاخیر
        ثابت؛ هم فشار کمتری روی سرور/تلگرام موقع قطعی طولانی می‌آورد و هم
        در قطعی‌های کوتاه سریع ریکاوری می‌کند.
    """
    logger.info(f"V2Ray Shop Bot v{BOT_VERSION} در حال اجراست...")
    backoff = 5
    max_backoff = 60
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
            backoff = 5
        except Exception:
            logger.error("خطای بحرانی در حلقه‌ی polling:\n%s", traceback.format_exc())
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

# ==============================================================================
# V2Ray Shop Telegram Bot - Built by Hossein Ghorbani
# GitHub: https://github.com/Hosseinghorbani0
# All Rights Reserved
# ==============================================================================

if __name__ == '__main__':
    run_bot()

import asyncio
import os
import sqlite3
from datetime import datetime
from html import escape

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "taxi.db")
MANAGER_PHONE = os.getenv("MANAGER_PHONE", "+998771202255")
MANAGER_NAME = os.getenv("MANAGER_NAME", "Jamshidbek")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN .env faylida yoki Render Environment Variables ichida yo'q.")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            license_number TEXT NOT NULL,
            card_number TEXT NOT NULL,
            balance REAL DEFAULT 0,
            trips_today INTEGER DEFAULT 0,
            trips_week INTEGER DEFAULT 0,
            earnings_today REAL DEFAULT 0,
            earnings_week REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS withdraw_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            paid_at TEXT,
            FOREIGN KEY(driver_id) REFERENCES drivers(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            message TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(driver_id) REFERENCES drivers(id)
        )
    """)
    conn.commit()
    conn.close()

def get_driver(tg_id):
    conn = db()
    row = conn.execute("SELECT * FROM drivers WHERE telegram_id = ?", (tg_id,)).fetchone()
    conn.close()
    return row

def get_driver_by_id(driver_id):
    conn = db()
    row = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
    conn.close()
    return row

def create_driver(tg_id, username, full_name, phone, license_number, card_number):
    conn = db()
    conn.execute("""
        INSERT INTO drivers (telegram_id, username, full_name, phone, license_number, card_number)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tg_id, username, full_name, phone, license_number, card_number))
    conn.commit()
    conn.close()

def create_report(driver_id, report_type, message=""):
    conn = db()
    cur = conn.execute(
        "INSERT INTO reports (driver_id, report_type, message) VALUES (?, ?, ?)",
        (driver_id, report_type, message),
    )
    conn.commit()
    report_id = cur.lastrowid
    conn.close()
    return report_id

def create_withdraw(driver_id, amount):
    conn = db()
    cur = conn.execute(
        "INSERT INTO withdraw_requests (driver_id, amount) VALUES (?, ?)",
        (driver_id, amount),
    )
    conn.commit()
    withdraw_id = cur.lastrowid
    conn.close()
    return withdraw_id

def get_withdraw(withdraw_id):
    conn = db()
    row = conn.execute("""
        SELECT w.*, d.telegram_id, d.username, d.full_name, d.phone, d.license_number,
               d.card_number, d.balance
        FROM withdraw_requests w
        JOIN drivers d ON d.id = w.driver_id
        WHERE w.id = ?
    """, (withdraw_id,)).fetchone()
    conn.close()
    return row

def update_withdraw_status(withdraw_id, status):
    column = "reviewed_at" if status in ("reviewing", "rejected") else "paid_at"
    conn = db()
    conn.execute(
        f"UPDATE withdraw_requests SET status = ?, {column} = CURRENT_TIMESTAMP WHERE id = ?",
        (status, withdraw_id),
    )
    conn.commit()
    conn.close()

def update_driver_balance(driver_id, new_balance):
    conn = db()
    conn.execute("UPDATE drivers SET balance = ? WHERE id = ?", (new_balance, driver_id))
    conn.commit()
    conn.close()

def update_trips(driver_id, today_count, today_earn, week_count, week_earn):
    conn = db()
    conn.execute("""
        UPDATE drivers
        SET trips_today = ?, earnings_today = ?, trips_week = ?, earnings_week = ?
        WHERE id = ?
    """, (today_count, today_earn, week_count, week_earn, driver_id))
    conn.commit()
    conn.close()

def get_new_withdraws():
    conn = db()
    rows = conn.execute("""
        SELECT w.*, d.full_name, d.phone, d.license_number, d.card_number, d.balance, d.telegram_id
        FROM withdraw_requests w
        JOIN drivers d ON d.id = w.driver_id
        WHERE w.status IN ('new', 'reviewing')
        ORDER BY w.created_at DESC
    """).fetchall()
    conn.close()
    return rows

def get_paid_history(driver_id):
    conn = db()
    rows = conn.execute("""
        SELECT * FROM withdraw_requests
        WHERE driver_id = ? AND status = 'paid'
        ORDER BY created_at DESC
        LIMIT 10
    """, (driver_id,)).fetchall()
    conn.close()
    return rows

def get_stats():
    conn = db()
    drivers = conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]
    total_paid = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM withdraw_requests WHERE status = 'paid'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status IN ('new', 'reviewing')").fetchone()[0]
    reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    conn.close()
    return drivers, total_paid, pending, reports

def list_drivers_rows():
    conn = db()
    rows = conn.execute(
        "SELECT id, telegram_id, full_name, phone, license_number, balance FROM drivers ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows

init_db()

WELCOME_TEXT = (
    "Assalomu alaykum, hurmatli haydovchi!\n\n"
    "Yakomfort jamoamizga xush kelibsiz. Yakomfortda komissiya atigi 1%.\n\n"
    "Ro'yxatdan o'tish tugmasini bosib ro'yxatdan o'ting."
)

AFTER_REG_TEXT = (
    "Hurmatli haydovchi, biz bilan hamkorlik qilganingizdan mamnunmiz.\n\n"
    "Yo'lovchilar bilan har doim xushmuomala bo'ling. Xushmuomalalik ikki inson "
    "o'rtasidagi yaxshi kayfiyat garovidir!!!\n\n"
    "Hurmatli haydovchi, biz bilan daromadingizni oshiring.\n"
    "Siz muvaffaqiyatli ro'yxatdan o'tdingiz. Oq yo'l, hech qachon charchamang!!!"
)

MENU = {
    "balance": "Hisobni bilish",
    "topup": "Hisobni to'ldirish",
    "trips": "Qancha zakaz ishlangan",
    "withdraw": "Pul yechish",
    "sos": "SOS",
    "dtp": "DTP",
    "manager": "Menejer bilan bog'lanish",
    "history": "To'lovlar tarixi",
    "card": "Kartam",
}

def start_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Ro'yxatdan o'tish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU["balance"]), KeyboardButton(text=MENU["topup"])],
            [KeyboardButton(text=MENU["trips"]), KeyboardButton(text=MENU["withdraw"])],
            [KeyboardButton(text=MENU["sos"]), KeyboardButton(text=MENU["dtp"])],
            [KeyboardButton(text=MENU["manager"])],
            [KeyboardButton(text=MENU["history"]), KeyboardButton(text=MENU["card"])],
        ],
        resize_keyboard=True,
    )

def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Yangi pul yechish so'rovlari"), KeyboardButton(text="Statistika")],
            [KeyboardButton(text="Haydovchilar ro'yxati")],
            [KeyboardButton(text="Zakaz statistikasini yangilash")],
            [KeyboardButton(text="Balans qo'shish")],
        ],
        resize_keyboard=True,
    )

def withdraw_admin_keyboard(withdraw_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ko'rilmoqda", callback_data=f"review_{withdraw_id}")],
            [
                InlineKeyboardButton(text="To'lov amalga oshirildi", callback_data=f"pay_{withdraw_id}"),
                InlineKeyboardButton(text="Rad etish", callback_data=f"reject_{withdraw_id}"),
            ],
        ]
    )

class RegState(StatesGroup):
    name = State()
    phone = State()
    license_number = State()
    card = State()

class WithdrawState(StatesGroup):
    amount = State()

class ContactState(StatesGroup):
    message = State()

class AdminTripState(StatesGroup):
    driver_id = State()
    today_count = State()
    today_earn = State()
    week_count = State()
    week_earn = State()

class AdminBalanceState(StatesGroup):
    driver_id = State()
    amount = State()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

def now_text():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")

def money(value):
    return f"{int(value):,}".replace(",", " ")

def card_mask(card):
    digits = "".join(ch for ch in card if ch.isdigit())
    return f"****{digits[-4:]}" if len(digits) >= 4 else "****"

def driver_link(driver):
    return f'<a href="tg://user?id={driver["telegram_id"]}">{escape(driver["full_name"])}</a>'

def user_name(username):
    return f"@{username}" if username else "Yo'q"

async def notify_admin(text, reply_markup=None):
    if ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, text, reply_markup=reply_markup)
        except Exception as exc:
            print(f"Admin xabar yuborishda xatolik: {exc}")

async def notify_button_click(driver, button, extra=""):
    create_report(driver["id"], button, extra)
    text = (
        "Haydovchi tugma bosdi!\n\n"
        f"Haydovchi: {driver_link(driver)}\n"
        f"Telefon: {escape(driver['phone'])}\n"
        f"Guvohnoma: {escape(driver['license_number'])}\n"
        f"Telegram ID: <code>{driver['telegram_id']}</code>\n"
        f"Username: {escape(user_name(driver['username']))}\n"
        f"Tugma: <b>{escape(button)}</b>\n"
        f"Vaqt: {now_text()}"
    )
    await notify_admin(text)

async def require_driver(message):
    driver = get_driver(message.from_user.id)
    if not driver:
        await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())
        return None
    return driver

@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()

    if message.from_user.id == ADMIN_ID:
        await message.answer("Menejer paneli ochildi.", reply_markup=admin_keyboard())
        return

    driver = get_driver(message.from_user.id)
    if driver:
        await message.answer("Asosiy menyu:", reply_markup=main_keyboard())
        return

    await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())

@dp.message(F.text == "Ro'yxatdan o'tish")
async def reg_start(message: types.Message, state: FSMContext):
    if get_driver(message.from_user.id):
        await message.answer("Siz allaqachon ro'yxatdan o'tgansiz.", reply_markup=main_keyboard())
        return

    await state.set_state(RegState.name)
    await message.answer("Ism familiyangizni kiriting:", reply_markup=ReplyKeyboardRemove())

@dp.message(RegState.name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(RegState.phone)
    await message.answer("Telefon raqamingizni kiriting. Masalan: +998901234567")

@dp.message(RegState.phone)
async def reg_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await state.set_state(RegState.license_number)
    await message.answer("Haydovchilik guvohnomasi raqamini kiriting:")

@dp.message(RegState.license_number)
async def reg_license(message: types.Message, state: FSMContext):
    await state.update_data(license_number=message.text.strip().upper())
    await state.set_state(RegState.card)
    await message.answer("Bank karta raqamingizni kiriting:")

@dp.message(RegState.card)
async def reg_card(message: types.Message, state: FSMContext):
    if get_driver(message.from_user.id):
        await state.clear()
        await message.answer("Siz allaqachon ro'yxatdan o'tgansiz.", reply_markup=main_keyboard())
        return

    data = await state.get_data()
    username = message.from_user.username or ""
    create_driver(
        message.from_user.id,
        username,
        data["name"],
        data["phone"],
        data["license_number"],
        message.text.strip(),
    )
    driver = get_driver(message.from_user.id)

    admin_text = (
        "Yangi haydovchi ro'yxatdan o'tdi!\n\n"
        f"Ismi: {driver_link(driver)}\n"
        f"Telefon: {escape(driver['phone'])}\n"
        f"Haydovchilik guvohnomasi: {escape(driver['license_number'])}\n"
        f"Bank karta: {escape(card_mask(driver['card_number']))}\n"
        f"Telegram ID: <code>{driver['telegram_id']}</code>\n"
        f"Username: {escape(user_name(driver['username']))}\n"
        f"Vaqt: {now_text()}"
    )
    await notify_admin(admin_text)

    await message.answer(AFTER_REG_TEXT, reply_markup=main_keyboard())
    await state.clear()

@dp.message(F.text == MENU["balance"])
async def show_balance(message: types.Message):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["balance"])
    await message.answer(
        f"Hisobingiz: {money(driver['balance'])} so'm\n"
        f"Pul yechish mumkin: {money(driver['balance'])} so'm"
    )

@dp.message(F.text == MENU["topup"])
async def topup_request(message: types.Message):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["topup"])
    await message.answer(
        "Hisobni to'ldirish uchun menejer bilan bog'laning.\n\n"
        f"Salom, mening ismim {MANAGER_NAME}. Sizga qanday yordam kerak?\n"
        f"Zarur bo'lsa hoziroq quyidagi raqamga qo'ng'iroq qiling: {MANAGER_PHONE}"
    )

@dp.message(F.text == MENU["trips"])
async def show_trips(message: types.Message):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["trips"])
    await message.answer(
        "Zakaz statistikasi:\n\n"
        f"Bugun: {driver['trips_today']} ta / {money(driver['earnings_today'])} so'm\n"
        f"Hafta: {driver['trips_week']} ta / {money(driver['earnings_week'])} so'm"
    )

@dp.message(F.text == MENU["withdraw"])
async def withdraw_start(message: types.Message, state: FSMContext):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["withdraw"])

    if driver["balance"] <= 0:
        await message.answer("Hisobingizda pul yetarli emas.")
        return

    await state.update_data(driver_id=driver["id"])
    await state.set_state(WithdrawState.amount)
    await message.answer(f"Qancha pul yechmoqchisiz? Maksimum: {money(driver['balance'])} so'm")

@dp.message(F.text == MENU["sos"])
async def sos(message: types.Message):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["sos"])
    await message.answer("SOS xabaringiz menejerga yuborildi. Tez orada siz bilan bog'lanishadi.")

@dp.message(F.text == MENU["dtp"])
async def dtp(message: types.Message):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["dtp"])
    await message.answer("DTP xabaringiz menejerga yuborildi. Xavfsiz joyda turing va menejer qo'ng'irog'ini kuting.")

@dp.message(F.text == MENU["manager"])
async def contact_manager_start(message: types.Message, state: FSMContext):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["manager"])
    await state.set_state(ContactState.message)
    await message.answer(
        f"Salom, mening ismim {MANAGER_NAME}. Sizga qanday yordam kerak?\n\n"
        f"Zarur bo'lsa hoziroq quyidagi raqamga qo'ng'iroq qiling: {MANAGER_PHONE}\n\n"
        "Menejerga yuboriladigan xabaringizni yozing:"
    )

@dp.message(F.text == MENU["history"])
async def payment_history(message: types.Message):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["history"])
    rows = get_paid_history(driver["id"])
    if not rows:
        await message.answer("To'lovlar tarixi hozircha bo'sh.")
        return
    text = "Oxirgi to'lovlar:\n\n"
    for row in rows:
        text += f"#{row['id']} - {money(row['amount'])} so'm - {row['created_at'][:16]}\n"
    await message.answer(text)

@dp.message(F.text == MENU["card"])
async def my_card(message: types.Message):
    driver = await require_driver(message)
    if not driver:
        return
    await notify_button_click(driver, MENU["card"])
    await message.answer(f"Kartangiz: {card_mask(driver['card_number'])}")

@dp.message(WithdrawState.amount)
async def withdraw_amount(message: types.Message, state: FSMContext):
    text = message.text.replace(" ", "").replace(",", ".")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Iltimos, summani to'g'ri kiriting. Masalan: 150000")
        return

    data = await state.get_data()
    driver = get_driver_by_id(data["driver_id"])
    if not driver:
        await state.clear()
        return

    if amount > driver["balance"]:
        await message.answer(f"Hisobingizda yetarli pul yo'q. Mavjud: {money(driver['balance'])} so'm")
        return

    withdraw_id = create_withdraw(driver["id"], amount)
    await message.answer(
        f"So'rovingiz #{withdraw_id} menejerga yuborildi. Holati: yangi.",
        reply_markup=main_keyboard(),
    )

    admin_text = (
        f"Yangi pul yechish so'rovi #{withdraw_id}\n\n"
        f"Haydovchi: {driver_link(driver)}\n"
        f"Telefon: {escape(driver['phone'])}\n"
        f"Guvohnoma: {escape(driver['license_number'])}\n"
        f"Karta: {escape(card_mask(driver['card_number']))}\n"
        f"Telegram ID: <code>{driver['telegram_id']}</code>\n"
        f"Username: {escape(user_name(driver['username']))}\n"
        f"Hisob: {money(driver['balance'])} so'm\n"
        f"Yechish summasi: <b>{money(amount)} so'm</b>\n"
        f"Vaqt: {now_text()}"
    )
    await notify_admin(admin_text, reply_markup=withdraw_admin_keyboard(withdraw_id))
    await state.clear()

@dp.message(ContactState.message)
async def contact_manager_message(message: types.Message, state: FSMContext):
    driver = get_driver(message.from_user.id)
    if not driver:
        await state.clear()
        return

    create_report(driver["id"], MENU["manager"], message.text)
    admin_text = (
        "Menejerga murojaat!\n\n"
        f"Haydovchi: {driver_link(driver)}\n"
        f"Telefon: {escape(driver['phone'])}\n"
        f"Telegram ID: <code>{driver['telegram_id']}</code>\n"
        f"Xabar: {escape(message.text)}\n"
        f"Vaqt: {now_text()}"
    )
    await notify_admin(admin_text)
    await message.answer("Xabaringiz menejerga yuborildi.", reply_markup=main_keyboard())
    await state.clear()

@dp.message(F.text == "Yangi pul yechish so'rovlari")
async def admin_new_withdraws(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    rows = get_new_withdraws()
    if not rows:
        await message.answer("Yangi pul yechish so'rovlari yo'q.")
        return

    for row in rows:
        text = (
            f"Pul yechish so'rovi #{row['id']}\n\n"
            f"Haydovchi: {escape(row['full_name'])}\n"
            f"Telefon: {escape(row['phone'])}\n"
            f"Guvohnoma: {escape(row['license_number'])}\n"
            f"Karta: {escape(card_mask(row['card_number']))}\n"
            f"Telegram ID: <code>{row['telegram_id']}</code>\n"
            f"Hisob: {money(row['balance'])} so'm\n"
            f"Summa: <b>{money(row['amount'])} so'm</b>\n"
            f"Holat: {escape(row['status'])}"
        )
        await message.answer(text, reply_markup=withdraw_admin_keyboard(row["id"]))

@dp.message(F.text == "Statistika")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    drivers, total_paid, pending, reports = get_stats()
    await message.answer(
        "Statistika:\n\n"
        f"Haydovchilar: {drivers} ta\n"
        f"Jami to'langan: {money(total_paid)} so'm\n"
        f"Kutilayotgan pul yechish: {pending} ta\n"
        f"Tugma/xabarlar tarixi: {reports} ta"
    )

@dp.message(F.text == "Haydovchilar ro'yxati")
@dp.message(F.text == "/list_drivers")
async def admin_list_drivers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    rows = list_drivers_rows()
    if not rows:
        await message.answer("Haydovchilar ro'yxati bo'sh.")
        return
    text = "Haydovchilar ro'yxati:\n\n"
    for row in rows:
        text += (
            f"ID: {row['id']} | TG: {row['telegram_id']}\n"
            f"{escape(row['full_name'])}\n"
            f"Tel: {escape(row['phone'])} | Guvohnoma: {escape(row['license_number'])}\n"
            f"Hisob: {money(row['balance'])} so'm\n\n"
        )
    await message.answer(text)

@dp.message(F.text == "Zakaz statistikasini yangilash")
async def admin_trip_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminTripState.driver_id)
    await message.answer("Haydovchi ID raqamini kiriting. ID uchun /list_drivers dan foydalaning.")

@dp.message(AdminTripState.driver_id)
async def admin_trip_driver(message: types.Message, state: FSMContext):
    try:
        driver_id = int(message.text)
    except ValueError:
        await message.answer("Faqat ID raqamini kiriting.")
        return
    driver = get_driver_by_id(driver_id)
    if not driver:
        await message.answer("Bunday ID li haydovchi topilmadi.")
        await state.clear()
        return
    await state.update_data(driver_id=driver_id)
    await state.set_state(AdminTripState.today_count)
    await message.answer(f"{driver['full_name']} uchun bugungi zakaz sonini kiriting:")

@dp.message(AdminTripState.today_count)
async def admin_trip_today_count(message: types.Message, state: FSMContext):
    try:
        count = int(message.text)
    except ValueError:
        await message.answer("Faqat son kiriting.")
        return
    await state.update_data(today_count=count)
    await state.set_state(AdminTripState.today_earn)
    await message.answer("Bugungi daromadni kiriting:")

@dp.message(AdminTripState.today_earn)
async def admin_trip_today_earn(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("Summani son bilan kiriting.")
        return
    await state.update_data(today_earn=amount)
    await state.set_state(AdminTripState.week_count)
    await message.answer("Haftalik zakaz sonini kiriting:")

@dp.message(AdminTripState.week_count)
async def admin_trip_week_count(message: types.Message, state: FSMContext):
    try:
        count = int(message.text)
    except ValueError:
        await message.answer("Faqat son kiriting.")
        return
    await state.update_data(week_count=count)
    await state.set_state(AdminTripState.week_earn)
    await message.answer("Haftalik daromadni kiriting:")

@dp.message(AdminTripState.week_earn)
async def admin_trip_finish(message: types.Message, state: FSMContext):
    try:
        week_earn = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("Summani son bilan kiriting.")
        return

    data = await state.get_data()
    update_trips(
        data["driver_id"],
        data["today_count"],
        data["today_earn"],
        data["week_count"],
        week_earn,
    )
    driver = get_driver_by_id(data["driver_id"])
    await message.answer(
        "Zakaz statistikasi yangilandi:\n\n"
        f"{driver['full_name']}\n"
        f"Bugun: {data['today_count']} ta / {money(data['today_earn'])} so'm\n"
        f"Hafta: {data['week_count']} ta / {money(week_earn)} so'm",
        reply_markup=admin_keyboard(),
    )
    await state.clear()

@dp.message(F.text == "Balans qo'shish")
async def admin_balance_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminBalanceState.driver_id)
    await message.answer("Balans qo'shiladigan haydovchi ID raqamini kiriting.")

@dp.message(AdminBalanceState.driver_id)
async def admin_balance_driver(message: types.Message, state: FSMContext):
    try:
        driver_id = int(message.text)
    except ValueError:
        await message.answer("Faqat ID raqamini kiriting.")
        return
    driver = get_driver_by_id(driver_id)
    if not driver:
        await message.answer("Bunday ID li haydovchi topilmadi.")
        await state.clear()
        return
    await state.update_data(driver_id=driver_id)
    await state.set_state(AdminBalanceState.amount)
    await message.answer(f"{driver['full_name']} balansiga qancha qo'shilsin?")

@dp.message(AdminBalanceState.amount)
async def admin_balance_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("Summani son bilan kiriting.")
        return

    data = await state.get_data()
    driver = get_driver_by_id(data["driver_id"])
    new_balance = driver["balance"] + amount
    update_driver_balance(driver["id"], new_balance)
    await message.answer(
        f"Balans yangilandi. {driver['full_name']}: {money(new_balance)} so'm",
        reply_markup=admin_keyboard(),
    )
    try:
        await bot.send_message(
            driver["telegram_id"],
            f"Hisobingizga {money(amount)} so'm qo'shildi.\nYangi hisob: {money(new_balance)} so'm",
        )
    except Exception:
        pass
    await state.clear()

@dp.callback_query(F.data.startswith("review_"))
async def review_withdraw(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Ruxsat yo'q.")
        return
    withdraw_id = int(callback.data.split("_")[1])
    row = get_withdraw(withdraw_id)
    if not row or row["status"] not in ("new", "reviewing"):
        await callback.answer("So'rov topilmadi yoki yakunlangan.")
        return
    update_withdraw_status(withdraw_id, "reviewing")
    await callback.answer("Haydovchiga tekshirilmoqda deb yuborildi.")
    await bot.send_message(row["telegram_id"], f"#{withdraw_id} pul yechish so'rovingiz tekshirilmoqda.")

@dp.callback_query(F.data.startswith("pay_"))
async def pay_withdraw(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Ruxsat yo'q.")
        return
    withdraw_id = int(callback.data.split("_")[1])
    row = get_withdraw(withdraw_id)
    if not row or row["status"] not in ("new", "reviewing"):
        await callback.answer("So'rov topilmadi yoki allaqachon ishlangan.")
        return
    if row["amount"] > row["balance"]:
        await callback.answer("Haydovchi balansida yetarli mablag' yo'q.", show_alert=True)
        return

    new_balance = row["balance"] - row["amount"]
    update_driver_balance(row["driver_id"], new_balance)
    update_withdraw_status(withdraw_id, "paid")
    await callback.message.edit_text(
        f"#{withdraw_id} to'lov amalga oshirildi.\n"
        f"Summa: {money(row['amount'])} so'm\n"
        f"Yangi balans: {money(new_balance)} so'm"
    )
    await callback.answer("To'lov amalga oshirildi.")
    await bot.send_message(
        row["telegram_id"],
        f"#{withdraw_id} so'rovingiz bo'yicha to'lov amalga oshirildi.\n"
        f"Summa: {money(row['amount'])} so'm\n"
        f"Yangi hisob: {money(new_balance)} so'm",
    )

@dp.callback_query(F.data.startswith("reject_"))
async def reject_withdraw(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Ruxsat yo'q.")
        return
    withdraw_id = int(callback.data.split("_")[1])
    row = get_withdraw(withdraw_id)
    if not row or row["status"] not in ("new", "reviewing"):
        await callback.answer("So'rov topilmadi yoki allaqachon ishlangan.")
        return
    update_withdraw_status(withdraw_id, "rejected")
    await callback.message.edit_text(f"#{withdraw_id} pul yechish so'rovi rad etildi.")
    await callback.answer("Rad etildi.")
    await bot.send_message(row["telegram_id"], f"#{withdraw_id} pul yechish so'rovingiz rad etildi.")

@dp.message()
async def fallback(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Menejer panelidan kerakli tugmani tanlang.", reply_markup=admin_keyboard())
    else:
        driver = get_driver(message.from_user.id)
        if driver:
            await message.answer("Menyudan kerakli bo'limni tanlang.", reply_markup=main_keyboard())
        else:
            await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())

async def main():
    print("Yakomfort Telegram bot ishga tushdi.")
    print(f"Admin ID: {ADMIN_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

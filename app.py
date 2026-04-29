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
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "taxi.db")
MANAGER_PHONE = os.getenv("MANAGER_PHONE", "+998771202255")
MANAGER_NAME = os.getenv("MANAGER_NAME", "Jamshidbek")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. Render Environment Variables ichiga BOT_TOKEN qo'shing.")


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect_db()
    cur = conn.cursor()

    cur.execute("""
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(driver_id) REFERENCES drivers(id)
        )
    """)

    conn.commit()
    conn.close()


def get_driver_by_tg(telegram_id):
    conn = connect_db()
    row = conn.execute("SELECT * FROM drivers WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return row


def get_driver_by_id(driver_id):
    conn = connect_db()
    row = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
    conn.close()
    return row


def create_driver(telegram_id, username, full_name, phone, license_number, card_number):
    conn = connect_db()
    conn.execute("""
        INSERT INTO drivers (telegram_id, username, full_name, phone, license_number, card_number)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (telegram_id, username, full_name, phone, license_number, card_number))
    conn.commit()
    conn.close()


def add_report(driver_id, report_type, message=""):
    conn = connect_db()
    conn.execute(
        "INSERT INTO reports (driver_id, report_type, message) VALUES (?, ?, ?)",
        (driver_id, report_type, message),
    )
    conn.commit()
    conn.close()


def create_withdraw(driver_id, amount):
    conn = connect_db()
    cur = conn.execute(
        "INSERT INTO withdraw_requests (driver_id, amount) VALUES (?, ?)",
        (driver_id, amount),
    )
    conn.commit()
    withdraw_id = cur.lastrowid
    conn.close()
    return withdraw_id


def get_withdraw(withdraw_id):
    conn = connect_db()
    row = conn.execute("""
        SELECT w.*, d.telegram_id, d.username, d.full_name, d.phone,
               d.license_number, d.card_number, d.balance
        FROM withdraw_requests w
        JOIN drivers d ON d.id = w.driver_id
        WHERE w.id = ?
    """, (withdraw_id,)).fetchone()
    conn.close()
    return row


def set_withdraw_status(withdraw_id, status):
    conn = connect_db()
    if status == "reviewing":
        conn.execute(
            "UPDATE withdraw_requests SET status = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, withdraw_id),
        )
    elif status == "paid":
        conn.execute(
            "UPDATE withdraw_requests SET status = ?, paid_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, withdraw_id),
        )
    else:
        conn.execute(
            "UPDATE withdraw_requests SET status = ? WHERE id = ?",
            (status, withdraw_id),
        )
    conn.commit()
    conn.close()


def set_balance(driver_id, balance):
    conn = connect_db()
    conn.execute("UPDATE drivers SET balance = ? WHERE id = ?", (balance, driver_id))
    conn.commit()
    conn.close()


def add_balance(driver_id, amount):
    driver = get_driver_by_id(driver_id)
    if not driver:
        return None
    new_balance = float(driver["balance"] or 0) + amount
    set_balance(driver_id, new_balance)
    return new_balance


def update_trips(driver_id, trips_today, trips_week):
    conn = connect_db()
    conn.execute(
        "UPDATE drivers SET trips_today = ?, trips_week = ? WHERE id = ?",
        (trips_today, trips_week, driver_id),
    )
    conn.commit()
    conn.close()


def get_pending_withdraws():
    conn = connect_db()
    rows = conn.execute("""
        SELECT w.*, d.telegram_id, d.full_name, d.phone, d.license_number, d.card_number, d.balance
        FROM withdraw_requests w
        JOIN drivers d ON d.id = w.driver_id
        WHERE w.status IN ('new', 'reviewing')
        ORDER BY w.created_at DESC
    """).fetchall()
    conn.close()
    return rows


def get_paid_history(driver_id):
    conn = connect_db()
    rows = conn.execute("""
        SELECT * FROM withdraw_requests
        WHERE driver_id = ? AND status = 'paid'
        ORDER BY created_at DESC
        LIMIT 10
    """, (driver_id,)).fetchall()
    conn.close()
    return rows


def get_all_drivers():
    conn = connect_db()
    rows = conn.execute("""
        SELECT id, telegram_id, username, full_name, phone, license_number, card_number, balance,
               trips_today, trips_week, created_at
        FROM drivers
        ORDER BY id DESC
    """).fetchall()
    conn.close()
    return rows


def get_stats():
    conn = connect_db()
    drivers = conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status IN ('new', 'reviewing')").fetchone()[0]
    paid_sum = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM withdraw_requests WHERE status = 'paid'").fetchone()[0]
    reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    conn.close()
    return drivers, pending, paid_sum, reports


init_db()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


BTN_REGISTER = "Ro'yxatdan o'tish"
BTN_BALANCE = "Hisobni bilish"
BTN_TOPUP = "Hisobni to'ldirish"
BTN_TRIPS = "Qancha zakaz ishlangan"
BTN_WITHDRAW = "Pul yechish"
BTN_SOS = "SOS"
BTN_DTP = "DTP"
BTN_MANAGER = "Menejer bilan bog'lanish"
BTN_HISTORY = "To'lovlar tarixi"
BTN_CARD = "Kartam"

ADMIN_WITHDRAWS = "Pul yechish so'rovlari"
ADMIN_DRIVERS = "Haydovchilar ro'yxati"
ADMIN_STATS = "Statistika"
ADMIN_ADD_BALANCE = "Balans qo'shish"
ADMIN_UPDATE_TRIPS = "Zakaz sonini yangilash"

WELCOME_TEXT = (
    "Assalomu alaykum, hurmatli haydovchi!\n\n"
    "Yakomfort jamoamizga xush kelibsiz.\n"
    "Yakomfortda komissiya atigi 1%.\n\n"
    "Ro'yxatdan o'tish tugmasini bosib ro'yxatdan o'ting."
)

AFTER_REGISTER_TEXT = (
    "Hurmatli haydovchi, biz bilan hamkorlik qilganingizdan mamnunmiz.\n\n"
    "Yo'lovchilar bilan har doim xushmuomala bo'ling. "
    "Xushmuomalalik ikki inson o'rtasidagi yaxshi kayfiyat garovidir!!!\n\n"
    "Hurmatli haydovchi, biz bilan daromadingizni oshiring.\n"
    "Siz muvaffaqiyatli ro'yxatdan o'tdingiz. Oq yo'l, hech qachon charchamang!!!"
)


def now():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def money(value):
    try:
        return f"{int(float(value)):,}".replace(",", " ")
    except Exception:
        return "0"


def clean_amount(text):
    return float(text.replace(" ", "").replace(",", "."))


def mask_card(card):
    digits = "".join(ch for ch in str(card) if ch.isdigit())
    if len(digits) >= 4:
        return "****" + digits[-4:]
    return "****"


def tg_link(driver):
    return f'<a href="tg://user?id={driver["telegram_id"]}">{escape(driver["full_name"])}</a>'


def username_text(username):
    if username:
        return f"@{escape(username)}"
    return "Yo'q"


def driver_admin_text(driver):
    return (
        f"Haydovchi: {tg_link(driver)}\n"
        f"Telefon: {escape(driver['phone'])}\n"
        f"Haydovchilik guvohnomasi: {escape(driver['license_number'])}\n"
        f"Karta: {escape(mask_card(driver['card_number']))}\n"
        f"Telegram ID: <code>{driver['telegram_id']}</code>\n"
        f"Username: {username_text(driver['username'])}"
    )


def start_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_REGISTER)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BALANCE), KeyboardButton(text=BTN_TOPUP)],
            [KeyboardButton(text=BTN_TRIPS), KeyboardButton(text=BTN_WITHDRAW)],
            [KeyboardButton(text=BTN_SOS), KeyboardButton(text=BTN_DTP)],
            [KeyboardButton(text=BTN_MANAGER)],
            [KeyboardButton(text=BTN_HISTORY), KeyboardButton(text=BTN_CARD)],
        ],
        resize_keyboard=True,
    )


def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADMIN_WITHDRAWS), KeyboardButton(text=ADMIN_STATS)],
            [KeyboardButton(text=ADMIN_DRIVERS)],
            [KeyboardButton(text=ADMIN_ADD_BALANCE), KeyboardButton(text=ADMIN_UPDATE_TRIPS)],
        ],
        resize_keyboard=True,
    )


def withdraw_keyboard(withdraw_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ko'rilmoqda", callback_data=f"review:{withdraw_id}")],
            [
                InlineKeyboardButton(text="To'lov amalga oshirildi", callback_data=f"paid:{withdraw_id}"),
                InlineKeyboardButton(text="Rad etish", callback_data=f"reject:{withdraw_id}"),
            ],
        ]
    )


class RegisterState(StatesGroup):
    full_name = State()
    phone = State()
    license_number = State()
    card_number = State()


class WithdrawState(StatesGroup):
    amount = State()


class ManagerMessageState(StatesGroup):
    message = State()


class AddBalanceState(StatesGroup):
    driver_id = State()
    amount = State()


class UpdateTripsState(StatesGroup):
    driver_id = State()
    today = State()
    week = State()


async def send_admin(text, reply_markup=None):
    if ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, text, reply_markup=reply_markup)
        except Exception as e:
            print("Admin xabar yuborishda xatolik:", e)


async def notify_menu_click(driver, button_name, extra=""):
    add_report(driver["id"], button_name, extra)
    text = (
        "Haydovchi tugma bosdi!\n\n"
        f"{driver_admin_text(driver)}\n"
        f"Tugma: <b>{escape(button_name)}</b>\n"
        f"Vaqt: {now()}"
    )
    await send_admin(text)


async def get_or_start_register(message):
    driver = get_driver_by_tg(message.from_user.id)
    if driver:
        return driver
    await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())
    return None


@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    await state.clear()

    if message.from_user.id == ADMIN_ID:
        await message.answer("Menejer paneli.", reply_markup=admin_keyboard())
        return

    driver = get_driver_by_tg(message.from_user.id)
    if driver:
        await message.answer("Asosiy menyu:", reply_markup=main_keyboard())
        return

    await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())


@dp.message(F.text == BTN_REGISTER)
async def register_start(message: types.Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Menejer paneli.", reply_markup=admin_keyboard())
        return

    if get_driver_by_tg(message.from_user.id):
        await message.answer("Siz avval ro'yxatdan o'tgansiz.", reply_markup=main_keyboard())
        return

    await state.set_state(RegisterState.full_name)
    await message.answer("Ism familiyangizni kiriting:", reply_markup=ReplyKeyboardRemove())


@dp.message(RegisterState.full_name)
async def register_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await state.set_state(RegisterState.phone)
    await message.answer("Telefon raqamingizni kiriting. Masalan: +998901234567")


@dp.message(RegisterState.phone)
async def register_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await state.set_state(RegisterState.license_number)
    await message.answer("Haydovchilik guvohnomasi raqamini kiriting:")


@dp.message(RegisterState.license_number)
async def register_license(message: types.Message, state: FSMContext):
    await state.update_data(license_number=message.text.strip().upper())
    await state.set_state(RegisterState.card_number)
    await message.answer("Bank karta raqamingizni kiriting:")


@dp.message(RegisterState.card_number)
async def register_card(message: types.Message, state: FSMContext):
    if get_driver_by_tg(message.from_user.id):
        await state.clear()
        await message.answer("Siz avval ro'yxatdan o'tgansiz.", reply_markup=main_keyboard())
        return

    data = await state.get_data()
    create_driver(
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=data["full_name"],
        phone=data["phone"],
        license_number=data["license_number"],
        card_number=message.text.strip(),
    )

    driver = get_driver_by_tg(message.from_user.id)
    admin_text = (
        "Yangi haydovchi ro'yxatdan o'tdi!\n\n"
        f"{driver_admin_text(driver)}\n"
        f"Vaqt: {now()}"
    )
    await send_admin(admin_text)

    await message.answer(AFTER_REGISTER_TEXT, reply_markup=main_keyboard())
    await state.clear()


@dp.message(F.text == BTN_BALANCE)
async def balance(message: types.Message):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_BALANCE)
    await message.answer(
        f"Hisobingiz: {money(driver['balance'])} so'm\n"
        f"Pul yechish mumkin: {money(driver['balance'])} so'm"
    )


@dp.message(F.text == BTN_TOPUP)
async def topup(message: types.Message):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_TOPUP)
    await message.answer(
        "Hisobni to'ldirish uchun menejer bilan bog'laning.\n\n"
        f"Salom, mening ismim {MANAGER_NAME}. Sizga qanday yordam kerak?\n"
        f"Zarur bo'lsa hoziroq quyidagi raqamga qo'ng'iroq qiling: {MANAGER_PHONE}"
    )


@dp.message(F.text == BTN_TRIPS)
async def trips(message: types.Message):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_TRIPS)
    await message.answer(
        "Zakaz statistikasi:\n\n"
        f"Bugun ishlangan zakaz: {driver['trips_today']} ta\n"
        f"Hafta davomida ishlangan zakaz: {driver['trips_week']} ta"
    )


@dp.message(F.text == BTN_WITHDRAW)
async def withdraw_start(message: types.Message, state: FSMContext):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_WITHDRAW)

    if float(driver["balance"] or 0) <= 0:
        await message.answer("Hisobingizda pul mavjud emas. Menejer bilan bog'laning.")
        return

    await state.update_data(driver_id=driver["id"])
    await state.set_state(WithdrawState.amount)
    await message.answer(f"Qancha pul yechmoqchisiz? Mavjud hisob: {money(driver['balance'])} so'm")


@dp.message(WithdrawState.amount)
async def withdraw_amount(message: types.Message, state: FSMContext):
    try:
        amount = clean_amount(message.text)
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer("Summani to'g'ri kiriting. Masalan: 150000")
        return

    data = await state.get_data()
    driver = get_driver_by_id(data["driver_id"])

    if not driver:
        await state.clear()
        await message.answer("Xatolik yuz berdi. /start ni qayta bosing.")
        return

    if amount > float(driver["balance"] or 0):
        await message.answer(f"Hisobingizda yetarli mablag' yo'q. Mavjud: {money(driver['balance'])} so'm")
        return

    withdraw_id = create_withdraw(driver["id"], amount)

    await message.answer(
        f"Pul yechish so'rovingiz #{withdraw_id} menejerga yuborildi.\n"
        "Tez orada ko'rib chiqiladi.",
        reply_markup=main_keyboard(),
    )

    admin_text = (
        f"Yangi pul yechish so'rovi #{withdraw_id}\n\n"
        f"{driver_admin_text(driver)}\n"
        f"Hisob: {money(driver['balance'])} so'm\n"
        f"So'ralgan summa: <b>{money(amount)} so'm</b>\n"
        f"Vaqt: {now()}"
    )
    await send_admin(admin_text, reply_markup=withdraw_keyboard(withdraw_id))
    await state.clear()


@dp.message(F.text == BTN_SOS)
async def sos(message: types.Message):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_SOS)
    await message.answer("SOS xabaringiz menejerga yuborildi. Tez orada siz bilan bog'lanishadi.")


@dp.message(F.text == BTN_DTP)
async def dtp(message: types.Message):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_DTP)
    await message.answer("DTP xabaringiz menejerga yuborildi. Xavfsiz joyda turing va menejer qo'ng'irog'ini kuting.")


@dp.message(F.text == BTN_MANAGER)
async def manager_start(message: types.Message, state: FSMContext):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_MANAGER)
    await state.set_state(ManagerMessageState.message)
    await message.answer(
        f"Salom, mening ismim {MANAGER_NAME}. Sizga qanday yordam kerak?\n\n"
        f"Zarur bo'lsa hoziroq quyidagi raqamga qo'ng'iroq qiling: {MANAGER_PHONE}\n\n"
        "Menejerga xabar yozing:"
    )


@dp.message(ManagerMessageState.message)
async def manager_message(message: types.Message, state: FSMContext):
    driver = get_driver_by_tg(message.from_user.id)
    if not driver:
        await state.clear()
        await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())
        return

    add_report(driver["id"], BTN_MANAGER, message.text)
    admin_text = (
        "Haydovchidan murojaat!\n\n"
        f"{driver_admin_text(driver)}\n"
        f"Xabar: {escape(message.text)}\n"
        f"Vaqt: {now()}"
    )
    await send_admin(admin_text)

    await message.answer("Xabaringiz menejerga yuborildi.", reply_markup=main_keyboard())
    await state.clear()


@dp.message(F.text == BTN_HISTORY)
async def history(message: types.Message):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_HISTORY)
    rows = get_paid_history(driver["id"])

    if not rows:
        await message.answer("To'lovlar tarixi hozircha bo'sh.")
        return

    text = "Oxirgi to'lovlar:\n\n"
    for row in rows:
        text += f"#{row['id']} - {money(row['amount'])} so'm - {row['created_at'][:16]}\n"

    await message.answer(text)


@dp.message(F.text == BTN_CARD)
async def card(message: types.Message):
    driver = await get_or_start_register(message)
    if not driver:
        return

    await notify_menu_click(driver, BTN_CARD)
    await message.answer(f"Kartangiz: {mask_card(driver['card_number'])}")


@dp.message(F.text == ADMIN_WITHDRAWS)
async def admin_withdraws(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())
        return

    rows = get_pending_withdraws()
    if not rows:
        await message.answer("Yangi pul yechish so'rovlari yo'q.")
        return

    for row in rows:
        text = (
            f"Pul yechish so'rovi #{row['id']}\n\n"
            f"Haydovchi: {escape(row['full_name'])}\n"
            f"Telefon: {escape(row['phone'])}\n"
            f"Guvohnoma: {escape(row['license_number'])}\n"
            f"Karta: {mask_card(row['card_number'])}\n"
            f"Telegram ID: <code>{row['telegram_id']}</code>\n"
            f"Hisob: {money(row['balance'])} so'm\n"
            f"Summa: <b>{money(row['amount'])} so'm</b>\n"
            f"Holat: {escape(row['status'])}"
        )
        await message.answer(text, reply_markup=withdraw_keyboard(row["id"]))


@dp.message(F.text == ADMIN_STATS)
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())
        return

    drivers, pending, paid_sum, reports = get_stats()
    await message.answer(
        "Statistika:\n\n"
        f"Haydovchilar: {drivers} ta\n"
        f"Kutilayotgan pul yechish: {pending} ta\n"
        f"Jami to'langan: {money(paid_sum)} so'm\n"
        f"Tugma/xabarlar: {reports} ta"
    )


@dp.message(F.text == ADMIN_DRIVERS)
@dp.message(F.text == "/list_drivers")
async def admin_drivers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())
        return

    rows = get_all_drivers()
    if not rows:
        await message.answer("Haydovchilar ro'yxati bo'sh.")
        return

    text = "Haydovchilar ro'yxati:\n\n"
    for d in rows:
        text += (
            f"ID: {d['id']} | TG: {d['telegram_id']}\n"
            f"Ism: {escape(d['full_name'])}\n"
            f"Tel: {escape(d['phone'])}\n"
            f"Guvohnoma: {escape(d['license_number'])}\n"
            f"Karta: {mask_card(d['card_number'])}\n"
            f"Hisob: {money(d['balance'])} so'm\n\n"
        )

    if len(text) > 3900:
        parts = [text[i:i + 3900] for i in range(0, len(text), 3900)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(text)


@dp.message(F.text == ADMIN_ADD_BALANCE)
async def admin_add_balance_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())
        return

    await state.set_state(AddBalanceState.driver_id)
    await message.answer("Haydovchi ID raqamini kiriting. ID uchun /list_drivers ni bosing.")


@dp.message(AddBalanceState.driver_id)
async def admin_add_balance_driver(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    try:
        driver_id = int(message.text)
    except Exception:
        await message.answer("Faqat ID raqamini kiriting.")
        return

    driver = get_driver_by_id(driver_id)
    if not driver:
        await message.answer("Bunday ID li haydovchi topilmadi.")
        await state.clear()
        return

    await state.update_data(driver_id=driver_id)
    await state.set_state(AddBalanceState.amount)
    await message.answer(f"{driver['full_name']} balansiga qancha pul qo'shilsin?")


@dp.message(AddBalanceState.amount)
async def admin_add_balance_amount(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    try:
        amount = clean_amount(message.text)
    except Exception:
        await message.answer("Summani to'g'ri kiriting.")
        return

    data = await state.get_data()
    driver = get_driver_by_id(data["driver_id"])
    new_balance = add_balance(driver["id"], amount)

    await message.answer(
        f"Balans qo'shildi.\n"
        f"Haydovchi: {driver['full_name']}\n"
        f"Yangi hisob: {money(new_balance)} so'm",
        reply_markup=admin_keyboard(),
    )

    try:
        await bot.send_message(
            driver["telegram_id"],
            f"Hisobingizga {money(amount)} so'm qo'shildi.\n"
            f"Yangi hisob: {money(new_balance)} so'm",
        )
    except Exception:
        pass

    await state.clear()


@dp.message(F.text == ADMIN_UPDATE_TRIPS)
async def admin_update_trips_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())
        return

    await state.set_state(UpdateTripsState.driver_id)
    await message.answer("Haydovchi ID raqamini kiriting. ID uchun /list_drivers ni bosing.")


@dp.message(UpdateTripsState.driver_id)
async def admin_update_trips_driver(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    try:
        driver_id = int(message.text)
    except Exception:
        await message.answer("Faqat ID raqamini kiriting.")
        return

    driver = get_driver_by_id(driver_id)
    if not driver:
        await message.answer("Bunday ID li haydovchi topilmadi.")
        await state.clear()
        return

    await state.update_data(driver_id=driver_id)
    await state.set_state(UpdateTripsState.today)
    await message.answer(f"{driver['full_name']} bugun nechta zakaz ishladi?")


@dp.message(UpdateTripsState.today)
async def admin_update_trips_today(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    try:
        today = int(message.text)
    except Exception:
        await message.answer("Faqat son kiriting.")
        return

    await state.update_data(today=today)
    await state.set_state(UpdateTripsState.week)
    await message.answer("Hafta davomida nechta zakaz ishladi?")


@dp.message(UpdateTripsState.week)
async def admin_update_trips_week(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    try:
        week = int(message.text)
    except Exception:
        await message.answer("Faqat son kiriting.")
        return

    data = await state.get_data()
    update_trips(data["driver_id"], data["today"], week)
    driver = get_driver_by_id(data["driver_id"])

    await message.answer(
        f"Zakaz soni yangilandi.\n\n"
        f"Haydovchi: {driver['full_name']}\n"
        f"Bugun: {data['today']} ta\n"
        f"Hafta: {week} ta",
        reply_markup=admin_keyboard(),
    )
    await state.clear()


@dp.callback_query(F.data.startswith("review:"))
async def review_withdraw(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Bu tugma faqat menejer uchun.", show_alert=True)
        return

    withdraw_id = int(callback.data.split(":")[1])
    row = get_withdraw(withdraw_id)

    if not row or row["status"] not in ("new", "reviewing"):
        await callback.answer("So'rov topilmadi yoki yakunlangan.", show_alert=True)
        return

    set_withdraw_status(withdraw_id, "reviewing")
    await callback.answer("Haydovchiga xabar yuborildi.")
    await bot.send_message(row["telegram_id"], f"#{withdraw_id} pul yechish so'rovingiz tekshirilmoqda.")


@dp.callback_query(F.data.startswith("paid:"))
async def paid_withdraw(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Bu tugma faqat menejer uchun.", show_alert=True)
        return

    withdraw_id = int(callback.data.split(":")[1])
    row = get_withdraw(withdraw_id)

    if not row or row["status"] not in ("new", "reviewing"):
        await callback.answer("So'rov topilmadi yoki yakunlangan.", show_alert=True)
        return

    if float(row["amount"]) > float(row["balance"] or 0):
        await callback.answer("Haydovchi balansida yetarli pul yo'q.", show_alert=True)
        return

    new_balance = float(row["balance"] or 0) - float(row["amount"])
    set_balance(row["driver_id"], new_balance)
    set_withdraw_status(withdraw_id, "paid")

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


@dp.callback_query(F.data.startswith("reject:"))
async def reject_withdraw(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Bu tugma faqat menejer uchun.", show_alert=True)
        return

    withdraw_id = int(callback.data.split(":")[1])
    row = get_withdraw(withdraw_id)

    if not row or row["status"] not in ("new", "reviewing"):
        await callback.answer("So'rov topilmadi yoki yakunlangan.", show_alert=True)
        return

    set_withdraw_status(withdraw_id, "rejected")

    await callback.message.edit_text(f"#{withdraw_id} pul yechish so'rovi rad etildi.")
    await callback.answer("Rad etildi.")

    await bot.send_message(row["telegram_id"], f"#{withdraw_id} pul yechish so'rovingiz rad etildi.")


@dp.message()
async def fallback(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Menejer paneli:", reply_markup=admin_keyboard())
        return

    driver = get_driver_by_tg(message.from_user.id)
    if driver:
        await message.answer("Menyudan kerakli tugmani tanlang.", reply_markup=main_keyboard())
    else:
        await message.answer(WELCOME_TEXT, reply_markup=start_keyboard())


async def main():
    print("Yakomfort bot ishga tushdi")
    print(f"ADMIN_ID: {ADMIN_ID}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

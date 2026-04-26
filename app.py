import os
import asyncio
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import FastAPI, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, BigInteger, Boolean, Text, select, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import httpx

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/taxi_db")
DRIVER_BOT_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
MANAGER_BOT_TOKEN = os.getenv("MANAGER_BOT_TOKEN")
YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_PARK_ID = os.getenv("YANDEX_PARK_ID")
MANAGER_IDS = [int(x.strip()) for x in os.getenv("MANAGER_IDS", "").split(",") if x.strip()]
NON_WITHDRAWABLE = int(os.getenv("NON_WITHDRAWABLE", "10000"))
PORT = int(os.getenv("PORT", "8000"))

# ==================== БАЗА ДАННЫХ ====================
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Driver(Base):
    __tablename__ = "drivers"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)
    yandex_driver_id = Column(String(100), nullable=False)
    card_number = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")
    balance = Column(Float, default=0)
    language = Column(String(10), default="uz")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class WithdrawRequest(Base):
    __tablename__ = "withdraw_requests"
    id = Column(Integer, primary_key=True)
    driver_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String(20), default="new")
    manager_id = Column(Integer, nullable=True)
    manager_telegram_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

class PayoutLog(Base):
    __tablename__ = "payout_logs"
    id = Column(Integer, primary_key=True)
    withdraw_id = Column(Integer, nullable=False)
    driver_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    previous_balance = Column(Float, nullable=False)
    new_balance = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==================== YANDEX FLEET API ====================
class YandexFleetAPI:
    def __init__(self):
        self.base_url = "https://fleet-api.taxi.yandex.net/v1/parks"
        self.client_id = YANDEX_CLIENT_ID
        self.api_key = YANDEX_API_KEY
        self.park_id = YANDEX_PARK_ID

    async def _request(self, method: str, endpoint: str, data: Dict = None):
        if not self.client_id or not self.api_key:
            return None
        url = f"{self.base_url}/{endpoint}"
        headers = {
            "X-Client-ID": self.client_id,
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if method == "GET":
                    response = await client.get(url, headers=headers, params=data)
                else:
                    response = await client.post(url, headers=headers, json=data)
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            print(f"Yandex API error: {e}")
        return None

    async def get_driver_balance(self, driver_id: str) -> float:
        data = {"query": {"park": {"id": self.park_id}, "driver": {"id": driver_id}}}
        result = await self._request("POST", "drivers", data)
        if result and result.get("drivers"):
            return float(result["drivers"][0].get("balance", {}).get("total", 0))
        return 0

    async def get_driver_orders(self, driver_id: str, date_from: str, date_to: str) -> Dict:
        data = {
            "query": {
                "park": {"id": self.park_id},
                "driver": {"id": driver_id},
                "order": {"statuses": ["complete"], "date_from": date_from, "date_to": date_to}
            }
        }
        result = await self._request("POST", "orders", data)
        if result:
            orders = result.get("orders", [])
            return {"orders": len(orders), "earned": sum(float(o.get("price", 0)) for o in orders)}
        return {"orders": 0, "earned": 0}

yandex_api = YandexFleetAPI()

# ==================== ТЕКСТЫ ====================
TEXTS = {
    "uz": {
        "welcome": "🚖 Yakomfort taksoparkiga xush kelibsiz!",
        "menu": "💰 Balansim\n🚖 Buyurtmalarim\n💸 Pul yechish\n📜 To'lovlar tarixi\n💳 Kartam\n☎️ Yordam\n🌐 Tilni almashtirish",
        "balance": "💰 Balansingiz:\n\nJami: {balance} so'm\nYechish mumkin: {available} so'm\n⚠️ Minimal qoldiq: 10000 so'm",
        "enter_amount": "💰 Yechmoqchi bo'lgan summani kiriting:",
        "insufficient": "❌ Yetarli emas! Yechish mumkin: {available} so'm",
        "success": "✅ So'rov #{id} yuborildi!",
        "blocked": "❌ Hisobingiz bloklangan",
        "active_request": "❌ Sizda faol so'rov mavjud",
        "orders_today": "🚖 BUGUN:\n📦 {orders} ta buyurtma\n💰 {earned} so'm",
        "orders_week": "📊 HAFTA:\n📦 {orders} ta buyurtma\n💰 {earned} so'm",
        "card": "💳 Karta: ****{card}\n🔄 O'zgartirish uchun menedjerga murojaat qiling",
        "help": "☎️ Yordam: +998 71 202 55 55",
        "lang_changed": "✅ Til o'zgartirildi!",
        "no_history": "📭 To'lovlar tarixi bo'sh",
        "history_header": "📜 TO'LOVLAR TARIXI:\n",
        "register_name": "📝 Ism familiyangizni kiriting:",
        "register_phone": "📞 Telefon raqamingizni kiriting (+998xxxxxxxxx):",
        "register_yandex": "🆔 Yandex Driver ID ni kiriting:",
        "register_card": "💳 Karta raqamingizni kiriting (8600xxxxxx):",
        "register_success": "✅ Ro'yxatdan o'tdingiz! Menedjer tasdiqlashidan keyin hisobingiz faollashadi.",
        "register_exists": "❌ Siz allaqachon ro'yxatdan o'tgansiz!",
    },
    "ru": {
        "welcome": "🚖 Добро пожаловать в таксопарк Yakomfort!",
        "menu": "💰 Мой баланс\n🚖 Мои заказы\n💸 Вывести деньги\n📜 История выплат\n💳 Моя карта\n☎️ Помощь\n🌐 Сменить язык",
        "balance": "💰 Ваш баланс:\n\nВсего: {balance} сум\nДоступно: {available} сум\n⚠️ Минимальный остаток: 10000 сум",
        "enter_amount": "💰 Введите сумму для вывода:",
        "insufficient": "❌ Недостаточно! Доступно: {available} сум",
        "success": "✅ Заявка #{id} отправлена!",
        "blocked": "❌ Ваш аккаунт заблокирован",
        "active_request": "❌ У вас есть активная заявка",
        "orders_today": "🚖 СЕГОДНЯ:\n📦 {orders} заказов\n💰 {earned} сум",
        "orders_week": "📊 НЕДЕЛЯ:\n📦 {orders} заказов\n💰 {earned} сум",
        "card": "💳 Карта: ****{card}\n🔄 Для смены карты обратитесь к менеджеру",
        "help": "☎️ Помощь: +998 71 202 55 55",
        "lang_changed": "✅ Язык изменен!",
        "no_history": "📭 История выплат пуста",
        "history_header": "📜 ИСТОРИЯ ВЫПЛАТ:\n",
        "register_name": "📝 Введите ваше ФИО:",
        "register_phone": "📞 Введите номер телефона (+998xxxxxxxxx):",
        "register_yandex": "🆔 Введите Yandex Driver ID:",
        "register_card": "💳 Введите номер карты (8600xxxxxx):",
        "register_success": "✅ Вы зарегистрированы! После подтверждения менеджером ваш аккаунт будет активирован.",
        "register_exists": "❌ Вы уже зарегистрированы!",
    }
}

# ==================== FSM СОСТОЯНИЯ ====================
class RegisterState(StatesGroup):
    name = State()
    phone = State()
    yandex_id = State()
    card = State()

class WithdrawState(StatesGroup):
    amount = State()

# ==================== КЛАВИАТУРЫ ====================
def get_driver_keyboard(lang: str):
    texts = TEXTS[lang]["menu"].split("\n")
    buttons = [[KeyboardButton(text=text)] for text in texts]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_manager_keyboard():
    buttons = [[KeyboardButton(text="📋 Новые заявки")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ==================== УВЕДОМЛЕНИЯ МЕНЕДЖЕРАМ ====================
async def notify_managers(text: str, reply_markup: InlineKeyboardMarkup = None):
    for mgr_id in MANAGER_IDS:
        try:
            mgr_bot = Bot(token=MANAGER_BOT_TOKEN)
            await mgr_bot.send_message(mgr_id, text, reply_markup=reply_markup)
        except:
            pass

# ==================== DRIVER BOT ====================
driver_bot = Bot(token=DRIVER_BOT_TOKEN)
driver_storage = MemoryStorage()
driver_dp = Dispatcher(storage=driver_storage)

@driver_dp.message(F.text == "/start")
async def driver_start(message: types.Message, state: FSMContext):
    await state.clear()
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()

    if driver:
        await message.answer(TEXTS[driver.language]["menu"], reply_markup=get_driver_keyboard(driver.language))
    else:
        await message.answer("🇺🇿 Assalomu alaykum! / 🇷🇺 Добро пожаловать!\n\n" + TEXTS["uz"]["register_name"])
        await state.set_state(RegisterState.name)

# Регистрация
@driver_dp.message(RegisterState.name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(RegisterState.phone)
    await message.answer(TEXTS["uz"]["register_phone"])

@driver_dp.message(RegisterState.phone)
async def reg_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(RegisterState.yandex_id)
    await message.answer(TEXTS["uz"]["register_yandex"])

@driver_dp.message(RegisterState.yandex_id)
async def reg_yandex(message: types.Message, state: FSMContext):
    await state.update_data(yandex_id=message.text)
    await state.set_state(RegisterState.card)
    await message.answer(TEXTS["uz"]["register_card"])

@driver_dp.message(RegisterState.card)
async def reg_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    db = next(get_db())

    existing = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if existing:
        await message.answer(TEXTS["uz"]["register_exists"])
        await state.clear()
        return

    new_driver = Driver(
        telegram_id=message.from_user.id,
        full_name=data['name'],
        phone=data['phone'],
        yandex_driver_id=data['yandex_id'],
        card_number=message.text,
        status="pending",
        balance=0,
        language="uz"
    )
    db.add(new_driver)
    db.commit()

    await message.answer(TEXTS["uz"]["register_success"])
    await message.answer(TEXTS["uz"]["menu"], reply_markup=get_driver_keyboard("uz"))
    await state.clear()

    await notify_managers(
        f"🆕 НОВЫЙ ВОДИТЕЛЬ!\n\n"
        f"👤 {data['name']}\n"
        f"📞 {data['phone']}\n"
        f"🆔 {data['yandex_id']}\n"
        f"💳 ****{data['card'][-4:]}"
    )

@driver_dp.message(F.text.in_(["💰 Balansim", "💰 Мой баланс"]))
async def show_balance(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting / Зарегистрируйтесь")
        return
    available = max(0, driver.balance - NON_WITHDRAWABLE)
    await message.answer(TEXTS[driver.language]["balance"].format(balance=int(driver.balance), available=int(available)))

@driver_dp.message(F.text.in_(["🚖 Buyurtmalarim", "🚖 Мои заказы"]))
async def show_orders(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    today_data = await yandex_api.get_driver_orders(driver.yandex_driver_id, today, today)
    week_data = await yandex_api.get_driver_orders(driver.yandex_driver_id, week_ago, today)

    await message.answer(
        f"{TEXTS[driver.language]['orders_today'].format(orders=today_data['orders'], earned=int(today_data['earned']))}\n\n"
        f"{TEXTS[driver.language]['orders_week'].format(orders=week_data['orders'], earned=int(week_data['earned']))}"
    )

@driver_dp.message(F.text.in_(["💸 Pul yechish", "💸 Вывести деньги"]))
async def start_withdraw(message: types.Message, state: FSMContext):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()

    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting")
        return

    if driver.status == "blocked":
        await message.answer(TEXTS[driver.language]["blocked"])
        return

    active = db.query(WithdrawRequest).filter(
        WithdrawRequest.driver_id == driver.id,
        WithdrawRequest.status.in_(["new", "taken", "processing"])
    ).first()

    if active:
        await message.answer(TEXTS[driver.language]["active_request"])
        return

    available = max(0, driver.balance - NON_WITHDRAWABLE)
    if available <= 0:
        await message.answer(TEXTS[driver.language]["insufficient"].format(available=0))
        return

    await state.set_state(WithdrawState.amount)
    await message.answer(TEXTS[driver.language]["enter_amount"])

@driver_dp.message(WithdrawState.amount)
async def process_withdraw(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Iltimos, to'g'ri summa kiriting!")
        return

    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    available = max(0, driver.balance - NON_WITHDRAWABLE)

    if amount > available:
        await message.answer(TEXTS[driver.language]["insufficient"].format(available=int(available)))
        await state.clear()
        return

    withdraw = WithdrawRequest(driver_id=driver.id, amount=amount, status="new")
    db.add(withdraw)
    db.commit()

    await message.answer(TEXTS[driver.language]["success"].format(id=withdraw.id))
    await state.clear()

    for mgr_id in MANAGER_IDS:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"take_{withdraw.id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{withdraw.id}")],
            [InlineKeyboardButton(text="👤 Профиль", callback_data=f"profile_{driver.id}")],
            [InlineKeyboardButton(text="💸 Выплачено", callback_data=f"paid_{withdraw.id}")]
        ])
        text = (
            f"🆕 НОВАЯ ЗАЯВКА #{withdraw.id}\n\n"
            f"👤 {driver.full_name}\n"
            f"📞 {driver.phone}\n"
            f"💳 ****{driver.card_number[-4:]}\n"
            f"💰 Баланс: {int(driver.balance)} сум\n"
            f"💸 Доступно: {int(available)} сум\n"
            f"💵 Сумма: {int(amount)} сум"
        )
        try:
            mgr_bot = Bot(token=MANAGER_BOT_TOKEN)
            await mgr_bot.send_message(mgr_id, text, reply_markup=kb)
        except:
            pass

@driver_dp.message(F.text.in_(["📜 To'lovlar tarixi", "📜 История выплат"]))
async def show_history(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if not driver:
        return

    history = db.query(WithdrawRequest).filter(
        WithdrawRequest.driver_id == driver.id,
        WithdrawRequest.status == "paid"
    ).order_by(WithdrawRequest.created_at.desc()).limit(10).all()

    if not history:
        await message.answer(TEXTS[driver.language]["no_history"])
        return

    text = TEXTS[driver.language]["history_header"]
    for h in history:
        text += f"#{h.id} - {int(h.amount)} so'm - {h.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    await message.answer(text)

@driver_dp.message(F.text.in_(["💳 Kartam", "💳 Моя карта"]))
async def show_card(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if not driver:
        return
    masked = driver.card_number[-4:] if len(driver.card_number) >= 4 else "****"
    await message.answer(TEXTS[driver.language]["card"].format(card=masked))

@driver_dp.message(F.text.in_(["☎️ Yordam", "☎️ Помощь"]))
async def show_help(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    lang = driver.language if driver else "uz"
    await message.answer(TEXTS[lang]["help"])

@driver_dp.message(F.text.in_(["🌐 Tilni almashtirish", "🌐 Сменить язык"]))
async def change_language(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if driver:
        new_lang = "ru" if driver.language == "uz" else "uz"
        driver.language = new_lang
        db.commit()
        await message.answer(TEXTS[new_lang]["lang_changed"])
        await message.answer(TEXTS[new_lang]["menu"], reply_markup=get_driver_keyboard(new_lang))

# ==================== MANAGER BOT ====================
manager_bot = Bot(token=MANAGER_BOT_TOKEN)
manager_storage = MemoryStorage()
manager_dp = Dispatcher(storage=manager_storage)

@manager_dp.message(F.text == "/start")
async def manager_start(message: types.Message):
    if message.from_user.id not in MANAGER_IDS:
        await message.answer("⛔ У вас нет доступа к этому боту!")
        return
    await message.answer("👨‍💼 Панель менеджера\n\nНовые заявки приходят автоматически.", reply_markup=get_manager_keyboard())

@manager_dp.message(F.text == "📋 Новые заявки")
async def show_new_requests(message: types.Message):
    if message.from_user.id not in MANAGER_IDS:
        return

    db = next(get_db())
    requests = db.query(WithdrawRequest).filter(WithdrawRequest.status == "new").all()

    if not requests:
        await message.answer("📭 Новых заявок нет")
        return

    for req in requests:
        driver = db.query(Driver).filter(Driver.id == req.driver_id).first()
        available = max(0, driver.balance - NON_WITHDRAWABLE)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"take_{req.id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{req.id}")],
            [InlineKeyboardButton(text="👤 Профиль", callback_data=f"profile_{driver.id}")],
            [InlineKeyboardButton(text="💸 Выплачено", callback_data=f"paid_{req.id}")]
        ])

        await message.answer(
            f"🆕 ЗАЯВКА #{req.id}\n\n"
            f"👤 {driver.full_name}\n"
            f"📞 {driver.phone}\n"
            f"💳 ****{driver.card_number[-4:]}\n"
            f"💰 Баланс: {int(driver.balance)} сум\n"
            f"💸 Доступно: {int(available)} сум\n"
            f"💵 Сумма: {int(req.amount)} сум",
            reply_markup=kb
        )

@manager_dp.callback_query(F.data.startswith("take_"))
async def take_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    db = next(get_db())

    withdraw = db.query(WithdrawRequest).filter(
        WithdrawRequest.id == withdraw_id,
        WithdrawRequest.status == "new"
    ).first()

    if not withdraw:
        await callback.answer("❌ Заявка уже обработана!")
        return

    withdraw.status = "taken"
    withdraw.manager_telegram_id = callback.from_user.id
    db.commit()

    await callback.message.edit_text(f"✅ Заявка #{withdraw_id} взята в работу!", reply_markup=None)
    await callback.answer("✅ Взято!")

    driver = db.query(Driver).filter(Driver.id == withdraw.driver_id).first()
    try:
        await driver_bot.send_message(
            driver.telegram_id,
            f"✅ Ваша заявка #{withdraw_id} принята менеджером в работу!"
        )
    except:
        pass

@manager_dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    db = next(get_db())

    withdraw = db.query(WithdrawRequest).filter(WithdrawRequest.id == withdraw_id).first()
    if not withdraw or withdraw.status != "new":
        await callback.answer("❌ Заявка уже обработана!")
        return

    withdraw.status = "rejected"
    withdraw.manager_telegram_id = callback.from_user.id
    db.commit()

    await callback.message.edit_text(f"❌ Заявка #{withdraw_id} отклонена!", reply_markup=None)
    await callback.answer("❌ Отклонено!")

    driver = db.query(Driver).filter(Driver.id == withdraw.driver_id).first()
    try:
        await driver_bot.send_message(
            driver.telegram_id,
            f"❌ Ваша заявка #{withdraw_id} на сумму {int(withdraw.amount)} сум отклонена менеджером."
        )
    except:
        pass

@manager_dp.callback_query(F.data.startswith("paid_"))
async def paid_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    db = next(get_db())

    withdraw = db.query(WithdrawRequest).filter(WithdrawRequest.id == withdraw_id).first()
    if not withdraw or withdraw.status not in ["taken", "processing"]:
        await callback.answer("❌ Заявка не в работе!")
        return

    driver = db.query(Driver).filter(Driver.id == withdraw.driver_id).first()

    prev_balance = driver.balance
    driver.balance -= withdraw.amount
    withdraw.status = "paid"
    withdraw.completed_at = datetime.utcnow()
    withdraw.manager_telegram_id = callback.from_user.id

    log = PayoutLog(
        withdraw_id=withdraw.id,
        driver_id=driver.id,
        amount=withdraw.amount,
        previous_balance=prev_balance,
        new_balance=driver.balance
    )
    db.add(log)
    db.commit()

    await callback.message.edit_text(
        f"✅ Выплата #{withdraw_id} подтверждена!\nСумма: {int(withdraw.amount)} сум\nВодитель: {driver.full_name}",
        reply_markup=None
    )
    await callback.answer("✅ Выплачено!")

    try:
        await driver_bot.send_message(
            driver.telegram_id,
            f"✅ ВЫПЛАТА #{withdraw_id} ПРОИЗВЕДЕНА!\n\n"
            f"Сумма: {int(withdraw.amount)} сум\n"
            f"Текущий баланс: {int(driver.balance)} сум"
        )
    except:
        pass

@manager_dp.callback_query(F.data.startswith("profile_"))
async def show_profile(callback: types.CallbackQuery):
    driver_id = int(callback.data.split("_")[1])
    db = next(get_db())

    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        await callback.answer("❌ Водитель не найден!")
        return

    available = max(0, driver.balance - NON_WITHDRAWABLE)

    await callback.message.answer(
        f"👤 ПРОФИЛЬ ВОДИТЕЛЯ\n\n"
        f"Имя: {driver.full_name}\n"
        f"Телефон: {driver.phone}\n"
        f"Yandex ID: {driver.yandex_driver_id}\n"
        f"Карта: ****{driver.card_number[-4:]}\n"
        f"Статус: {driver.status}\n"
        f"Баланс: {int(driver.balance)} сум\n"
        f"Доступно: {int(available)} сум\n"
        f"Язык: {'Узбекский' if driver.language == 'uz' else 'Русский'}\n"
        f"Регистрация: {driver.created_at.strftime('%d.%m.%Y %H:%M')}"
    )
    await callback.answer()

# ==================== FASTAPI ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(driver_dp.start_polling(driver_bot))
    asyncio.create_task(manager_dp.start_polling(manager_bot))
    yield

app = FastAPI(title="Yakomfort Taxi Payout", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Yakomfort Taxi Payout System"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/drivers")
async def get_drivers():
    db = next(get_db())
    drivers = db.query(Driver).all()
    return [{"id": d.id, "name": d.full_name, "phone": d.phone, "balance": d.balance, "status": d.status} for d in drivers]

@app.get("/api/withdraws")
async def get_withdraws():
    db = next(get_db())
    withdraws = db.query(WithdrawRequest).all()
    return [{"id": w.id, "amount": w.amount, "status": w.status, "created_at": w.created_at.isoformat()} for w in withdraws]

@app.post("/api/sync_balance")
async def sync_balance():
    db = next(get_db())
    drivers = db.query(Driver).filter(Driver.status == "active").all()

    for driver in drivers:
        balance = await yandex_api.get_driver_balance(driver.yandex_driver_id)
        if balance is not None:
            driver.balance = balance
            db.commit()

    return {"synced": len(drivers)}

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

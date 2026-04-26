import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, BigInteger, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import httpx

load_dotenv()

# ==================== КОНФИГ ====================
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/taxi_db")
DRIVER_BOT_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
MANAGER_BOT_TOKEN = os.getenv("MANAGER_BOT_TOKEN")
YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_PARK_ID = os.getenv("YANDEX_PARK_ID")
MANAGER_IDS = [int(x.strip()) for x in os.getenv("MANAGER_IDS", "").split(",") if x.strip()]
NON_WITHDRAWABLE = 10000

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
    yandex_driver_id = Column(String(100), unique=True, nullable=False)
    card_number = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")
    balance = Column(Float, default=0)
    language = Column(String(10), default="uz")
    created_at = Column(DateTime, default=datetime.utcnow)

class WithdrawRequest(Base):
    __tablename__ = "withdraw_requests"
    id = Column(Integer, primary_key=True)
    driver_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String(20), default="new")
    manager_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==================== YANDEX API ====================
class YandexAPI:
    async def get_driver_balance(self, driver_id: str) -> float:
        return 150000
    
    async def get_driver_orders_today(self, driver_id: str) -> Dict:
        return {"orders": 5, "earned": 120000}
    
    async def get_driver_orders_week(self, driver_id: str) -> Dict:
        return {"orders": 32, "earned": 850000}

yandex = YandexAPI()

# ==================== ТЕКСТЫ ====================
TEXTS = {
    "uz": {
        "menu": "💰 Balansim\n🚖 Buyurtmalarim\n💸 Pul yechish\n📜 To'lovlar tarixi\n💳 Kartam\n☎️ Yordam\n🌐 Tilni almashtirish",
        "balance": "💰 Balans: {balance} so'm\n💸 Yechish mumkin: {available} so'm\n⚠️ Minimal qoldiq: 10000 so'm",
        "enter_amount": "💰 Summani kiriting:",
        "insufficient": "❌ Yetarli emas! Yechish mumkin: {available} so'm",
        "success": "✅ So'rov #{id} yuborildi!",
        "blocked": "❌ Hisobingiz bloklangan",
        "active_request": "❌ Avvalgi so'rovingiz hali ko'rib chiqilmoqda",
        "orders_today": "🚖 BUGUN:\n📦 {orders} ta buyurtma\n💰 {earned} so'm",
        "orders_week": "📊 HAfta:\n📦 {orders} ta buyurtma\n💰 {earned} so'm",
        "card": "💳 Karta: ****{card}\n🔄 O'zgartirish uchun menedjerga murojaat qiling",
        "help": "☎️ Yordam: +998 90 123 45 67",
        "lang_changed": "✅ Til o'zgartirildi!",
        "no_history": "📭 To'lovlar tarixi bo'sh",
        "history": "📜 TO'LOVLAR TARIXI:\n"
    },
    "ru": {
        "menu": "💰 Мой баланс\n🚖 Мои заказы\n💸 Вывести деньги\n📜 История выплат\n💳 Моя карта\n☎️ Помощь\n🌐 Сменить язык",
        "balance": "💰 Баланс: {balance} сум\n💸 Доступно: {available} сум\n⚠️ Минимальный остаток: 10000 сум",
        "enter_amount": "💰 Введите сумму:",
        "insufficient": "❌ Недостаточно! Доступно: {available} сум",
        "success": "✅ Заявка #{id} отправлена!",
        "blocked": "❌ Аккаунт заблокирован",
        "active_request": "❌ Предыдущая заявка еще рассматривается",
        "orders_today": "🚖 СЕГОДНЯ:\n📦 {orders} заказов\n💰 {earned} сум",
        "orders_week": "📊 НЕДЕЛЯ:\n📦 {orders} заказов\n💰 {earned} сум",
        "card": "💳 Карта: ****{card}\n🔄 Для смены карты обратитесь к менеджеру",
        "help": "☎️ Помощь: +998 90 123 45 67",
        "lang_changed": "✅ Язык изменен!",
        "no_history": "📭 История выплат пуста",
        "history": "📜 ИСТОРИЯ ВЫПЛАТ:\n"
    }
}

# ==================== РЕГИСТРАЦИЯ ====================
class RegisterState(StatesGroup):
    name = State()
    phone = State()
    yandex_id = State()
    card = State()

class WithdrawState(StatesGroup):
    amount = State()

def get_keyboard(lang: str):
    texts = TEXTS[lang]["menu"].split("\n")
    buttons = [[KeyboardButton(text=text)] for text in texts]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

async def send_to_managers(text: str, reply_markup=None):
    for mgr_id in MANAGER_IDS:
        try:
            bot = Bot(token=MANAGER_BOT_TOKEN)
            await bot.send_message(mgr_id, text, reply_markup=reply_markup)
        except:
            pass

# ==================== DRIVER BOT ====================
driver_bot = Bot(token=DRIVER_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

@dp.message(F.text == "/start")
async def start(message: types.Message, state: FSMContext):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    
    if driver:
        await state.clear()
        await message.answer(TEXTS[driver.language]["menu"], reply_markup=get_keyboard(driver.language))
    else:
        await state.set_state(RegisterState.name)
        await message.answer("🇺🇿 Assalomu alaykum! Ism familiyangizni kiriting:\n🇷🇺 Введите ваше ФИО:")

@dp.message(RegisterState.name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(RegisterState.phone)
    await message.answer("📞 Telefon raqam (+998xxxxxxxxx):\n📞 Номер телефона:")

@dp.message(RegisterState.phone)
async def reg_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(RegisterState.yandex_id)
    await message.answer("🆔 Yandex Driver ID ni kiriting:\n🆔 Введите Yandex Driver ID:")

@dp.message(RegisterState.yandex_id)
async def reg_yandex(message: types.Message, state: FSMContext):
    await state.update_data(yandex_id=message.text)
    await state.set_state(RegisterState.card)
    await message.answer("💳 Karta raqami (8600xxxxxx):\n💳 Номер карты:")

@dp.message(RegisterState.card)
async def reg_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    db = next(get_db())
    
    new_driver = Driver(
        telegram_id=message.from_user.id,
        full_name=data['name'],
        phone=data['phone'],
        yandex_driver_id=data['yandex_id'],
        card_number=message.text,
        status="active",
        balance=350000,
        language="uz"
    )
    db.add(new_driver)
    db.commit()
    
    await message.answer("✅ Ro'yxatdan o'tdingiz!\n✅ Вы зарегистрированы!")
    await message.answer(TEXTS["uz"]["menu"], reply_markup=get_keyboard("uz"))
    await state.clear()
    
    await send_to_managers(f"🆕 Новый водитель!\n{data['name']}\n{data['phone']}")

@dp.message(F.text.in_(["💰 Balansim", "💰 Мой баланс"]))
async def show_balance(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting / Зарегистрируйтесь")
        return
    
    available = max(0, driver.balance - NON_WITHDRAWABLE)
    await message.answer(TEXTS[driver.language]["balance"].format(balance=driver.balance, available=available))

@dp.message(F.text.in_(["🚖 Buyurtmalarim", "🚖 Мои заказы"]))
async def show_orders(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting")
        return
    
    today = await yandex.get_driver_orders_today(driver.yandex_driver_id)
    week = await yandex.get_driver_orders_week(driver.yandex_driver_id)
    
    text_today = TEXTS[driver.language]["orders_today"].format(orders=today['orders'], earned=today['earned'])
    text_week = TEXTS[driver.language]["orders_week"].format(orders=week['orders'], earned=week['earned'])
    await message.answer(f"{text_today}\n\n{text_week}")

@dp.message(F.text.in_(["💸 Pul yechish", "💸 Вывести деньги"]))
async def start_withdraw(message: types.Message, state: FSMContext):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    
    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting")
        return
    
    if driver.status == "blocked":
        await message.answer(TEXTS[driver.language]["blocked"])
        return
    
    active = db.query(WithdrawRequest).filter(WithdrawRequest.driver_id == driver.id, WithdrawRequest.status == "new").first()
    if active:
        await message.answer(TEXTS[driver.language]["active_request"])
        return
    
    available = max(0, driver.balance - NON_WITHDRAWABLE)
    if available <= 0:
        await message.answer(TEXTS[driver.language]["insufficient"].format(available=0))
        return
    
    await state.set_state(WithdrawState.amount)
    await message.answer(TEXTS[driver.language]["enter_amount"])

@dp.message(WithdrawState.amount)
async def process_withdraw(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
    except:
        await message.answer("❌ Faqat son kiriting!")
        return
    
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    available = max(0, driver.balance - NON_WITHDRAWABLE)
    
    if amount <= 0 or amount > available:
        await message.answer(TEXTS[driver.language]["insufficient"].format(available=available))
        return
    
    withdraw = WithdrawRequest(driver_id=driver.id, amount=amount)
    db.add(withdraw)
    db.commit()
    
    await message.answer(TEXTS[driver.language]["success"].format(id=withdraw.id))
    await state.clear()
    
    for mgr_id in MANAGER_IDS:
        text = f"🆕 ЗАЯВКА #{withdraw.id}\n👤 {driver.full_name}\n📞 {driver.phone}\n💳 {driver.card_number}\n💰 Баланс: {driver.balance}\n💵 Сумма: {amount}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Взять", callback_data=f"take_{withdraw.id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{withdraw.id}")],
            [InlineKeyboardButton(text="💸 Выплачено", callback_data=f"paid_{withdraw.id}")]
        ])
        try:
            bot = Bot(token=MANAGER_BOT_TOKEN)
            await bot.send_message(mgr_id, text, reply_markup=kb)
        except:
            pass

@dp.message(F.text.in_(["📜 To'lovlar tarixi", "📜 История выплат"]))
async def show_history(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if not driver:
        return
    
    history = db.query(WithdrawRequest).filter(WithdrawRequest.driver_id == driver.id, WithdrawRequest.status == "paid").order_by(WithdrawRequest.created_at.desc()).limit(10).all()
    
    if not history:
        await message.answer(TEXTS[driver.language]["no_history"])
        return
    
    text = TEXTS[driver.language]["history"]
    for h in history:
        text += f"#{h.id} - {h.amount} so'm - {h.created_at.strftime('%d.%m.%Y')}\n"
    await message.answer(text)

@dp.message(F.text.in_(["💳 Kartam", "💳 Моя карта"]))
async def show_card(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if not driver:
        return
    
    masked = driver.card_number[-4:] if len(driver.card_number) >= 4 else "****"
    await message.answer(TEXTS[driver.language]["card"].format(card=masked))

@dp.message(F.text.in_(["☎️ Yordam", "☎️ Помощь"]))
async def show_help(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    lang = driver.language if driver else "uz"
    await message.answer(TEXTS[lang]["help"])

@dp.message(F.text.in_(["🌐 Tilni almashtirish", "🌐 Сменить язык"]))
async def change_lang(message: types.Message):
    db = next(get_db())
    driver = db.query(Driver).filter(Driver.telegram_id == message.from_user.id).first()
    if driver:
        new_lang = "ru" if driver.language == "uz" else "uz"
        driver.language = new_lang
        db.commit()
        await message.answer(TEXTS[new_lang]["lang_changed"])
        await message.answer(TEXTS[new_lang]["menu"], reply_markup=get_keyboard(new_lang))

# ==================== MANAGER BOT ====================
manager_bot = Bot(token=MANAGER_BOT_TOKEN)
manager_dp = Dispatcher()

@manager_dp.message(F.text == "/start")
async def mgr_start(message: types.Message):
    if message.from_user.id not in MANAGER_IDS:
        await message.answer("❌ Доступ запрещен!")
        return
    await message.answer("✅ Бот менеджера запущен!\nНовые заявки приходят автоматически.")

@manager_dp.callback_query(F.data.startswith("take_"))
async def take_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    db = next(get_db())
    
    withdraw = db.query(WithdrawRequest).filter(WithdrawRequest.id == withdraw_id, WithdrawRequest.status == "new").first()
    if not withdraw:
        await callback.answer("❌ Заявка уже обработана!")
        return
    
    withdraw.status = "taken"
    withdraw.manager_id = callback.from_user.id
    db.commit()
    
    await callback.message.edit_text(f"✅ Заявка #{withdraw_id} взята в работу!", reply_markup=None)
    await callback.answer("✅ Взято!")
    
    driver = db.query(Driver).filter(Driver.id == withdraw.driver_id).first()
    try:
        await driver_bot.send_message(driver.telegram_id, f"✅ Ваша заявка #{withdraw_id} принята менеджером!")
    except:
        pass

@manager_dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    db = next(get_db())
    
    withdraw = db.query(WithdrawRequest).filter(WithdrawRequest.id == withdraw_id).first()
    if withdraw and withdraw.status == "new":
        withdraw.status = "rejected"
        db.commit()
        
        await callback.message.edit_text(f"❌ Заявка #{withdraw_id} отклонена!", reply_markup=None)
        
        driver = db.query(Driver).filter(Driver.id == withdraw.driver_id).first()
        try:
            await driver_bot.send_message(driver.telegram_id, f"❌ Заявка #{withdraw_id} отклонена менеджером!")
        except:
            pass
    
    await callback.answer()

@manager_dp.callback_query(F.data.startswith("paid_"))
async def paid_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    db = next(get_db())
    
    withdraw = db.query(WithdrawRequest).filter(WithdrawRequest.id == withdraw_id).first()
    if not withdraw or withdraw.status not in ["taken", "processing"]:
        await callback.answer("❌ Заявка не в работе!")
        return
    
    driver = db.query(Driver).filter(Driver.id == withdraw.driver_id).first()
    
    withdraw.status = "paid"
    withdraw.completed_at = datetime.utcnow()
    driver.balance -= withdraw.amount
    db.commit()
    
    await callback.message.edit_text(f"✅ Выплата #{withdraw_id} подтверждена!", reply_markup=None)
    await callback.answer("✅ Выплачено!")
    
    try:
        await driver_bot.send_message(driver.telegram_id, f"✅ ВЫПЛАТА #{withdraw_id}!\nСумма: {withdraw.amount} so'm\nОстаток: {driver.balance} so'm")
    except:
        pass

# ==================== FASTAPI ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(dp.start_polling(driver_bot))
    asyncio.create_task(manager_dp.start_polling(manager_bot))
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/drivers")
async def get_drivers(db: Session = Depends(get_db)):
    return db.query(Driver).all()

@app.get("/api/withdraws")
async def get_withdraws(db: Session = Depends(get_db)):
    return db.query(WithdrawRequest).all()

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

import os
import asyncio
from datetime import datetime
from typing import Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, select
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import httpx

# Загружаем переменные окружения из .env (для Render они уже есть в Environment)
load_dotenv()

# ==================== КОНФИГ ДЛЯ RENDER ====================
# База данных: используем SQLite для простоты на Render. Для PostgreSQL позже заменим строку.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./taxi.db")
DRIVER_BOT_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
MANAGER_BOT_TOKEN = os.getenv("MANAGER_BOT_TOKEN")
MANAGER_IDS = [int(x.strip()) for x in os.getenv("MANAGER_IDS", "").split(",") if x.strip()]
NON_WITHDRAWABLE = 10000
print("DRIVER_BOT_TOKEN =", repr(DRIVER_BOT_TOKEN))
print("MANAGER_BOT_TOKEN =", repr(MANAGER_BOT_TOKEN))
print("MANAGER_IDS =", repr(os.getenv("MANAGER_IDS")))

# Заглушка для Yandex API (позже подключите реальный)
class YandexAPI:
    async def get_driver_orders_today(self, driver_id: str) -> Dict:
        return {"orders": 5, "earned": 120000}
    async def get_driver_orders_week(self, driver_id: str) -> Dict:
        return {"orders": 32, "earned": 850000}

yandex = YandexAPI()

# ==================== АСИНХРОННАЯ БАЗА ДАННЫХ ====================
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
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

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

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

# ==================== FSM ====================
class RegisterState(StatesGroup):
    name = State()
    phone = State()
    yandex_id = State()
    card = State()

class WithdrawState(StatesGroup):
    amount = State()

# ==================== DRIVER BOT ====================
driver_bot = Bot(token=DRIVER_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

@dp.message(F.text == "/start")
async def start(message: types.Message, state: FSMContext):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
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
    async for db in get_db():
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
        await db.commit()
        await message.answer("✅ Ro'yxatdan o'tdingiz!\n✅ Вы зарегистрированы!")
        await message.answer(TEXTS["uz"]["menu"], reply_markup=get_keyboard("uz"))
        await state.clear()
        await send_to_managers(f"🆕 Новый водитель!\n{data['name']}\n{data['phone']}")

@dp.message(F.text.in_(["💰 Balansim", "💰 Мой баланс"]))
async def show_balance(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if not driver:
            await message.answer("❌ Ro'yxatdan o'ting / Зарегистрируйтесь")
            return
        available = max(0, driver.balance - NON_WITHDRAWABLE)
        await message.answer(TEXTS[driver.language]["balance"].format(balance=driver.balance, available=available))

@dp.message(F.text.in_(["🚖 Buyurtmalarim", "🚖 Мои заказы"]))
async def show_orders(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
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
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if not driver:
            await message.answer("❌ Ro'yxatdan o'ting")
            return
        if driver.status == "blocked":
            await message.answer(TEXTS[driver.language]["blocked"])
            return
        active_result = await db.execute(select(WithdrawRequest).where(WithdrawRequest.driver_id == driver.id, WithdrawRequest.status == "new"))
        active = active_result.scalar_one_or_none()
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
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if not driver: return
        available = max(0, driver.balance - NON_WITHDRAWABLE)
        if amount <= 0 or amount > available:
            await message.answer(TEXTS[driver.language]["insufficient"].format(available=available))
            return
        withdraw = WithdrawRequest(driver_id=driver.id, amount=amount, status="new")
        db.add(withdraw)
        await db.commit()
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
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if not driver:
            return
        history_result = await db.execute(select(WithdrawRequest).where(WithdrawRequest.driver_id == driver.id, WithdrawRequest.status == "paid").order_by(WithdrawRequest.created_at.desc()).limit(10))
        history = history_result.scalars().all()
        if not history:
            await message.answer(TEXTS[driver.language]["no_history"])
            return
        text = TEXTS[driver.language]["history"]
        for h in history:
            text += f"#{h.id} - {h.amount} so'm - {h.created_at.strftime('%d.%m.%Y')}\n"
        await message.answer(text)

@dp.message(F.text.in_(["💳 Kartam", "💳 Моя карта"]))
async def show_card(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if not driver:
            return
        masked = driver.card_number[-4:] if len(driver.card_number) >= 4 else "****"
        await message.answer(TEXTS[driver.language]["card"].format(card=masked))

@dp.message(F.text.in_(["☎️ Yordam", "☎️ Помощь"]))
async def show_help(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        lang = driver.language if driver else "uz"
        await message.answer(TEXTS[lang]["help"])

@dp.message(F.text.in_(["🌐 Tilni almashtirish", "🌐 Сменить язык"]))
async def change_lang(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if driver:
            new_lang = "ru" if driver.language == "uz" else "uz"
            driver.language = new_lang
            await db.commit()
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
    async for db in get_db():
        result = await db.execute(select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id, WithdrawRequest.status == "new"))
        withdraw = result.scalar_one_or_none()
        if not withdraw:
            await callback.answer("❌ Заявка уже обработана!")
            return
        withdraw.status = "taken"
        withdraw.manager_id = callback.from_user.id
        await db.commit()
        await callback.message.edit_text(f"✅ Заявка #{withdraw_id} взята в работу!", reply_markup=None)
        await callback.answer("✅ Взято!")
        driver_result = await db.execute(select(Driver).where(Driver.id == withdraw.driver_id))
        driver = driver_result.scalar_one_or_none()
        if driver:
            try:
                await driver_bot.send_message(driver.telegram_id, f"✅ Ваша заявка #{withdraw_id} принята менеджером!")
            except:
                pass

@manager_dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    async for db in get_db():
        result = await db.execute(select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id))
        withdraw = result.scalar_one_or_none()
        if withdraw and withdraw.status == "new":
            withdraw.status = "rejected"
            await db.commit()
            await callback.message.edit_text(f"❌ Заявка #{withdraw_id} отклонена!", reply_markup=None)
            driver_result = await db.execute(select(Driver).where(Driver.id == withdraw.driver_id))
            driver = driver_result.scalar_one_or_none()
            if driver:
                try:
                    await driver_bot.send_message(driver.telegram_id, f"❌ Заявка #{withdraw_id} отклонена менеджером!")
                except:
                    pass
        await callback.answer()

@manager_dp.callback_query(F.data.startswith("paid_"))
async def paid_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    async for db in get_db():
        result = await db.execute(select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id))
        withdraw = result.scalar_one_or_none()
        if not withdraw or withdraw.status not in ["taken", "processing"]:
            await callback.answer("❌ Заявка не в работе!")
            return
        driver_result = await db.execute(select(Driver).where(Driver.id == withdraw.driver_id))
        driver = driver_result.scalar_one_or_none()
        if driver:
            withdraw.status = "paid"
            withdraw.completed_at = datetime.utcnow()
            driver.balance -= withdraw.amount
            await db.commit()
            await callback.message.edit_text(f"✅ Выплата #{withdraw_id} подтверждена!", reply_markup=None)
            await callback.answer("✅ Выплачено!")
            try:
                await driver_bot.send_message(driver.telegram_id, f"✅ ВЫПЛАТА #{withdraw_id}!\nСумма: {withdraw.amount} so'm\nОстаток: {driver.balance} so'm")
            except:
                pass

# ==================== FASTAPI ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(dp.start_polling(driver_bot))
    asyncio.create_task(manager_dp.start_polling(manager_bot))
    yield
    # здесь можно закрыть сессии

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/drivers")
async def get_drivers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Driver))
    drivers = result.scalars().all()
    return drivers

@app.get("/api/withdraws")
async def get_withdraws(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WithdrawRequest))
    withdraws = result.scalars().all()
    return withdraws

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    import uvicorn
    # Render требует привязки к 0.0.0.0 и может использовать порт через PORT
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

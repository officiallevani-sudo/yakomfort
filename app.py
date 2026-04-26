import os
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Float, BigInteger, DateTime, select
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./taxi.db")
DRIVER_BOT_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
MANAGER_BOT_TOKEN = os.getenv("MANAGER_BOT_TOKEN")
MANAGER_IDS = [int(x.strip()) for x in os.getenv("MANAGER_IDS", "").split(",") if x.strip()]
RESERVE = 10000  # Неснимаемый остаток

# ==================== БАЗА ДАННЫХ ====================
engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

class Driver(Base):
    __tablename__ = "drivers"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    balance = Column(Float, default=0)
    card = Column(String, nullable=False)
    status = Column(String, default="active")

class Withdraw(Base):
    __tablename__ = "withdraws"
    id = Column(Integer, primary_key=True)
    driver_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, default="new")
    manager_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

async def get_db():
    async with SessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ==================== КЛАВИАТУРЫ ====================
def get_driver_keyboard():
    buttons = [
        [KeyboardButton(text="💰 Баланс")],
        [KeyboardButton(text="💸 Вывести деньги")],
        [KeyboardButton(text="📜 История выплат")],
        [KeyboardButton(text="💳 Моя карта")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_manager_keyboard():
    buttons = [[KeyboardButton(text="📋 Новые заявки")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ==================== DRIVER BOT ====================
driver_bot = Bot(token=DRIVER_BOT_TOKEN)
driver_dp = Dispatcher()

@driver_dp.message(F.text == "/start")
async def driver_start(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        
        if driver:
            await message.answer(f"👋 Здравствуйте, {driver.name}!\n\n💰 Ваш баланс: {driver.balance} сум\n💳 Карта: ****{driver.card[-4:]}", reply_markup=get_driver_keyboard())
        else:
            await message.answer("🚖 Добро пожаловать в таксопарк!\n\nОтправьте ваше ФИО для регистрации:")
            await driver_dp.state.set_state("waiting_name")

@driver_dp.message(F.text == "💰 Баланс")
async def show_balance(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if driver:
            available = max(0, driver.balance - RESERVE)
            await message.answer(f"💰 Ваш баланс: {driver.balance} сум\n💸 Доступно к выводу: {available} сум\n⚠️ Неснимаемый остаток: {RESERVE} сум")

@driver_dp.message(F.text == "💸 Вывести деньги")
async def withdraw_request(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        
        if not driver:
            await message.answer("❌ Сначала зарегистрируйтесь! Отправьте /start")
            return
        
        available = max(0, driver.balance - RESERVE)
        if available <= 0:
            await message.answer(f"❌ Недостаточно средств! Доступно: {available} сум")
            return
        
        # Проверяем есть ли активная заявка
        active = await db.execute(select(Withdraw).where(Withdraw.driver_id == driver.id, Withdraw.status == "new"))
        if active.scalar_one_or_none():
            await message.answer("❌ У вас уже есть активная заявка на вывод!")
            return
        
        # Создаем заявку на всю доступную сумму
        withdraw = Withdraw(driver_id=driver.id, amount=available, status="new")
        db.add(withdraw)
        await db.commit()
        
        await message.answer(f"✅ Заявка на вывод {available} сум отправлена менеджеру!\nНомер заявки: #{withdraw.id}")
        
        # Уведомляем всех менеджеров
        for mgr_id in MANAGER_IDS:
            try:
                mgr_bot = Bot(token=MANAGER_BOT_TOKEN)
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Выплачено", callback_data=f"pay_{withdraw.id}")],
                    [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{withdraw.id}")]
                ])
                await mgr_bot.send_message(
                    mgr_id,
                    f"🆕 НОВАЯ ЗАЯВКА #{withdraw.id}\n\n"
                    f"👤 Водитель: {driver.name}\n"
                    f"📞 Телефон: {driver.phone}\n"
                    f"💳 Карта: ****{driver.card[-4:]}\n"
                    f"💰 Баланс: {driver.balance} сум\n"
                    f"💸 Сумма вывода: {available} сум",
                    reply_markup=kb
                )
            except:
                pass

@driver_dp.message(F.text == "📜 История выплат")
async def show_history(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if not driver:
            return
        
        history = await db.execute(
            select(Withdraw).where(Withdraw.driver_id == driver.id, Withdraw.status == "paid")
            .order_by(Withdraw.created_at.desc()).limit(10)
        )
        history_list = history.scalars().all()
        
        if not history_list:
            await message.answer("📭 История выплат пуста")
            return
        
        text = "📜 ИСТОРИЯ ВЫПЛАТ:\n\n"
        for h in history_list:
            text += f"#{h.id} - {h.amount} сум - {h.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        await message.answer(text)

@driver_dp.message(F.text == "💳 Моя карта")
async def show_card(message: types.Message):
    async for db in get_db():
        result = await db.execute(select(Driver).where(Driver.telegram_id == message.from_user.id))
        driver = result.scalar_one_or_none()
        if driver:
            await message.answer(f"💳 Ваша карта: ****{driver.card[-4:]}\n\nДля смены карты обратитесь к менеджеру.")

# Регистрация (FSM через простые состояния)
@driver_dp.message(F.text, driver_dp.state.is_state("waiting_name"))
async def reg_name(message: types.Message):
    await driver_dp.state.update_data(name=message.text)
    await driver_dp.state.set_state("waiting_phone")
    await message.answer("📞 Отправьте номер телефона (например: +998901234567):")

@driver_dp.message(F.text, driver_dp.state.is_state("waiting_phone"))
async def reg_phone(message: types.Message):
    await driver_dp.state.update_data(phone=message.text)
    await driver_dp.state.set_state("waiting_card")
    await message.answer("💳 Отправьте номер карты (например: 8600123456789012):")

@driver_dp.message(F.text, driver_dp.state.is_state("waiting_card"))
async def reg_card(message: types.Message):
    data = await driver_dp.state.get_data()
    
    async for db in get_db():
        new_driver = Driver(
            telegram_id=message.from_user.id,
            name=data['name'],
            phone=data['phone'],
            card=message.text,
            balance=0,
            status="active"
        )
        db.add(new_driver)
        await db.commit()
        
        await message.answer("✅ Регистрация завершена!", reply_markup=get_driver_keyboard())
        await driver_dp.state.clear()

# ==================== MANAGER BOT ====================
manager_bot = Bot(token=MANAGER_BOT_TOKEN)
manager_dp = Dispatcher()

@manager_dp.message(F.text == "/start")
async def manager_start(message: types.Message):
    if message.from_user.id not in MANAGER_IDS:
        await message.answer("⛔ У вас нет доступа к этому боту!")
        return
    await message.answer("👨‍💼 Добро пожаловать в панель менеджера!\n\nНовые заявки будут приходить автоматически.", reply_markup=get_manager_keyboard())

@manager_dp.message(F.text == "📋 Новые заявки")
async def show_new_requests(message: types.Message):
    if message.from_user.id not in MANAGER_IDS:
        return
    
    async for db in get_db():
        result = await db.execute(select(Withdraw).where(Withdraw.status == "new"))
        requests = result.scalars().all()
        
        if not requests:
            await message.answer("📭 Новых заявок нет")
            return
        
        for req in requests:
            driver_result = await db.execute(select(Driver).where(Driver.id == req.driver_id))
            driver = driver_result.scalar_one_or_none()
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Выплачено", callback_data=f"pay_{req.id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{req.id}")]
            ])
            
            await message.answer(
                f"🆕 ЗАЯВКА #{req.id}\n\n"
                f"👤 Водитель: {driver.name}\n"
                f"📞 Телефон: {driver.phone}\n"
                f"💳 Карта: ****{driver.card[-4:]}\n"
                f"💰 Баланс: {driver.balance} сум\n"
                f"💸 Сумма: {req.amount} сум",
                reply_markup=kb
            )

@manager_dp.callback_query(F.data.startswith("pay_"))
async def pay_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    
    async for db in get_db():
        result = await db.execute(select(Withdraw).where(Withdraw.id == withdraw_id))
        withdraw = result.scalar_one_or_none()
        
        if not withdraw or withdraw.status != "new":
            await callback.answer("❌ Заявка уже обработана!")
            return
        
        driver_result = await db.execute(select(Driver).where(Driver.id == withdraw.driver_id))
        driver = driver_result.scalar_one_or_none()
        
        # Обновляем баланс
        driver.balance -= withdraw.amount
        withdraw.status = "paid"
        withdraw.manager_id = callback.from_user.id
        await db.commit()
        
        await callback.message.edit_text(f"✅ Заявка #{withdraw_id} выплачена!\nСумма: {withdraw.amount} сум", reply_markup=None)
        await callback.answer("✅ Выплата подтверждена!")
        
        # Уведомляем водителя
        try:
            await driver_bot.send_message(
                driver.telegram_id,
                f"✅ ВЫПЛАТА ПРОИЗВЕДЕНА!\n\nСумма: {withdraw.amount} сум\nТекущий баланс: {driver.balance} сум"
            )
        except:
            pass

@manager_dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    
    async for db in get_db():
        result = await db.execute(select(Withdraw).where(Withdraw.id == withdraw_id))
        withdraw = result.scalar_one_or_none()
        
        if not withdraw or withdraw.status != "new":
            await callback.answer("❌ Заявка уже обработана!")
            return
        
        driver_result = await db.execute(select(Driver).where(Driver.id == withdraw.driver_id))
        driver = driver_result.scalar_one_or_none()
        
        withdraw.status = "rejected"
        withdraw.manager_id = callback.from_user.id
        await db.commit()
        
        await callback.message.edit_text(f"❌ Заявка #{withdraw_id} отклонена!", reply_markup=None)
        await callback.answer("❌ Отклонено!")
        
        # Уведомляем водителя
        try:
            await driver_bot.send_message(
                driver.telegram_id,
                f"❌ Ваша заявка #{withdraw_id} на сумму {withdraw.amount} сум отклонена менеджером."
            )
        except:
            pass

# ==================== FASTAPI ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализируем базу данных
    await init_db()
    
    # Запускаем ботов
    asyncio.create_task(driver_dp.start_polling(driver_bot))
    asyncio.create_task(manager_dp.start_polling(manager_bot))
    
    yield

app = FastAPI(title="Taxi Payout System", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Bot is running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

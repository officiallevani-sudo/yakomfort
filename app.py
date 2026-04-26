import os
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

# ==================== КОНФИГ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ТВОЙ TELEGRAM ID!

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            card_number TEXT NOT NULL,
            balance REAL DEFAULT 350000,
            language TEXT DEFAULT 'uz',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdraw_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def is_admin(telegram_id):
    return telegram_id == ADMIN_ID

def get_driver(telegram_id):
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def create_driver(telegram_id, name, phone, card):
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO drivers (telegram_id, full_name, phone, card_number, balance, language)
        VALUES (?, ?, ?, ?, 350000, 'uz')
    ''', (telegram_id, name, phone, card))
    conn.commit()
    conn.close()

def create_withdraw(driver_id, amount):
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO withdraw_requests (driver_id, amount, status)
        VALUES (?, ?, 'new')
    ''', (driver_id, amount))
    conn.commit()
    withdraw_id = cursor.lastrowid
    conn.close()
    return withdraw_id

def get_withdraw(withdraw_id):
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.*, d.full_name, d.phone, d.card_number, d.telegram_id as driver_tg
        FROM withdraw_requests w
        JOIN drivers d ON d.id = w.driver_id
        WHERE w.id = ?
    ''', (withdraw_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_new_withdraws():
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.*, d.full_name, d.phone, d.card_number
        FROM withdraw_requests w
        JOIN drivers d ON d.id = w.driver_id
        WHERE w.status = 'new'
        ORDER BY w.created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_withdraw_status(withdraw_id, status):
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE withdraw_requests SET status = ? WHERE id = ?", (status, withdraw_id))
    conn.commit()
    conn.close()

def get_driver_balance(driver_id):
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM drivers WHERE id = ?", (driver_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def update_driver_balance(driver_id, new_balance):
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE drivers SET balance = ? WHERE id = ?", (new_balance, driver_id))
    conn.commit()
    conn.close()

def get_paid_history(driver_id):
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM withdraw_requests 
        WHERE driver_id = ? AND status = 'paid' 
        ORDER BY created_at DESC LIMIT 10
    ''', (driver_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_stats():
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM drivers")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(amount) FROM withdraw_requests WHERE status = 'paid'")
    total_paid = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'new'")
    pending = cursor.fetchone()[0]
    conn.close()
    return users, total_paid, pending

# ==================== ТЕКСТЫ ====================
TEXTS = {
    "uz": {
        "menu": "💰 Balansim\n🚖 Buyurtmalarim\n💸 Pul yechish\n📜 To'lovlar tarixi\n💳 Kartam\n☎️ Yordam\n🌐 Tilni almashtirish",
        "balance": "💰 Balans: {balance} so'm\n💸 Yechish mumkin: {available} so'm",
        "enter_amount": "💰 Summani kiriting:",
        "insufficient": "❌ Yetarli emas! Yechish mumkin: {available} so'm",
        "success": "✅ So'rov #{id} yuborildi!",
        "orders": "🚖 BUGUN: 5 ta / 120000 so'm\n📊 HAFTA: 32 ta / 850000 so'm",
        "card": "💳 Karta: ****{card}",
        "help": "☎️ Yordam: +998771202255",
        "lang_changed": "✅ Til o'zgartirildi!",
        "no_history": "📭 To'lovlar tarixi bo'sh",
        "history": "📜 TO'LOVLAR TARIXI:\n",
        "register_name": "📝 Ism familiyangizni kiriting:",
        "register_phone": "📞 Telefon raqamingiz:",
        "register_card": "💳 Karta raqami:",
        "register_success": "✅ Ro'yxatdan o'tdingiz!",
        "new_request": "🆕 YANGI SO'ROV #{id}\n\n👤 {name}\n📞 {phone}\n💳 ****{card}\n💰 Balans: {balance}\n💵 Summa: {amount} so'm",
        "paid_notify": "✅ Sizning #{id} so'rovingiz bo'yicha {amount} so'm to'landi!",
        "admin_new": "📋 Yangi so'rovlar:",
        "admin_no_requests": "📭 Yangi so'rovlar yo'q",
        "admin_stats": "📊 STATISTIKA\n\n👥 Foydalanuvchilar: {users}\n💰 Jami to'lovlar: {total_paid} so'm\n📝 Kutilayotgan: {pending} ta",
    },
    "ru": {
        "menu": "💰 Мой баланс\n🚖 Мои заказы\n💸 Вывести деньги\n📜 История выплат\n💳 Моя карта\n☎️ Помощь\n🌐 Сменить язык",
        "balance": "💰 Баланс: {balance} сум\n💸 Доступно: {available} сум",
        "enter_amount": "💰 Введите сумму:",
        "insufficient": "❌ Недостаточно! Доступно: {available} сум",
        "success": "✅ Заявка #{id} отправлена!",
        "orders": "🚖 СЕГОДНЯ: 5 зак / 120000 сум\n📊 НЕДЕЛЯ: 32 зак / 850000 сум",
        "card": "💳 Карта: ****{card}",
        "help": "☎️ Помощь: +998771202255",
        "lang_changed": "✅ Язык изменен!",
        "no_history": "📭 История выплат пуста",
        "history": "📜 ИСТОРИЯ ВЫПЛАТ:\n",
        "register_name": "📝 Введите ваше ФИО:",
        "register_phone": "📞 Введите номер телефона:",
        "register_card": "💳 Введите номер карты:",
        "register_success": "✅ Вы зарегистрированы!",
        "new_request": "🆕 НОВАЯ ЗАЯВКА #{id}\n\n👤 {name}\n📞 {phone}\n💳 ****{card}\n💰 Баланс: {balance}\n💵 Сумма: {amount} сум",
        "paid_notify": "✅ По вашей заявке #{id} выплачено {amount} сум!",
        "admin_new": "📋 Новые заявки:",
        "admin_no_requests": "📭 Новых заявок нет",
        "admin_stats": "📊 СТАТИСТИКА\n\n👥 Пользователей: {users}\n💰 Всего выплат: {total_paid} сум\n📝 Ожидают: {pending} шт",
    }
}

# ==================== КЛАВИАТУРЫ ====================
def get_driver_keyboard(lang):
    texts = TEXTS[lang]["menu"].split("\n")
    buttons = [[KeyboardButton(text=text)] for text in texts]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Yangi so'rovlar"), KeyboardButton(text="📊 Statistika")]],
        resize_keyboard=True
    )

# ==================== FSM ====================
class RegisterState(StatesGroup):
    name = State()
    phone = State()
    card = State()

class WithdrawState(StatesGroup):
    amount = State()

# ==================== БОТ ====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(F.text == "/start")
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    driver = get_driver(message.from_user.id)
    
    if driver:
        lang = driver[7]
        await message.answer(TEXTS[lang]["menu"], reply_markup=get_driver_keyboard(lang))
    elif is_admin(message.from_user.id):
        await message.answer("👨‍💼 Admin panel", reply_markup=get_admin_keyboard())
    else:
        await message.answer("🇺🇿 Assalomu alaykum! / 🇷🇺 Добро пожаловать!\n\n" + TEXTS["uz"]["register_name"])
        await state.set_state(RegisterState.name)

@dp.message(RegisterState.name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(RegisterState.phone)
    await message.answer(TEXTS["uz"]["register_phone"])

@dp.message(RegisterState.phone)
async def reg_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(RegisterState.card)
    await message.answer(TEXTS["uz"]["register_card"])

@dp.message(RegisterState.card)
async def reg_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    existing = get_driver(message.from_user.id)
    if existing:
        await message.answer("❌ Siz allaqachon ro'yxatdan o'tgansiz!")
        await state.clear()
        return
    
    create_driver(message.from_user.id, data['name'], data['phone'], message.text)
    await message.answer(TEXTS["uz"]["register_success"])
    await message.answer(TEXTS["uz"]["menu"], reply_markup=get_driver_keyboard("uz"))
    await state.clear()

# ==================== ДЛЯ ВОДИТЕЛЕЙ ====================
@dp.message(F.text.in_(["💰 Balansim", "💰 Мой баланс"]))
async def show_balance(message: types.Message):
    driver = get_driver(message.from_user.id)
    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting!")
        return
    
    balance = driver[5]
    available = max(0, balance - 10000)
    lang = driver[7]
    await message.answer(TEXTS[lang]["balance"].format(balance=int(balance), available=int(available)))

@dp.message(F.text.in_(["🚖 Buyurtmalarim", "🚖 Мои заказы"]))
async def show_orders(message: types.Message):
    driver = get_driver(message.from_user.id)
    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting!")
        return
    lang = driver[7]
    await message.answer(TEXTS[lang]["orders"])

@dp.message(F.text.in_(["💸 Pul yechish", "💸 Вывести деньги"]))
async def start_withdraw(message: types.Message, state: FSMContext):
    driver = get_driver(message.from_user.id)
    if not driver:
        await message.answer("❌ Ro'yxatdan o'ting!")
        return
    
    balance = driver[5]
    available = max(0, balance - 10000)
    lang = driver[7]
    
    if available <= 0:
        await message.answer(TEXTS[lang]["insufficient"].format(available=0))
        return
    
    await state.update_data(driver_id=driver[0])
    await state.set_state(WithdrawState.amount)
    await message.answer(TEXTS[lang]["enter_amount"])

@dp.message(WithdrawState.amount)
async def process_withdraw(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
    except:
        await message.answer("❌ Faqat son kiriting!")
        return
    
    data = await state.get_data()
    driver_id = data['driver_id']
    
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, language, full_name, phone, card_number FROM drivers WHERE id = ?", (driver_id,))
    driver = cursor.fetchone()
    conn.close()
    
    balance = driver[0]
    lang = driver[1]
    available = max(0, balance - 10000)
    
    if amount <= 0 or amount > available:
        await message.answer(TEXTS[lang]["insufficient"].format(available=int(available)))
        await state.clear()
        return
    
    withdraw_id = create_withdraw(driver_id, amount)
    
    await message.answer(TEXTS[lang]["success"].format(id=withdraw_id))
    await state.clear()
    
    # Отправляем уведомление админу
    if ADMIN_ID:
        text = TEXTS[lang]["new_request"].format(
            id=withdraw_id,
            name=driver[2],
            phone=driver[3],
            card=driver[4][-4:],
            balance=int(balance),
            amount=int(amount)
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выплачено", callback_data=f"pay_{withdraw_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{withdraw_id}")]
        ])
        await bot.send_message(ADMIN_ID, text, reply_markup=kb)

@dp.message(F.text.in_(["📜 To'lovlar tarixi", "📜 История выплат"]))
async def show_history(message: types.Message):
    driver = get_driver(message.from_user.id)
    if not driver:
        return
    
    history = get_paid_history(driver[0])
    lang = driver[7]
    
    if not history:
        await message.answer(TEXTS[lang]["no_history"])
        return
    
    text = TEXTS[lang]["history"]
    for h in history:
        text += f"#{h[0]} - {int(h[2])} so'm - {h[5][:16]}\n"
    await message.answer(text)

@dp.message(F.text.in_(["💳 Kartam", "💳 Моя карта"]))
async def show_card(message: types.Message):
    driver = get_driver(message.from_user.id)
    if not driver:
        return
    lang = driver[7]
    masked = driver[4][-4:] if len(driver[4]) >= 4 else "****"
    await message.answer(TEXTS[lang]["card"].format(card=masked))

@dp.message(F.text.in_(["☎️ Yordam", "☎️ Помощь"]))
async def show_help(message: types.Message):
    driver = get_driver(message.from_user.id)
    lang = driver[7] if driver else "uz"
    await message.answer(TEXTS[lang]["help"])

@dp.message(F.text.in_(["🌐 Tilni almashtirish", "🌐 Сменить язык"]))
async def change_lang(message: types.Message):
    driver = get_driver(message.from_user.id)
    if driver:
        new_lang = "ru" if driver[7] == "uz" else "uz"
        conn = sqlite3.connect("taxi.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE drivers SET language = ? WHERE telegram_id = ?", (new_lang, message.from_user.id))
        conn.commit()
        conn.close()
        await message.answer(TEXTS[new_lang]["lang_changed"])
        await message.answer(TEXTS[new_lang]["menu"], reply_markup=get_driver_keyboard(new_lang))

# ==================== ДЛЯ АДМИНА ====================
@dp.message(F.text == "📋 Yangi so'rovlar")
async def admin_new_requests(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    requests = get_new_withdraws()
    
    if not requests:
        await message.answer(TEXTS["uz"]["admin_no_requests"])
        return
    
    await message.answer(TEXTS["uz"]["admin_new"])
    for req in requests:
        text = TEXTS["uz"]["new_request"].format(
            id=req[0],
            name=req[6],
            phone=req[7],
            card=req[8][-4:],
            balance=0,
            amount=int(req[2])
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выплачено", callback_data=f"pay_{req[0]}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{req[0]}")]
        ])
        await message.answer(text, reply_markup=kb)

@dp.message(F.text == "📊 Statistika")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    users, total_paid, pending = get_stats()
    await message.answer(TEXTS["uz"]["admin_stats"].format(
        users=users,
        total_paid=int(total_paid),
        pending=pending
    ))

@dp.callback_query(F.data.startswith("pay_"))
async def pay_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    
    withdraw = get_withdraw(withdraw_id)
    if not withdraw:
        await callback.answer("❌ So'rov topilmadi!")
        return
    
    if withdraw[3] != "new":
        await callback.answer("❌ So'rov allaqachon ishlangan!")
        return
    
    # Обновляем баланс водителя
    balance = get_driver_balance(withdraw[1])
    new_balance = balance - withdraw[2]
    update_driver_balance(withdraw[1], new_balance)
    
    # Обновляем статус заявки
    update_withdraw_status(withdraw_id, "paid")
    
    await callback.message.edit_text(f"✅ Заявка #{withdraw_id} выплачена! Сумма: {int(withdraw[2])} so'm")
    await callback.answer("✅ Выплачено!")
    
    # Уведомляем водителя
    try:
        driver = get_driver(withdraw[5])
        if driver:
            lang = driver[7]
            await bot.send_message(
                withdraw[5],
                TEXTS[lang]["paid_notify"].format(id=withdraw_id, amount=int(withdraw[2]))
            )
    except:
        pass

@dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery):
    withdraw_id = int(callback.data.split("_")[1])
    
    withdraw = get_withdraw(withdraw_id)
    if not withdraw:
        await callback.answer("❌ So'rov topilmadi!")
        return
    
    if withdraw[3] != "new":
        await callback.answer("❌ So'rov allaqachon ishlangan!")
        return
    
    update_withdraw_status(withdraw_id, "rejected")
    
    await callback.message.edit_text(f"❌ Заявка #{withdraw_id} отклонена!")
    await callback.answer("❌ Отклонено!")
    
    # Уведомляем водителя
    try:
        driver = get_driver(withdraw[5])
        if driver:
            lang = driver[7]
            await bot.send_message(
                withdraw[5],
                f"❌ Sizning #{withdraw_id} so'rovingiz {int(withdraw[2])} so'm miqdorida rad etildi!"
            )
    except:
        pass

# ==================== ЗАПУСК ====================
async def main():
    print("Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

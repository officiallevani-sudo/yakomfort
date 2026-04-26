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

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ============ БАЗА ДАННЫХ ============
def init_db():
    conn = sqlite3.connect("taxi.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        card_number TEXT NOT NULL,
        balance REAL DEFAULT 350000,
        language TEXT DEFAULT 'uz',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        driver_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        status TEXT DEFAULT 'new',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

def get_driver(tg_id):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("SELECT * FROM drivers WHERE telegram_id = ?", (tg_id,))
    r = c.fetchone()
    conn.close()
    return r

def create_driver(tg_id, name, phone, card):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("INSERT INTO drivers (telegram_id, full_name, phone, card_number) VALUES (?,?,?,?)", (tg_id, name, phone, card))
    conn.commit()
    conn.close()

def create_withdraw(driver_id, amount):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("INSERT INTO withdraw_requests (driver_id, amount) VALUES (?,?)", (driver_id, amount))
    conn.commit()
    wid = c.lastrowid
    conn.close()
    return wid

def get_withdraw(wid):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("SELECT w.*, d.telegram_id, d.full_name, d.phone, d.card_number, d.balance FROM withdraw_requests w JOIN drivers d ON d.id = w.driver_id WHERE w.id = ?", (wid,))
    r = c.fetchone()
    conn.close()
    return r

def update_withdraw_status(wid, status):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("UPDATE withdraw_requests SET status = ? WHERE id = ?", (status, wid))
    conn.commit()
    conn.close()

def update_driver_balance(driver_id, new_balance):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("UPDATE drivers SET balance = ? WHERE id = ?", (new_balance, driver_id))
    conn.commit()
    conn.close()

def get_paid_history(driver_id):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("SELECT * FROM withdraw_requests WHERE driver_id = ? AND status = 'paid' ORDER BY created_at DESC LIMIT 10", (driver_id,))
    r = c.fetchall()
    conn.close()
    return r

def get_new_withdraws():
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("SELECT w.*, d.full_name, d.phone, d.card_number FROM withdraw_requests w JOIN drivers d ON d.id = w.driver_id WHERE w.status = 'new' ORDER BY w.created_at DESC")
    r = c.fetchall()
    conn.close()
    return r

def get_stats():
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM drivers")
    users = c.fetchone()[0]
    c.execute("SELECT SUM(amount) FROM withdraw_requests WHERE status = 'paid'")
    total = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'new'")
    pending = c.fetchone()[0]
    conn.close()
    return users, total, pending

# ============ ТЕКСТЫ ============
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
        "paid_notify": "✅ So'rovingiz #{id} bo'yicha {amount} so'm to'landi!",
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
        "admin_no_requests": "📭 Новых заявок нет",
        "admin_stats": "📊 СТАТИСТИКА\n\n👥 Пользователей: {users}\n💰 Всего выплат: {total_paid} сум\n📝 Ожидают: {pending} шт",
    }
}

def get_keyboard(lang):
    texts = TEXTS[lang]["menu"].split("\n")
    buttons = [[KeyboardButton(text=t)] for t in texts]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Yangi so'rovlar"), KeyboardButton(text="📊 Statistika")]], resize_keyboard=True)

# ============ FSM ============
class RegState(StatesGroup):
    name = State()
    phone = State()
    card = State()

class WithdrawState(StatesGroup):
    amount = State()

# ============ БОТ ============
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(F.text == "/start")
async def start(m: types.Message, state: FSMContext):
    await state.clear()
    
    # 1. Сначала проверяем, есть ли пользователь в базе водителей
    driver = get_driver(m.from_user.id)
    
    if driver:
        # Это зарегистрированный водитель
        lang = driver[7]
        await m.answer(TEXTS[lang]["menu"], reply_markup=get_keyboard(lang))
    
    elif m.from_user.id == ADMIN_ID:
        # Это админ (менеджер)
        await m.answer("👨‍💼 Добро пожаловать в панель менеджера!\n\nНовые заявки будут приходить автоматически.", reply_markup=get_admin_keyboard())
    
    else:
        # Новый пользователь - отправляем на регистрацию
        await m.answer("🇺🇿 Assalomu alaykum! / 🇷🇺 Добро пожаловать!\n\n" + TEXTS["uz"]["register_name"])
        await state.set_state(RegState.name)

@dp.message(RegState.name)
async def reg_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text)
    await state.set_state(RegState.phone)
    await m.answer(TEXTS["uz"]["register_phone"])

@dp.message(RegState.phone)
async def reg_phone(m: types.Message, state: FSMContext):
    await state.update_data(phone=m.text)
    await state.set_state(RegState.card)
    await m.answer(TEXTS["uz"]["register_card"])

@dp.message(RegState.card)
async def reg_card(m: types.Message, state: FSMContext):
    data = await state.get_data()
    create_driver(m.from_user.id, data['name'], data['phone'], m.text)
    await m.answer(TEXTS["uz"]["register_success"])
    await m.answer(TEXTS["uz"]["menu"], reply_markup=get_keyboard("uz"))
    await state.clear()

@dp.message(F.text.in_(["💰 Balansim", "💰 Мой баланс"]))
async def show_balance(m: types.Message):
    d = get_driver(m.from_user.id)
    if not d:
        await m.answer("❌ Iltimos, avval ro'yxatdan o'ting!\n❌ Пожалуйста, сначала зарегистрируйтесь!\n\n/start")
        return
    balance = d[5]
    available = max(0, balance - 10000)
    await m.answer(TEXTS[d[7]]["balance"].format(balance=int(balance), available=int(available)))

@dp.message(F.text.in_(["🚖 Buyurtmalarim", "🚖 Мои заказы"]))
async def show_orders(m: types.Message):
    d = get_driver(m.from_user.id)
    if not d:
        await m.answer("❌ Iltimos, avval ro'yxatdan o'ting!\n/start")
        return
    await m.answer(TEXTS[d[7]]["orders"])

@dp.message(F.text.in_(["💸 Pul yechish", "💸 Вывести деньги"]))
async def start_withdraw(m: types.Message, state: FSMContext):
    d = get_driver(m.from_user.id)
    if not d:
        await m.answer("❌ Iltimos, avval ro'yxatdan o'ting!\n/start")
        return
    balance = d[5]
    available = max(0, balance - 10000)
    if available <= 0:
        await m.answer(TEXTS[d[7]]["insufficient"].format(available=0))
        return
    await state.update_data(driver_id=d[0])
    await state.set_state(WithdrawState.amount)
    await m.answer(TEXTS[d[7]]["enter_amount"])

@dp.message(WithdrawState.amount)
async def process_withdraw(m: types.Message, state: FSMContext):
    try:
        amount = float(m.text)
        if amount <= 0: raise ValueError
    except:
        await m.answer("❌ Faqat son kiriting!")
        return
    data = await state.get_data()
    driver_id = data['driver_id']
    d = get_driver(driver_id)
    if not d: return
    available = max(0, d[5] - 10000)
    if amount > available:
        await m.answer(TEXTS[d[7]]["insufficient"].format(available=int(available)))
        await state.clear()
        return
    wid = create_withdraw(driver_id, amount)
    await m.answer(TEXTS[d[7]]["success"].format(id=wid))
    await state.clear()
    if ADMIN_ID:
        text = TEXTS[d[7]]["new_request"].format(id=wid, name=d[2], phone=d[3], card=d[4][-4:], balance=int(d[5]), amount=int(amount))
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Выплачено", callback_data=f"pay_{wid}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{wid}")
        ]])
        await bot.send_message(ADMIN_ID, text, reply_markup=kb)

@dp.message(F.text.in_(["📜 To'lovlar tarixi", "📜 История выплат"]))
async def show_history(m: types.Message):
    d = get_driver(m.from_user.id)
    if not d:
        await m.answer("❌ Ro'yxatdan o'ting! /start")
        return
    hist = get_paid_history(d[0])
    if not hist:
        await m.answer(TEXTS[d[7]]["no_history"])
        return
    text = TEXTS[d[7]]["history"]
    for h in hist:
        text += f"#{h[0]} - {int(h[2])} so'm - {h[5][:16]}\n"
    await m.answer(text)

@dp.message(F.text.in_(["💳 Kartam", "💳 Моя карта"]))
async def show_card(m: types.Message):
    d = get_driver(m.from_user.id)
    if not d:
        await m.answer("❌ Ro'yxatdan o'ting! /start")
        return
    await m.answer(TEXTS[d[7]]["card"].format(card=d[4][-4:]))

@dp.message(F.text.in_(["☎️ Yordam", "☎️ Помощь"]))
async def show_help(m: types.Message):
    d = get_driver(m.from_user.id)
    lang = d[7] if d else "uz"
    await m.answer(TEXTS[lang]["help"])

@dp.message(F.text.in_(["🌐 Tilni almashtirish", "🌐 Сменить язык"]))
async def change_lang(m: types.Message):
    d = get_driver(m.from_user.id)
    if d:
        new = "ru" if d[7] == "uz" else "uz"
        conn = sqlite3.connect("taxi.db")
        c = conn.cursor()
        c.execute("UPDATE drivers SET language = ? WHERE telegram_id = ?", (new, m.from_user.id))
        conn.commit()
        conn.close()
        await m.answer(TEXTS[new]["lang_changed"])
        await m.answer(TEXTS[new]["menu"], reply_markup=get_keyboard(new))

# ============ АДМИН КОМАНДЫ ============
@dp.message(F.text == "📋 Yangi so'rovlar")
async def admin_requests(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    reqs = get_new_withdraws()
    if not reqs:
        await m.answer(TEXTS["uz"]["admin_no_requests"])
        return
    for r in reqs:
        text = TEXTS["uz"]["new_request"].format(id=r[0], name=r[6], phone=r[7], card=r[8][-4:], balance=0, amount=int(r[2]))
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Выплачено", callback_data=f"pay_{r[0]}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{r[0]}")
        ]])
        await m.answer(text, reply_markup=kb)

@dp.message(F.text == "📊 Statistika")
async def admin_stats(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    users, total, pending = get_stats()
    await m.answer(TEXTS["uz"]["admin_stats"].format(users=users, total_paid=int(total), pending=pending))

@dp.callback_query(F.data.startswith("pay_"))
async def pay(c: types.CallbackQuery):
    wid = int(c.data.split("_")[1])
    w = get_withdraw(wid)
    if not w or w[3] != "new":
        await c.answer("❌ So'rov topilmadi yoki ishlangan!")
        return
    new_balance = w[11] - w[2]
    update_driver_balance(w[1], new_balance)
    update_withdraw_status(wid, "paid")
    await c.message.edit_text(f"✅ Заявка #{wid} выплачена! Сумма: {int(w[2])} so'm")
    await c.answer("✅ Выплачено!")
    try:
        driver_info = get_driver(w[5])
        if driver_info:
            lang = driver_info[7]
            await bot.send_message(w[5], TEXTS[lang]["paid_notify"].format(id=wid, amount=int(w[2])))
    except: pass

@dp.callback_query(F.data.startswith("reject_"))
async def reject(c: types.CallbackQuery):
    wid = int(c.data.split("_")[1])
    w = get_withdraw(wid)
    if not w or w[3] != "new":
        await c.answer("❌ So'rov topilmadi yoki ishlangan!")
        return
    update_withdraw_status(wid, "rejected")
    await c.message.edit_text(f"❌ Заявка #{wid} отклонена!")
    await c.answer("❌ Отклонено!")
    try:
        await bot.send_message(w[5], f"❌ Sizning #{wid} so'rovingiz {int(w[2])} so'm miqdorida rad etildi!")
    except: pass

async def main():
    print("Bot ishlayapti...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

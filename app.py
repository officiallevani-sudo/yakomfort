import os
import sqlite3
import asyncio
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

# ============ DATABASE ============
def init_db():
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS drivers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        car_number TEXT NOT NULL,
        phone TEXT NOT NULL,
        card_number TEXT NOT NULL,
        balance REAL DEFAULT 0,
        trips_today INTEGER DEFAULT 0,
        trips_week INTEGER DEFAULT 0,
        earnings_today REAL DEFAULT 0,
        earnings_week REAL DEFAULT 0,
        language TEXT DEFAULT 'uz',
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        driver_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        status TEXT DEFAULT 'new',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        driver_id INTEGER NOT NULL,
        report_type TEXT,
        message TEXT,
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

def get_driver_by_id(driver_id):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,))
    r = c.fetchone()
    conn.close()
    return r

def create_driver(tg_id, name, car_number, phone, card, language='uz'):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute('''INSERT INTO drivers 
        (telegram_id, full_name, car_number, phone, card_number, balance, trips_today, trips_week, earnings_today, earnings_week, language, status)
        VALUES (?,?,?,?,?, 0, 0, 0, 0, 0, ?, 'active')''', 
        (tg_id, name, car_number, phone, card, language))
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
    c.execute('''SELECT w.*, d.telegram_id, d.full_name, d.phone, d.card_number, d.balance, d.car_number
                FROM withdraw_requests w JOIN drivers d ON d.id = w.driver_id WHERE w.id = ?''', (wid,))
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
    c.execute('''SELECT w.*, d.full_name, d.phone, d.card_number, d.car_number, d.balance 
                FROM withdraw_requests w JOIN drivers d ON d.id = w.driver_id 
                WHERE w.status = 'new' ORDER BY w.created_at DESC''')
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

def update_trips(driver_id, today_count, today_earn, week_count, week_earn):
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute('''UPDATE drivers SET 
        trips_today = ?, earnings_today = ?,
        trips_week = ?, earnings_week = ?
        WHERE id = ?''', (today_count, today_earn, week_count, week_earn, driver_id))
    conn.commit()
    conn.close()

# ============ TEXTS ============
TEXTS = {
    "uz": {
        "welcome": "🚖 Assalomu Alaykum! Yakomfort taksoparkiga xush kelibsiz!\n\n🤝 Biz bilan hamkorlik qiling va daromadingizni oshiring!\n💰 Taksi komissiyasi atigi 1%\n\nBotdan foydalanish uchun /start bosing",
        "reg_start": "📝 Iltimos, ro'yxatdan o'tish uchun quyidagi ma'lumotlarni kiriting.\n\nIsm familiyangizni kiriting:",
        "after_reg": "✅ Hurmatli haydovchi, kuningiz unumli va barokatli bo'lsin!\n\n✨ Sizdan yana shuni iltimos qilamiz: mijozlar bilan har doim xushmuomala bo'ling!\n🤝 Yaxshi muomala ikki insonning kayfiyati a'lo darajada bo'lishi kafolatidir!\n\n🚖 Yo'lingiz ochiq bo'lsin!",
        "register_name": "📝 Ism familiyangizni kiriting:",
        "register_car": "🚗 Avtotransport raqamingizni kiriting (masalan: 01A777AA):",
        "register_phone": "📞 Telefon raqamingizni kiriting (+998xxxxxxxxx):",
        "register_card": "💳 Pul o'tkazish uchun karta raqamingizni kiriting (8600xxxxxx):",
        "register_success": "🎉 Tabriklaymiz! Siz muvaffaqiyatli ro'yxatdan o'tdingiz!",
        "register_exists": "❌ Siz allaqachon ro'yxatdan o'tgansiz!",
        "menu": "📊 Mijozlarim\n💰 Pul yechish\n👨‍💼 Menejer bilan bog'lanish\n🆘 SOS / DTP\n📜 To'lovlar tarixi\n💳 Kartam\n🌐 Til",
        "my_trips": "🚖 Mijozlarim:\n\n✅ Bugun: {today_count} ta mijoz / {today_earn} so'm\n📊 Hafta: {week_count} ta mijoz / {week_earn} so'm",
        "balance": "💰 Balans: {balance} so'm\n💸 Yechish mumkin: {available} so'm",
        "enter_amount": "💰 Qancha pul yechmoqchisiz?\nSummani kiriting:",
        "insufficient": "❌ Yetarli emas! Yechish mumkin: {available} so'm",
        "success": "✅ So'rovingiz #{id} menedjerga yuborildi!\nTez orada ko'rib chiqiladi.",
        "card": "💳 Kartangiz: ****{card}",
        "no_history": "📭 To'lovlar tarixi bo'sh",
        "history": "📜 TO'LOVLAR TARIXI:\n",
        "contact": "📞 Menejer bilan bog'lanish:\n\n☎️ +998771202255\n\n✍️ Xabaringizni yozing:",
        "contact_sent": "✅ Xabaringiz menedjerga yuborildi!\nTez orada javob olasiz.",
        "sos_sent": "🆘 SOS signal yuborildi! Menejer tez orada siz bilan bog'lanadi.",
        "sos_admin": "🆘 SOS SIGNAL!\n\n👤 Haydovchi: {name}\n🚗 Avto: {car}\n📞 Tel: {phone}\n🕐 Vaqt: {time}",
        "contact_admin": "📞 MURIJAT!\n\n👤 Haydovchi: {name}\n🚗 Avto: {car}\n📞 Tel: {phone}\n💬 Xabar: {msg}\n🕐 Vaqt: {time}",
        "admin_new": "📋 YANGI SO'ROVLAR:\n\n",
        "admin_no_requests": "📭 Yangi so'rovlar yo'q",
        "admin_stats": "📊 STATISTIKA\n\n👥 Haydovchilar: {users}\n💰 Jami to'lovlar: {total_paid} so'm\n📝 Kutilayotgan: {pending} ta",
        "new_withdraw": "🆕 YANGI PUL YECHISH SO'ROVI #{id}\n\n👤 {name}\n🚗 {car}\n📞 {phone}\n💳 ****{card}\n💰 Balans: {balance}\n💵 Summa: {amount} so'm",
        "paid_notify": "✅ Sizning #{id} so'rovingiz bo'yicha {amount} so'm to'landi!\n💰 Yangi balans: {new_balance} so'm",
        "reject_notify": "❌ Sizning #{id} so'rovingiz {amount} so'm miqdorida rad etildi!",
        "lang_changed": "✅ Til o'zgartirildi!",
        "select_lang": "🇺🇿 Iltimos, tilni tanlang:\n🇷🇺 Пожалуйста, выберите язык:",
        "button_click_admin": "🔔 HAYDOVCHI TUGMA BOSDI!\n\n👤 Haydovchi: {name}\n🚗 Avto: {car}\n📞 Tel: {phone}\n🔘 Tugma: {button}\n🕐 Vaqt: {time}",
        "new_driver_admin": "🆕 **YANGI HAYDOVCHI RO'YXATDAN O'TDI!**\n\n👤 **Ismi:** {name}\n🚗 **Avtomobil:** {car}\n📞 **Telefon:** {phone}\n💳 **Karta:** ****{card}\n🆔 **Telegram ID:** `{tg_id}`\n👤 **Username:** @{username}\n⏰ **Vaqt:** {time}\n\n✅ Haydovchi muvaffaqiyatli ro'yxatdan o'tdi!"
    },
    "ru": {
        "welcome": "🚖 Ассаламу Алейкум! Добро пожаловать в таксопарк Yakomfort!\n\n🤝 Сотрудничайте с нами и увеличивайте свой доход!\n💰 Комиссия таксопарка всего 1%\n\nДля использования бота нажмите /start",
        "reg_start": "📝 Для регистрации введите следующие данные.\n\nВведите ваше имя и фамилию:",
        "after_reg": "✅ Уважаемый водитель, пусть ваш рабочий день будет плодотворным и благословенным!\n\n✨ Еще одна просьба: всегда будьте вежливы с клиентами!\n🤝 Хорошее отношение - залог отличного настроения двух людей!\n\n🚖 Счастливого пути!",
        "register_name": "📝 Введите ваше имя и фамилию:",
        "register_car": "🚗 Введите номер автомобиля (например: 01A777AA):",
        "register_phone": "📞 Введите номер телефона (+998xxxxxxxxx):",
        "register_card": "💳 Введите номер карты для перевода (8600xxxxxx):",
        "register_success": "🎉 Поздравляем! Вы успешно зарегистрированы!",
        "register_exists": "❌ Вы уже зарегистрированы!",
        "menu": "📊 Мои поездки\n💰 Вывести деньги\n👨‍💼 Связаться с менеджером\n🆘 SOS / ДТП\n📜 История выплат\n💳 Моя карта\n🌐 Язык",
        "my_trips": "🚖 Мои поездки:\n\n✅ Сегодня: {today_count} поездок / {today_earn} сум\n📊 Неделя: {week_count} поездок / {week_earn} сум",
        "balance": "💰 Баланс: {balance} сум\n💸 Доступно: {available} сум",
        "enter_amount": "💰 Введите сумму для вывода:",
        "insufficient": "❌ Недостаточно! Доступно: {available} сум",
        "success": "✅ Заявка #{id} отправлена менеджеру!\nСкоро будет рассмотрена.",
        "card": "💳 Ваша карта: ****{card}",
        "no_history": "📭 История выплат пуста",
        "history": "📜 ИСТОРИЯ ВЫПЛАТ:\n",
        "contact": "📞 Связаться с менеджером:\n\n☎️ +998771202255\n\n✍️ Напишите ваше сообщение:",
        "contact_sent": "✅ Ваше сообщение отправлено менеджеру!\nСкоро получите ответ.",
        "sos_sent": "🆘 SOS сигнал отправлен! Менеджер скоро свяжется с вами.",
        "sos_admin": "🆘 SOS СИГНАЛ!\n\n👤 Водитель: {name}\n🚗 Авто: {car}\n📞 Тел: {phone}\n🕐 Время: {time}",
        "contact_admin": "📞 ОБРАЩЕНИЕ!\n\n👤 Водитель: {name}\n🚗 Авто: {car}\n📞 Тел: {phone}\n💬 Сообщение: {msg}\n🕐 Время: {time}",
        "admin_new": "📋 НОВЫЕ ЗАЯВКИ:\n\n",
        "admin_no_requests": "📭 Новых заявок нет",
        "admin_stats": "📊 СТАТИСТИКА\n\n👥 Водителей: {users}\n💰 Всего выплат: {total_paid} сум\n📝 Ожидают: {pending} шт",
        "new_withdraw": "🆕 НОВАЯ ЗАЯВКА НА ВЫВОД #{id}\n\n👤 {name}\n🚗 {car}\n📞 {phone}\n💳 ****{card}\n💰 Баланс: {balance}\n💵 Сумма: {amount} сум",
        "paid_notify": "✅ По вашей заявке #{id} выплачено {amount} сум!\n💰 Новый баланс: {new_balance} сум",
        "reject_notify": "❌ Ваша заявка #{id} на сумму {amount} сум отклонена!",
        "lang_changed": "✅ Язык изменен!",
        "select_lang": "🇷🇺 Пожалуйста, выберите язык:\n🇺🇿 Iltimos, tilni tanlang:",
        "button_click_admin": "🔔 ВОДИТЕЛЬ НАЖАЛ КНОПКУ!\n\n👤 Водитель: {name}\n🚗 Авто: {car}\n📞 Тел: {phone}\n🔘 Кнопка: {button}\n🕐 Время: {time}",
        "new_driver_admin": "🆕 **НОВЫЙ ВОДИТЕЛЬ ЗАРЕГИСТРИРОВАЛСЯ!**\n\n👤 **Имя:** {name}\n🚗 **Авто:** {car}\n📞 **Тел:** {phone}\n💳 **Карта:** ****{card}\n🆔 **Telegram ID:** `{tg_id}`\n👤 **Username:** @{username}\n⏰ **Время:** {time}\n\n✅ Водитель успешно зарегистрирован!"
    }
}

# ============ KEYBOARDS ============
def language_keyboard():
    buttons = [
        [KeyboardButton(text="🇺🇿 O'zbek tili")],
        [KeyboardButton(text="🇷🇺 Русский язык")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def get_main_keyboard(lang):
    texts = TEXTS[lang]["menu"].split("\n")
    buttons = [[KeyboardButton(text=t)] for t in texts]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Yangi so'rovlar"), KeyboardButton(text="📊 Statistika")],
            [KeyboardButton(text="📝 Trip statistikasini yangilash")]
        ],
        resize_keyboard=True
    )

# ============ FSM ============
class LanguageState(StatesGroup):
    choosing = State()

class RegState(StatesGroup):
    name = State()
    car = State()
    phone = State()
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

# ============ BOT ============
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ============ YORDAMCHI FUNKSIYA: MENEDJERGA XABAR YUBORISH ============
async def notify_admin(text, parse_mode=None):
    if ADMIN_ID and ADMIN_ID != 0:
        try:
            await bot.send_message(ADMIN_ID, text, parse_mode=parse_mode)
        except Exception as e:
            print(f"Admin xabar yuborishda xatolik: {e}")

# ============ START ============
@dp.message(F.text == "/start")
async def start_cmd(m: types.Message, state: FSMContext):
    await state.clear()
    driver = get_driver(m.from_user.id)
    
    if driver:
        lang = driver[11]
        await m.answer(TEXTS[lang]["menu"], reply_markup=get_main_keyboard(lang))
    elif m.from_user.id == ADMIN_ID:
        await m.answer("👨‍💼 Admin panel", reply_markup=get_admin_keyboard())
    else:
        await state.set_state(LanguageState.choosing)
        await m.answer(TEXTS["uz"]["select_lang"], reply_markup=language_keyboard())

# ============ LANGUAGE SELECTION ============
@dp.message(LanguageState.choosing, F.text.in_(["🇺🇿 O'zbek tili", "🇷🇺 Русский язык"]))
async def choose_lang(m: types.Message, state: FSMContext):
    if m.text == "🇺🇿 O'zbek tili":
        lang = "uz"
    else:
        lang = "ru"
    
    await state.update_data(lang=lang)
    await state.set_state(RegState.name)
    await m.answer(TEXTS[lang]["register_name"], reply_markup=types.ReplyKeyboardRemove())

@dp.message(LanguageState.choosing)
async def invalid_lang(m: types.Message, state: FSMContext):
    await m.answer("🇺🇿 Iltimos, tilni tanlang!\n🇷🇺 Пожалуйста, выберите язык!", reply_markup=language_keyboard())

# ============ REGISTRATION ============
@dp.message(RegState.name)
async def reg_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text)
    await state.set_state(RegState.car)
    data = await state.get_data()
    await m.answer(TEXTS[data['lang']]["register_car"])

@dp.message(RegState.car)
async def reg_car(m: types.Message, state: FSMContext):
    await state.update_data(car=m.text.upper())
    await state.set_state(RegState.phone)
    data = await state.get_data()
    await m.answer(TEXTS[data['lang']]["register_phone"])

@dp.message(RegState.phone)
async def reg_phone(m: types.Message, state: FSMContext):
    await state.update_data(phone=m.text)
    await state.set_state(RegState.card)
    data = await state.get_data()
    await m.answer(TEXTS[data['lang']]["register_card"])

@dp.message(RegState.card)
async def reg_card(m: types.Message, state: FSMContext):
    data = await state.get_data()
    existing = get_driver(m.from_user.id)
    
    if existing:
        await m.answer(TEXTS[data['lang']]["register_exists"])
        await state.clear()
        return
    
    # Yangi driver yaratish
    create_driver(m.from_user.id, data['name'], data['car'], data['phone'], m.text, data['lang'])
    
    # ============ MENEDJERGA YANGI HAYDOVCHI XABARI ============
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    username = m.from_user.username if m.from_user.username else "Yo'q"
    card_last4 = m.text[-4:] if len(m.text) >= 4 else "****"
    
    admin_text = TEXTS[data['lang']]["new_driver_admin"].format(
        name=data['name'],
        car=data['car'],
        phone=data['phone'],
        card=card_last4,
        tg_id=m.from_user.id,
        username=username,
        time=now
    )
    await notify_admin(admin_text, parse_mode="Markdown")
    # ============================================================
    
    await m.answer(TEXTS[data['lang']]["register_success"])
    await m.answer(TEXTS[data['lang']]["after_reg"])
    await m.answer(TEXTS[data['lang']]["menu"], reply_markup=get_main_keyboard(data['lang']))
    await state.clear()

# ============ BARCHA TUGMALAR UCHUN UMUMIY ISHLOVCHI (MENEDJERGA XABAR BORADI) ============
@dp.message(F.text.in_([
    "📊 Mijozlarim", "📊 Мои поездки",
    "💰 Pul yechish", "💰 Вывести деньги",
    "👨‍💼 Menejer bilan bog'lanish", "👨‍💼 Связаться с менеджером",
    "🆘 SOS / DTP", "🆘 SOS / ДТП",
    "📜 To'lovlar tarixi", "📜 История выплат",
    "💳 Kartam", "💳 Моя карта",
    "🌐 Til", "🌐 Язык"
]))
async def all_buttons_handler(m: types.Message, state: FSMContext):
    driver = get_driver(m.from_user.id)
    if not driver:
        await m.answer("❌ Iltimos, avval ro'yxatdan o'ting!\n/start")
        return
    
    lang = driver[11]
    button_text = m.text
    
    # ============ MENEDJERGA TUGMA BOSILGANI HAQIDA XABAR ============
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    admin_text = TEXTS[lang]["button_click_admin"].format(
        name=driver[2],
        car=driver[3],
        phone=driver[4],
        button=button_text,
        time=now
    )
    await notify_admin(admin_text)
    # ================================================================
    
    # Tugmalarga qarab amallar
    if button_text in ["📊 Mijozlarim", "📊 Мои поездки"]:
        await m.answer(TEXTS[lang]["my_trips"].format(
            today_count=int(driver[7] or 0),
            today_earn=int(driver[9] or 0),
            week_count=int(driver[8] or 0),
            week_earn=int(driver[10] or 0)
        ))
    
    elif button_text in ["💰 Pul yechish", "💰 Вывести деньги"]:
        balance = driver[6]
        available = balance
        
        if available <= 0:
            await m.answer(TEXTS[lang]["insufficient"].format(available=0))
            return
        
        await state.update_data(driver_id=driver[0])
        await state.set_state(WithdrawState.amount)
        await m.answer(TEXTS[lang]["enter_amount"])
    
    elif button_text in ["👨‍💼 Menejer bilan bog'lanish", "👨‍💼 Связаться с менеджером"]:
        await state.set_state(ContactState.message)
        await m.answer(TEXTS[lang]["contact"])
    
    elif button_text in ["🆘 SOS / DTP", "🆘 SOS / ДТП"]:
        # SOS uchun alohida xabar
        sos_admin_text = TEXTS[lang]["sos_admin"].format(
            name=driver[2],
            car=driver[3],
            phone=driver[4],
            time=datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        )
        await notify_admin(sos_admin_text)
        await m.answer(TEXTS[lang]["sos_sent"])
    
    elif button_text in ["📜 To'lovlar tarixi", "📜 История выплат"]:
        hist = get_paid_history(driver[0])
        if not hist:
            await m.answer(TEXTS[lang]["no_history"])
            return
        text = TEXTS[lang]["history"]
        for h in hist:
            text += f"#{h[0]} - {int(h[2])} so'm - {h[5][:16]}\n"
        await m.answer(text)
    
    elif button_text in ["💳 Kartam", "💳 Моя карта"]:
        card = driver[5][-4:] if len(driver[5]) >= 4 else "****"
        await m.answer(TEXTS[lang]["card"].format(card=card))
    
    elif button_text in ["🌐 Til", "🌐 Язык"]:
        new_lang = "ru" if driver[11] == "uz" else "uz"
        conn = sqlite3.connect("taxi.db")
        c = conn.cursor()
        c.execute("UPDATE drivers SET language = ? WHERE telegram_id = ?", (new_lang, m.from_user.id))
        conn.commit()
        conn.close()
        await m.answer(TEXTS[new_lang]["lang_changed"])
        await m.answer(TEXTS[new_lang]["menu"], reply_markup=get_main_keyboard(new_lang))

# ============ PUL YECHISH SUMKA KIRITISH ============
@dp.message(WithdrawState.amount)
async def process_withdraw(m: types.Message, state: FSMContext):
    try:
        amount = float(m.text)
        if amount <= 0: raise ValueError
    except:
        await m.answer("❌ Iltimos, to'g'ri summa kiriting!")
        return
    
    data = await state.get_data()
    driver_id = data['driver_id']
    driver = get_driver_by_id(driver_id)
    if not driver: return
    
    lang = driver[11]
    balance = driver[6]
    
    if amount > balance:
        await m.answer(TEXTS[lang]["insufficient"].format(available=int(balance)))
        await state.clear()
        return
    
    wid = create_withdraw(driver_id, amount)
    await m.answer(TEXTS[lang]["success"].format(id=wid))
    await state.clear()
    
    if ADMIN_ID:
        text = TEXTS[lang]["new_withdraw"].format(
            id=wid, 
            name=driver[2], 
            car=driver[3], 
            phone=driver[4], 
            card=driver[5][-4:], 
            balance=int(balance), 
            amount=int(amount)
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ To'landi", callback_data=f"pay_{wid}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{wid}")
        ]])
        await bot.send_message(ADMIN_ID, text, reply_markup=kb)

# ============ MENEDJERGA XABAR YOZISH ============
@dp.message(ContactState.message)
async def send_manager_msg(m: types.Message, state: FSMContext):
    driver = get_driver(m.from_user.id)
    if not driver:
        await state.clear()
        return
    
    lang = driver[11]
    msg = m.text
    
    if ADMIN_ID:
        text = TEXTS[lang]["contact_admin"].format(
            name=driver[2],
            car=driver[3],
            phone=driver[4],
            msg=msg,
            time=datetime.now().strftime("%H:%M:%S")
        )
        await bot.send_message(ADMIN_ID, text)
    
    await m.answer(TEXTS[lang]["contact_sent"])
    await state.clear()

# ============ ADMIN COMMANDS ============
@dp.message(F.text == "📋 Yangi so'rovlar")
async def admin_requests(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    
    reqs = get_new_withdraws()
    if not reqs:
        await m.answer(TEXTS["uz"]["admin_no_requests"])
        return
    
    await m.answer(TEXTS["uz"]["admin_new"])
    for r in reqs:
        text = TEXTS["uz"]["new_withdraw"].format(
            id=r[0], name=r[6], car=r[9], phone=r[7], card=r[8][-4:], balance=int(r[11]), amount=int(r[2])
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ To'landi", callback_data=f"pay_{r[0]}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{r[0]}")
        ]])
        await m.answer(text, reply_markup=kb)

@dp.message(F.text == "📊 Statistika")
async def admin_stats(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    
    users, total, pending = get_stats()
    await m.answer(TEXTS["uz"]["admin_stats"].format(users=users, total_paid=int(total), pending=pending))

@dp.message(F.text == "📝 Trip statistikasini yangilash")
async def admin_update_trip_start(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.set_state(AdminTripState.driver_id)
    await m.answer("📝 Haydovchi ID sini kiriting:\n\n(ID ni bilish uchun /list_drivers buyrug'ini ishlating)")

@dp.message(AdminTripState.driver_id)
async def admin_update_trip_driver(m: types.Message, state: FSMContext):
    try:
        driver_id = int(m.text)
        driver = get_driver_by_id(driver_id)
        if not driver:
            await m.answer("❌ Bunday ID li haydovchi topilmadi!")
            await state.clear()
            return
        await state.update_data(driver_id=driver_id)
        await state.set_state(AdminTripState.today_count)
        await m.answer(f"👤 Haydovchi: {driver[2]}\n\nBugungi mijozlar sonini kiriting:")
    except:
        await m.answer("❌ Iltimos, to'g'ri ID kiriting!")

@dp.message(AdminTripState.today_count)
async def admin_update_trip_today_count(m: types.Message, state: FSMContext):
    try:
        today_count = int(m.text)
        await state.update_data(today_count=today_count)
        await state.set_state(AdminTripState.today_earn)
        await m.answer("💰 Bugungi daromadni kiriting (so'm):")
    except:
        await m.answer("❌ Iltimos, son kiriting!")

@dp.message(AdminTripState.today_earn)
async def admin_update_trip_today_earn(m: types.Message, state: FSMContext):
    try:
        today_earn = float(m.text)
        await state.update_data(today_earn=today_earn)
        await state.set_state(AdminTripState.week_count)
        await m.answer("📊 Haftalik mijozlar sonini kiriting:")
    except:
        await m.answer("❌ Iltimos, son kiriting!")

@dp.message(AdminTripState.week_count)
async def admin_update_trip_week_count(m: types.Message, state: FSMContext):
    try:
        week_count = int(m.text)
        await state.update_data(week_count=week_count)
        await state.set_state(AdminTripState.week_earn)
        await m.answer("💰 Haftalik daromadni kiriting (so'm):")
    except:
        await m.answer("❌ Iltimos, son kiriting!")

@dp.message(AdminTripState.week_earn)
async def admin_update_trip_finish(m: types.Message, state: FSMContext):
    try:
        week_earn = float(m.text)
        data = await state.get_data()
        
        week_count = data.get('week_count', 0)
        
        update_trips(data['driver_id'], data['today_count'], data['today_earn'], week_count, week_earn)
        
        driver = get_driver_by_id(data['driver_id'])
        await m.answer(f"✅ Yangilandi!\n\n👤 {driver[2]}\n📊 Bugun: {data['today_count']} ta / {int(data['today_earn'])} so'm\n📊 Hafta: {week_count} ta / {int(week_earn)} so'm")
        await state.clear()
    except Exception as e:
        await m.answer(f"❌ Xatolik: {e}")
        await state.clear()

# ============ LIST DRIVERS ============
@dp.message(F.text == "/list_drivers")
async def list_drivers(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    
    conn = sqlite3.connect("taxi.db")
    c = conn.cursor()
    c.execute("SELECT id, full_name, phone, balance, car_number FROM drivers")
    drivers = c.fetchall()
    conn.close()
    
    if not drivers:
        await m.answer("📭 Haydovchilar ro'yxati bo'sh")
        return
    
    text = "📋 HAYDOVCHILAR RO'YXATI:\n\n"
    for d in drivers:
        text += f"ID: {d[0]} | {d[1]}\n🚗 {d[4]} | 📞 {d[2]} | 💰 {int(d[3])} so'm\n\n"
    await m.answer(text)

# ============ CALLBACKS ============
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
    
    await c.message.edit_text(f"✅ #{wid} to'landi! Summa: {int(w[2])} so'm")
    await c.answer("✅ To'landi!")
    
    try:
        driver_info = get_driver(w[5])
        if driver_info:
            lang = driver_info[11]
            await bot.send_message(w[5], TEXTS[lang]["paid_notify"].format(
                id=wid, 
                amount=int(w[2]),
                new_balance=int(new_balance)
            ))
    except: pass

@dp.callback_query(F.data.startswith("reject_"))
async def reject(c: types.CallbackQuery):
    wid = int(c.data.split("_")[1])
    w = get_withdraw(wid)
    
    if not w or w[3] != "new":
        await c.answer("❌ So'rov topilmadi yoki ishlangan!")
        return
    
    update_withdraw_status(wid, "rejected")
    await c.message.edit_text(f"❌ #{wid} rad etildi!")
    await c.answer("❌ Rad etildi!")
    
    try:
        driver_info = get_driver(w[5])
        if driver_info:
            lang = driver_info[11]
            await bot.send_message(w[5], TEXTS[lang]["reject_notify"].format(id=wid, amount=int(w[2])))
    except: pass

# ============ MAIN ============
async def main():
    print("🚖 Yakomfort Taxi Bot ishga tushdi...")
    print(f"🤖 Bot token: {BOT_TOKEN[:10]}...")
    print(f"👨‍💼 Admin ID: {ADMIN_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

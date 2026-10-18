import asyncio
import logging
import aiosqlite
import requests
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "ТВОЇ_ТОКЕН_БОТА_ВІД_BOTFATHER")
MONO_API_TOKEN = os.getenv("MONO_API_TOKEN", "ТВОЇ_ТОКЕН_МОНОБАНКУ")
MONO_JAR_ID = os.getenv("MONO_JAR_ID", "ІДЕНТИФІКАТОР_БАНКИ") 

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "database.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                telegram_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending'
            )
        """)
        await db.commit()

# Додати боржника: /add @username 1200
@dp.message(Command("add"))
async def add_user(message: Message):
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Формат: `/add @username сума`", parse_mode="Markdown")
        return
    
    username = args[1]
    try:
        amount = float(args[2])
    except ValueError:
        await message.answer("Сума має бути числом!")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO users (username, amount, status) VALUES (?, ?, 'pending')",
            (username, amount)
        )
        await db.commit()
    
    await message.answer(f"✅ Додано {username} з сумою {amount} грн (статус: очікується).")

# Зв'язати свій Telegram ID: /start
@dp.message(Command("start"))
async def start_cmd(message: Message):
    username = f"@{message.from_user.username}" if message.from_user.username else ""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET telegram_id = ? WHERE username = ?",
            (user_id, username)
        )
        await db.commit()
    
    await message.answer("Привіт! Твій Telegram ID зв'язано з базою даних бота.")

# Перевірити статус усіх боржників і звірити з Monobank API: /check
@dp.message(Command("check"))
async def check_monobank(message: Message):
    url = f"https://api.monobank.ua/personal/statement/0/{MONO_JAR_ID}"
    headers = {"X-Token": MONO_API_TOKEN}
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        await message.answer(f"Помилка запиту до Monobank API: {response.text}")
        return
    
    transactions = response.json()
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Отримуємо список усіх користувачів зі статусом pending
        async with db.execute("SELECT id, username, amount, status FROM users") as cursor:
            users = await cursor.fetchall()
            
        report = "📊 **Звіт по спільних зборах:**\n\n"
        
        for user_id, username, target_amount, current_status in users:
            is_paid = False
            
            # Якщо вже оплачено раніше, пропускаємо перевірку транзакцій
            if current_status == 'paid':
                report += f"✅ {username} — Оплачено ({target_amount} грн)\n"
                continue
            
            # Шукаємо у транзакціях збіги за сумою та наявністю юзернейму в коментарі
            for tx in transactions:
                sum_uah = tx.get('amount', 0) / 100
                comment = tx.get('comment', '').lower()
                
                # Перевіряємо, чи збігається сума і чи є згадка юзернейму (наприклад, '@ivan') у коментарі
                clean_username = username.replace("@", "").lower()
                if sum_uah >= target_amount and clean_username in comment:
                    is_paid = True
                    break
            
            if is_paid:
                # Оновлюємо статус в таблиці на 'paid'
                await db.execute("UPDATE users SET status = 'paid' WHERE id = ?", (user_id,))
                await db.commit()
                report += f"✅ {username} — Щойно зараховано! Статус змінено на **Оплачено**.\n"
            else:
                report += f"❌ {username} — Не оплачено (очікується {target_amount} грн)\n"
                
    await message.answer(report, parse_mode="Markdown")

# Нагадування людині в особисті: /remind @username [посилання]
@dp.message(Command("remind"))
async def remind_user(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Формат: `/remind @username [посилання_на_банку]`", parse_mode="Markdown")
        return
    
    username = args[1]
    jar_link = args[2] if len(args) > 2 else "банку"

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT telegram_id, amount, status FROM users WHERE username = ?", (username,)) as cursor:
            row = await cursor.fetchone()
            
    if not row or not row[0]:
        await message.answer(f"❌ Користувача {username} не знайдено або він ще не написав боту `/start`.")
        return
    
    telegram_id, amount, status = row
    if status == 'paid':
        await message.answer(f"Користувач {username} **вже сплатив** свою частину, нагадування не потрібне!")
        return

    text = f"Привіт! Нагадую про необхідність скинути {amount} грн до загального бюджету. Посилання на банку: {jar_link}"
    
    try:
        await bot.send_message(telegram_id, text)
        await message.answer(f"Нагадування для {username} успішно надіслано!")
    except Exception as e:
        await message.answer(f"Помилка надсилання: {e}")

async def main():
    await init_db()
    print("Бот запущено...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main)
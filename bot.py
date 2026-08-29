import os
import aiohttp
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# قراءة المتغيرات بشكل آمن من Railway Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# دالة لجلب أسعار العملات الحقيقية والمضبوطة من مصدر موثوق (Frankfurter API)
async def get_exchange_rates():
    url = "https://api.frankfurter.app/latest?from=USD&to=EUR"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                usd_to_eur = data["rates"]["EUR"]
                eur_to_usd = 1 / usd_to_eur
                return usd_to_eur, eur_to_usd
    return None, None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 LEX Bot خدام\n"
        "5️ USD / EUR\n"
        "📊 Live exchange rate\n"
        "⏰ تحديث مباشر"
    )

@dp.message(Command("price"))
async def cmd_price(message: types.Message):
    usd_to_eur, eur_to_usd = await get_exchange_rates()
    if usd_to_eur and eur_to_usd:
        text = (
            f"🇺🇸 1 USD = {usd_to_eur:.5f} EUR\n"
            f"🇪🇺 1 EUR = {eur_to_usd:.5f} USD\n\n"
            f"By LEX"
        )
        await message.answer(text)
    else:
        await message.answer("⚠️ حدث خطأ أثناء جلب أسعار العملات، حاول مرة أخرى.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

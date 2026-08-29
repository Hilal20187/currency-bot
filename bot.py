import os
import re
import requests
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")

XE_URL = "https://www.xe.com/currencyconverter/convert/?Amount=1&From=USD&To=EUR"


def get_xe_rate():
    response = requests.get(
        XE_URL,
        timeout=20,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    response.raise_for_status()
    html = response.text

    # نبحث عن الرقم الذي تعرضه XE للسعر
    match = re.search(
        r"1\s*USD\s*=\s*([0-9]+\.[0-9]+)\s*EUR",
        html
    )

    if not match:
        raise Exception("XE rate not found")

    usd_eur = float(match.group(1))
    eur_usd = 1 / usd_eur

    return usd_eur, eur_usd


async def send_price(context: ContextTypes.DEFAULT_TYPE):
    try:
        usd_eur, eur_usd = get_xe_rate()

        message = (
            "💱 XE LIVE RATE\n\n"
            f"🇺🇸 1 USD = {usd_eur:.6f} EUR\n"
            f"🇪🇺 1 EUR = {eur_usd:.6f} USD\n\n"
            "📊 Mid-market rate\n"
            "🔄 XE"
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=message
        )

        print("✅ XE price sent:", usd_eur)

    except Exception as e:
        print("❌ XE ERROR:", e)


async def start(update, context):
    await update.message.reply_text(
        "🤖 البوت خدام\n"
        "💱 السعر من XE\n"
        "⏰ تحديث تلقائي كل 3 ساعات"
    )


async def price(update, context):
    try:
        usd_eur, eur_usd = get_xe_rate()

        await update.message.reply_text(
            "💱 XE LIVE RATE\n\n"
            f"🇺🇸 1 USD = {usd_eur:.6f} EUR\n"
            f"🇪🇺 1 EUR = {eur_usd:.6f} USD\n\n"
            "📊 Mid-market rate"
        )

    except Exception as e:
        print("❌ ERROR:", e)
        await update.message.reply_text(
            "❌ ماقدرتش نجيب سعر XE حاليا."
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    if not GROUP_ID:
        raise RuntimeError("GROUP_ID missing")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))

    # أول رسالة بعد 10 ثواني
    # وبعدها كل 3 ساعات
    app.job_queue.run_repeating(
        send_price,
        interval=3 * 60 * 60,
        first=10
    )

    print("🤖 XE Currency Bot started")

    app.run_polling()


if __name__ == "__main__":
    main()

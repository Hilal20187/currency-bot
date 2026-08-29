import os
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
GROUP_ID = os.getenv("GROUP_ID")


def get_price():
    url = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/USD"

    response = requests.get(
        url,
        timeout=15,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
    )

    data = response.json()

    if data.get("result") != "success":
        raise Exception("API error")

    usd_eur = data["conversion_rates"]["EUR"]
    eur_usd = 1 / usd_eur

    return usd_eur, eur_usd


async def send_price(context: ContextTypes.DEFAULT_TYPE):
    try:
        usd_eur, eur_usd = get_price()

        message = (
            "🌐 Live Currency Rate (API)\n\n"
            f"💵 1 USD = {usd_eur:.4f} EUR\n"
            f"💶 1 EUR = {eur_usd:.4f} USD"
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=message
        )

        print("✅ Price sent successfully")

    except Exception as e:
        print("❌ ERROR:", e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 البوت خدام.\n\n"
        "💱 السعر يتحدث تلقائياً كل 3 ساعات."
    )


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd_eur, eur_usd = get_price()

        await update.message.reply_text(
            "🌐 Live Currency Rate (API)\n\n"
            f"💵 1 USD = {usd_eur:.4f} EUR\n"
            f"💶 1 EUR = {eur_usd:.4f} USD"
        )

    except Exception:
        await update.message.reply_text(
            "❌ تعذر الحصول على السعر حاليا."
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    if not API_KEY:
        raise RuntimeError("API_KEY missing")

    if not GROUP_ID:
        raise RuntimeError("GROUP_ID missing")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))

    # إرسال السعر كل 3 ساعات
    app.job_queue.run_repeating(
        send_price,
        interval=3 * 60 * 60,
        first=3 * 60 * 60
    )

    print("🤖 Bot started - sending price every 3 hours")

    app.run_polling()


if __name__ == "__main__":
    main()

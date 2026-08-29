import os
import requests
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")


def get_price():
    url = "https://api.frankfurter.app/latest?from=USD&to=EUR"

    response = requests.get(url, timeout=15)
    data = response.json()

    usd_eur = data["rates"]["EUR"]
    eur_usd = 1 / usd_eur

    return usd_eur, eur_usd


async def send_price(context: ContextTypes.DEFAULT_TYPE):
    try:
        usd_eur, eur_usd = get_price()

        message = (
            "🌐 Live Currency Rate\n\n"
            f"💵 1 USD = {usd_eur:.4f} EUR\n"
            f"💶 1 EUR = {eur_usd:.4f} USD\n\n"
            "🔄 Updated automatically"
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=message
        )

        print("✅ Price sent")

    except Exception as e:
        print("❌ ERROR:", e)


async def start(update, context):
    await update.message.reply_text(
        "🤖 Bot is working.\n"
        "💱 Price updates every 3 hours."
    )


async def price(update, context):
    try:
        usd_eur, eur_usd = get_price()

        await update.message.reply_text(
            "🌐 Live Currency Rate\n\n"
            f"💵 1 USD = {usd_eur:.4f} EUR\n"
            f"💶 1 EUR = {eur_usd:.4f} USD"
        )

    except Exception:
        await update.message.reply_text("❌ Error getting price.")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))

    app.job_queue.run_repeating(
        send_price,
        interval=3 * 60 * 60,
        first=10
    )

    print("🤖 Bot started")

    app.run_polling()


if __name__ == "__main__":
    main()

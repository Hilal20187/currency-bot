import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلا بك! 👋\n\n"
        "💱 لمعرفة السعر الحالي استعمل:\n"
        "/price"
    )


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        url = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/USD"

        response = requests.get(
            url,
            timeout=10,
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache"
            }
        )

        data = response.json()

        if data.get("result") != "success":
            await update.message.reply_text(
                "❌ تعذر الحصول على السعر حاليا."
            )
            return

        usd_eur = data["conversion_rates"]["EUR"]
        eur_usd = 1 / usd_eur

        await update.message.reply_text(
            "🌐 Live Currency Rate (API)\n\n"
            f"💵 1 USD = {usd_eur:.4f} EUR\n"
            f"💶 1 EUR = {eur_usd:.4f} USD\n\n"
            "🔄 تم جلب السعر عند الطلب."
        )

    except Exception as e:
        print("ERROR:", e)
        await update.message.reply_text(
            "❌ حدث خطأ أثناء جلب السعر."
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود في Render")

    if not API_KEY:
        raise RuntimeError("API_KEY غير موجود في Render")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))

    print("🤖 Currency bot started")

    app.run_polling()


if __name__ == "__main__":
    main()

import os
import re
import asyncio
import logging
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")

XE_URL = (
    "https://www.xe.com/currencyconverter/"
    "convert/?Amount=1&From=USD&To=EUR"
)

# =========================
# LOGGING
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# GET XE RATE
# =========================

def get_xe_rate():
    response = requests.get(
        XE_URL,
        timeout=15,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            ),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    response.raise_for_status()

    html = response.text

    match = re.search(
        r"1\s*USD\s*=\s*([0-9]+\.[0-9]+)\s*EUR",
        html,
        re.IGNORECASE,
    )

    if not match:
        raise Exception("XE rate not found in page")

    usd_eur = float(match.group(1))
    eur_usd = 1 / usd_eur

    return usd_eur, eur_usd


# =========================
# ASYNC XE REQUEST
# =========================

async def get_rate_async():
    """
    Run requests in a separate thread so Telegram
    event loop doesn't freeze.
    """

    return await asyncio.to_thread(get_xe_rate)


# =========================
# SEND PRICE
# =========================

async def send_price(context: ContextTypes.DEFAULT_TYPE):

    logger.info("🔄 Getting XE rate...")

    try:
        usd_eur, eur_usd = await get_rate_async()

        message = (
    f"🇺🇸 1 USD = {usd_eur:.6f} EUR\n"
    f"🇪🇺 1 EUR = {eur_usd:.6f} USD\n\n"
    "By LEX"
)
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=message,
        )

        logger.info(
            "✅ XE price sent: %.6f",
            usd_eur,
        )

    except Exception:
        logger.exception("❌ XE ERROR")


# =========================
# /START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🤖 البوت خدام\n"
        "💱 السعر من XE\n"
        "⏰ تحديث تلقائي كل 3 ساعات"
    )


# =========================
# /PRICE
# =========================

async def price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    try:
        logger.info("📊 Manual /price request")

        usd_eur, eur_usd = await get_rate_async()

        await update.message.reply_text(
            "💱 XE LIVE RATE\n\n"
            f"🇺🇸 1 USD = {usd_eur:.6f} EUR\n"
            f"🇪🇺 1 EUR = {eur_usd:.6f} USD\n\n"
            "📊 Mid-market rate\n"
            "🔄 XE"
        )

    except Exception:
        logger.exception("❌ /price ERROR")

        await update.message.reply_text(
            "❌ ماقدرتش نجيب سعر XE حاليا، "
            "عاود بعد شوية."
        )


# =========================
# MAIN
# =========================

def main():

    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN missing")

    if not GROUP_ID:
        raise RuntimeError("❌ GROUP_ID missing")

    logger.info("🤖 Starting XE Currency Bot...")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("price", price)
    )

    # Automatic update
    app.job_queue.run_repeating(
        send_price,
        interval=3 * 60 * 60,
        first=10,
    )

    logger.info("✅ Bot started successfully")
    logger.info("⏰ Automatic update: every 3 hours")

    # Telegram polling
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()

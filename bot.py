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
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    response.raise_for_status()

    html = response.text

    # البحث عن سعر USD → EUR
    match = re.search(
        r"1\s*USD\s*=\s*([0-9]+\.[0-9]+)\s*EUR",
        html,
        re.IGNORECASE,
    )

    if not match:
        raise Exception("XE rate not found")

    usd_eur = float(match.group(1))

    if usd_eur <= 0:
        raise Exception("Invalid XE rate")

    eur_usd = 1 / usd_eur

    return usd_eur, eur_usd


# =========================
# ASYNC REQUEST
# =========================

async def get_rate_async():

    # requests ما يجمّدش Telegram
    return await asyncio.to_thread(
        get_xe_rate
    )


# =========================
# FORMAT MESSAGE
# =========================

def create_message(usd_eur, eur_usd):

    return (
        f"🇺🇸 1 USD = {usd_eur:.6f} EUR\n"
        f"🇪🇺 1 EUR = {eur_usd:.6f} USD\n\n"
        "By LEX"
    )


# =========================
# AUTOMATIC PRICE
# =========================

async def send_price(
    context: ContextTypes.DEFAULT_TYPE
):

    logger.info("🔄 Getting XE rate...")

    try:

        usd_eur, eur_usd = await get_rate_async()

        message = create_message(
            usd_eur,
            eur_usd,
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=message,
        )

        logger.info(
            "✅ Price sent: USD/EUR %.6f",
            usd_eur,
        )

    except Exception as e:

        logger.error(
            "❌ XE ERROR: %s",
            e,
        )


# =========================
# /START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🤖 البوت خدام\n"
        "💱 USD / EUR\n"
        "⏰ تحديث كل 3 ساعات\n"
        "By LEX"
    )


# =========================
# /PRICE
# =========================

async def price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    try:

        logger.info(
            "📊 Manual /price request"
        )

        usd_eur, eur_usd = await get_rate_async()

        message = create_message(
            usd_eur,
            eur_usd,
        )

        await update.message.reply_text(
            message
        )

    except Exception as e:

        logger.error(
            "❌ /price ERROR: %s",
            e,
        )

        await update.message.reply_text(
            "❌ ماقدرتش نجيب السعر حاليا، "
            "عاود بعد شوية."
        )


# =========================
# ERROR HANDLER
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "❌ Telegram error: %s",
        context.error,
    )


# =========================
# MAIN
# =========================

def main():

    # التأكد من Environment Variables

    if not BOT_TOKEN:
        raise RuntimeError(
            "❌ BOT_TOKEN missing"
        )

    if not GROUP_ID:
        raise RuntimeError(
            "❌ GROUP_ID missing"
        )

    logger.info(
        "🤖 Starting LEX Currency Bot..."
    )

    # إنشاء البوت

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "price",
            price,
        )
    )

    # Error handler

    app.add_error_handler(
        error_handler
    )

    # =========================
    # AUTOMATIC UPDATE
    # =========================

    # أول تحديث بعد 10 ثواني
    # ثم كل 3 ساعات

    app.job_queue.run_repeating(
        send_price,
        interval=3 * 60 * 60,
        first=10,
    )

    logger.info(
        "✅ LEX Currency Bot started"
    )

    logger.info(
        "⏰ Automatic update: every 3 hours"
    )

    # =========================
    # START POLLING
    # =========================

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# =========================
# RUN
# =========================

if __name__ == "__main__":
    main() 

import os
import asyncio
import logging
import requests

from telegram import Update
from telegram.error import (
    Conflict,
    NetworkError,
    TimedOut,
    RetryAfter,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")

# API يمكن تغييره من Environment بدون تعديل الكود
# الافتراضي: Frankfurter
API_URL = os.getenv(
    "API_URL",
    "https://api.frankfurter.app/latest?from=USD&to=EUR"
)

# تحديث تلقائي كل 3 ساعات
UPDATE_INTERVAL = 3 * 60 * 60

# أول تحديث بعد 10 ثواني
FIRST_UPDATE = 10


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("LEX")


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "LEX-Currency-Bot/1.0",
    "Accept": "application/json",
})


# ============================================================
# GET LIVE RATE
# ============================================================

def get_rate_sync():

    logger.info("🌐 Requesting USD/EUR rate...")

    response = session.get(
        API_URL,
        timeout=(5, 15),
    )

    response.raise_for_status()

    data = response.json()

    # Frankfurter format:
    # {
    #   "amount": 1,
    #   "base": "USD",
    #   "date": "...",
    #   "rates": {
    #       "EUR": 0.86
    #   }
    # }

    rates = data.get("rates")

    if not isinstance(rates, dict):
        raise RuntimeError(
            "Invalid API response: rates missing"
        )

    if "EUR" not in rates:
        raise RuntimeError(
            "EUR rate missing"
        )

    usd_eur = float(rates["EUR"])

    # ========================================================
    # SAFETY CHECK
    # ========================================================

    if not 0.50 < usd_eur < 1.50:
        raise RuntimeError(
            f"Suspicious USD/EUR rate: {usd_eur}"
        )

    eur_usd = 1 / usd_eur

    logger.info(
        "✅ Rate received: USD/EUR %.6f",
        usd_eur,
    )

    return usd_eur, eur_usd


# ============================================================
# ASYNC RATE WITH RETRIES
# ============================================================

async def get_rate():

    delays = [2, 5, 10]

    for attempt in range(1, 4):

        try:

            return await asyncio.to_thread(
                get_rate_sync
            )

        except Exception as e:

            logger.warning(
                "Rate attempt %s/3 failed: %s",
                attempt,
                e,
            )

            if attempt < 3:
                await asyncio.sleep(
                    delays[attempt - 1]
                )

    raise RuntimeError(
        "Unable to obtain live rate"
    )


# ============================================================
# MESSAGE
# ============================================================

def make_message(
    usd_eur,
    eur_usd,
):

    return (
        f"🇺🇸 1 USD = {usd_eur:.6f} EUR\n"
        f"🇪🇺 1 EUR = {eur_usd:.6f} USD\n\n"
        "By LEX"
    )


# ============================================================
# TELEGRAM SEND
# ============================================================

async def send_message_safe(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id,
    text,
):

    for attempt in range(1, 4):

        try:

            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
            )

            logger.info(
                "✅ Telegram message sent"
            )

            return True

        except RetryAfter as e:

            logger.warning(
                "Telegram rate limit: waiting %s seconds",
                e.retry_after,
            )

            await asyncio.sleep(
                e.retry_after
            )

        except (
            TimedOut,
            NetworkError,
        ) as e:

            logger.warning(
                "Telegram network error %s/3: %s",
                attempt,
                e,
            )

            if attempt < 3:

                await asyncio.sleep(
                    attempt * 3
                )

        except Conflict:

            logger.critical(
                "🚨 409 CONFLICT"
            )

            logger.critical(
                "Another process is using "
                "this BOT_TOKEN."
            )

            return False

        except Exception as e:

            logger.exception(
                "Telegram send error: %s",
                e,
            )

            return False

    return False


# ============================================================
# AUTOMATIC PRICE UPDATE
# ============================================================

async def send_price(
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.info(
        "========== PRICE UPDATE =========="
    )

    try:

        usd_eur, eur_usd = await get_rate()

        text = make_message(
            usd_eur,
            eur_usd,
        )

        await send_message_safe(
            context,
            GROUP_ID,
            text,
        )

    except Exception as e:

        logger.exception(
            "❌ Price update failed: %s",
            e,
        )

    logger.info(
        "=================================="
    )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🤖 LEX Bot خدام\n"
        "💱 USD / EUR\n"
        "📊 Live exchange rate\n"
        "⏰ تحديث كل 3 ساعات\n"
        "By LEX"
    )


# ============================================================
# /PRICE
# ============================================================

async def price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    try:

        usd_eur, eur_usd = await get_rate()

        await update.message.reply_text(
            make_message(
                usd_eur,
                eur_usd,
            )
        )

    except Exception as e:

        logger.exception(
            "/price failed: %s",
            e,
        )

        await update.message.reply_text(
            "❌ السعر غير متوفر حاليا.\n"
            "عاود بعد شوية."
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    error = context.error

    if isinstance(error, Conflict):

        logger.critical(
            "🚨 409 CONFLICT"
        )

        logger.critical(
            "Only ONE instance can use "
            "this BOT_TOKEN."
        )

        return

    logger.exception(
        "Telegram error: %s",
        error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN missing"
        )

    if not GROUP_ID:

        raise RuntimeError(
            "GROUP_ID missing"
        )

    logger.info(
        "======================================"
    )

    logger.info(
        "🚀 LEX Currency Bot starting"
    )

    logger.info(
        "API: %s",
        API_URL,
    )

    logger.info(
        "Update interval: 3 hours"
    )

    logger.info(
        "======================================"
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(10)
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

    # Errors
    app.add_error_handler(
        error_handler
    )

    # Automatic updates
    app.job_queue.run_repeating(
        send_price,
        interval=UPDATE_INTERVAL,
        first=FIRST_UPDATE,
    )

    logger.info(
        "✅ Bot initialized"
    )

    logger.info(
        "▶️ Starting Telegram polling..."
    )

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()

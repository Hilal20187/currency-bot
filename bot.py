import os
import asyncio
import logging
import requests

from telegram import Update
from telegram.error import Conflict, NetworkError, TimedOut, RetryAfter
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

# تحديث كل 3 ساعات
UPDATE_INTERVAL = 3 * 60 * 60

# أول تحديث بعد 10 ثواني
FIRST_UPDATE = 10

# JSON exchange-rate API
API_URL = "https://api.exchangerate.dev/v1/latest/USD"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("LEX")


# ============================================================
# GET RATE
# ============================================================

def get_rate_sync():

    response = requests.get(
        API_URL,
        params={
            "symbols": "EUR",
        },
        timeout=(5, 15),
    )

    response.raise_for_status()

    data = response.json()

    if data.get("error"):
        raise RuntimeError(
            f"API error: {data['error']}"
        )

    rates = data.get("rates")

    if not isinstance(rates, dict):
        raise RuntimeError("Invalid API response")

    if "EUR" not in rates:
        raise RuntimeError("EUR rate missing")

    usd_eur = float(rates["EUR"])

    # حماية من رقم غير منطقي
    if not 0.1 < usd_eur < 2:
        raise RuntimeError(
            f"Invalid USD/EUR rate: {usd_eur}"
        )

    eur_usd = 1 / usd_eur

    logger.info(
        "💱 USD/EUR = %.6f | EUR/USD = %.6f",
        usd_eur,
        eur_usd,
    )

    return usd_eur, eur_usd


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
        "Could not get exchange rate"
    )


# ============================================================
# MESSAGE
# ============================================================

def make_message(usd_eur, eur_usd):

    return (
        f"🇺🇸 1 USD = {usd_eur:.6f} EUR\n"
        f"🇪🇺 1 EUR = {eur_usd:.6f} USD\n\n"
        "By LEX"
    )


# ============================================================
# SAFE TELEGRAM SEND
# ============================================================

async def send_safe(context, chat_id, text):

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
                "Telegram rate limit: %s sec",
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
# AUTOMATIC UPDATE
# ============================================================

async def send_price(
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.info(
        "========== PRICE UPDATE =========="
    )

    try:

        usd_eur, eur_usd = await get_rate()

        await send_safe(
            context,
            GROUP_ID,
            make_message(
                usd_eur,
                eur_usd,
            ),
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
        "📊 Exchange rate\n"
        "⏰ تحديث تلقائي كل 3 ساعات\n"
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
    update,
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
        "🚀 Starting LEX Currency Bot"
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

    app.add_error_handler(
        error_handler
    )

    app.job_queue.run_repeating(
        send_price,
        interval=UPDATE_INTERVAL,
        first=FIRST_UPDATE,
    )

    logger.info(
        "✅ LEX Bot initialized"
    )

    logger.info(
        "⏰ Automatic update every 3 hours"
    )

    logger.info(
        "▶️ Starting Telegram polling..."
    )

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main() 

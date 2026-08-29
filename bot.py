import os
import asyncio
import logging
from decimal import Decimal, InvalidOperation

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

# تحديث تلقائي كل 15 دقيقة
UPDATE_INTERVAL = 15 * 60

# أول تحديث بعد 10 ثواني
FIRST_UPDATE = 10

# Intraday FX API
API_URL = "https://api.exchangerate.dev/v1/rates/USD/EUR"


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
# RATE VALIDATION
# ============================================================

def validate_rate(value):
    try:
        rate = Decimal(str(value))

        # USD/EUR منطقي
        if rate <= Decimal("0.50"):
            return None

        if rate >= Decimal("1.50"):
            return None

        return rate

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None


# ============================================================
# GET USD/EUR
# ============================================================

def get_usd_eur_sync():

    logger.info("🌐 Getting intraday USD/EUR rate...")

    response = session.get(
        API_URL,
        timeout=(5, 15),
    )

    response.raise_for_status()

    data = response.json()

    logger.info(
        "API response received"
    )

    # --------------------------------------------------------
    # exchangerate.dev response
    # --------------------------------------------------------

    rate = data.get("rate")

    if rate is None:

        # fallback لبعض أشكال JSON
        rates = data.get("rates")

        if isinstance(rates, dict):
            rate = rates.get("EUR")

    rate = validate_rate(rate)

    if rate is None:

        raise RuntimeError(
            f"Invalid USD/EUR rate: {data}"
        )

    eur_usd = Decimal("1") / rate

    # --------------------------------------------------------
    # Metadata إذا كانت موجودة
    # --------------------------------------------------------

    source = (
        data.get("source")
        or data.get("provider")
        or "FX API"
    )

    updated = (
        data.get("data_updated_at")
        or data.get("updated_at")
        or data.get("timestamp")
        or ""
    )

    logger.info(
        "✅ USD/EUR = %s | source=%s | updated=%s",
        rate,
        source,
        updated,
    )

    return rate, eur_usd, source, updated


# ============================================================
# ASYNC RATE + RETRY
# ============================================================

async def get_rate():

    delays = [2, 5, 10]

    for attempt in range(1, 4):

        try:

            return await asyncio.to_thread(
                get_usd_eur_sync
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
        "Live FX rate unavailable"
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

async def send_safe(
    context,
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
                "Another instance is using "
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

        usd_eur, eur_usd, source, updated = (
            await get_rate()
        )

        await send_safe(
            context,
            GROUP_ID,
            make_message(
                usd_eur,
                eur_usd,
            ),
        )

        logger.info(
            "✅ PRICE SENT | SOURCE=%s",
            source,
        )

    except Exception as e:

        logger.exception(
            "❌ PRICE UPDATE FAILED: %s",
            e,
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
        "📊 Live FX rate\n"
        "⏰ تحديث كل 15 دقيقة\n"
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

        usd_eur, eur_usd, source, updated = (
            await get_rate()
        )

        await update.message.reply_text(
            make_message(
                usd_eur,
                eur_usd,
            )
        )

        logger.info(
            "/price OK | SOURCE=%s | UPDATED=%s",
            source,
            updated,
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
        "======================================"
    )

    logger.info(
        "🚀 LEX PRO Currency Bot"
    )

    logger.info(
        "📊 Intraday FX source"
    )

    logger.info(
        "⏰ Update every 15 minutes"
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
        "✅ Bot initialized"
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

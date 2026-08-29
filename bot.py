import os
import json
import time
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

UPDATE_INTERVAL = 3 * 60 * 60
FIRST_UPDATE = 10

API_URL = "https://api.exchangerate.dev/v1/latest/USD"

CACHE_FILE = "last_rate.json"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("LEX")


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "LEX-Currency-Bot/5.0",
    "Accept": "application/json",
})


# ============================================================
# CACHE
# ============================================================

def save_cache(usd_eur, eur_usd):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "usd_eur": usd_eur,
                    "eur_usd": eur_usd,
                    "saved_at": int(time.time()),
                },
                f,
            )
    except Exception as e:
        logger.warning("Cache save failed: %s", e)


def load_cache():
    try:
        if not os.path.exists(CACHE_FILE):
            return None

        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        usd_eur = float(data["usd_eur"])
        eur_usd = float(data["eur_usd"])
        saved_at = int(data["saved_at"])

        if usd_eur <= 0 or eur_usd <= 0:
            return None

        return usd_eur, eur_usd, saved_at

    except Exception:
        return None


# ============================================================
# RATE
# ============================================================

def get_live_rate_sync():

    logger.info("🌐 Requesting live USD/EUR...")

    response = session.get(
        API_URL,
        params={"symbols": "EUR"},
        timeout=(5, 15),
    )

    response.raise_for_status()

    data = response.json()

    logger.info("API response received")

    if data.get("error"):
        raise RuntimeError(
            f"API error: {data['error']}"
        )

    rates = data.get("rates")

    if not isinstance(rates, dict):
        raise RuntimeError(
            "Invalid API response"
        )

    if "EUR" not in rates:
        raise RuntimeError(
            "EUR rate missing"
        )

    usd_eur = float(rates["EUR"])

    if not (0.1 < usd_eur < 2.0):
        raise RuntimeError(
            f"Invalid USD/EUR rate: {usd_eur}"
        )

    eur_usd = 1 / usd_eur

    save_cache(
        usd_eur,
        eur_usd,
    )

    logger.info(
        "✅ LIVE USD/EUR = %.6f",
        usd_eur,
    )

    return (
        usd_eur,
        eur_usd,
        "LIVE",
    )


async def get_rate():

    delays = [2, 5, 10]

    for attempt in range(1, 4):

        try:

            return await asyncio.to_thread(
                get_live_rate_sync
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

    cached = load_cache()

    if cached:

        usd_eur, eur_usd, saved_at = cached

        age = int(time.time()) - saved_at

        logger.warning(
            "⚠️ API unavailable - using cache "
            "(age=%s sec)",
            age,
        )

        return (
            usd_eur,
            eur_usd,
            "CACHE",
        )

    raise RuntimeError(
        "No live rate and no cache"
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
                "Rate limited, waiting %s sec",
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
                "🚨 409 CONFLICT!"
            )

            logger.critical(
                "ANOTHER INSTANCE IS USING "
                "THIS BOT TOKEN."
            )

            return False

        except Exception as e:

            logger.exception(
                "Telegram send failed: %s",
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

        usd_eur, eur_usd, source = (
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
            "PRICE UPDATE OK | SOURCE=%s",
            source,
        )

    except Exception as e:

        logger.exception(
            "PRICE UPDATE ERROR: %s",
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
        "📊 Live market rate\n"
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

        usd_eur, eur_usd, source = (
            await get_rate()
        )

        await update.message.reply_text(
            make_message(
                usd_eur,
                eur_usd,
            )
        )

    except Exception as e:

        logger.exception(
            "/price ERROR: %s",
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
            "🚨 TELEGRAM 409 CONFLICT"
        )

        logger.critical(
            "Another process is using "
            "this BOT_TOKEN."
        )

        return

    logger.exception(
        "Telegram error: %s",
        error,
    )


# ============================================================
# START BOT
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
        "===================================="
    )

    logger.info(
        "🚀 LEX CURRENCY BOT STARTING"
    )

    logger.info(
        "Python process PID: %s",
        os.getpid(),
    )

    logger.info(
        "===================================="
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
        "✅ Application initialized"
    )

    logger.info(
        "⏰ Automatic update: every 3 hours"
    )

    logger.info(
        "▶️ Starting Telegram polling..."
    )

    try:

        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )

    except Conflict:

        logger.critical(
            "🚨 409 CONFLICT - BOT STOPPED"
        )

        logger.critical(
            "Only ONE running instance "
            "may use this token."
        )

        raise

    except Exception as e:

        logger.exception(
            "🔥 POLLING CRASHED: %s",
            e,
        )

        raise

    finally:

        logger.critical(
            "🛑 run_polling() EXITED"
        )


if __name__ == "__main__":
    main() 

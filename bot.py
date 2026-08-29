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

# تحديث كل 3 ساعات
UPDATE_INTERVAL = 3 * 60 * 60

# أول تحديث بعد 10 ثواني
FIRST_UPDATE = 10

# Frankfurter JSON API
# بدون API KEY
FRANKFURTER_URL = (
    "https://api.frankfurter.dev/v2/rate/USD/EUR"
)

# مهم:
# لا نضع providers=ECB
# حتى لا نجبر السعر على ECB reference rate.

CACHE_FILE = "last_rate.json"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger("LEX")


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "LEX-Currency-Bot/2.0",
    "Accept": "application/json",
})


# ============================================================
# CACHE
# ============================================================

def save_cache(
    usd_eur,
    eur_usd,
    rate_date=None,
):

    try:

        data = {
            "usd_eur": usd_eur,
            "eur_usd": eur_usd,
            "rate_date": rate_date,
            "timestamp": int(time.time()),
        }

        with open(
            CACHE_FILE,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
            )

    except Exception as e:

        logger.warning(
            "Cache save failed: %s",
            e,
        )


def load_cache():

    try:

        if not os.path.exists(
            CACHE_FILE
        ):
            return None

        with open(
            CACHE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        usd_eur = float(
            data["usd_eur"]
        )

        eur_usd = float(
            data["eur_usd"]
        )

        timestamp = int(
            data["timestamp"]
        )

        rate_date = data.get(
            "rate_date"
        )

        if usd_eur <= 0:
            return None

        if eur_usd <= 0:
            return None

        return (
            usd_eur,
            eur_usd,
            rate_date,
            timestamp,
        )

    except Exception as e:

        logger.warning(
            "Cache load failed: %s",
            e,
        )

        return None


# ============================================================
# VALIDATE RATE
# ============================================================

def validate_rate(rate):

    try:

        rate = float(rate)

        # حماية من API يعطي قيمة غير منطقية
        if not (
            0.1 < rate < 2.0
        ):
            return None

        return rate

    except (
        TypeError,
        ValueError,
    ):

        return None


# ============================================================
# GET FRANKFURTER RATE
# ============================================================

def get_frankfurter_rate():

    logger.info(
        "🌐 Requesting Frankfurter JSON..."
    )

    response = session.get(
        FRANKFURTER_URL,
        timeout=(5, 10),
    )

    response.raise_for_status()

    # JSON فقط
    data = response.json()

    logger.info(
        "Frankfurter response: %s",
        data,
    )

    # Expected:
    #
    # {
    #   "date": "2026-08-28",
    #   "base": "USD",
    #   "quote": "EUR",
    #   "rate": 0.86...
    # }

    if data.get("base") != "USD":
        raise RuntimeError(
            "Unexpected base currency"
        )

    if data.get("quote") != "EUR":
        raise RuntimeError(
            "Unexpected quote currency"
        )

    if "rate" not in data:
        raise RuntimeError(
            "Rate missing from JSON"
        )

    usd_eur = validate_rate(
        data["rate"]
    )

    if usd_eur is None:
        raise RuntimeError(
            "Invalid USD/EUR rate"
        )

    eur_usd = 1 / usd_eur

    rate_date = data.get(
        "date"
    )

    # حفظ آخر سعر صحيح
    save_cache(
        usd_eur,
        eur_usd,
        rate_date,
    )

    logger.info(
        "✅ USD/EUR = %.9f",
        usd_eur,
    )

    logger.info(
        "📅 Rate date = %s",
        rate_date,
    )

    return (
        usd_eur,
        eur_usd,
        "FRANKFURTER",
        rate_date,
    )


# ============================================================
# ASYNC RATE + RETRY
# ============================================================

async def get_rate():

    retry_delays = [
        2,
        5,
        10,
    ]

    for attempt in range(1, 4):

        try:

            logger.info(
                "💱 Rate attempt %s/3",
                attempt,
            )

            result = await asyncio.to_thread(
                get_frankfurter_rate
            )

            return result

        except Exception as e:

            logger.warning(
                "❌ Rate attempt %s failed: %s",
                attempt,
                e,
            )

            if attempt < 3:

                await asyncio.sleep(
                    retry_delays[
                        attempt - 1
                    ]
                )

    # ========================================================
    # CACHE FALLBACK
    # ========================================================

    cached = load_cache()

    if cached:

        (
            usd_eur,
            eur_usd,
            rate_date,
            timestamp,
        ) = cached

        age = (
            int(time.time())
            - timestamp
        )

        logger.warning(
            "⚠️ Frankfurter unavailable."
        )

        logger.warning(
            "Using cached rate."
        )

        logger.warning(
            "Cache age: %s seconds",
            age,
        )

        return (
            usd_eur,
            eur_usd,
            "CACHE",
            rate_date,
        )

    raise RuntimeError(
        "Frankfurter unavailable "
        "and no cached rate"
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
                "Telegram rate limit: "
                "%s seconds",
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
                "Telegram network error "
                "%s/3: %s",
                attempt,
                e,
            )

            if attempt < 3:

                await asyncio.sleep(
                    attempt * 3
                )

        except Conflict:

            logger.error(
                "🚨 409 CONFLICT"
            )

            logger.error(
                "Another bot instance "
                "is using this BOT_TOKEN."
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
# AUTOMATIC PRICE
# ============================================================

async def send_price(
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.info(
        "========== PRICE UPDATE START =========="
    )

    try:

        (
            usd_eur,
            eur_usd,
            source,
            rate_date,
        ) = await get_rate()

        message = make_message(
            usd_eur,
            eur_usd,
        )

        success = await send_message_safe(
            context,
            GROUP_ID,
            message,
        )

        if success:

            logger.info(
                "✅ PRICE SENT"
            )

            logger.info(
                "USD/EUR: %.6f",
                usd_eur,
            )

            logger.info(
                "SOURCE: %s",
                source,
            )

            logger.info(
                "RATE DATE: %s",
                rate_date,
            )

    except Exception as e:

        logger.exception(
            "❌ PRICE UPDATE FAILED: %s",
            e,
        )

    finally:

        logger.info(
            "========== PRICE UPDATE END =========="
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

    logger.info(
        "📊 /price received"
    )

    try:

        (
            usd_eur,
            eur_usd,
            source,
            rate_date,
        ) = await get_rate()

        await update.message.reply_text(
            make_message(
                usd_eur,
                eur_usd,
            )
        )

        logger.info(
            "✅ /price successful | "
            "SOURCE=%s | DATE=%s",
            source,
            rate_date,
        )

    except Exception as e:

        logger.exception(
            "❌ /price failed: %s",
            e,
        )

        await update.message.reply_text(
            "❌ تعذر جلب السعر حاليا."
        )


# ============================================================
# TELEGRAM ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context: ContextTypes.DEFAULT_TYPE,
):

    error = context.error

    if isinstance(
        error,
        Conflict,
    ):

        logger.error(
            "🚨 409 CONFLICT"
        )

        logger.error(
            "Only ONE instance of "
            "this bot can run."
        )

        return

    logger.exception(
        "Telegram application error: %s",
        error,
    )


# ============================================================
# RUN BOT
# ============================================================

def run_bot():

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
        .read_timeout(20)
        .write_timeout(20)
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

    # Automatic update
    app.job_queue.run_repeating(
        send_price,
        interval=UPDATE_INTERVAL,
        first=FIRST_UPDATE,
    )

    logger.info(
        "✅ Bot initialized"
    )

    logger.info(
        "⏰ Update every 3 hours"
    )

    logger.info(
        "🔄 First update after 10 seconds"
    )

    # Telegram polling
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# ============================================================
# AUTO RESTART
# ============================================================

def main():

    while True:

        try:

            run_bot()

            logger.warning(
                "⚠️ Bot stopped."
            )

            break

        except KeyboardInterrupt:

            logger.info(
                "🛑 Bot stopped manually."
            )

            break

        except Conflict:

            logger.error(
                "🚨 409 CONFLICT"
            )

            logger.error(
                "Stop every other instance "
                "using this BOT_TOKEN."
            )

            # لا نعيد التشغيل بسرعة
            # لأن restart لن يحل Conflict
            time.sleep(30)

        except Exception as e:

            logger.exception(
                "🔥 Fatal bot error: %s",
                e,
            )

            logger.info(
                "♻️ Restarting in 15 seconds..."
            )

            time.sleep(15)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main() 

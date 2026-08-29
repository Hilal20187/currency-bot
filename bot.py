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
API_KEY = os.getenv("CURRENCYFREAKS_API_KEY")

# نشر السعر كل 3 ساعات
UPDATE_INTERVAL = 3 * 60 * 60

# أول نشر بعد 10 ثواني
FIRST_UPDATE = 10

# CurrencyFreaks API
API_URL = (
    "https://api.currencyfreaks.com/v2.0/rates/latest"
)

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
    "User-Agent": "LEX-Currency-Bot/3.0",
    "Accept": "application/json",
})


# ============================================================
# CACHE
# ============================================================

def save_cache(
    usd_eur,
    eur_usd,
    api_date=None,
):

    try:

        data = {
            "usd_eur": usd_eur,
            "eur_usd": eur_usd,
            "api_date": api_date,
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

        api_date = data.get(
            "api_date"
        )

        if usd_eur <= 0:
            return None

        if eur_usd <= 0:
            return None

        return (
            usd_eur,
            eur_usd,
            api_date,
            timestamp,
        )

    except Exception as e:

        logger.warning(
            "Cache load failed: %s",
            e,
        )

        return None


# ============================================================
# RATE VALIDATION
# ============================================================

def validate_rate(value):

    try:

        value = float(value)

        # Basic sanity check
        if not (
            0.1 < value < 2.0
        ):
            return None

        return value

    except (
        TypeError,
        ValueError,
    ):

        return None


# ============================================================
# CURRENCYFREAKS
# ============================================================

def get_currencyfreaks_rate():

    if not API_KEY:

        raise RuntimeError(
            "CURRENCYFREAKS_API_KEY missing"
        )

    logger.info(
        "🌐 Requesting CurrencyFreaks..."
    )

    params = {
        "apikey": API_KEY,
        "symbols": "EUR",
    }

    response = session.get(
        API_URL,
        params=params,
        timeout=(5, 15),
    )

    response.raise_for_status()

    data = response.json()

    logger.info(
        "CurrencyFreaks response received"
    )

    # ========================================================
    # CHECK API ERROR
    # ========================================================

    if "error" in data:

        raise RuntimeError(
            f"CurrencyFreaks API error: "
            f"{data['error']}"
        )

    # ========================================================
    # CHECK STRUCTURE
    # ========================================================

    rates = data.get(
        "rates"
    )

    if not isinstance(
        rates,
        dict,
    ):

        raise RuntimeError(
            "Invalid API response: rates missing"
        )

    if "EUR" not in rates:

        raise RuntimeError(
            "EUR rate missing"
        )

    # ========================================================
    # USD -> EUR
    # ========================================================

    usd_eur = validate_rate(
        rates["EUR"]
    )

    if usd_eur is None:

        raise RuntimeError(
            "Invalid USD/EUR rate"
        )

    # ========================================================
    # EUR -> USD
    # ========================================================

    eur_usd = 1 / usd_eur

    api_date = data.get(
        "date"
    )

    # Save valid rate
    save_cache(
        usd_eur,
        eur_usd,
        api_date,
    )

    logger.info(
        "✅ USD/EUR = %.9f",
        usd_eur,
    )

    logger.info(
        "📅 API date = %s",
        api_date,
    )

    return (
        usd_eur,
        eur_usd,
        "LIVE",
        api_date,
    )


# ============================================================
# ASYNC RATE + RETRY
# ============================================================

async def get_rate():

    delays = [
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
                get_currencyfreaks_rate
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
                    delays[
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
            api_date,
            timestamp,
        ) = cached

        age = (
            int(time.time())
            - timestamp
        )

        logger.warning(
            "⚠️ API unavailable."
        )

        logger.warning(
            "Using last valid cached rate."
        )

        logger.warning(
            "Cache age: %s seconds",
            age,
        )

        return (
            usd_eur,
            eur_usd,
            "CACHE",
            api_date,
        )

    raise RuntimeError(
        "CurrencyFreaks unavailable "
        "and no cache exists"
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

        (
            usd_eur,
            eur_usd,
            source,
            api_date,
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
                "✅ PRICE SENT | "
                "USD/EUR %.6f | "
                "SOURCE %s | "
                "DATE %s",
                usd_eur,
                source,
                api_date,
            )

    except Exception as e:

        logger.exception(
            "❌ PRICE UPDATE FAILED: %s",
            e,
        )

    logger.info(
        "================================="
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
        "⏰ تحديث تلقائي\n"
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

        (
            usd_eur,
            eur_usd,
            source,
            api_date,
        ) = await get_rate()

        await update.message.reply_text(
            make_message(
                usd_eur,
                eur_usd,
            )
        )

        logger.info(
            "/price successful | "
            "SOURCE=%s | DATE=%s",
            source,
            api_date,
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

    if isinstance(
        error,
        Conflict,
    ):

        logger.error(
            "🚨 409 CONFLICT"
        )

        logger.error(
            "Only ONE bot instance "
            "can run."
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

    if not API_KEY:

        raise RuntimeError(
            "CURRENCYFREAKS_API_KEY missing"
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
        "⏰ Automatic update every 3 hours"
    )

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# ============================================================
# MAIN
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
                "Another bot instance "
                "is using this token."
            )

            # لا تعيد التشغيل بلا نهاية
            break

        except Exception as e:

            logger.exception(
                "🔥 Fatal error: %s",
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

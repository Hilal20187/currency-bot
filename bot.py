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

# API key اختياري:
# يشتغل exchangerate.dev بدون key للتجربة.
# إذا عندك Free API Key حطو في Render.
EXCHANGERATE_API_KEY = os.getenv(
    "EXCHANGERATE_API_KEY"
)

# تحديث البوت كل 3 ساعات
UPDATE_INTERVAL = 3 * 60 * 60

# أول تحديث بعد 10 ثواني
FIRST_UPDATE = 10

# exchangerate.dev
API_URL = (
    "https://api.exchangerate.dev/v1/latest/USD"
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
    "User-Agent": "LEX-Currency-Bot/4.0",
    "Accept": "application/json",
})


# ============================================================
# CACHE
# ============================================================

def save_cache(
    usd_eur,
    eur_usd,
    timestamp_api=None,
    source=None,
    market_session=None,
):

    try:

        data = {
            "usd_eur": usd_eur,
            "eur_usd": eur_usd,
            "api_timestamp": timestamp_api,
            "source": source,
            "market_session": market_session,
            "saved_at": int(time.time()),
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

        saved_at = int(
            data["saved_at"]
        )

        source = data.get(
            "source"
        )

        market_session = data.get(
            "market_session"
        )

        api_timestamp = data.get(
            "api_timestamp"
        )

        if usd_eur <= 0:
            return None

        if eur_usd <= 0:
            return None

        return (
            usd_eur,
            eur_usd,
            api_timestamp,
            source,
            market_session,
            saved_at,
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

        # USD/EUR منطقيًا لازم يكون داخل هذا النطاق
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
# GET LIVE RATE
# ============================================================

def get_live_rate():

    logger.info(
        "🌐 Requesting exchangerate.dev..."
    )

    params = {
        "symbols": "EUR",
    }

    # إذا عندنا API key نستعمله
    if EXCHANGERATE_API_KEY:

        params["apikey"] = (
            EXCHANGERATE_API_KEY
        )

    response = session.get(
        API_URL,
        params=params,
        timeout=(5, 15),
    )

    response.raise_for_status()

    data = response.json()

    logger.info(
        "Exchange API response received"
    )

    # ========================================================
    # API ERROR
    # ========================================================

    if data.get("error"):

        raise RuntimeError(
            f"API error: {data['error']}"
        )

    # ========================================================
    # RATES
    # ========================================================

    rates = data.get(
        "rates"
    )

    if not isinstance(
        rates,
        dict,
    ):

        raise RuntimeError(
            "Invalid API response: "
            "rates missing"
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

    # ========================================================
    # METADATA
    # ========================================================

    api_timestamp = data.get(
        "timestamp"
    )

    source = data.get(
        "source"
    )

    market_session = data.get(
        "market_session"
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "✅ USD/EUR = %.9f",
        usd_eur,
    )

    logger.info(
        "✅ EUR/USD = %.9f",
        eur_usd,
    )

    logger.info(
        "📡 SOURCE = %s",
        source,
    )

    logger.info(
        "📊 MARKET SESSION = %s",
        market_session,
    )

    logger.info(
        "🕐 API TIMESTAMP = %s",
        api_timestamp,
    )

    logger.info(
        "======================================"
    )

    # Save valid rate
    save_cache(
        usd_eur,
        eur_usd,
        api_timestamp,
        source,
        market_session,
    )

    return (
        usd_eur,
        eur_usd,
        "LIVE",
        api_timestamp,
        source,
        market_session,
    )


# ============================================================
# ASYNC RATE WITH RETRY
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
                get_live_rate
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
            api_timestamp,
            source,
            market_session,
            saved_at,
        ) = cached

        age = (
            int(time.time())
            - saved_at
        )

        logger.warning(
            "⚠️ Live API unavailable."
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
            api_timestamp,
            source,
            market_session,
        )

    raise RuntimeError(
        "Live API unavailable "
        "and no cached rate exists"
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
# TELEGRAM SAFE SEND
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
                "Another instance is "
                "using this BOT_TOKEN."
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
# AUTOMATIC PRICE
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
            source_type,
            api_timestamp,
            source,
            market_session,
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
                "USD/EUR = %.6f",
                usd_eur,
            )

            logger.info(
                "TYPE = %s",
                source_type,
            )

            logger.info(
                "SOURCE = %s",
                source,
            )

            logger.info(
                "SESSION = %s",
                market_session,
            )

    except Exception as e:

        logger.exception(
            "❌ PRICE UPDATE FAILED: %s",
            e,
        )

    finally:

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

    logger.info(
        "📊 /price command received"
    )

    try:

        (
            usd_eur,
            eur_usd,
            source_type,
            api_timestamp,
            source,
            market_session,
        ) = await get_rate()

        await update.message.reply_text(
            make_message(
                usd_eur,
                eur_usd,
            )
        )

        logger.info(
            "✅ /price successful"
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
            "Only ONE instance can "
            "use this bot token."
        )

        return

    logger.exception(
        "Telegram application error: %s",
        error,
    )


# ============================================================
# RUN
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

    if EXCHANGERATE_API_KEY:

        logger.info(
            "🔑 exchangerate.dev API key enabled"
        )

    else:

        logger.info(
            "🔓 exchangerate.dev anonymous mode"
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

    # Error handler
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

    logger.info(
        "🔄 First update after 10 seconds"
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
                "Stop the other bot instance."
            )

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

import os
import re
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

XE_CONVERTER_URL = (
    "https://www.xe.com/currencyconverter/"
    "?Amount=1&From=USD&To=EUR"
)

XE_TABLE_URL = (
    "https://www.xe.com/currencytables/"
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
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


# ============================================================
# CACHE
# ============================================================

def save_cache(usd_eur, eur_usd):

    data = {
        "usd_eur": usd_eur,
        "eur_usd": eur_usd,
        "timestamp": int(time.time()),
    }

    try:
        with open(
            CACHE_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                data,
                f,
            )

    except Exception as e:

        logger.warning(
            "Could not save cache: %s",
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
        ) as f:

            data = json.load(f)

        usd_eur = float(
            data["usd_eur"]
        )

        eur_usd = float(
            data["eur_usd"]
        )

        timestamp = int(
            data["timestamp"]
        )

        if usd_eur <= 0 or eur_usd <= 0:
            return None

        return (
            usd_eur,
            eur_usd,
            timestamp,
        )

    except Exception as e:

        logger.warning(
            "Could not load cache: %s",
            e,
        )

        return None


# ============================================================
# VALIDATE RATE
# ============================================================

def validate_rate(rate):

    try:

        rate = float(rate)

        if not (0.1 < rate < 2):
            return None

        return rate

    except (
        TypeError,
        ValueError,
    ):

        return None


# ============================================================
# METHOD 1
# XE CONVERTER - STRUCTURED DATA
# ============================================================

def get_rate_from_converter():

    response = session.get(
        XE_CONVERTER_URL,
        timeout=(5, 15),
    )

    response.raise_for_status()

    html = response.text

    # --------------------------------------------------------
    # Look for JSON / structured data containing EUR value
    # --------------------------------------------------------

    patterns = [

        # Common JSON-style representations
        r'"EUR"\s*:\s*([0-9]+\.[0-9]+)',

        r'"toCurrency"\s*:\s*"EUR".{0,500}?'
        r'"rate"\s*:\s*([0-9]+\.[0-9]+)',

        r'"rate"\s*:\s*([0-9]+\.[0-9]+).{0,500}?'
        r'"EUR"',

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if match:

            rate = validate_rate(
                match.group(1)
            )

            if rate:

                logger.info(
                    "XE converter rate found: %.9f",
                    rate,
                )

                return rate

    # --------------------------------------------------------
    # Fallback: extract converter numeric value
    # --------------------------------------------------------

    fallback_patterns = [

        r'1\.00\s*USD\s*=\s*'
        r'([0-9]+\.[0-9]+)\s*EUR',

        r'1\s*USD\s*=\s*'
        r'([0-9]+\.[0-9]+)\s*EUR',

    ]

    for pattern in fallback_patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE,
        )

        if match:

            rate = validate_rate(
                match.group(1)
            )

            if rate:

                logger.info(
                    "XE converter fallback rate: %.9f",
                    rate,
                )

                return rate

    raise RuntimeError(
        "XE converter rate not found"
    )


# ============================================================
# METHOD 2
# XE CURRENCY TABLES
# ============================================================

def get_rate_from_table():

    response = session.get(
        XE_TABLE_URL,
        timeout=(5, 15),
    )

    response.raise_for_status()

    html = response.text

    # EUR / USD = 1.xxxxx
    patterns = [

        r'EUR\s*/\s*USD'
        r'.{0,300}?'
        r'([0-9]+\.[0-9]+)',

        r'USD\s*/\s*EUR'
        r'.{0,300}?'
        r'([0-9]+\.[0-9]+)',

    ]

    for index, pattern in enumerate(
        patterns
    ):

        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if not match:
            continue

        value = validate_rate(
            match.group(1)
        )

        if not value:
            continue

        if index == 0:
            # EUR/USD -> inverse
            eur_usd = value
            usd_eur = 1 / eur_usd

        else:
            # USD/EUR
            usd_eur = value
            eur_usd = 1 / usd_eur

        logger.info(
            "XE table rate found: %.9f",
            usd_eur,
        )

        return (
            usd_eur,
            eur_usd,
        )

    raise RuntimeError(
        "XE table rate not found"
    )


# ============================================================
# MAIN RATE FUNCTION
# ============================================================

def get_xe_rate():

    # --------------------------------------------------------
    # METHOD 1
    # --------------------------------------------------------

    try:

        usd_eur = (
            get_rate_from_converter()
        )

        eur_usd = 1 / usd_eur

        save_cache(
            usd_eur,
            eur_usd,
        )

        return (
            usd_eur,
            eur_usd,
            "LIVE",
        )

    except Exception as e:

        logger.warning(
            "Converter method failed: %s",
            e,
        )


    # --------------------------------------------------------
    # METHOD 2
    # --------------------------------------------------------

    try:

        usd_eur, eur_usd = (
            get_rate_from_table()
        )

        save_cache(
            usd_eur,
            eur_usd,
        )

        return (
            usd_eur,
            eur_usd,
            "LIVE",
        )

    except Exception as e:

        logger.warning(
            "Table method failed: %s",
            e,
        )


    # --------------------------------------------------------
    # METHOD 3 - CACHE
    # --------------------------------------------------------

    cached = load_cache()

    if cached:

        usd_eur, eur_usd, timestamp = (
            cached
        )

        age = (
            int(time.time())
            - timestamp
        )

        logger.warning(
            "Using cached XE rate. Age: %s seconds",
            age,
        )

        return (
            usd_eur,
            eur_usd,
            "CACHED",
        )


    raise RuntimeError(
        "XE unavailable and no cached rate"
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
                "Getting XE rate %s/3",
                attempt,
            )

            result = await asyncio.to_thread(
                get_xe_rate
            )

            logger.info(
                "XE rate obtained successfully"
            )

            return result

        except Exception as e:

            logger.warning(
                "XE attempt %s failed: %s",
                attempt,
                e,
            )

            if attempt < 3:

                await asyncio.sleep(
                    delays[attempt - 1]
                )

    raise RuntimeError(
        "XE failed after 3 attempts"
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
# TELEGRAM SEND WITH RETRY
# ============================================================

async def send_telegram(
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
                "Telegram message sent"
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
                "🚨 CONFLICT: another bot "
                "instance is using this token!"
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

        usd_eur, eur_usd, source = (
            await get_rate()
        )

        message = make_message(
            usd_eur,
            eur_usd,
        )

        success = await send_telegram(
            context,
            GROUP_ID,
            message,
        )

        if success:

            logger.info(
                "✅ PRICE SENT | "
                "USD/EUR %.6f | SOURCE %s",
                usd_eur,
                source,
            )

    except Exception as e:

        logger.exception(
            "❌ PRICE UPDATE FAILED: %s",
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

        usd_eur, eur_usd, source = (
            await get_rate()
        )

        await update.message.reply_text(
            make_message(
                usd_eur,
                eur_usd,
            )
        )

        logger.info(
            "/price successful | SOURCE %s",
            source,
        )

    except Exception as e:

        logger.exception(
            "/price failed: %s",
            e,
        )

        await update.message.reply_text(
            "❌ تعذر جلب السعر حاليا."
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    error = context.error

    if isinstance(
        error,
        Conflict,
    ):

        logger.error(
            "🚨 409 CONFLICT - "
            "another instance is running"
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
        "🚀 Starting LEX Bot"
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

    app.job_queue.run_repeating(
        send_price,
        interval=UPDATE_INTERVAL,
        first=FIRST_UPDATE,
    )

    logger.info(
        "✅ Bot initialized"
    )

    logger.info(
        "⏰ Updates every 3 hours"
    )

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
                "Bot stopped."
            )

            break

        except KeyboardInterrupt:

            logger.info(
                "Bot stopped manually."
            )

            break

        except Conflict:

            logger.error(
                "🚨 409 CONFLICT detected."
            )

            logger.error(
                "Stop every other instance "
                "using this BOT_TOKEN."
            )

            # لا نعيد التشغيل بسرعة
            # لأن هذا لن يحل Conflict
            time.sleep(30)

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

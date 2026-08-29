import os
import re
import time
import asyncio
import logging
import requests

from telegram import Update
from telegram.error import (
    NetworkError,
    TimedOut,
    RetryAfter,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ==================================================
# CONFIG
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")

XE_URL = (
    "https://www.xe.com/currencyconverter/"
    "?Amount=1&From=USD&To=EUR"
)

UPDATE_INTERVAL = 3 * 60 * 60

# ==================================================
# LOGGING
# ==================================================

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


# ==================================================
# GET XE RATE
# ==================================================

def get_xe_rate():

    response = requests.get(
        XE_URL,
        timeout=(5, 10),
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
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

    match = re.search(
        r"1\s*USD\s*=\s*([0-9]+\.[0-9]+)\s*EUR",
        html,
        re.IGNORECASE,
    )

    if not match:
        raise ValueError(
            "XE rate not found"
        )

    usd_eur = float(match.group(1))

    if usd_eur <= 0:
        raise ValueError(
            "Invalid XE rate"
        )

    eur_usd = 1 / usd_eur

    return usd_eur, eur_usd


# ==================================================
# ASYNC XE REQUEST WITH RETRIES
# ==================================================

async def get_rate_with_retry():

    delays = [2, 5, 10]

    for attempt in range(1, 4):

        try:

            logger.info(
                "XE request attempt %s/3",
                attempt,
            )

            result = await asyncio.to_thread(
                get_xe_rate
            )

            logger.info(
                "XE request successful"
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
        "XE unavailable after 3 attempts"
    )


# ==================================================
# MESSAGE
# ==================================================

def make_message(
    usd_eur,
    eur_usd,
):

    return (
        f"🇺🇸 1 USD = {usd_eur:.6f} EUR\n"
        f"🇪🇺 1 EUR = {eur_usd:.6f} USD\n\n"
        "By LEX"
    )


# ==================================================
# SEND MESSAGE WITH RETRY
# ==================================================

async def safe_send_message(
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
                "Telegram message sent successfully"
            )

            return True

        except RetryAfter as e:

            logger.warning(
                "Telegram rate limit. Waiting %s seconds",
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
                "(attempt %s/3): %s",
                attempt,
                e,
            )

            if attempt < 3:
                await asyncio.sleep(
                    3 * attempt
                )

        except Exception as e:

            logger.exception(
                "Telegram send error: %s",
                e,
            )

            return False

    return False


# ==================================================
# AUTOMATIC PRICE
# ==================================================

async def send_price(
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.info(
        "========== PRICE UPDATE START =========="
    )

    try:

        usd_eur, eur_usd = (
            await get_rate_with_retry()
        )

        message = make_message(
            usd_eur,
            eur_usd,
        )

        success = await safe_send_message(
            context,
            GROUP_ID,
            message,
        )

        if success:

            logger.info(
                "✅ PRICE UPDATE SUCCESS | "
                "USD/EUR=%.6f",
                usd_eur,
            )

        else:

            logger.error(
                "❌ PRICE UPDATE FAILED"
            )

    except Exception as e:

        logger.exception(
            "❌ PRICE UPDATE ERROR: %s",
            e,
        )

    finally:

        logger.info(
            "========== PRICE UPDATE END =========="
        )


# ==================================================
# /START
# ==================================================

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


# ==================================================
# /PRICE
# ==================================================

async def price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.info(
        "/price command received"
    )

    try:

        usd_eur, eur_usd = (
            await get_rate_with_retry()
        )

        message = make_message(
            usd_eur,
            eur_usd,
        )

        await update.message.reply_text(
            message
        )

        logger.info(
            "✅ /price completed"
        )

    except Exception as e:

        logger.exception(
            "❌ /price failed: %s",
            e,
        )

        try:

            await update.message.reply_text(
                "❌ السعر غير متوفر حاليا.\n"
                "عاود بعد شوية."
            )

        except Exception:
            pass


# ==================================================
# ERROR HANDLER
# ==================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    error = context.error

    logger.exception(
        "Telegram application error: %s",
        error,
    )


# ==================================================
# RUN BOT
# ==================================================

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

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(20)
        .write_timeout(20)
        .pool_timeout(10)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "price",
            price,
        )
    )

    # Errors
    application.add_error_handler(
        error_handler
    )

    # Automatic price
    application.job_queue.run_repeating(
        send_price,
        interval=UPDATE_INTERVAL,
        first=10,
    )

    logger.info(
        "✅ Bot initialized"
    )

    logger.info(
        "⏰ Update interval: 3 hours"
    )

    logger.info(
        "🔄 First update: 10 seconds"
    )

    # Start Telegram
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# ==================================================
# AUTO RESTART
# ==================================================

def main():

    restart_delay = 10

    while True:

        try:

            run_bot()

            logger.warning(
                "⚠️ Bot stopped normally."
            )

            break

        except KeyboardInterrupt:

            logger.info(
                "🛑 Bot stopped manually."
            )

            break

        except Exception as e:

            logger.exception(
                "🔥 BOT CRASHED: %s",
                e,
            )

            logger.info(
                "♻️ Restarting in %s seconds...",
                restart_delay,
            )

            time.sleep(
                restart_delay
            )


# ==================================================
# START
# ==================================================

if __name__ == "__main__":
    main()

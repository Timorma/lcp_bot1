
import os
import json
import logging
import asyncio
from pathlib import Path
from datetime import time
from zoneinfo import ZoneInfo
from html import escape

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from fetcher import fetch_market_bundle
from analyzer import analyze_multitimeframe
from chart_drawer import generate_timeframe_chart


# ==============================
# ICB BOT CONFIGURATION
# ==============================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_USERNAME = "@ICBVO"
CAIRO_TZ = ZoneInfo("Africa/Cairo")

BASE_DIR = Path(__file__).resolve().parent
SYMBOLS_DIR = BASE_DIR / "symbols"

DAILY_REPORT_TIME = time(hour=3, minute=0, tzinfo=CAIRO_TZ)

DAILY_SYMBOLS = ["GOLD", "BTCUSDT"]

MAX_REPORT_LENGTH = 3900

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("ICB_BOT")


# ==============================
# SYMBOL CONFIGURATION
# ==============================

def load_json_file(filename):
    path = SYMBOLS_DIR / filename

    if not path.exists():
        logger.warning("Symbols file not found: %s", path)
        return {}

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        logger.exception("Cannot read symbols file: %s", filename)
        return {}


def normalize_symbol(symbol):
    return str(symbol).strip().upper().replace("/", "").replace(" ", "")


def load_symbol_configuration():
    forex_data = load_json_file("forex.json")
    crypto_data = load_json_file("crypto.json")

    aliases = forex_data.get("aliases", {})
    normalized_aliases = {}

    if isinstance(aliases, dict):
        for name, value in aliases.items():
            normalized_aliases[normalize_symbol(name)] = str(value).strip()

    crypto_symbols = set()

    def collect_crypto_symbols(data):
        if isinstance(data, str):
            value = normalize_symbol(data)
            if value:
                crypto_symbols.add(value)

        elif isinstance(data, list):
            for item in data:
                collect_crypto_symbols(item)

        elif isinstance(data, dict):
            for key, value in data.items():
                if key in ("provider", "category", "market_types", "quote_asset"):
                    continue

                if key == "symbols":
                    collect_crypto_symbols(value)
                elif isinstance(value, (dict, list)):
                    collect_crypto_symbols(value)
                elif isinstance(value, str):
                    collect_crypto_symbols(value)

    collect_crypto_symbols(crypto_data)

    return normalized_aliases, crypto_symbols


SYMBOL_ALIASES, CRYPTO_SYMBOLS = load_symbol_configuration()


def resolve_symbol(user_symbol):
    original = normalize_symbol(user_symbol)

    if not original:
        return None

    if original in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[original]

    if original in CRYPTO_SYMBOLS:
        return original

    if original.endswith("USDT"):
        return original

    return None


def refresh_symbols():
    global SYMBOL_ALIASES, CRYPTO_SYMBOLS
    SYMBOL_ALIASES, CRYPTO_SYMBOLS = load_symbol_configuration()


# ==============================
# SUBSCRIPTION CHECK
# ==============================

async def is_subscribed(user_id, context):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=user_id
        )

        return member.status in ("creator", "administrator", "member")

    except Exception:
        logger.exception("Subscription verification failed")
        return None


async def subscription_message(update):
    await update.effective_message.reply_text(
        "لاستخدام بوت ICB يجب الاشتراك في القناة أولاً:\n\n"
        "https://t.me/ICBVO\n\n"
        "بعد الاشتراك أرسل /start مرة أخرى."
    )


# ==============================
# ACCESS CONTROL
# ==============================

async def check_access(update, context):
    if not update.effective_user or not update.effective_message:
        return False

    result = await is_subscribed(
        update.effective_user.id,
        context
    )

    if result is True:
        return True

    if result is False:
        await subscription_message(update)
        return False

    await update.effective_message.reply_text(
        "تعذر التحقق من الاشتراك حالياً.\n"
        "حاول مرة أخرى بعد قليل."
    )

    return False


# ==============================
# REPORT HELPERS
# ==============================

def safe_value(value, default="غير متاح"):
    if value is None:
        return default

    try:
        if isinstance(value, float) and value != value:
            return default
    except Exception:
        pass

    return str(value)


def format_number(value):
    try:
        number = float(value)

        if abs(number) >= 1000:
            return f"{number:,.2f}"

        return f"{number:.5f}".rstrip("0").rstrip(".")

    except Exception:
        return safe_value(value)


def format_levels(levels, limit=5):
    if not isinstance(levels, list) or not levels:
        return "لا توجد مستويات كافية"

    lines = []

    for item in levels[:limit]:
        if isinstance(item, dict):
            price = item.get("price", item.get("level"))
            strength = item.get("strength", item.get("touches"))

            line = f"• {format_number(price)}"

            if strength is not None:
                line += f" | القوة: {safe_value(strength)}"

            lines.append(line)

        else:
            lines.append(f"• {format_number(item)}")

    return "\n".join(lines)


def format_group(group):
    if not isinstance(group, dict):
        return "غير متاح"

    direction = safe_value(
        group.get("direction", group.get("bias"))
    )

    agreement = group.get("agreement")

    result = f"الاتجاه الوصفي: {direction}"

    if agreement is not None:
        result += f"\nالتوافق: {safe_value(agreement)}"

    return result


def build_report(symbol, analysis):
    if not isinstance(analysis, dict):
        return "تعذر تكوين التقرير."

    summary = analysis.get("summary", {})

    if not isinstance(summary, dict):
        summary = {}

    price = format_number(
        summary.get("current_price_reference")
    )

    bias = safe_value(summary.get("bias"))
    confidence = summary.get("confidence")

    consensus = safe_value(
        summary.get("consensus_state")
    )

    main_direction = safe_value(
        summary.get("main_direction")
    )

    medium_direction = safe_value(
        summary.get("medium_direction")
    )

    short_direction = safe_value(
        summary.get("short_direction")
    )

    groups = summary.get("groups", {})

    if not isinstance(groups, dict):
        groups = {}

    report = [
        "📊 <b>ICB | MARKET RESEARCH</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"الأداة: <b>{escape(symbol)}</b>",
        f"السعر المرجعي: <b>{escape(price)}</b>",
        "",
        "🧠 <b>قراءة الهيكل العام</b>",
        f"الميل الوصفي: {escape(bias)}",
        f"حالة التوافق: {escape(consensus)}",
        ""
    ]

    if confidence is not None:
        report.append(
            f"قوة النموذج النسبية: {escape(safe_value(confidence))}"
        )
        report.append(
            "<i>هذه درجة تقييم داخلية وليست احتمالاً مضموناً.</i>"
        )
        report.append("")

    report.extend([
        "📌 <b>تحليل المجموعات الزمنية</b>",
        "",
        "🔵 <b>الرئيسي</b>",
        escape(format_group(groups.get("main", {}))),
        f"الاتجاه: {escape(main_direction)}",
        "",
        "🟡 <b>المتوسط</b>",
        escape(format_group(groups.get("medium", {}))),
        f"الاتجاه: {escape(medium_direction)}",
        "",
        "🟢 <b>القصير</b>",
        escape(format_group(groups.get("short", {}))),
        f"الاتجاه: {escape(short_direction)}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🧱 <b>مناطق الدعم</b>",
        escape(format_levels(summary.get("support", []))),
        "",
        "🧱 <b>مناطق المقاومة</b>",
        escape(format_levels(summary.get("resistance", []))),
        "",
        "━━━━━━━━━━━━━━━━━━",
        "<i>التقرير للدراسة وفهم بنية السوق فقط، "
        "ولا يمثل توصية شراء أو بيع.</i>",
        "",
        "<b>ICB | Institutional Code Breaker</b>"
    ])

    text = "\n".join(report)

    if len(text) > MAX_REPORT_LENGTH:
        text = text[:MAX_REPORT_LENGTH - 30] + "\n\n<i>تم اختصار التقرير.</i>"

    return text


# ==============================
# MARKET ANALYSIS ENGINE
# ==============================

async def run_analysis(symbol):
    logger.info("Starting analysis for %s", symbol)

    bundle = await asyncio.to_thread(
        fetch_market_bundle,
        symbol
    )

    if not bundle:
        raise ValueError("مصدر البيانات لم يرجع بيانات.")

    analysis = await asyncio.to_thread(
        analyze_multitimeframe,
        bundle
    )

    if not analysis:
        raise ValueError("تعذر تحليل البيانات.")

    return bundle, analysis


# ==============================
# SEND ANALYSIS
# ==============================

async def send_analysis(update, context, user_symbol):
    message = update.effective_message

    resolved = resolve_symbol(user_symbol)

    if not resolved:
        await message.reply_text(
            "الرمز غير موجود في ملفات الرموز الحالية.\n\n"
            "راجع symbols/forex.json أو symbols/crypto.json."
        )
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING
    )

    status_message = await message.reply_text(
        f"⏳ جاري جمع بيانات {user_symbol} وتحليل الأطر الزمنية..."
    )

    try:
        bundle, analysis = await run_analysis(resolved)

        report = build_report(user_symbol, analysis)

        await status_message.edit_text(
            report,
            parse_mode="HTML"
        )

        try:
            chart = await asyncio.to_thread(
                generate_timeframe_chart,
                bundle,
                analysis,
                user_symbol
            )

            if chart:
                if hasattr(chart, "seek"):
                    chart.seek(0)

                await message.reply_photo(
                    photo=chart,
                    caption=f"ICB | {user_symbol} | Market Structure"
                )

        except Exception:
            logger.exception("Chart generation failed")

    except Exception as error:
        logger.exception("Analysis failed for %s", user_symbol)

        await status_message.edit_text(
            "❌ تعذر إكمال التحليل.\n\n"
            f"التفاصيل: {escape(str(error)[:700])}\n\n"
            "راجع سجلات Railway لمعرفة مصدر المشكلة.",
            parse_mode="HTML"
        )


# ==============================
# START COMMAND
# ==============================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    await update.effective_message.reply_text(
        "🌋 <b>مرحباً بك في ICB</b>\n\n"
        "منصة بحث متعددة الأطر الزمنية.\n\n"
        "الأوامر المتاحة:\n"
        "/analyze GOLD - تحليل الذهب\n"
        "/analyze BTCUSDT - تحليل البيتكوين\n"
        "/symbols - عرض الرموز المتاحة\n"
        "/help - المساعدة\n\n"
        "أو أرسل الرمز مباشرة في رسالة.",
        parse_mode="HTML"
    )


# ==============================
# HELP COMMAND
# ==============================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    await update.effective_message.reply_text(
        "📘 <b>طريقة استخدام ICB</b>\n\n"
        "1. أرسل /analyze ثم اسم الأداة.\n"
        "2. انتظر جمع البيانات من المصادر.\n"
        "3. سيظهر التقرير متعدد الأطر الزمنية.\n"
        "4. قد يظهر الرسم البياني إذا توفرت بياناته.\n\n"
        "أمثلة:\n"
        "<code>/analyze GOLD</code>\n"
        "<code>/analyze BTCUSDT</code>\n\n"
        "التقارير مخصصة للبحث ودراسة حركة السوق.",
        parse_mode="HTML"
    )


# ==============================
# SYMBOLS COMMAND
# ==============================

async def symbols_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    refresh_symbols()

    forex_names = sorted(SYMBOL_ALIASES.keys())
    crypto_names = sorted(CRYPTO_SYMBOLS)

    lines = [
        "📚 <b>رموز ICB المتاحة</b>",
        "",
        "🟡 <b>العملات والسلع والمؤشرات</b>"
    ]

    lines.extend(f"• {escape(item)}" for item in forex_names[:60])

    lines.extend([
        "",
        "₿ <b>العملات الرقمية</b>"
    ])

    lines.extend(f"• {escape(item)}" for item in crypto_names[:60])

    if not forex_names and not crypto_names:
        lines.append("لم يتم العثور على رموز في ملفات JSON.")

    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode="HTML"
    )


# ==============================
# ANALYZE COMMAND
# ==============================

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "اكتب الرمز بعد الأمر.\n\n"
            "مثال:\n"
            "/analyze GOLD"
        )
        return

    symbol = context.args[0]
    await send_analysis(update, context, symbol)


# ==============================
# DIRECT SYMBOL MESSAGE
# ==============================

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    text_value = update.effective_message.text.strip()

    if not text_value or len(text_value.split()) != 1:
        return

    if text_value.startswith("/"):
        return

    refresh_symbols()

    if resolve_symbol(text_value):
        await send_analysis(update, context, text_value)


# ==============================
# DAILY REPORT
# ==============================

async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Starting ICB daily report")

    for symbol in DAILY_SYMBOLS:
        try:
            resolved = resolve_symbol(symbol)

            if not resolved:
                logger.warning("Daily symbol not configured: %s", symbol)
                continue

            bundle, analysis = await run_analysis(resolved)

            report = build_report(symbol, analysis)

            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=report,
                parse_mode="HTML"
            )

            chart = await asyncio.to_thread(
                generate_timeframe_chart,
                bundle,
                analysis,
                symbol
            )

            if chart:
                if hasattr(chart, "seek"):
                    chart.seek(0)

                await context.bot.send_photo(
                    chat_id=context.job.chat_id,
                    photo=chart,
                    caption=f"ICB Daily Research | {symbol}"
                )

        except Exception:
            logger.exception("Daily report failed for %s", symbol)


async def set_daily_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    chat_id = update.effective_chat.id

    if context.job_queue is None:
        await update.effective_message.reply_text(
            "ميزة التقارير المجدولة غير مفعلة. "
            "تأكد من تثبيت python-telegram-bot[job-queue]."
        )
        return

    existing = context.job_queue.get_jobs_by_name(
        f"daily_{chat_id}"
    )

    for job in existing:
        job.schedule_removal()

    context.job_queue.run_daily(
        daily_report,
        time=DAILY_REPORT_TIME,
        chat_id=chat_id,
        name=f"daily_{chat_id}",
        timezone=CAIRO_TZ
    )

    await update.effective_message.reply_text(
        "✅ تم تفعيل التقرير اليومي في هذه المحادثة.\n"
        "موعد الإرسال: 03:00 صباحاً بتوقيت القاهرة.\n"
        "الأدوات: الذهب والبيتكوين."
    )


# ==============================
# ERROR HANDLER
# ==============================

async def error_handler(update, context):
    logger.exception(
        "Telegram application error",
        exc_info=context.error
    )


# ==============================
# APPLICATION STARTUP
# ==============================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing from Railway Variables."
        )

    logger.info("Loading ICB symbol configuration")

    refresh_symbols()

    logger.info(
        "Loaded %s aliases and %s crypto symbols",
        len(SYMBOL_ALIASES),
        len(CRYPTO_SYMBOLS)
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start_command)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("symbols", symbols_command)
    )

    application.add_handler(
        CommandHandler("analyze", analyze_command)
    )

    application.add_handler(
        CommandHandler("daily", set_daily_report_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message_handler
        )
    )

    application.add_error_handler(error_handler)

    logger.info("ICB BOT IS STARTING")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()

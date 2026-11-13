import os
import json
import html
import logging
import asyncio
import time
from users import can_analyze, increment_usage
from pathlib import Path
from datetime import time as datetime_time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from fetcher import (
    fetch_market_bundle,
    TIMEFRAMES
)
from analyzer import analyze_multitimeframe
from ai_brain import (
    interpret_analysis,
    split_text,
    get_ai_status
)
from chart_drawer import generate_timeframe_chart

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("ICB")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")
CAIRO_TZ = ZoneInfo("Africa/Cairo")

BASE_DIR = Path(__file__).resolve().parent
SYMBOLS_DIR = BASE_DIR / "symbols"

MAX_REPORT_LENGTH = 3500
MAX_AI_CHUNK_LENGTH = 3000
REQUEST_TIMEOUT = 120
DAILY_REPORT_TIME = datetime_time(hour=3, minute=0, tzinfo=CAIRO_TZ)

DAILY_SYMBOLS = [
    item.strip().upper()
    for item in os.getenv("DAILY_SYMBOLS", "GOLD,BTCUSDT").split(",")
    if item.strip()
]

ACTIVE_REQUESTS = set()
ACTIVE_REQUESTS_LOCK = asyncio.Lock()

def escape_html(value):
    return html.escape(str(value or ""))

def safe_number(value, digits=4):
    try:
        number = float(value)
        if not __import__("math").isfinite(number):
            return "N/A"
        return f"{number:,.{digits}f}"
    except (TypeError, ValueError, OverflowError):
        return "N/A"

def load_json_file(filename):
    path = SYMBOLS_DIR / filename
    if not path.exists():
        logger.warning("Symbol file not found: %s", path)
        return {}
    try:
        with path.open("r", encoding="utf-8") as file:
            content = json.load(file)
        return content if isinstance(content, dict) else {}
    except Exception:
        logger.exception("Failed to load symbol file: %s", filename)
        return {}

def load_symbol_configuration():
    forex = load_json_file("forex.json")
    crypto = load_json_file("crypto.json")
    return {"forex": forex, "crypto": crypto}

SYMBOL_CONFIG = load_symbol_configuration()

def _collect_symbols(config):
    symbols = set()
    for category in ["forex", "crypto"]:
        data = config.get(category, {})
        if not isinstance(data, dict):
            continue
        for symbol in data.get("symbols", []):
            if isinstance(symbol, str):
                symbols.add(symbol.strip().upper())
        aliases = data.get("aliases", {})
        if isinstance(aliases, dict):
            symbols.update(str(alias).strip().upper() for alias in aliases.keys())
    forex_aliases = SYMBOL_CONFIG.get("forex", {}).get("aliases", {})
    if isinstance(forex_aliases, dict):
        symbols.update(str(alias).strip().upper() for alias in forex_aliases.keys())
    return symbols

SUPPORTED_SYMBOLS = _collect_symbols(SYMBOL_CONFIG)

def normalize_symbol(symbol):
    return str(symbol or "").strip().upper().replace("/", "")

def resolve_symbol(symbol):
    normalized = normalize_symbol(symbol)
    if not normalized:
        return None
    aliases = SYMBOL_CONFIG.get("forex", {}).get("aliases", {})
    if isinstance(aliases, dict):
        for alias, target in aliases.items():
            if str(alias).upper() == normalized:
                return normalized
    if normalized in SUPPORTED_SYMBOLS:
        return normalized
    if normalized.endswith("USDT") and normalized[:-4].isalnum():
        return normalized
    return None

def refresh_symbols():
    global SYMBOL_CONFIG
    global SUPPORTED_SYMBOLS
    SYMBOL_CONFIG = load_symbol_configuration()
    SUPPORTED_SYMBOLS = _collect_symbols(SYMBOL_CONFIG)
    return len(SUPPORTED_SYMBOLS)

def _format_levels(levels, limit=5):
    if not isinstance(levels, list) or not levels:
        return "غير متاحة"
    lines = []
    for level in levels[:limit]:
        if not isinstance(level, dict):
            continue
        price = safe_number(level.get("price"), 5)
        strength = safe_number(level.get("strength"), 2)
        lines.append(f"• {price} | القوة: {strength}")
    return "\n".join(lines) if lines else "غير متاحة"

def build_analysis_report(symbol, analysis):
    """تقرير مختصر يدعم الصفقة"""
    summary = analysis.get("summary", {})
    groups = analysis.get("groups", {})
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(groups, dict):
        groups = {}

    bias_names = {
        "bullish": "إيجابي",
        "bearish": "سلبي",
        "neutral": "محايد"
    }

    bias = bias_names.get(summary.get("bias", "neutral"), "غير محدد")

    lines = [
        f"📊 <b>ICB | تحليل {escape_html(symbol)}</b>",
        "",
        f"الحالة العامة: <b>{bias}</b>",
        f"الدرجة: <b>{safe_number(summary.get('score'), 4)}</b>",
        f"التغطية: <b>{safe_number(summary.get('coverage'), 2)}</b>",
        "",
        "━━━━━━━━━━━━━━━━",
        "🧭 <b>توافق الأطر</b>"
    ]

    for name, label in [("main", "الكبيرة"), ("medium", "المتوسطة"), ("short", "الصغيرة")]:
        group = groups.get(name, {})
        group_bias = bias_names.get(group.get("bias", "neutral"), "غير محدد")
        lines.append(
            f"{label}: <b>{group_bias}</b> | {safe_number(group.get('score'), 3)}"
        )

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━",
        "🟢 <b>الدعم</b>",
        _format_levels(summary.get("support"), 4),
        "",
        "🔴 <b>المقاومة</b>",
        _format_levels(summary.get("resistance"), 4),
        "",
        "<i>هذا تحليل بحثي. الصفقة التفصيلية في الرسالة التالية.</i>"
    ])

    report = "\n".join(lines)
    if len(report) > MAX_REPORT_LENGTH:
        report = report[:MAX_REPORT_LENGTH - 40] + "\n\n<i>تم اختصار التقرير.</i>"
    return report

async def run_analysis(symbol):
    normalized = resolve_symbol(symbol)
    if not normalized:
        raise ValueError("الرمز غير موجود في قائمة الأدوات المدعومة.")

    started = time.monotonic()

    bundle = await asyncio.wait_for(
        asyncio.to_thread(fetch_market_bundle, normalized, TIMEFRAMES),
        timeout=REQUEST_TIMEOUT
    )

    if not isinstance(bundle, dict):
        raise RuntimeError("مزود البيانات أعاد نتيجة غير صحيحة.")

    analysis = await asyncio.to_thread(analyze_multitimeframe, bundle)

    if not isinstance(analysis, dict) or not analysis.get("summary"):
        raise RuntimeError("محرك التحليل لم ينتج تقريرًا صالحًا.")

    elapsed = round(time.monotonic() - started, 2)

    return {
        "symbol": normalized,
        "bundle": bundle,
        "analysis": analysis,
        "elapsed_seconds": elapsed
    }

async def send_ai_report(message, analysis):
    try:
        ai_text = await asyncio.to_thread(interpret_analysis, analysis)
        chunks = split_text(ai_text, MAX_AI_CHUNK_LENGTH)
        for chunk in chunks:
            await message.reply_text(chunk, disable_web_page_preview=True)
    except Exception:
        logger.exception("AI report delivery failed")
        await message.reply_text(
            "تعذر إرسال التفسير النصي حالياً، لكن التقرير الحسابي متاح."
        )

async def send_chart(message, symbol, bundle, analysis):
    try:
        chart = await asyncio.to_thread(
            generate_timeframe_chart,
            symbol,
            bundle,
            analysis
        )
        if chart is None:
            await message.reply_text("تعذر إنشاء الرسم البياني.")
            return
        await message.reply_photo(
            photo=chart,
            caption=f"ICB | {symbol} | الرسم البحثي"
        )
    except Exception:
        logger.exception("Chart delivery failed")
        await message.reply_text("تعذر إنشاء الرسم البياني حالياً.")

async def send_analysis(update, symbol):
    message = update.effective_message
    if message is None:
        return

    normalized = resolve_symbol(symbol)
    if not normalized:
        await message.reply_text("الرمز غير مدعوم أو غير موجود في قائمة الأدوات.")
        return

    chat_id = update.effective_chat.id
    request_key = (chat_id, normalized)

    async with ACTIVE_REQUESTS_LOCK:
        if request_key in ACTIVE_REQUESTS:
            await message.reply_text("يوجد تحليل جارٍ لنفس الأداة. انتظر حتى ينتهي.")
            return
        ACTIVE_REQUESTS.add(request_key)

    status_message = None

    try:
        status_message = await message.reply_text(
            f"⏳ جارٍ تحليل {escape_html(normalized)}..."
        )

        await message.chat.send_action(ChatAction.TYPING)

        result = await run_analysis(normalized)

        report = build_analysis_report(normalized, result["analysis"])
        await status_message.edit_text(report, parse_mode="HTML")

        await send_ai_report(message, result["analysis"])
        await send_chart(message, normalized, result["bundle"], result["analysis"])

        logger.info(
            "Analysis completed for %s in %s seconds",
            normalized,
            result["elapsed_seconds"]
        )

    except asyncio.TimeoutError:
        if status_message:
            await status_message.edit_text("انتهت مهلة جلب البيانات. حاول مرة أخرى لاحقاً.")
    except Exception as error:
        logger.exception("Analysis failed for %s", normalized)
        if status_message:
            await status_message.edit_text(
                "تعذر إكمال التحليل: " + escape_html(str(error))[:800],
                parse_mode="HTML"
            )
        else:
            await message.reply_text("حدث خطأ أثناء التحليل.")
    finally:
        async with ACTIVE_REQUESTS_LOCK:
            ACTIVE_REQUESTS.discard(request_key)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(
        "مرحبًا بك في ICB Research Engine\n\n"
        "منظومة بحثية لتحليل الأسواق.\n\n"
        "الأوامر:\n"
        "/analyze BTCUSDT\n"
        "/symbols\n"
        "/status\n"
        "/help\n\n"
        "يمكنك إرسال الرمز مباشرة."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(
        "📘 ICB Research Engine\n\n"
        "أرسل:\n"
        "/analyze GOLD\n"
        "/analyze BTCUSDT\n\n"
        "أو أرسل الرمز مباشرة.\n\n"
        "الأوامر:\n"
        "/start\n"
        "/help\n"
        "/symbols\n"
        "/status"
    )

async def symbols_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None:
        return
    refresh_symbols()
    symbols = sorted(SUPPORTED_SYMBOLS)
    if not symbols:
        await message.reply_text("قائمة الأدوات غير متاحة.")
        return
    forex = []
    crypto = []
    for symbol in symbols:
        if symbol.endswith("USDT"):
            crypto.append(symbol)
        else:
            forex.append(symbol)
    lines = ["📚 ICB | الأدوات المدعومة", "", "العملات الرقمية:"]
    lines.extend(crypto[:80] or ["لا توجد."])
    lines.extend(["", "الفوركس والأسواق الأخرى:"])
    lines.extend(forex[:80] or ["لا توجد."])
    text = "\n".join(lines)
    for chunk in split_text(text, 3500):
        await message.reply_text(chunk)

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None:
        return
    if not context.args:
        await message.reply_text("اكتب الرمز بعد الأمر.\nمثال:\n/analyze BTCUSDT")
        return
    await send_analysis(update, context.args[0])

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or not message.text:
        return
    symbol = message.text.strip().split()[0]
    if symbol.startswith("/"):
        return
    if resolve_symbol(symbol):
        await send_analysis(update, symbol)
        return
    await message.reply_text(
        "لم أتعرف على الرمز.\nاستخدم /symbols لعرض الأدوات المدعومة."
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None:
        return
    ai_status = get_ai_status()
    symbols_count = len(SUPPORTED_SYMBOLS)
    lines = [
        "🧠 ICB | حالة النظام",
        "",
        "محرك البيانات: جاهز",
        "محرك التحليل: جاهز",
        "محرك الرسوم: جاهز",
        f"محرك الذكاء: {'مهيأ' if ai_status['configured'] else 'مفتاح API غير موجود'}",
        f"النموذج: {ai_status['model']}",
        f"عدد الأدوات: {symbols_count}",
    ]
    await message.reply_text("\n".join(lines))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    logger.error("Telegram application error: %s", type(error).__name__ if error else "Unknown")
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("حدث خطأ غير متوقع. حاول مرة أخرى.")
        except Exception:
            logger.exception("Could not send error notification")

async def post_init(application: Application):
    logger.info("ICB application initialized")
    logger.info("Loaded symbols: %s", len(SUPPORTED_SYMBOLS))

async def post_shutdown(application: Application):
    logger.info("ICB application shutting down")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is missing")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("symbols", symbols_command))
    application.add_handler(CommandHandler("analyze", analyze_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^[^/]"), text_handler))
    application.add_error_handler(error_handler)
    logger.info("Starting ICB Telegram Research Engine")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
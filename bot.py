import os
import logging
import asyncio

from datetime import time as clock_time
from zoneinfo import ZoneInfo

from telegram import Update, BotCommand

from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)

from openai import OpenAI

from fetcher import (
    fetch_market_bundle,
    TIMEFRAMES
)

from analyzer import analyze_multitimeframe

from chart_drawer import generate_timeframe_chart


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

CHANNEL_USERNAME = "@ICBVO"

CAIRO_TZ = ZoneInfo("Africa/Cairo")

DAILY_UPDATE_HOUR = 3
DAILY_UPDATE_MINUTE = 0


ai_client = None

if GROQ_API_KEY:
    ai_client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=GROQ_API_KEY
    )


AVAILABLE_MODELS = [
    os.getenv(
        "GROQ_MODEL",
        "openai/gpt-oss-20b"
    )
]


def is_symbol_supported(symbol):
    sym = symbol.strip().upper()

    known = {
        "XAUUSD",
        "GOLD",
        "XAGUSD",
        "SILVER",
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "AUDUSD",
        "USDCAD",
        "NZDUSD",
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "ADAUSDT",
        "XRPUSDT"
    }

    return (
        sym in known
        or (
            sym.endswith("USDT")
            and len(sym) >= 6
        )
    )


async def check_subscription(user_id, context):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception:
        logger.exception(
            "Subscription check failed"
        )

        return False


def _format_level(level):
    price = level.get("price")

    if price is None:
        return "غير متاح"

    frames = ", ".join(
        level.get("timeframes", [])[:6]
    ) or "غير محدد"

    return (
        f"{price:.8g} | "
        f"قوة تجميع: {level.get('strength', 0)} | "
        f"الفريمات: {frames}"
    )


def build_report(symbol, result, bundle):
    summary = result["summary"]

    lines = [
        f"📊 تقرير ICB البحثي — {symbol}",
        "",
        f"الخلاصة الزمنية: {summary.get('bias', 'غير محدد')}",
        (
            f"توازن الأدلة الموزونة: "
            f"{summary.get('confidence', 0)}% "
            f"(ليس احتمال نجاح)"
        ),
        (
            f"الفريمات المتاحة: "
            f"{summary.get('available_timeframes', 0)}/"
            f"{summary.get('requested_timeframes', len(TIMEFRAMES))}"
        ),
        (
            f"المرجع السعري من آخر إغلاق يومي/متاح: "
            f"{summary.get('current_price_reference', 'غير متاح')}"
        ),
        "",
        "🧭 توافق الفريمات:",
        (
            f"الصاعدة: "
            f"{', '.join(summary.get('bullish_timeframes', [])) or 'لا يوجد'}"
        ),
        (
            f"الهابطة: "
            f"{', '.join(summary.get('bearish_timeframes', [])) or 'لا يوجد'}"
        ),
        (
            f"التعارض: "
            f"{'موجود' if summary.get('conflict') else 'غير ظاهر'}"
        ),
        "",
        "🟢 أقوى مناطق الدعم المرصودة:"
    ]

    supports = summary.get(
        "support",
        []
    )

    lines.extend(
        [
            f"• {_format_level(x)}"
            for x in supports[:5]
        ] or [
            "• لا توجد مستويات كافية"
        ]
    )

    lines += [
        "",
        "🔴 أقوى مناطق المقاومة المرصودة:"
    ]

    resistances = summary.get(
        "resistance",
        []
    )

    lines.extend(
        [
            f"• {_format_level(x)}"
            for x in resistances[:5]
        ] or [
            "• لا توجد مستويات كافية"
        ]
    )

    lines += [
        "",
        "🕒 حالة الفريمات:"
    ]

    for tf in TIMEFRAMES:
        item = bundle.get(
            tf,
            {}
        )

        frame = result.get(
            "timeframes",
            {}
        ).get(tf)

        if frame:
            lines.append(
                f"• {tf}: {frame['bias']} | "
                f"توازن أدلة {frame['confidence']}% | "
                f"آخر شمعة {frame['last_time']}"
            )

        else:
            lines.append(
                f"• {tf}: غير متاح "
                f"({item.get('status', 'unknown')})"
            )

    warnings = summary.get(
        "warnings",
        []
    )

    if warnings:
        lines += [
            "",
            "⚠️ ملاحظات جودة البيانات والتعارض:"
        ]

        lines.extend(
            [
                f"• {w}"
                for w in warnings[:12]
            ]
        )

    lines += [
        "",
        "الخلاصة النهائية:",
        (
            "هذه قراءة بحثية مبنية على البيانات المتاحة وقت الفحص. "
            "تُعرض الاتجاهات والمستويات كاحتمالات وصفية وليست توصية "
            "بتنفيذ صفقة أو ضمانًا للمستقبل."
        )
    ]

    return "\n".join(lines)


def consult_ai_brain(report):
    if not ai_client:
        return (
            "التحليل الآلي النصي غير متصل؛ "
            "التقرير الرقمي متعدد الفريمات متاح أعلاه."
        )

    system_prompt = (
        "أنت مساعد بحثي لـ ICB. "
        "لخص التقرير المرفق فقط. "
        "لا تخترع أسعارًا أو فريمات أو مستويات. "
        "وضح التعارضات ونقص البيانات. "
        "لا تقدم أوامر شراء أو بيع أو نقاط دخول أو وقف خسارة "
        "أو أهداف تنفيذية. "
        "لا تصف درجة توازن الأدلة بأنها احتمال نجاح."
    )

    for model in AVAILABLE_MODELS:
        try:
            response = ai_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": report
                    }
                ],
                temperature=0.2,
                max_tokens=700,
                timeout=35
            )

            if (
                response.choices
                and response.choices[0].message.content
            ):
                return response.choices[0].message.content.strip()

        except Exception:
            logger.exception(
                "Groq model failed: %s",
                model
            )

    return (
        "تعذر الحصول على الملخص النصي من Groq؛ "
        "راجع التقرير الرقمي أعلاه."
    )


async def _run_analysis(symbol):
    bundle = await asyncio.to_thread(
        fetch_market_bundle,
        symbol
    )

    result = analyze_multitimeframe(bundle)

    report = build_report(
        symbol,
        result,
        bundle
    )

    ai_summary = await asyncio.to_thread(
        consult_ai_brain,
        report
    )

    chart = generate_timeframe_chart(
        bundle,
        result,
        symbol
    )

    return (
        bundle,
        result,
        report,
        ai_summary,
        chart
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    await update.message.reply_text(
        "🔥 أهلًا بك في ICB Research Engine\n\n"
        "يشترط الاشتراك في القناة أولًا:\n"
        "https://t.me/ICBVO\n\n"
        "أرسل رمزًا مثل XAUUSD أو BTCUSDT للحصول على تقرير "
        "متعدد الفريمات من الدقيقة حتى 144 يومًا، "
        "حسب توفر البيانات."
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id

    if not await check_subscription(
        user_id,
        context
    ):
        await update.message.reply_text(
            "🚀 يجب الانضمام إلى القناة الرسمية أولًا:\n"
            "https://t.me/ICBVO"
        )

        return

    text = update.message.text.strip()

    if (
        len(text.split()) == 1
        and is_symbol_supported(text)
    ):
        symbol = text.upper()

        status = await update.message.reply_text(
            f"⏳ جارٍ فحص الفريمات والبيانات المتاحة للأداة {symbol}..."
        )

        try:
            (
                bundle,
                result,
                report,
                ai_summary,
                chart
            ) = await _run_analysis(symbol)

            if chart is not None:
                await update.message.reply_photo(
                    photo=chart,
                    caption=(
                        f"ICB | {symbol}\n"
                        f"{result['summary']['bias']}\n"
                        f"الفريمات المتاحة: "
                        f"{result['summary']['available_timeframes']}/"
                        f"{result['summary']['requested_timeframes']}"
                    )
                )

            full_text = (
                report +
                "\n\n🧠 الملخص البحثي:\n" +
                ai_summary
            )

            for start_index in range(
                0,
                len(full_text),
                3900
            ):
                await update.message.reply_text(
                    full_text[
                        start_index:start_index + 3900
                    ]
                )

            await status.delete()

        except Exception:
            logger.exception(
                "User analysis failed for %s",
                symbol
            )

            await status.edit_text(
                "❌ حدث خطأ أثناء التحليل. راجع سجل Railway."
            )

        return

    await update.message.reply_text(
        "أرسل رمز أداة مدعوم مثل XAUUSD أو BTCUSDT "
        "للحصول على التقرير متعدد الفريمات."
    )


async def send_daily_updates(
    context: ContextTypes.DEFAULT_TYPE
):
    for symbol in (
        "XAUUSD",
        "BTCUSDT"
    ):
        try:
            (
                bundle,
                result,
                report,
                ai_summary,
                chart
            ) = await _run_analysis(symbol)

            daily = bundle.get(
                "1d",
                {}
            ).get("data")

            if daily is None or daily.empty:
                logger.warning(
                    "Daily candle unavailable; skipping %s",
                    symbol
                )

                continue

            if chart is not None:
                await context.bot.send_photo(
                    chat_id=CHANNEL_USERNAME,
                    photo=chart,
                    caption=(
                        f"🌅 تحديث ICB اليومي — {symbol}\n"
                        f"{result['summary']['bias']}\n"
                        "03:00 صباحًا بتوقيت القاهرة"
                    )
                )

            full_text = (
                report +
                "\n\n🧠 الملخص البحثي:\n" +
                ai_summary
            )

            for start_index in range(
                0,
                len(full_text),
                3900
            ):
                await context.bot.send_message(
                    chat_id=CHANNEL_USERNAME,
                    text=full_text[
                        start_index:start_index + 3900
                    ]
                )

        except Exception:
            logger.exception(
                "Daily update failed for %s",
                symbol
            )


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand(
            "start",
            "تشغيل البوت وعرض التعليمات"
        )
    ])

    job_queue = application.job_queue

    if job_queue:
        job_queue.run_daily(
            send_daily_updates,
            time=clock_time(
                hour=DAILY_UPDATE_HOUR,
                minute=DAILY_UPDATE_MINUTE,
                tzinfo=CAIRO_TZ
            ),
            name="icb_daily_market_report"
        )

        logger.info(
            "Daily reports scheduled for 03:00 Africa/Cairo"
        )

    else:
        logger.error(
            "Job queue unavailable; install python-telegram-bot[job-queue]"
        )


async def error_handler(update, context):
    logger.error(
        "Unhandled Telegram error",
        exc_info=context.error
    )


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is missing"
        )

        return

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_error_handler(
        error_handler
    )

    logger.info(
        "ICB Multi-Timeframe Bot starting"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
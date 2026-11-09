
import os
import json
import logging
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from fetcher import fetch_market_data
from analyzer import analyze_confluence
from chart_drawer import generate_chart
from openai import OpenAI

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CHANNEL_USERNAME = "@ICBVO"

ai_client = None

if GROQ_API_KEY:
    ai_client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=GROQ_API_KEY
    )

AVAILABLE_MODELS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b"
]


async def check_subscription(user_id, context):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=user_id
        )

        return member.status in [
            "member",
            "administrator",
            "creator"
        ]

    except Exception:
        logger.exception("Subscription check failed")
        return False


def is_symbol_supported(symbol):
    sym = symbol.strip().upper()
    symbols_dir = "symbols"

    if os.path.exists(symbols_dir):
        for filename in os.listdir(symbols_dir):
            if not filename.endswith(".json"):
                continue

            file_path = os.path.join(symbols_dir, filename)

            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    data = json.load(file)

                for key, values in data.items():
                    if isinstance(values, list):
                        if sym in [
                            str(value).upper()
                            for value in values
                        ]:
                            return True

                    elif isinstance(values, dict):
                        if sym in [
                            str(value).upper()
                            for value in values.keys()
                        ]:
                            return True

                        if sym in [
                            str(value).upper()
                            for value in values.values()
                        ]:
                            return True

            except Exception:
                logger.exception("Symbol file reading failed")

    known_symbols = [
        "XAUUSD",
        "GOLD",
        "GC=F",
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "AUDUSD",
        "USDCAD",
        "OIL",
        "WTI",
        "CL=F",
        "SI=F",
        "XAGUSD",
        "BTCUSDT",
        "ETHUSDT"
    ]

    return (
        sym in known_symbols
        or sym.endswith("=X")
        or sym.endswith("=F")
        or sym.startswith("^")
        or sym.endswith("USDT")
    )


def consult_ai_brain(user_query):
    if not ai_client:
        return "🧠 عقل الذكاء الاصطناعي غير متصل. تحقق من GROQ_API_KEY."

    system_prompt = (
        "أنت المحلل البحثي الرئيسي في Institutional Code Breaker ICB. "
        "حلل بيانات السوق المقدمة لك بعقلية بحثية مستقلة. "
        "استخدم حركة السعر والسيولة والقمم والقيعان والفتائل والتذبذب. "
        "لا تخترع أسعارًا أو بيانات غير موجودة. "
        "ميّز بين آخر إغلاق مسجل والسعر اللحظي. "
        "اذكر الأدلة التي تدعم قراءتك والأدلة التي تعارضها. "
        "لا تقدم يقينًا بشأن المستقبل."
    )

    for model_name in AVAILABLE_MODELS:
        try:
            response = ai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_query
                    }
                ],
                temperature=0.4,
                max_tokens=1000,
                timeout=30
            )

            if response and response.choices:
                answer = response.choices[0].message.content

                if answer:
                    return answer

        except Exception:
            logger.exception(
                "Groq model failed: %s",
                model_name
            )

    return "تعذر الاتصال بنماذج التحليل حاليًا."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "🔥 *أهلاً بك في العقل السيبراني لـ ICB*\n\n"
        "⚠️ اشترك في القناة لتفعيل البوت:\n"
        "https://t.me/ICBVO\n\n"
        "🤖 *طريقة الاستخدام:*\n"
        "1. أرسل رمز الأداة المالية مثل XAUUSD أو BTCUSDT.\n"
        "2. سيحاول البوت جلب البيانات وإنشاء الشارت.\n"
        "3. يمكنك أيضًا طرح أسئلة تحليلية واستفسارات."
    )

    await update.message.reply_text(
        welcome_msg,
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id

    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            "🚀 يجب الانضمام لقناتنا الرسمية أولاً:\n"
            "https://t.me/ICBVO"
        )
        return

    text = update.message.text.strip()
    words = text.split()
    symbol = text.upper()

    is_symbol_request = (
        len(words) == 1
        and words[0].isascii()
        and len(text) <= 10
        and is_symbol_supported(symbol)
    )

    if is_symbol_request:
        status_message = await update.message.reply_text(
            f"⏳ جارٍ جلب بيانات {symbol} والتحقق من الشارت..."
        )

        try:
            data = fetch_market_data(symbol)

            if data is None or data.empty:
                await status_message.edit_text(
                    f"❌ لم أتمكن من جلب بيانات صالحة للرمز {symbol}."
                )
                return

            analysis = analyze_confluence(data)

            if not isinstance(analysis, dict):
                raise ValueError("Invalid analyzer result")

            latest_time = data.index[-1]
            latest_close = float(data["Close"].iloc[-1])

            source = data.attrs.get(
                "source",
                "Unknown"
            )

            source_symbol = data.attrs.get(
                "source_symbol",
                symbol
            )

            ai_prompt = (
                f"الأداة: {symbol}\n"
                f"مصدر البيانات: {source}\n"
                f"رمز المصدر: {source_symbol}\n"
                f"الفريم: {data.attrs.get('interval', 'Unknown')}\n"
                f"وقت آخر شمعة: {latest_time}\n"
                f"آخر إغلاق مسجل: {latest_close}\n\n"
                f"بيانات آخر 20 شمعة:\n"
                f"{data.tail(20).to_string()}\n\n"
                "حلل السلوك والاتجاه والتذبذب والفتائل والسيولة. "
                "اذكر حدود البيانات، ولا تعتبر آخر إغلاق سعرًا لحظيًا."
            )

            ai_insight = consult_ai_brain(ai_prompt)

            chart_buf = generate_chart(data, analysis)

            if chart_buf is None:
                await status_message.edit_text(
                    "⚠️ البيانات والتحليل جاهزان، لكن إنشاء الشارت فشل. "
                    "راجع أخطاء chart_drawer.py في Railway."
                )
                return

            if hasattr(chart_buf, "seek"):
                chart_buf.seek(0)

            caption = (
                f"📊 *تحليل {symbol} - ICB*\n\n"
                f"🔹 الاتجاه: {analysis.get('bias', 'N/A')}\n"
                f"آخر إغلاق: {latest_close}\n"
                f"🕒 آخر شمعة: {latest_time}\n"
                f"📡 المصدر: {source}\n\n"
                f"🧠 *قراءة البيانات:*\n"
                f"{ai_insight[:700]}"
            )

            await update.message.reply_photo(
                photo=chart_buf,
                caption=caption,
                parse_mode="Markdown"
            )

            await status_message.delete()

        except Exception:
            logger.exception(
                "Symbol analysis or chart delivery failed"
            )

            try:
                await status_message.edit_text(
                    "❌ حدث خطأ أثناء التحليل أو إرسال الشارت. "
                    "راجع سجل Railway."
                )
            except Exception:
                logger.exception("Could not update status message")

        return

    await update.message.reply_text(
        "🧠 العقل السيبراني يحلل سؤالك..."
    )

    ai_reply = consult_ai_brain(text)

    await update.message.reply_text(ai_reply)


async def send_hourly_updates(context: ContextTypes.DEFAULT_TYPE):
    symbols_to_update = [
        "XAUUSD",
        "BTCUSDT"
    ]

    for symbol in symbols_to_update:
        try:
            data = fetch_market_data(symbol)

            if data is None or data.empty:
                logger.warning(
                    "No data available for hourly update: %s",
                    symbol
                )
                continue

            analysis = analyze_confluence(data)

            if not isinstance(analysis, dict):
                logger.error(
                    "Invalid analysis for %s",
                    symbol
                )
                continue

            chart_buf = generate_chart(data, analysis)

            if chart_buf is None:
                logger.error(
                    "Chart generation failed for %s",
                    symbol
                )
                continue

            if hasattr(chart_buf, "seek"):
                chart_buf.seek(0)

            latest_close = float(data["Close"].iloc[-1])
            latest_time = data.index[-1]

            caption = (
                f"⏰ *تحديث ICB الدوري*\n\n"
                f"📊 الأصل: {symbol}\n"
                f"🔹 الاتجاه: {analysis.get('bias', 'N/A')}\n"
                f"آخر إغلاق: {latest_close}\n"
                f"🕒 آخر شمعة: {latest_time}"
            )

            await context.bot.send_photo(
                chat_id=CHANNEL_USERNAME,
                photo=chart_buf,
                caption=caption,
                parse_mode="Markdown"
            )

        except Exception:
            logger.exception(
                "Hourly update failed for %s",
                symbol
            )


async def post_init(application):
    commands = [
        BotCommand(
            "start",
            "تشغيل البوت وعرض التعليمات"
        )
    ]

    await application.bot.set_my_commands(commands)

    job_queue = application.job_queue

    if job_queue:
        job_queue.run_repeating(
            send_hourly_updates,
            interval=3600,
            first=10
        )
    else:
        logger.error("Job queue is not available")


async def error_handler(update, context):
    logger.error(
        "Unhandled Telegram error",
        exc_info=context.error
    )


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing")
        return

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_error_handler(error_handler)

    logger.info("ICB Bot is starting")

    app.run_polling()


if __name__ == "__main__":
    main()

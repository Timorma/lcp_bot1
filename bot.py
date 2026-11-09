import os
import json
import logging
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from fetcher import fetch_market_data
from analyzer import analyze_confluence
from chart_drawer import generate_chart
from openai import OpenAI

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CHANNEL_USERNAME = "@ICBVO"

# تفعيل عقل الذكاء الاصطناعي عبر Groq
ai_client = None
if GROQ_API_KEY:
    ai_client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=GROQ_API_KEY
    )

async def check_subscription(user_id, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        logging.error(f"Error checking subscription for {user_id}: {e}")
        return False

def is_symbol_supported(symbol: str) -> bool:
    sym = symbol.strip().upper()
    symbols_dir = "symbols"
    
    if os.path.exists(symbols_dir):
        for filename in os.listdir(symbols_dir):
            if filename.endswith(".json"):
                file_path = os.path.join(symbols_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for key, values in data.items():
                            if isinstance(values, list):
                                if sym in [v.upper() for v in values]:
                                    return True
                            elif isinstance(values, dict):
                                if sym in [k.upper() for k in values.keys()] or sym in [str(v).upper() for v in values.values()]:
                                    return True
                except Exception:
                    continue
                    
    known_directs = ["XAUUSD", "GOLD", "GC=F", "EURUSD", "GBPUSD", "OIL", "WTI", "CL=F", "SI=F", "XAGUSD", "BTCUSDT"]
    if sym in known_directs or sym.endswith("=X") or sym.endswith("=F") or sym.startswith("^") or sym.endswith("USDT"):
        return True
        
    return False

def consult_ai_brain(user_query: str) -> str:
    """استدعاء العقل السيبراني الحقيقي من Groq"""
    if not ai_client:
        return "🧠 عقل الـ AI غير متصل حالياً (تأكد من GROQ_API_KEY)."
    
    system_prompt = (
        "أنت العقل التوجيهي والمحلل الرئيسي لمدرسة Institutional Code Breaker (ICB).\n"
        "لست مساعداً آلياً تقليدياً، بل خبير تداول مؤسسي ومحلل أسواق محنك.\n"
        "تتكلم بثقة، تفهم لغة المتحدث بعمق (سواء كانت فصحى أو عامية تداول)، وتغوص في سيولة صانع السوق، "
        "فريم 144 دقيقة، وأماكن تمركز عقود المؤسسات (Order Blocks & Liquidity Pools).\n"
        "أجب باحترافية، وكن محللاً ذكياً يفكر خارج الصندوق."
    )
    
    # قائمة موديلات Groq الحالية (نوفمبر 2026)
    available_models = [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b"
    ]
    
    for model_name in available_models:
        try:
            response = ai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                temperature=0.7,
                max_tokens=800
            )
            if response and response.choices:
                return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Failed with {model_name}: {e}")
            continue
            
    return "عذراً يا فنان، حدث خلل في الربط بالموديل. جرب مرة ثانية."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "🔥 **أهلاً بك في العقل السيبراني لـ Institutional Code Breaker (ICB)**\n\n"
        "⚠️ **تنبيه هام:** اشترك في قناتنا أولاً لتفعيل الطاقة الكاملة للبوت:\n"
        "https://t.me/ICBVO\n\n"
        "🤖 **طريقة التعامل:**\n"
        "1️⃣ اكتب أي رمز أصل مالي (مثل `XAUUSD`, `BTCUSDT`) لسحب الشارت وتحليله.\n"
        "2️⃣ ناقشني في أي استراتيجية أو سيولة وسأرد عليك كمحلل مؤسسي محترف!"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    is_subscribed = await check_subscription(user_id, context)
    if not is_subscribed:
        await update.message.reply_text(
            f"🚀 عذراً، يجب الانضمام لقناتنا الرسمية أولاً لتفعيل البوت:\n"
            f"https://t.me/ICBVO"
        )
        return

    text = update.message.text.strip()
    words = text.split()
    symbol = text.upper()
    
    is_symbol_request = (len(words) == 1 and words[0].isascii() and len(text) <= 10) or is_symbol_supported(symbol)

    if is_symbol_request and not any(c in text for c in [' ', '؟', '?', 'اشرح', 'كيف', 'ما', 'ليه', 'رايك']):
        await update.message.reply_text(f"⏳ جارِ استخراج شارت {symbol} وغوص العقل المؤسسي في السيولة...")
        try:
            data = fetch_market_data(symbol)
            if data is not None and not data.empty:
                analysis = analyze_confluence(data)
                ai_insight = consult_ai_brain(f"قدم قراءة تحليلية عميقة لاتجاه وسلوك سعر رمز {symbol} بناءً على البيانات الحالية.")
                chart_buf = generate_chart(data, analysis)
                
                if chart_buf is not None:
                    if hasattr(chart_buf, 'seek'):
                        chart_buf.seek(0)
                    
                    caption = (
                        f"📊 **تحليل سيولة {symbol} - ICB Framework**\n\n"
                        f"🔹 الاتجاه: {analysis.get('bias', 'N/A')}\n"
                        f"🎯 منطقة الدخول: {analysis.get('entry', 'N/A')}\n"
                        f"🛑 وقف الخسارة: {analysis.get('sl', 'N/A')}\n"
                        f"🎯 الأهداف: {analysis.get('tp', 'N/A')}\n\n"
                        f"🧠 **قراءة العقل المؤسسي:**\n{ai_insight[:500]}"
                    )
                    await update.message.reply_photo(photo=chart_buf, caption=caption, parse_mode='Markdown')
                    return
        except Exception as e:
            logging.error(f"Analysis error: {e}")

    await update.message.reply_text("🧠 العقل السيبراني يحلل أبعاد سؤالك...")
    ai_reply = consult_ai_brain(text)
    await update.message.reply_text(ai_reply)

async def send_hourly_updates(context: ContextTypes.DEFAULT_TYPE):
    symbols_to_update = ["XAUUSD", "BTCUSDT"]
    for symbol in symbols_to_update:
        try:
            data = fetch_market_data(symbol)
            if data is not None and not data.empty:
                analysis = analyze_confluence(data)
                chart_buf = generate_chart(data, analysis)
                if chart_buf is not None:
                    if hasattr(chart_buf, 'seek'):
                        chart_buf.seek(0)
                    caption = (
                        f"⏰ **التحديث الساعي المؤسسي - ICB**\n"
                        f"📊 **الأصل:** {symbol}\n\n"
                        f"🔹 الاتجاه: {analysis.get('bias', 'N/A')}\n"
                        f"🎯 الدخول: {analysis.get('entry', 'N/A')}\n"
                        f"🛑 الوقف: {analysis.get('sl', 'N/A')}\n"
                        f"🎯 الهدف: {analysis.get('tp', 'N/A')}"
                    )
                    await context.bot.send_photo(chat_id=CHANNEL_USERNAME, photo=chart_buf, caption=caption, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Error in hourly update for {symbol}: {e}")

async def post_init(application):
    commands = [("start", "تشغيل البوت السيبراني وعرض التوجيهات")]
    await application.bot.set_my_commands([BotCommand(cmd, desc) for cmd, desc in commands])
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(send_hourly_updates, interval=3600, first=10)

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is missing!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    
    # حل آمن 100% بدون استخدام علامة \~
    text_filter = filters.TEXT & filters.COMMAND.__invert__()
    app.add_handler(MessageHandler(text_filter, handle_message))
    
    print("Cyber-Bot with Groq AI is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
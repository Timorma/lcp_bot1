import os
import json
import logging
import traceback
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from fetcher import fetch_market_data
from analyzer import analyze_confluence
from chart_drawer import generate_chart
from google import genai

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHANNEL_USERNAME = "@ICBVO"

# إعداد محرك الذكاء الاصطناعي
ai_client = None
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)

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
    """استشارة نموذج جوجل للذكاء الاصطناعي للإجابة على الأسئلة أو تحليل السوق"""
    if not ai_client:
        return "🧠 نموذج الذكاء الاصطناعي غير متصل (يرجى التأكد من إضافة GEMINI_API_KEY في Railway)."
    
    system_prompt = (
        "أنت مساعد ذكي ومحترف مخصص لمدرسة وتطبيق Institutional Code Breaker (ICB).\n"
        "تتخصص في تحليل الأسواق المالية وفق سيولة المؤسسات، صانع السوق، فريم 144 دقيقة، ومناطق Order Blocks.\n"
        "أجب عن أسئلة المستخدم بأسلوب دقيق، احترافي، وواضح باللغة العربية."
    )
    
    # تجربة الموديلات المتاحة تلقائياً لتجنب أي خطأ
    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-flash"]
    
    for model_name in models_to_try:
        try:
            response = ai_client.models.generate_content(
                model=model_name,
                contents=f"{system_prompt}\n\nطلب المستخدم: {user_query}"
            )
            if response and response.text:
                return response.text
        except Exception as e:
            logging.error(f"AI Error with model {model_name}: {e}")
            continue
            
    return "عذراً، حدث خطأ في معالجة طلب الذكاء الاصطناعي. يجدر التأكد من صحة وصلاحية مفتاح الـ API."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "👋 أهلاً بك في بوت Institutional Code Breaker - ICB\n\n"
        "⚠️ **تنبيه هام:** يجب الانضمام لقناتنا الرسمية أولاً لتفعيل البوت واستخدام أدوات التحليل:\n"
        "https://t.me/ICBVO\n\n"
        "🤖 **طريقة الاستخدام:**\n"
        "1️⃣ أرسل رمز أي أصل مالي (مثل: `XAUUSD`, `BTCUSDT`) للحصول على الشارت وتحليل السيولة.\n"
        "2️⃣ أرسل أي سؤال أو استفسار عن التداول والاستراتيجية وسيرد عليك الذكاء الاصطناعي فوراً!"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    is_subscribed = await check_subscription(user_id, context)
    if not is_subscribed:
        await update.message.reply_text(
            f"🚀 عذراً، لا يمكنك استخدام البوت إلا بعد الانضمام إلى قناتنا الرسمية أولاً:\n"
            f"https://t.me/ICBVO\n\n"
            f"انضم للقناة ثم أرسل الطلب مجدداً!"
        )
        return

    text = update.message.text.strip()
    words = text.split()
    symbol = text.upper()
    
    # 🎯 التمييز الذكي: هل النص رمز مالي أم سؤال عام؟
    is_symbol_request = (len(words) == 1 and words[0].isascii() and len(text) <= 10) or is_symbol_supported(symbol)

    if is_symbol_request and not any(c in text for c in [' ', '؟', '?', 'اشرح', 'كيف', 'ما', 'لماذا']):
        await update.message.reply_text(f"⏳ جاري تحليل {symbol} وحساب السيولة والمستويات عبر عقل ICB...")
        try:
            data = fetch_market_data(symbol)
            if data is not None and not data.empty:
                analysis = analyze_confluence(data)
                ai_insight = consult_ai_brain(f"قدم رؤية مؤسسية مختصرة لاتجاه رمز {symbol}.")
                chart_buf = generate_chart(data, analysis)
                
                if chart_buf is not None:
                    if hasattr(chart_buf, 'seek'):
                        chart_buf.seek(0)
                    
                    caption = (
                        f"📊 **تحليل {symbol} - ICB Framework**\n\n"
                        f"🔹 الاتجاه: {analysis.get('bias', 'N/A')}\n"
                        f"🎯 منطقة الدخول: {analysis.get('entry', 'N/A')}\n"
                        f"🛑 وقف الخسارة: {analysis.get('sl', 'N/A')}\n"
                        f"🎯 الأهداف: {analysis.get('tp', 'N/A')}\n\n"
                        f"🧠 **رؤية العقل المؤسسي:**\n{ai_insight[:300]}"
                    )
                    await update.message.reply_photo(photo=chart_buf, caption=caption, parse_mode='Markdown')
                    return
        except Exception as e:
            logging.error(f"Analysis error: {e}")

    # 🧠 إذا كان سؤالاً نصياً أو جملة عربية، يتم توجيهه لعقل الذكاء الاصطناعي مباشرة
    await update.message.reply_text("🧠 جاري التفكير والإجابة عبر عقل الذكاء الاصطناعي...")
    ai_reply = consult_ai_brain(text)
    await update.message.reply_text(ai_reply)

async def send_hourly_updates(context: ContextTypes.DEFAULT_TYPE):
    """وظيفة أوتوماتيكية يتم تشغيلها كل ساعة لإرسال تحديثات الذهب والبيتكوين للقناة"""
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
                        f"⏰ **تحديث تلقائي كل ساعة - ICB Framework**\n"
                        f"📊 **الأصل:** {symbol}\n\n"
                        f"🔹 الاتجاه: {analysis.get('bias', 'N/A')}\n"
                        f"🎯 منطقة الدخول: {analysis.get('entry', 'N/A')}\n"
                        f"🛑 وقف الخسارة: {analysis.get('sl', 'N/A')}\n"
                        f"🎯 الأهداف: {analysis.get('tp', 'N/A')}"
                    )
                    await context.bot.send_photo(chat_id=CHANNEL_USERNAME, photo=chart_buf, caption=caption, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Error in hourly update for {symbol}: {e}")

async def post_init(application):
    commands = [
        ("start", "بدء تشغيل بوت ICB وعرض التعليمات"),
    ]
    await application.bot.set_my_commands([BotCommand(cmd, desc) for cmd, desc in commands])
    
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(send_hourly_updates, interval=3600, first=10)

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is missing!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is running with AI Chat & Automated Updates...")
    app.run_polling()

if __name__ == '__main__':
    main()

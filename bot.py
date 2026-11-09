import os
import json
import logging
import traceback
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from fetcher import fetch_market_data
from analyzer import analyze_confluence
from chart_drawer import generate_chart

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_USERNAME = "@ICBVO"

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

def consult_ai_brain(user_query: str):
    strategy_rules = (
        "قواعد استراتيجية ICB (Institutional Code Breaker):\n"
        "- الاعتماد على فريم 144 دقيقة لدراسة الدورات المؤسسية وحركة صانع السوق.\n"
        "- تتبع الصفقات غير المكتملة ومناطق السيولة المتمثلة في Order Blocks.\n"
        "- دمج تحليل الفوليوم (Volume Profile) لتحديد نقاط الانعكاس بدقة."
    )
    return f"🧠 تحليل عقل ICB المؤسسي لطلبك ('{user_query}'):\n{strategy_rules}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "👋 أهلاً بك في بوت Institutional Code Breaker - ICB\n\n"
        "⚠️ **تنبيه هام:** يجب الانضمام لقناتنا الرسمية أولاً لتفعيل البوت واستخدام أدوات التحليل:\n"
        "https://t.me/ICBVO\n\n"
        "بعد الانضمام، أرسل اسم أي أداة مالية (مثل: XAUUSD, BTCUSDT) للحصول على:\n"
        "1️⃣ جلب بيانات وحركة السوق الحية على فريم 144 دقيقة\n"
        "2️⃣ تحليل السيولة المؤسسية وإستراتيجية ICB\n"
        "3️⃣ رسم الشارت مع مستويات الدخول، وقف الخسارة، والأهداف"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def handle_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    is_subscribed = await check_subscription(user_id, context)
    if not is_subscribed:
        await update.message.reply_text(
            f"🚀 عذراً، لا يمكنك استخدام البوت إلا بعد الانضمام إلى قناتنا الرسمية أولاً:\n"
            f"https://t.me/ICBVO\n\n"
            f"انضم للقناة ثم أرسل اسم العملة مجدداً لتفعيل التحليل!"
        )
        return

    symbol = update.message.text.strip().upper()
    
    if not is_symbol_supported(symbol) and not symbol.endswith("USDT") and "=" not in symbol:
        await update.message.reply_text(f"⚠️ تنبيه: الرمز '{symbol}' قد غير مسجل في القوائم الرسمية، ولكن جاري محاولة جلب بياناته...")

    await update.message.reply_text(f"⏳ جاري تحليل {symbol} وحساب السيولة والمستويات عبر عقل ICB...")
    
    try:
        data = fetch_market_data(symbol)
        
        if data is None or data.empty:
            await update.message.reply_text(f"❌ لم يتم العثور على بيانات لـ {symbol}. تأكد من صحة الرمز.")
            return
        
        analysis = analyze_confluence(data)
        ai_insight = consult_ai_brain(f"تحليل الرمز {symbol}")
        chart_buf = generate_chart(data, analysis)
        
        if chart_buf is None:
            await update.message.reply_text("❌ حدث خطأ أثناء رسم الشارت.")
            return

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
        
    except Exception as e:
        err_details = traceback.format_exc()
        logging.error(f"Detailed Error: {err_details}")
        await update.message.reply_text(f"⚠️ خطأ تقني أثناء المعالجة:\n{str(e)[:200]}")

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
    """تعيين أوامر البوت وجدولة التحديثات التلقائية كل ساعة (3600 ثانية)"""
    commands = [
        ("start", "بدء تشغيل بوت ICB وعرض التعليمات"),
    ]
    await application.bot.set_my_commands([BotCommand(cmd, desc) for cmd, desc in commands])
    
    # جدولة المهمة التلقائية (كل 3600 ثانية = ساعة) مع تأخير 10 ثوانٍ لبدء التشغيل
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(send_hourly_updates, interval=3600, first=10)

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is missing!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_analysis))
    print("Bot is running with automated hourly updates & ICB Integration...")
    app.run_polling()

if __name__ == '__main__':
    main()

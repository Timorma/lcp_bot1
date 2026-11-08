import os
import logging
import io
import traceback
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from fetcher import fetch_market_data
from analyzer import analyze_confluence
from chart_drawer import generate_chart

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "👋 أهلاً بك في بوت Institutional Code Breaker - ICB\n\n"
        "أرسل اسم أي أداة مالية (مثل: XAUUSD, BTCUSD) للحصول على:\n"
        "1️⃣ جلب بيانات وحركة السوق الحية\n"
        "2️⃣ إجراء تحليل متكامل (CRT، جان، العرض والطلب)\n"
        "3️⃣ رسم الشارت مع مستويات الدخول، وقف الخسارة، والأهداف"
    )
    await update.message.reply_text(welcome_msg)

async def handle_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.strip().upper()
    await update.message.reply_text(f"⏳ جاري تحليل {symbol} وحساب السيولة والمستويات...")
    try:
        data = fetch_market_data(symbol)
        if data is None or data.empty:
            await update.message.reply_text(f"❌ لم يتم العثور على بيانات لـ {symbol}")
            return
        
        analysis = analyze_confluence(data)
        chart_buf = generate_chart(data, analysis)
        
        if not chart_buf:
            await update.message.reply_text("❌ حدث خطأ أثناء رسم الشارت.")
            return

        if hasattr(chart_buf, 'seek'):
            chart_buf.seek(0)
        
        caption = (
            f"📊 **تحليل {symbol} - ICB Framework**\n\n"
            f"🔹 الاتجاه: {analysis.get('bias', 'N/A')}\n"
            f"🎯 منطقة الدخول: {analysis.get('entry', 'N/A')}\n"
            f"🛑 وقف الخسارة: {analysis.get('sl', 'N/A')}\n"
            f"🎯 الأهداف: {analysis.get('tp', 'N/A')}"
        )
        await update.message.reply_photo(photo=chart_buf, caption=caption, parse_mode='Markdown')
    except Exception as e:
        err_details = traceback.format_exc()
        logging.error(f"Detailed Error handling analysis: {err_details}")
        await update.message.reply_text(f"❌ خطأ تقني: {str(e)}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is missing!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_analysis))
    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()

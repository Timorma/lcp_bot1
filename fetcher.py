import pandas as pd
import yfinance as yf

def fetch_market_data(symbol: symbol if 'symbol' in locals() else str):
    # ضبط رمز العملة لتوافق منصة بينانس (إضافة USDT لو مش موجودة)
    sym = symbol.strip().upper()
    if not sym.endswith("USDT") and not sym.endswith("USD"):
        sym = sym + "USDT"
        
    try:
        # سحب بيانات الساعة لآخر 60 يوم لتكوين فريم 144 دقيقة حقيقي ودقيق
        df = yf.download(sym, period="60d", interval="1h", progress=False)
        
        if df is None or df.empty:
            # تجربة إضافية لو الرمز بدون USDT
            if sym.endswith("USDT"):
                df = yf.download(symbol.strip().upper(), period="60d", interval="1h", progress=False)
        
        if df is None or df.empty:
            return None
            
        # تنظيف أعمدة الـ MultiIndex لو وجدت
        if hasattr(df.columns, 'levels') or isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # إعادة تجميع الشموع إلى فريم 144 دقيقة (144 دقيقة = ساعتين و 24 دقيقة / تقريبًا كل 2.4 شمعة ساعة)
        df = df.resample('144min').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
        
        return df
    except Exception as e:
        print(f"Error fetching data for {sym}: {e}")
        return None

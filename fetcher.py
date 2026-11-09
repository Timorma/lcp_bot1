import pandas as pd
import yfinance as yf

def fetch_market_data(symbol: str):
    sym = symbol.strip().upper()
    
    # تنسيق الرمز ليتوافق مع Yahoo Finance (مثال: BTC يتحول إلى BTC-USD أو BTCUSDT)
    if not sym.endswith("USDT") and not sym.endswith("USD"):
        search_symbols = [f"{sym}-USD", f"{sym}USDT", sym]
    else:
        search_symbols = [sym]
        if sym.endswith("USDT"):
            search_symbols.append(sym.replace("USDT", "-USD"))

    df = None
    for s in search_symbols:
        try:
            # سحب بيانات حية لفريم الساعة لآخر 60 يوم
            temp_df = yf.download(s, period="60d", interval="1h", progress=False)
            if temp_df is not None and not temp_df.empty:
                df = temp_df
                break
        except Exception:
            continue
            
    if df is None or df.empty:
        return None
        
    # تنظيف أعمدة الـ MultiIndex لو وجدت
    if hasattr(df.columns, 'levels') or isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    # التأكد من وجود أعمدة الأسعار الأساسية
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not all(col in df.columns for col in required_cols):
        return None

    try:
        # إعادة تجميع الشموع إلى فريم 144 دقيقة الحقيقي
        df = df.resample('144min').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
    except Exception as e:
        print(f"Resample error: {e}")
        
    return df

import json
import os
import pandas as pd
import yfinance as yf

def fetch_market_data(symbol: str):
    sym = symbol.strip().upper()
    
    # قائمة الرموز البديلة والمباشرة للذهب والسلع لضمان جلب البيانات فوراً
    symbols_to_try = [sym]
    
    if sym in ["XAUUSD", "GOLD", "GC", "GC=F"]:
        symbols_to_try = ["GC=F", "GOLD", "IAU", "GLD"]
    elif sym in ["XAGUSD", "SILVER", "SI", "SI=F"]:
        symbols_to_try = ["SI=F", "SLV"]
    elif sym in ["OIL", "WTI", "CL", "CL=F"]:
        symbols_to_try = ["CL=F", "BZ=F"]
    elif "/" in sym:
        clean_sym = sym.replace("/", "") + "=X"
        symbols_to_try = [clean_sym, sym.replace("/", "-")]
    elif len(sym) == 6 and not sym.endswith("USDT") and not sym.endswith("USD"):
        symbols_to_try = [sym + "=X", sym]
    else:
        if not sym.endswith("USDT") and not sym.startswith("^"):
            symbols_to_try = [f"{sym}USDT", f"{sym}-USD", sym]

    df = None
    for s in symbols_to_try:
        try:
            # محاولة سحب البيانات لكل رمز محتمل
            df = yf.download(s, period="14d", interval="1h", progress=False)
            if df is not None and not df.empty:
                break
        except Exception:
            continue

    if df is None or df.empty:
        return None

    try:
        if hasattr(df.columns, 'levels') or isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_cols):
            return None

        # إعادة التجميع لفريم 144 دقيقة المؤسسي
        df = df.resample('144min').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
        
        return df if not df.empty else None
    except Exception as e:
        print(f"Error processing data for {symbol}: {e}")
        return None

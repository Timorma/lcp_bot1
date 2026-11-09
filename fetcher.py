import json
import os
import pandas as pd
import yfinance as yf

def load_aliases():
    alias_path = "symbols/asset_aliases.json"
    if os.path.exists(alias_path):
        try:
            with open(alias_path, "r", encoding="utf-8") as f:
                return json.load(f).get("aliases", {})
        except Exception:
            pass
    return {}

def fetch_market_data(symbol: str):
    sym = symbol.strip().upper()
    
    # تحميل قاموس المرادفات
    aliases = load_aliases()
    if sym in aliases:
        sym = aliases[sym]
    elif "/" in sym:
        sym = sym.replace("/", "") + "=X"
    elif len(sym) == 6 and not sym.endswith("USDT") and not sym.endswith("USD") and not sym.endswith("=X") and not sym.endswith("=F"):
        sym = sym + "=X"
    elif not sym.endswith("USDT") and not sym.endswith("USD") and not sym.startswith("^") and not sym.endswith("=F") and not sym.endswith("=X"):
        sym = f"{sym}USDT"

    df = None
    try:
        # محاولة أولى بسحب البيانات لفترة أطول قليلاً
        df = yf.download(sym, period="30d", interval="1h", progress=False)
        
        # لو فشلت وفوركس، جرب نضيف "=X"
        if (df is None or df.empty) and not sym.endswith("=X") and len(sym) == 6:
            df = yf.download(sym + "=X", period="30d", interval="1h", progress=False)
            
        # لو فشلت وكانت عملة رقمية، جرب -USD بدلاً من USDT
        if (df is None or df.empty) and "USDT" in sym:
            df = yf.download(sym.replace("USDT", "-USD"), period="30d", interval="1h", progress=False)

        if df is None or df.empty:
            return None
            
        if hasattr(df.columns, 'levels') or isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # التأكد من وجود أعمدة الأسعار الأساسية
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
        
        return df
    except Exception as e:
        print(f"Error fetching {sym}: {e}")
        return None

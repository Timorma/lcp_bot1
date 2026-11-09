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
    
    # تحميل قاموس المرادفات للتعامل مع اختلاف مسميات البروكرات
    aliases = load_aliases()
    if sym in aliases:
        sym = aliases[sym]
    
    # المعالجة التلقائية لبقية الأصول (الفوركس والعملات الرقمية)
    elif "/" in sym:
        sym = sym.replace("/", "") + "=X"
    elif len(sym) == 6 and not sym.endswith("USDT") and not sym.endswith("USD") and not sym.endswith("=X") and not sym.endswith("=F"):
        sym = sym + "=X"
    elif not sym.endswith("USDT") and not sym.endswith("USD") and not sym.startswith("^") and not sym.endswith("=F") and not sym.endswith("=X") and not sym.endswith("=BZ"):
        sym = f"{sym}USDT"

    try:
        df = yf.download(sym, period="60d", interval="1h", progress=False)
        
        # محاولة احتياطية للعملات الرقمية لو الـ USDT مشغلش معاه
        if (df is None or df.empty) and not sym.endswith("-USD") and "USDT" in sym:
            df = yf.download(sym.replace("USDT", "-USD"), period="60d", interval="1h", progress=False)

        if df is None or df.empty:
            return None
            
        if hasattr(df.columns, 'levels') or isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
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

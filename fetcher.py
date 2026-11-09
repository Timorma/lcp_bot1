import pandas as pd
import yfinance as yf

def fetch_market_data(symbol: str):
    sym = symbol.strip().upper()
    
    # تحديد الرمز بناءً على نوع السوق (الذهب، النفط، العملات، أو الفوركس)
    if sym in ["XAUUSD", "GOLD", "GC"]:
        sym = "GC=F"
    elif sym in ["XAGUSD", "SILVER", "SI"]:
        sym = "SI=F"
    elif sym in ["OIL", "BRENT", "WTI", "CL"]:
        sym = "CL=F"
    elif "/" in sym:
        sym = sym.replace("/", "") + "=X"
    elif len(sym) == 6 and not sym.endswith("USDT") and not sym.endswith("USD"):
        sym = sym + "=X"
    elif not sym.endswith("USDT") and not sym.endswith("USD") and not sym.startswith("^") and not sym.endswith("=F"):
        sym = f"{sym}-USD"

    try:
        df = yf.download(sym, period="60d", interval="1h", progress=False)
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

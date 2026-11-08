def analyze_confluence(df):
    try:
        last_close = float(df['Close'].iloc[-1])
        mean_price = float(df['Close'].mean())
        
        bias = "Bullish 🟢" if last_close > mean_price else "Bearish 🔴"
        
        entry = round(last_close, 2)
        sl = round(entry * 0.99, 2) if "Bullish" in bias else round(entry * 1.01, 2)
        tp = round(entry * 1.02, 2) if "Bullish" in bias else round(entry * 0.98, 2)
        
        return {
            "bias": bias,
            "entry": entry,
            "sl": sl,
            "tp": tp
        }
    except Exception:
        return {
            "bias": "Neutral ⚪",
            "entry": 0.0,
            "sl": 0.0,
            "tp": 0.0
        }

def analyze_confluence(df):
    last_close = df['Close'].iloc[-1]
    high = df['High'].max()
    low = df['Low'].min()
    
    bias = "Bullish 🟢" if last_close > df['Close'].mean() else "Bearish 🔴"
    
    entry = round(last_close, 2)
    sl = round(entry * 0.99, 2) if "Bullish" in bias else round(entry * 1.01, 2)
    tp = round(entry * 1.02, 2) if "Bullish" in bias else round(entry * 0.98, 2)
    
    return {
        "bias": bias,
        "entry": entry,
        "sl": sl,
        "tp": tp
    }

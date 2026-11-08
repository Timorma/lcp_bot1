import yfinance as yf

def fetch_market_data(symbol: str):
    # Mapping common symbols
    ticker_map = {
        "XAUUSD": "GC=F",
        "GOLD": "GC=F",
        "BTCUSD": "BTC-USD",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X"
    }
    target_symbol = ticker_map.get(symbol, symbol)
    try:
        ticker = yf.Ticker(target_symbol)
        df = ticker.history(period="1mo", interval="1d")
        if df.empty:
            return None
        return df
    except Exception:
        return None

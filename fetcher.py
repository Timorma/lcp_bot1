import yfinance as yf

def fetch_market_data(symbol: str):
    symbol = symbol.strip().upper()
    ticker_map = {
        "XAUUSD": "GC=F",
        "GOLD": "GC=F",
        "BTCUSD": "BTC-USD",
        "BTC": "BTC-USD",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X"
    }
    target_symbol = ticker_map.get(symbol, symbol)
    try:
        ticker = yf.Ticker(target_symbol)
        df = ticker.history(period="5d", interval="1d")
        if df.empty:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="5d", interval="1d")
        if df.empty:
            return None
        return df
    except Exception:
        return None


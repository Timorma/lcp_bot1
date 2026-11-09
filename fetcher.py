
import os
import logging
import requests
import pandas as pd

logger = logging.getLogger(__name__)

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

TD_INTERVALS = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "45m": "45min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "8h": "8h",
    "1d": "1day",
    "1w": "1week",
    "1mo": "1month"
}

BINANCE_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1d",
    "3d": "3d",
    "1w": "1w",
    "1mo": "1M"
}


def normalize_symbol(symbol):
    sym = str(symbol).strip().upper().replace(" ", "")

    aliases = {
        "GOLD": "XAU/USD",
        "XAUUSD": "XAU/USD",
        "SILVER": "XAG/USD",
        "XAGUSD": "XAG/USD",
        "EURUSD": "EUR/USD",
        "GBPUSD": "GBP/USD",
        "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD",
        "USDCAD": "USD/CAD",
        "NZDUSD": "NZD/USD"
    }

    return aliases.get(sym, sym)


def validate_data(df):
    if df is None or df.empty:
        return None

    required = ["Open", "High", "Low", "Close"]

    if not all(col in df.columns for col in required):
        return None

    df = df.copy()

    if "Volume" not in df.columns:
        df["Volume"] = 0

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required)
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    valid = (
        (df["Open"] > 0) &
        (df["High"] >= df["Low"]) &
        (df["High"] >= df["Open"]) &
        (df["High"] >= df["Close"]) &
        (df["Low"] <= df["Open"]) &
        (df["Low"] <= df["Close"])
    )

    df = df.loc[valid]

    if len(df) < 20:
        return None

    return df[["Open", "High", "Low", "Close", "Volume"]]


def fetch_binance(symbol, interval, limit):
    sym = str(symbol).strip().upper().replace("/", "")

    if sym.endswith("USD") and not sym.endswith("USDT"):
        sym = sym[:-3] + "USDT"

    if not sym.endswith("USDT") and not sym.endswith("BTC") and not sym.endswith("ETH") and not sym.endswith("BNB"):
        return None

    if interval not in BINANCE_INTERVALS:
        return None

    params = {
        "symbol": sym,
        "interval": BINANCE_INTERVALS[interval],
        "limit": min(max(int(limit), 20), 1000)
    }

    try:
        response = requests.get(
            BINANCE_URL,
            params=params,
            timeout=15
        )

        response.raise_for_status()
        rows = response.json()

        if not isinstance(rows, list) or not rows:
            return None

        columns = [
            "Time",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "CloseTime",
            "QuoteVolume",
            "Trades",
            "TakerBuyVolume",
            "TakerBuyQuoteVolume",
            "Ignore"
        ]

        raw = pd.DataFrame(rows, columns=columns)

        raw["Time"] = pd.to_datetime(
            raw["Time"],
            unit="ms",
            utc=True
        )

        raw = raw.set_index("Time")

        result = raw[["Open", "High", "Low", "Close", "Volume"]].copy()

        result = validate_data(result)

        if result is not None:
            result.attrs["source"] = "Binance Public API"
            result.attrs["source_symbol"] = sym
            result.attrs["interval"] = interval

        return result

    except Exception:
        logger.exception("Binance data request failed")
        return None


def fetch_twelve_data(symbol, interval, limit):
    api_key = os.getenv("TWELVE_DATA_API_KEY")

    if not api_key:
        logger.warning("TWELVE_DATA_API_KEY is missing")
        return None

    if interval not in TD_INTERVALS:
        logger.warning("Unsupported Twelve Data interval: %s", interval)
        return None

    sym = normalize_symbol(symbol)

    params = {
        "symbol": sym,
        "interval": TD_INTERVALS[interval],
        "outputsize": min(max(int(limit), 20), 5000),
        "timezone": "UTC",
        "order": "ASC",
        "apikey": api_key
    }

    try:
        response = requests.get(
            TWELVE_DATA_URL,
            params=params,
            timeout=20
        )

        response.raise_for_status()
        payload = response.json()

        if payload.get("status") == "error":
            logger.warning(
                "Twelve Data error: %s",
                payload.get("message", "Unknown error")
            )
            return None

        values = payload.get("values")

        if not values:
            logger.warning("No Twelve Data values for %s", sym)
            return None

        df = pd.DataFrame(values)

        required = ["datetime", "open", "high", "low", "close"]

        if not all(col in df.columns for col in required):
            return None

        df["datetime"] = pd.to_datetime(
            df["datetime"],
            utc=True,
            errors="coerce"
        )

        df = df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        })

        if "Volume" not in df.columns:
            df["Volume"] = 0

        df = df.set_index("datetime")

        df = validate_data(df)

        if df is not None:
            df.attrs["source"] = "Twelve Data"
            df.attrs["source_symbol"] = sym
            df.attrs["interval"] = interval

        return df

    except Exception:
        logger.exception("Twelve Data request failed")
        return None


def fetch_market_data(symbol, period=None, interval="1h", limit=500):
    sym = str(symbol).strip().upper()

    if not sym:
        logger.warning("Empty symbol received")
        return None

    if interval not in TD_INTERVALS:
        logger.warning("Unsupported interval: %s", interval)
        return None

    logger.info(
        "Fetching %s | interval=%s | limit=%s",
        sym,
        interval,
        limit
    )

    crypto_candidate = (
        sym.endswith("USDT") or
        sym.endswith("USD") or
        "/" in sym
    )

    if crypto_candidate:
        binance_data = fetch_binance(sym, interval, limit)

        if binance_data is not None:
            binance_data.attrs["requested_symbol"] = sym
            logger.info(
                "Loaded %s rows from Binance",
                len(binance_data)
            )
            return binance_data

    td_data = fetch_twelve_data(sym, interval, limit)

    if td_data is not None:
        td_data.attrs["requested_symbol"] = sym
        logger.info(
            "Loaded %s rows from Twelve Data",
            len(td_data)
        )
        return td_data

    logger.error("All market data sources failed for %s", sym)
    return None

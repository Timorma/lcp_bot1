
import os
import logging
import requests
import pandas as pd
import yfinance as yf

from datetime import datetime, timezone
from urllib.parse import quote

logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://data-api.binance.vision/api/v3/klines"
TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

TIMEFRAMES = [
    "1m", "3m", "5m", "15m", "30m", "45m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1mo", "45d", "90d", "144d"
]

BINANCE_INTERVALS = {
    "1m": "1m",
    "3m": "3m",
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
    "1w": "1w",
    "1mo": "1M"
}

TWELVE_INTERVALS = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "45m": "45min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1day",
    "1w": "1week",
    "1mo": "1month"
}

YAHOO_INTERVALS = {
    "1m": "1m",
    "3m": "5m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "45m": "30m",
    "1h": "60m",
    "2h": "60m",
    "4h": "60m",
    "6h": "60m",
    "8h": "60m",
    "12h": "60m",
    "1d": "1d",
    "1w": "1wk",
    "1mo": "1mo"
}

YAHOO_PERIODS = {
    "1m": "7d",
    "3m": "60d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "45m": "60d",
    "1h": "730d",
    "2h": "730d",
    "4h": "730d",
    "6h": "730d",
    "8h": "730d",
    "12h": "730d",
    "1d": "max",
    "1w": "max",
    "1mo": "max"
}

SYMBOL_ALIASES = {
    "GOLD": "GC=F",
    "XAUUSD": "GC=F",
    "GC": "GC=F",
    "XAU": "GC=F",
    "SILVER": "SI=F",
    "XAGUSD": "SI=F",
    "SI": "SI=F",
    "XAG": "SI=F",
    "OIL": "CL=F",
    "CRUDE": "CL=F",
    "WTI": "CL=F",
    "CL": "CL=F",
    "BRENT": "BZ=F",
    "BZ": "BZ=F",
    "SPX": "^GSPC",
    "SP500": "^GSPC",
    "S&P500": "^GSPC",
    "GSPC": "^GSPC",
    "NASDAQ": "^IXIC",
    "NSQ": "^IXIC",
    "IXIC": "^IXIC",
    "DOW": "^DJI",
    "DJI": "^DJI"
}

YAHOO_SYMBOLS = set(SYMBOL_ALIASES.values())


def _normalize_symbol(symbol):
    value = str(symbol).strip().upper()
    return SYMBOL_ALIASES.get(value, value)


def _utc_now():
    return pd.Timestamp.now(tz="UTC")


def _normalize_dataframe(data):
    if data is None or not isinstance(data, pd.DataFrame):
        return None
    if data.empty:
        return None

    data = data.copy()
    data.columns = [str(col).capitalize() for col in data.columns]

    required = ["Open", "High", "Low", "Close"]
    if any(col not in data.columns for col in required):
        return None

    if "Volume" not in data.columns:
        data["Volume"] = float("nan")

    for column in required + ["Volume"]:
        data[column] = pd.to_numeric(
            data[column],
            errors="coerce"
        )

    data = data.dropna(subset=required)
    data = data[~data.index.duplicated(keep="last")]
    data = data.sort_index()

    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index, utc=True)

    if data.index.tz is None:
        data.index = data.index.tz_localize("UTC")
    else:
        data.index = data.index.tz_convert("UTC")

    return data[required + ["Volume"]]


def _validate_data(data, symbol, timeframe):
    data = _normalize_dataframe(data)

    if data is None:
        logger.warning(
            "No valid data for %s on %s",
            symbol,
            timeframe
        )
        return None

    if len(data) < 20:
        logger.warning(
            "Insufficient data for %s on %s: %s rows",
            symbol,
            timeframe,
            len(data)
        )
        return None

    return data


def _drop_incomplete_fixed_bars(data, timeframe):
    if data is None or data.empty:
        return data

    now = _utc_now()

    if timeframe.endswith("d") and timeframe[:-1].isdigit():
        days = int(timeframe[:-1])
        cutoff = now.floor("D")
        data = data[data.index + pd.Timedelta(days=days) <= cutoff]

    elif timeframe == "1w":
        week_start = now.normalize() - pd.Timedelta(days=now.weekday())
        data = data[data.index + pd.Timedelta(days=7) <= week_start]

    elif timeframe == "1mo":
        current_month = now.normalize().replace(day=1)
        data = data[data.index < current_month]

    return data


def _fetch_binance(symbol, timeframe, limit=1000):
    interval = BINANCE_INTERVALS.get(timeframe)

    if interval is None:
        return None

    rows = []
    end_time = None
    max_pages = 5 if timeframe in ("1d", "1w", "1mo") else 1

    try:
        for _ in range(max_pages):
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": min(limit, 1000)
            }

            if end_time is not None:
                params["endTime"] = end_time

            response = requests.get(
                BINANCE_BASE_URL,
                params=params,
                timeout=20
            )

            response.raise_for_status()
            batch = response.json()

            if not isinstance(batch, list) or not batch:
                break

            rows = batch + rows
            oldest_time = batch[0][0]
            end_time = oldest_time - 1

            if len(batch) < 1000:
                break

        if not rows:
            return None

        columns = [
            "OpenTime",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "CloseTime",
            "QuoteVolume",
            "Trades",
            "TakerBuyBase",
            "TakerBuyQuote",
            "Ignore"
        ]

        data = pd.DataFrame(rows, columns=columns)

        data["Date"] = pd.to_datetime(
            data["OpenTime"],
            unit="ms",
            utc=True
        )

        data = data.set_index("Date")

        return data[[
            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
        ]]

    except Exception:
        logger.exception(
            "Binance fetch failed for %s %s",
            symbol,
            timeframe
        )
        return None


def _fetch_twelve_data(symbol, timeframe, outputsize=5000):
    interval = TWELVE_INTERVALS.get(timeframe)

    if interval is None or not TWELVE_DATA_API_KEY:
        return None

    try:
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": TWELVE_DATA_API_KEY,
            "format": "JSON",
            "timezone": "UTC"
        }

        response = requests.get(
            TWELVE_DATA_URL,
            params=params,
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        if not isinstance(result, dict) or "values" not in result:
            logger.warning(
                "Twelve Data response for %s: %s",
                symbol,
                result.get("message", result.get("code", "Invalid response"))
                if isinstance(result, dict)
                else "Invalid response"
            )
            return None

        data = pd.DataFrame(result["values"])

        if data.empty:
            return None

        data["datetime"] = pd.to_datetime(
            data["datetime"],
            utc=True
        )

        data = data.set_index("datetime")
        data.index.name = "Date"

        return data

    except Exception:
        logger.exception(
            "Twelve Data fetch failed for %s %s",
            symbol,
            timeframe
        )
        return None


def _fetch_yahoo(symbol, timeframe):
    interval = YAHOO_INTERVALS.get(timeframe)
    period = YAHOO_PERIODS.get(timeframe)

    if interval is None or period is None:
        return None

    try:
        ticker = yf.Ticker(symbol)

        data = ticker.history(
            period=period,
            interval=interval,
            auto_adjust=False,
            actions=False
        )

        if data is None or data.empty:
            return None

        data = data.copy()

        if data.index.tz is None:
            data.index = data.index.tz_localize("UTC")
        else:
            data.index = data.index.tz_convert("UTC")

        return data

    except Exception:
        logger.exception(
            "Yahoo Finance fetch failed for %s %s",
            symbol,
            timeframe
        )
        return None


def _resample_data(data, timeframe):
    if data is None or data.empty:
        return None

    rules = {
        "3d": "3D",
        "45d": "45D",
        "90d": "90D",
        "144d": "144D"
    }

    rule = rules.get(timeframe)

    if rule is None:
        return None

    try:
        aggregation = {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": lambda values: values.sum(min_count=1)
        }

        result = data.resample(
            rule,
            origin="epoch",
            label="left",
            closed="left"
        ).agg(aggregation)

        result = result.dropna(subset=["Open", "High", "Low", "Close"])
        result = _drop_incomplete_fixed_bars(result, timeframe)

        return result

    except Exception:
        logger.exception(
            "Resampling failed for timeframe %s",
            timeframe
        )
        return None


def _fetch_source(symbol, timeframe, source):
    if source == "binance":
        return _fetch_binance(symbol, timeframe)

    if source == "yfinance":
        return _fetch_yahoo(symbol, timeframe)

    if source == "twelvedata":
        return _fetch_twelve_data(symbol, timeframe)

    return None


def _get_source(symbol):
    if symbol in YAHOO_SYMBOLS or "=" in symbol or symbol.startswith("^"):
        return "yfinance"

    if symbol.endswith("USDT"):
        return "binance"

    return "twelvedata"


def fetch_timeframe(symbol, timeframe):
    symbol = _normalize_symbol(symbol)

    if timeframe not in TIMEFRAMES:
        logger.warning("Unsupported timeframe: %s", timeframe)
        return None

    source = _get_source(symbol)

    if timeframe in ("3d", "45d", "90d", "144d"):
        daily = _fetch_source(symbol, "1d", source)

        if daily is None:
            return None

        daily = _normalize_dataframe(daily)

        if daily is None:
            return None

        result = _resample_data(daily, timeframe)
        return _validate_data(result, symbol, timeframe)

    if source == "binance" and timeframe not in BINANCE_INTERVALS:
        if timeframe == "45m":
            base = _fetch_binance(symbol, "15m")
            if base is not None:
                result = base.resample("45min").agg({
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    "Volume": lambda values: values.sum(min_count=1)
                })
                return _validate_data(result, symbol, timeframe)
        return None

    if source == "yfinance" and timeframe in ("3m", "45m", "2h", "4h", "6h", "8h", "12h"):
        base_timeframe = "5m" if timeframe == "3m" else "30m" if timeframe == "45m" else "1h"
        base = _fetch_yahoo(symbol, base_timeframe)
        if base is None:
            return None

        rules = {
            "3m": "3min",
            "45m": "45min",
            "2h": "2h",
            "4h": "4h",
            "6h": "6h",
            "8h": "8h",
            "12h": "12h"
        }

        result = base.resample(rules[timeframe]).agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": lambda values: values.sum(min_count=1)
        })

        return _validate_data(result, symbol, timeframe)

    data = _fetch_source(symbol, timeframe, source)

    if data is None and source == "twelvedata":
        logger.warning(
            "No Twelve Data result for %s %s",
            symbol,
            timeframe
        )
        return None

    data = _validate_data(data, symbol, timeframe)

    if data is None:
        return None

    data = _drop_incomplete_fixed_bars(data, timeframe)

    return _validate_data(data, symbol, timeframe)


def fetch_market_bundle(symbol, timeframes=None):
    symbol = _normalize_symbol(symbol)
    requested = list(timeframes or TIMEFRAMES)

    bundle = {}
    daily_cache = None

    for timeframe in requested:
        try:
            if timeframe in ("3d", "45d", "90d", "144d"):
                if daily_cache is None:
                    daily_cache = fetch_timeframe(symbol, "1d")

                if daily_cache is None:
                    bundle[timeframe] = {"data": None, "error": "Daily data unavailable"}
                    continue

                result = _resample_data(daily_cache, timeframe)
                result = _validate_data(result, symbol, timeframe)

            else:
                result = fetch_timeframe(symbol, timeframe)

                if timeframe == "1d" and result is not None:
                    daily_cache = result

            bundle[timeframe] = {
                "data": result,
                "error": None if result is not None else "Data unavailable"
            }

        except Exception as exc:
            logger.exception(
                "Bundle fetch failed for %s %s",
                symbol,
                timeframe
            )
            bundle[timeframe] = {
                "data": None,
                "error": str(exc)
            }

    return bundle


def fetch_market_data(symbol, timeframe="1d"):
    return fetch_timeframe(symbol, timeframe)

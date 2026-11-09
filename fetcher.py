import os
import logging
import time
from typing import Dict, Optional, Tuple
import requests
import pandas as pd

logger = logging.getLogger(__name__)

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

TIMEFRAMES = [
    "1m", "3m", "5m", "15m", "30m", "45m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1mo",
    "45d", "90d", "144d"
]

BINANCE_INTERVALS = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h",
    "6h": "6h", "8h": "8h", "12h": "12h", "1d": "1d",
    "3d": "3d", "1w": "1w", "1mo": "1M"
}

TWELVE_INTERVALS = {
    "1m": "1min", "3m": "3min", "5m": "5min",
    "15m": "15min", "30m": "30min", "45m": "45min",
    "1h": "1h", "2h": "2h", "4h": "4h",
    "1d": "1day", "1w": "1week", "1mo": "1month"
}

DEFAULT_LIMITS = {
    "1m": 500, "3m": 500, "5m": 500, "15m": 500,
    "30m": 500, "45m": 500, "1h": 500, "2h": 500,
    "4h": 500, "6h": 500, "8h": 500, "12h": 500,
    "1d": 5000, "3d": 500, "1w": 400, "1mo": 240,
    "45d": 240, "90d": 180, "144d": 120
}

CRYPTO_QUOTES = ("USDT", "BTC", "ETH", "BNB")

SYMBOL_ALIASES = {
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


def normalize_symbol(symbol: str) -> str:
    sym = str(symbol).strip().upper().replace(" ", "")
    return SYMBOL_ALIASES.get(sym, sym)


def is_crypto_symbol(symbol: str) -> bool:
    sym = str(symbol).strip().upper().replace("/", "")
    return sym.endswith(CRYPTO_QUOTES) and len(sym) >= 6


def _validate_data(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None

    required = ["Open", "High", "Low", "Close"]

    if not all(c in df.columns for c in required):
        return None

    data = df.copy()

    if "Volume" not in data.columns:
        data["Volume"] = float("nan")

    for col in required + ["Volume"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    data = data.dropna(subset=required)
    data = data[~data.index.duplicated(keep="last")]
    data = data.sort_index()

    valid = (
        (data["Open"] > 0) &
        (data["High"] >= data["Low"]) &
        (data["High"] >= data["Open"]) &
        (data["High"] >= data["Close"]) &
        (data["Low"] <= data["Open"]) &
        (data["Low"] <= data["Close"])
    )

    data = data.loc[valid, required + ["Volume"]]

    return data if len(data) >= 20 else None


def _drop_incomplete_fixed_bars(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    durations = {
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
        "1d": "1d",
        "3d": "3d",
        "45d": "45d",
        "90d": "90d",
        "144d": "144d"
    }

    if df is None or df.empty:
        return df

    now = pd.Timestamp.now(tz="UTC")

    if interval == "1w":
        return df.loc[
            (df.index + pd.Timedelta(days=7)) <= now
        ]

    if interval == "1mo":
        next_month = df.index + pd.offsets.MonthBegin(1)
        return df.loc[next_month <= now]

    if interval not in durations:
        return df

    delta = pd.Timedelta(durations[interval])

    return df.loc[
        (df.index + delta) <= now
    ]


def _fetch_binance(symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    if interval not in BINANCE_INTERVALS:
        return None

    sym = str(symbol).strip().upper().replace("/", "")

    params = {
        "symbol": sym,
        "interval": BINANCE_INTERVALS[interval],
        "limit": min(max(int(limit), 20), 1000)
    }

    rows = []

    if interval == "1d" and int(limit) > 1000:
        end_time = None
        remaining = min(int(limit), 5000)

        while remaining > 0:
            page_params = dict(params)
            page_params["limit"] = min(remaining, 1000)

            if end_time is not None:
                page_params["endTime"] = end_time

            response = requests.get(
                BINANCE_KLINES_URL,
                params=page_params,
                timeout=25
            )

            response.raise_for_status()
            page = response.json()

            if not isinstance(page, list) or not page:
                break

            rows = page + rows
            remaining -= len(page)
            end_time = int(page[0][0]) - 1

            if len(page) < page_params["limit"]:
                break

    else:
        response = requests.get(
            BINANCE_KLINES_URL,
            params=params,
            timeout=20
        )

        response.raise_for_status()
        rows = response.json()

    if not isinstance(rows, list) or not rows:
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
        "TakerBuyVolume",
        "TakerBuyQuoteVolume",
        "Ignore"
    ]

    raw = pd.DataFrame(rows, columns=columns)

    raw["OpenTime"] = pd.to_datetime(
        raw["OpenTime"],
        unit="ms",
        utc=True
    )

    raw = raw.set_index("OpenTime")

    result = _validate_data(
        raw[["Open", "High", "Low", "Close", "Volume"]]
    )

    if result is None:
        return None

    result = _drop_incomplete_fixed_bars(result, interval)

    if result is None or len(result) < 20:
        return None

    result.attrs.update({
        "source": "Binance Public API",
        "source_symbol": sym,
        "interval": interval,
        "volume_available": True
    })

    return result


def _fetch_twelve(symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    api_key = os.getenv("TWELVE_DATA_API_KEY")

    if not api_key or interval not in TWELVE_INTERVALS:
        return None

    sym = normalize_symbol(symbol)

    params = {
        "symbol": sym,
        "interval": TWELVE_INTERVALS[interval],
        "outputsize": min(max(int(limit), 20), 5000),
        "timezone": "UTC",
        "order": "ASC",
        "apikey": api_key
    }

    response = requests.get(
        TWELVE_DATA_URL,
        params=params,
        timeout=25
    )

    response.raise_for_status()
    payload = response.json()

    if payload.get("status") == "error" or not payload.get("values"):
        logger.warning(
            "Twelve Data response for %s/%s: %s",
            sym,
            interval,
            payload.get("message", "no values")
        )
        return None

    raw = pd.DataFrame(payload["values"])

    required = [
        "datetime",
        "open",
        "high",
        "low",
        "close"
    ]

    if not all(c in raw.columns for c in required):
        return None

    raw["datetime"] = pd.to_datetime(
        raw["datetime"],
        utc=True,
        errors="coerce"
    )

    raw = raw.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    })

    if "Volume" not in raw.columns:
        raw["Volume"] = float("nan")

    raw = raw.dropna(subset=["datetime"])
    raw = raw.set_index("datetime")

    result = _validate_data(
        raw[["Open", "High", "Low", "Close", "Volume"]]
    )

    if result is None:
        return None

    result = _drop_incomplete_fixed_bars(result, interval)

    if result is None or len(result) < 20:
        return None

    result.attrs.update({
        "source": "Twelve Data",
        "source_symbol": sym,
        "interval": interval,
        "volume_available": bool(result["Volume"].notna().any())
    })

    return result


def _resample_daily(daily: pd.DataFrame, days: int) -> Optional[pd.DataFrame]:
    if daily is None or daily.empty:
        return None

    rule = f"{days}D"

    agg = daily.resample(
        rule,
        origin="epoch",
        label="left",
        closed="left"
    ).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna(
        subset=["Open", "High", "Low", "Close"]
    )

    now = pd.Timestamp.now(tz="UTC")

    agg = agg.loc[
        (agg.index + pd.Timedelta(days=days)) <= now
    ]

    agg = _validate_data(agg)

    if agg is not None:
        agg.attrs.update(daily.attrs)
        agg.attrs["interval"] = f"{days}d"
        agg.attrs["derived_from"] = "1d"
        agg.attrs["source"] = (
            daily.attrs.get("source", "Unknown") +
            " (derived daily)"
        )

    return agg


def fetch_timeframe(
    symbol: str,
    interval: str,
    limit: Optional[int] = None
) -> Tuple[Optional[pd.DataFrame], str]:

    limit = limit or DEFAULT_LIMITS.get(interval, 500)

    try:
        if is_crypto_symbol(symbol):
            data = _fetch_binance(symbol, interval, limit)

            if data is not None:
                data.attrs["requested_symbol"] = symbol
                return data, "ok"

            if interval in ("45d", "90d", "144d"):
                daily, status = fetch_timeframe(
                    symbol,
                    "1d",
                    DEFAULT_LIMITS["1d"]
                )

                if daily is not None:
                    derived = _resample_daily(
                        daily,
                        int(interval[:-1])
                    )

                    return (
                        derived,
                        "ok" if derived is not None else "insufficient_history"
                    )

            return None, "provider_unavailable"

        if interval in ("45d", "90d", "144d"):
            daily, status = fetch_timeframe(
                symbol,
                "1d",
                DEFAULT_LIMITS["1d"]
            )

            if daily is None:
                return None, status

            derived = _resample_daily(
                daily,
                int(interval[:-1])
            )

            return (
                derived,
                "ok" if derived is not None else "insufficient_history"
            )

        data = _fetch_twelve(symbol, interval, limit)

        if data is not None:
            data.attrs["requested_symbol"] = symbol
            return data, "ok"

        return None, "provider_unavailable"

    except requests.RequestException as exc:
        logger.warning(
            "Data request failed for %s %s: %s",
            symbol,
            interval,
            exc
        )
        return None, "network_error"

    except Exception:
        logger.exception(
            "Unexpected fetch error for %s %s",
            symbol,
            interval
        )
        return None, "invalid_response"


def fetch_market_bundle(symbol: str, timeframes=None) -> Dict[str, dict]:
    frames = timeframes or TIMEFRAMES
    bundle = {}
    daily_cache = None

    for interval in frames:
        if interval in ("45d", "90d", "144d") and daily_cache is not None:
            data = _resample_daily(
                daily_cache,
                int(interval[:-1])
            )

            status = "ok" if data is not None else "insufficient_history"

        else:
            data, status = fetch_timeframe(
                symbol,
                interval
            )

            if interval == "1d":
                daily_cache = data

        bundle[interval] = {
            "data": data,
            "status": status,
            "source": (
                data.attrs.get("source", "Unavailable")
                if data is not None
                else "Unavailable"
            ),
            "rows": len(data) if data is not None else 0,
            "last_time": (
                data.index[-1].isoformat()
                if data is not None and not data.empty
                else None
            )
        }

        time.sleep(0.12)

    return bundle


def fetch_market_data(symbol, period=None, interval="1h", limit=500):
    data, _ = fetch_timeframe(
        symbol,
        interval,
        limit
    )

    return data
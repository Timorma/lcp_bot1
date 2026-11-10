
import os
import time
import logging
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from threading import Lock

logger = logging.getLogger(__name__)

TIMEFRAMES = [
"1m","3m","5m","15m","30m","45m",
"1h","2h","4h","6h","8h","12h",
"1d","3d","1w","1mo","45d","90d","144d"
]

BINANCE_INTERVALS = {
"1m":"1m","3m":"3m","5m":"5m","15m":"15m",
"30m":"30m","1h":"1h","2h":"2h","4h":"4h",
"6h":"6h","8h":"8h","12h":"12h",
"1d":"1d","1w":"1w","1mo":"1M"
}

TWELVE_INTERVALS = {
"1m":"1min","3m":"3min","5m":"5min",
"15m":"15min","30m":"30min","45m":"45min",
"1h":"1h","2h":"2h","4h":"4h",
"6h":"6h","8h":"8h","12h":"12h",
"1d":"1day","1w":"1week","1mo":"1month"
}

YAHOO_INTERVALS = {
"1m":"1m","2m":"2m","5m":"5m",
"15m":"15m","30m":"30m","1h":"60m",
"1d":"1d","1w":"1wk","1mo":"1mo"
}

ALIASES = {
"GOLD":"XAUUSD",
"XAU/USD":"XAUUSD",
"GC":"GC=F",
"SILVER":"XAGUSD",
"XAG/USD":"XAGUSD",
"OIL":"CL=F",
"WTI":"CL=F",
"BRENT":"BZ=F",
"SPX":"^GSPC",
"SP500":"^GSPC",
"NASDAQ":"^IXIC",
"DOW":"^DJI",
"EUR/USD":"EURUSD",
"EURUSD":"EURUSD",
"GBP/USD":"GBPUSD",
"GBPUSD":"GBPUSD",
"USD/JPY":"USDJPY",
"USDJPY":"USDJPY",
"AUD/USD":"AUDUSD",
"AUDUSD":"AUDUSD",
"USD/CAD":"USDCAD",
"USDCAD":"USDCAD",
"USD/CHF":"USDCHF",
"USDCHF":"USDCHF",
"NZD/USD":"NZDUSD",
"NZDUSD":"NZDUSD"
}

TWELVE_SYMBOLS = {
"XAUUSD":"XAU/USD",
"XAGUSD":"XAG/USD",
"EURUSD":"EUR/USD",
"GBPUSD":"GBP/USD",
"USDJPY":"USD/JPY",
"AUDUSD":"AUD/USD",
"USDCAD":"USD/CAD",
"USDCHF":"USD/CHF",
"NZDUSD":"NZD/USD"
}

YAHOO_SYMBOLS = {
"XAUUSD":"GC=F",
"XAGUSD":"SI=F",
"EURUSD":"EURUSD=X",
"GBPUSD":"GBPUSD=X",
"USDJPY":"JPY=X",
"AUDUSD":"AUDUSD=X",
"USDCAD":"CAD=X",
"USDCHF":"CHF=X",
"NZDUSD":"NZD=X"
}

BINANCE_URL = "https://api.binance.com/api/v3/klines"
TWELVE_URL = "https://api.twelvedata.com/time_series"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
DEFAULT_LIMIT = 1000

TWELVE_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

_CACHE = {}
_CACHE_LOCK = Lock()

CACHE_SECONDS = {
"1m":15,"3m":20,"5m":30,"15m":45,
"30m":60,"45m":60,"1h":90,"2h":120,
"4h":180,"6h":240,"8h":300,"12h":300,
"1d":600,"3d":900,"1w":1200,"1mo":1800,
"45d":1800,"90d":1800,"144d":1800
}

def _safe_number(value):
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError,ValueError,OverflowError):
        return None

def _normalize_symbol(symbol):
    return str(symbol).strip().upper().replace(" ","")

def _resolve_symbol(symbol):
    normalized = _normalize_symbol(symbol)
    return ALIASES.get(normalized,normalized)

def _empty_frame():
    index = pd.DatetimeIndex([],tz="UTC",name="time")
    return pd.DataFrame(
        columns=["open","high","low","close","volume"],
        index=index
    )

def _normalize_dataframe(data):
    if data is None:
        return _empty_frame()

    if not isinstance(data,pd.DataFrame):
        try:
            data = pd.DataFrame(data)
        except Exception:
            return _empty_frame()

    if data.empty:
        return _empty_frame()

    frame = data.copy()

    if isinstance(frame.columns,pd.MultiIndex):
        frame.columns = [
            str(column[0]).lower().strip()
            for column in frame.columns
        ]
    else:
        frame.columns = [
            str(column).lower().strip()
            for column in frame.columns
        ]

    aliases = {
        "datetime":"time",
        "date":"time",
        "timestamp":"time",
        "adj close":"close",
        "vol":"volume"
    }

    frame = frame.rename(columns=aliases)

    required = ["open","high","low","close"]

    if not all(column in frame.columns for column in required):
        return _empty_frame()

    if "volume" not in frame.columns:
        frame["volume"] = 0.0

    for column in ["open","high","low","close","volume"]:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce"
        )

    frame = frame.replace([np.inf,-np.inf],np.nan)
    frame = frame.dropna(subset=required)

    frame = frame.loc[
        (frame["high"] >= frame["low"]) &
        (frame["high"] >= frame["open"]) &
        (frame["high"] >= frame["close"]) &
        (frame["low"] <= frame["open"]) &
        (frame["low"] <= frame["close"])
    ]

    if not isinstance(frame.index,pd.DatetimeIndex):
        time_column = next(
            (
                column for column in ["time","date","datetime"]
                if column in frame.columns
            ),
           None
        )

        if time_column:
            frame.index = pd.to_datetime(
                frame[time_column],
                utc=True,
                errors="coerce"
            )
            frame = frame.drop(columns=[time_column])
        else:
            frame.index = pd.to_datetime(
                frame.index,
                utc=True,
                errors="coerce"
            )
    else:
        frame.index = pd.to_datetime(
            frame.index,
            utc=True,
            errors="coerce"
        )

    frame = frame.loc[~frame.index.isna()]
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.sort_index()
    frame.index.name = "time"

    return frame[["open","high","low","close","volume"]]

def _validate_data(data,min_rows=30):
    frame = _normalize_dataframe(data)

    if len(frame) < min_rows:
        return None

    return frame

def _request_json(url,params=None):
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()
            result = response.json()

            if isinstance(result,dict):
                if result.get("status") == "error":
                    raise ValueError(
                        result.get("message","Provider error")
                    )

                if result.get("code") and "values" not in result:
                    raise ValueError(
                        result.get("message","Provider error")
                    )

            return result

        except Exception as error:
            last_error = error
            logger.warning(
                "Request attempt %s failed: %s",
                attempt+1,error
            )
            time.sleep(0.5*(attempt+1))

    raise RuntimeError(str(last_error))

def _fetch_binance(symbol,interval,limit=DEFAULT_LIMIT):
    if interval not in BINANCE_INTERVALS:
        return None

    params = {
        "symbol":symbol,
        "interval":BINANCE_INTERVALS[interval],
        "limit":min(max(int(limit),30),1000)
    }

    payload = _request_json(BINANCE_URL,params)

    if not isinstance(payload,list) or not payload:
        return None

    columns = [
        "time","open","high","low","close","volume",
        "close_time","quote_volume","trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ]

    frame = pd.DataFrame(payload,columns=columns)

    frame["time"] = pd.to_datetime(
        frame["time"],
        unit="ms",
        utc=True
    )

    return _validate_data(frame.set_index("time"))

def _fetch_twelve(symbol,interval,outputsize=5000):
    if not TWELVE_API_KEY:
        return None

    if interval not in TWELVE_INTERVALS:
        return None

    provider_symbol = TWELVE_SYMBOLS.get(symbol,symbol)

    params = {
        "symbol":provider_symbol,
        "interval":TWELVE_INTERVALS[interval],
        "outputsize":min(max(int(outputsize),30),5000),
        "timezone":"UTC",
        "apikey":TWELVE_API_KEY
    }

    payload = _request_json(TWELVE_URL,params)

    if not isinstance(payload,dict) or "values" not in payload:
        if isinstance(payload,dict):
            raise ValueError(
                payload.get("message","Twelve Data returned no values")
            )
        return None

    frame = pd.DataFrame(payload["values"])

    if "datetime" not in frame.columns:
        return None

    frame["datetime"] = pd.to_datetime(
        frame["datetime"],
        utc=True,
        errors="coerce"
    )

    return _validate_data(frame.set_index("datetime"))

def _fetch_yahoo(symbol,interval,period=None):
    yahoo_interval = YAHOO_INTERVALS.get(interval)

    if not yahoo_interval:
        return None

    provider_symbol = YAHOO_SYMBOLS.get(symbol,symbol)

    if period is None:
        period = "60d" if interval in ["1m","2m","5m","15m","30m","1h"] else "2y"

    ticker = yf.Ticker(provider_symbol)

    frame = ticker.history(
        period=period,
        interval=yahoo_interval,
        auto_adjust=False,
        actions=False
    )

    return _validate_data(frame)

def _resample_data(data,rule,min_rows=30):
    frame = _normalize_dataframe(data)

    if frame.empty:
        return None

    try:
        result = frame.resample(
            rule,
            origin="epoch",
            label="left",
            closed="left"
        ).agg({
            "open":"first",
            "high":"max",
            "low":"min",
            "close":"last",
            "volume":"sum"
        })

        result = result.dropna(
            subset=["open","high","low","close"]
        )

        return _validate_data(result,min_rows=min_rows)

    except Exception as error:
        logger.warning(
            "Resample failed for %s: %s",
            rule,error
        )
        return None

def _source_candidates(symbol,timeframe):
    crypto = (
        symbol.endswith("USDT") and
        symbol.isalnum()
    )

    if crypto:
        return ["binance","twelve"]

    if symbol == "XAUUSD":
        return ["twelve","yahoo_futures_proxy"]

    if symbol == "XAGUSD":
        return ["twelve","yahoo_futures_proxy"]

    return ["twelve","yahoo"]

def _fetch_source(symbol,timeframe,source):
    if source == "binance":
        return _fetch_binance(symbol,timeframe)

    if source == "twelve":
        return _fetch_twelve(symbol,timeframe)

    if source == "yahoo":
        return _fetch_yahoo(symbol,timeframe)

    if source == "yahoo_futures_proxy":
        proxy_symbol = YAHOO_SYMBOLS.get(symbol)

        if not proxy_symbol:
            return None

        return _fetch_yahoo(proxy_symbol,timeframe)

    return None

def _cache_key(symbol,timeframe):
    return f"{symbol}:{timeframe}"

def _get_cached(symbol,timeframe):
    key = _cache_key(symbol,timeframe)

    with _CACHE_LOCK:
        item = _CACHE.get(key)

        if not item:
            return None

        age = time.time()-item["stored_at"]
        ttl = CACHE_SECONDS.get(timeframe,60)

        if age > ttl:
            _CACHE.pop(key,None)
            return None

        return {
            "data":item["data"].copy() if item["data"] is not None else None,
            "provider":item.get("provider"),
            "elapsed_seconds":item.get("elapsed_seconds",0),
            "stored_at":item["stored_at"]
        }

def _set_cached(symbol,timeframe,data,provider,elapsed_seconds=0):
    key = _cache_key(symbol,timeframe)

    with _CACHE_LOCK:
        _CACHE[key] = {
            "data":data.copy() if data is not None else None,
            "provider":provider,
            "elapsed_seconds":elapsed_seconds,
            "stored_at":time.time()
        }

def _custom_rule(timeframe):
    rules = {
        "3d":"3D",
        "45d":"45D",
        "90d":"90D",
        "144d":"144D"
    }

    return rules.get(timeframe)

def _fetch_daily_for_custom(symbol):
    errors = []

    for source in _source_candidates(symbol,"1d"):
        try:
            if source == "yahoo_futures_proxy":
                data = _fetch_source(symbol,"1d",source)
            else:
                data = _fetch_source(symbol,"1d",source)

            if data is not None and len(data) >= 30:
                return data,source,None

            errors.append(f"{source}: insufficient daily history")

        except Exception as error:
            errors.append(f"{source}: {str(error)}")

    return None,None,"; ".join(errors)

def fetch_timeframe_info(symbol,timeframe,force_refresh=False):
    normalized = _resolve_symbol(symbol)
    timeframe = str(timeframe).strip()

    if timeframe not in TIMEFRAMES:
        return {
            "data":None,
            "provider":None,
            "error":"Unsupported timeframe",
            "elapsed_seconds":0
        }

    cached = None if force_refresh else _get_cached(
        normalized,timeframe
    )

    if cached and cached.get("data") is not None:
        return {
            "data":cached["data"],
            "provider":cached["provider"],
            "error":None,
            "elapsed_seconds":cached["elapsed_seconds"],
            "cached":True
        }

    started = time.time()
    rule = _custom_rule(timeframe)

    if rule:
        daily,source,error = _fetch_daily_for_custom(normalized)

        if daily is not None:
            result = _resample_data(daily,rule,min_rows=3)

            if result is not None and len(result) >= 3:
                elapsed = round(time.time()-started,3)

                _set_cached(
                    normalized,
                    timeframe,
                    result,
                    source,
                    elapsed
                )

                return {
                    "data":result,
                    "provider":source,
                    "error":None,
                    "elapsed_seconds":elapsed,
                    "cached":False
                }

            error = "Insufficient history after resampling"

        return {
            "data":None,
            "provider":source,
            "error":error or "Custom timeframe unavailable",
            "elapsed_seconds":round(time.time()-started,3),
            "cached":False
        }

    errors = []

    for source in _source_candidates(normalized,timeframe):
        try:
            result = _fetch_source(
                normalized,
                timeframe,
                source
            )

            if result is not None and len(result) >= 30:
                elapsed = round(time.time()-started,3)

                _set_cached(
                    normalized,
                    timeframe,
                    result,
                    source,
                    elapsed
                )

                return {
                    "data":result,
                    "provider":source,
                    "error":None,
                    "elapsed_seconds":elapsed,
                    "cached":False
                }

            errors.append(f"{source}: no sufficient data")

        except Exception as error:
            logger.warning(
                "Provider %s failed for %s %s: %s",
                source,normalized,timeframe,error
            )

            errors.append(f"{source}: {str(error)}")

    return {
        "data":None,
        "provider":None,
        "error":" | ".join(errors) if errors else "Data unavailable",
        "elapsed_seconds":round(time.time()-started,3),
        "cached":False
    }

def fetch_timeframe(symbol,timeframe,force_refresh=False):
    result = fetch_timeframe_info(
        symbol,
        timeframe,
        force_refresh
    )

    return result["data"]

def fetch_market_bundle(symbol,timeframes=None,force_refresh=False):
    normalized = _resolve_symbol(symbol)
    selected = list(timeframes or TIMEFRAMES)
    bundle = {}

    for timeframe in selected:
        try:
            result = fetch_timeframe_info(
                normalized,
                timeframe,
                force_refresh
            )

            data = result["data"]

            bundle[timeframe] = {
                "data":data,
                "error":result["error"],
                "provider":result["provider"],
                "elapsed_seconds":result["elapsed_seconds"],
                "last_candle_time":(
                    data.index[-1].isoformat()
                    if data is not None and not data.empty
                    else None
                ),
                "rows":len(data) if data is not None else 0,
                "cached":result.get("cached",False)
            }

        except Exception as error:
            logger.exception(
                "Market bundle error: %s %s",
                normalized,timeframe
            )

            bundle[timeframe] = {
                "data":None,
                "error":str(error),
                "provider":None,
                "elapsed_seconds":0,
                "last_candle_time":None,
                "rows":0,
                "cached":False
            }

    return bundle

def fetch_market_data(symbol,timeframe="1d",force_refresh=False):
    return fetch_timeframe(
        symbol,
        timeframe,
        force_refresh
    )

def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()

def get_cache_status():
    now = time.time()

    with _CACHE_LOCK:
        return {
            key:{
                "age_seconds":round(
                    now-value["stored_at"],2
                ),
                "rows":(
                    len(value["data"])
                    if value["data"] is not None
                    else 0
                ),
                "provider":value.get("provider")
            }
            for key,value in _CACHE.items()
        }

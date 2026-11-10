
import os
import time
import json
import logging
import threading
from urllib.parse import urlencode
from datetime import datetime, timezone
from threading import Lock

import requests
import pandas as pd
import numpy as np
import yfinance as yf
import websocket

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
"1m":"1min","5m":"5min","15m":"15min",
"30m":"30min","45m":"45min","1h":"1h",
"2h":"2h","4h":"4h","1d":"1day",
"1w":"1week","1mo":"1month"
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
TWELVE_WS_URL = "wss://ws.twelvedata.com/v1/quotes/price"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
DEFAULT_LIMIT = 500
TWELVE_OUTPUTSIZE = int(os.getenv("TWELVE_OUTPUTSIZE","500"))
TWELVE_MIN_INTERVAL = float(os.getenv("TWELVE_MIN_INTERVAL","1.0"))
TWELVE_COOLDOWN_SECONDS = int(os.getenv("TWELVE_COOLDOWN_SECONDS","60"))

TWELVE_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

_CACHE = {}
_CACHE_LOCK = Lock()

_TWELVE_LOCK = Lock()
_TWELVE_LAST_REQUEST = 0.0
_TWELVE_COOLDOWN_UNTIL = 0.0

_ERROR_LOCK = Lock()
_LAST_ERRORS = {}

CACHE_SECONDS = {
"1m":15,"3m":20,"5m":30,"15m":45,
"30m":60,"45m":60,"1h":90,"2h":120,
"4h":180,"6h":240,"8h":300,"12h":300,
"1d":600,"3d":900,"1w":1200,"1mo":1800,
"45d":1800,"90d":1800,"144d":1800
}

_LIVE_LOCK = Lock()
_LIVE_STOP = threading.Event()
_LIVE_APP = None
_LIVE_THREAD = None
_LIVE_HEARTBEAT = None

_LIVE_DATA = {
"symbol":None,
"price":None,
"timestamp":None,
"received_at":None,
"provider":"twelve",
"status":"disconnected",
"error":None
}

class ProviderError(Exception):
    def __init__(self,message,status_code=None):
        super().__init__(message)
        self.status_code = status_code

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
        selected_columns = []
        for column in frame.columns:
            parts = [str(x).lower().strip() for x in column]
            selected = next(
                (
                    part for part in parts
                    if part in [
                        "open","high","low","close",
                        "adj close","volume"
                    ]
                ),
                parts[-1]
            )
            selected_columns.append(selected)
        frame.columns = selected_columns
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

    if frame.columns.duplicated().any():
        frame = frame.loc[:,~frame.columns.duplicated(keep="first")]

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

def _log_error_once(key,message,level="warning"):
    now = time.time()

    with _ERROR_LOCK:
        previous = _LAST_ERRORS.get(key,0)

        if now-previous < 300:
            return

        _LAST_ERRORS[key] = now

    log_method = getattr(logger,level,logger.warning)
    log_method("%s",message)

def _request_json(url,params=None):
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 429:
                global _TWELVE_COOLDOWN_UNTIL
                _TWELVE_COOLDOWN_UNTIL = max(
                    _TWELVE_COOLDOWN_UNTIL,
                    time.time()+TWELVE_COOLDOWN_SECONDS
                )
                raise ProviderError(
                    "Provider rate limit reached",
                    429
                )

            if response.status_code >= 400:
                try:
                    body = response.json()
                    message = body.get(
                        "message",
                        body.get("code","Provider request rejected")
                    )
                except Exception:
                    message = "Provider request rejected"

                raise ProviderError(
                    str(message),
                    response.status_code
                )

            try:
                result = response.json()
            except Exception:
                raise ProviderError("Invalid JSON response")

            if isinstance(result,dict):
                if result.get("status") == "error":
                    raise ProviderError(
                        result.get("message","Provider error")
                    )

                if result.get("code") and "values" not in result:
                    raise ProviderError(
                        result.get("message","Provider error")
                    )

            return result

        except ProviderError as error:
            last_error = error

            if error.status_code == 429:
                break

            if error.status_code is not None and error.status_code < 500:
                break

        except (requests.Timeout,requests.ConnectionError) as error:
            last_error = error

        except Exception as error:
            last_error = error
            break

        if attempt < MAX_RETRIES-1:
            time.sleep(0.5*(attempt+1))

    raise RuntimeError(str(last_error or "Provider request failed"))

def _wait_twelve_slot():
    global _TWELVE_LAST_REQUEST

    with _TWELVE_LOCK:
        now = time.time()

        if now < _TWELVE_COOLDOWN_UNTIL:
            raise ProviderError(
                "Twelve Data temporarily paused after rate limit",
                429
            )

        wait_time = (
            TWELVE_MIN_INTERVAL -
            (now-_TWELVE_LAST_REQUEST)
        )

        if wait_time > 0:
            time.sleep(wait_time)

        _TWELVE_LAST_REQUEST = time.time()

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

def _fetch_twelve(symbol,interval,outputsize=None):
    if not TWELVE_API_KEY:
        return None

    if interval not in TWELVE_INTERVALS:
        return None

    _wait_twelve_slot()

    provider_symbol = TWELVE_SYMBOLS.get(symbol,symbol)

    requested_size = (
        TWELVE_OUTPUTSIZE
        if outputsize is None
        else int(outputsize)
    )

    params = {
        "symbol":provider_symbol,
        "interval":TWELVE_INTERVALS[interval],
        "outputsize":min(max(requested_size,30),5000),
        "timezone":"UTC",
        "apikey":TWELVE_API_KEY
    }

    payload = _request_json(TWELVE_URL,params)

    if not isinstance(payload,dict) or "values" not in payload:
        if isinstance(payload,dict):
            raise ProviderError(
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
        period = (
            "7d"
            if interval in ["1m"]
            else "60d"
            if interval in ["2m","5m","15m","30m","1h"]
            else "2y"
        )

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
        arguments = {
            "label":"left",
            "closed":"left"
        }

        if not str(rule).upper().endswith("D"):
            arguments["origin"] = "epoch"

        result = frame.resample(
            rule,
            **arguments
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
        _log_error_once(
            f"resample:{rule}",
            f"Resample failed for {rule}: {error}"
        )
        return None

def _source_candidates(symbol,timeframe):
    crypto = (
        symbol.endswith("USDT") and
        symbol.isalnum()
    )

    if crypto:
        return ["binance","twelve"]

    if symbol in ["XAUUSD","XAGUSD"]:
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

CACHE_SECONDS = {
"1m":15,"3m":20,"5m":30,"15m":45,
"30m":60,"45m":60,"1h":90,"2h":120,
"4h":180,"6h":240,"8h":300,"12h":300,
"1d":600,"3d":900,"1w":1200,"1mo":1800,
"45d":1800,"90d":1800,"144d":1800
}

def _custom_rule(timeframe):
    rules = {
        "3d":"3D",
        "45d":"45D",
        "90d":"90D",
        "144d":"144D"
    }
    return rules.get(timeframe)

def _derived_rule(timeframe):
    rules = {
        "3m":("1m","3min"),
        "6h":("1h","6h"),
        "8h":("1h","8h"),
        "12h":("1h","12h")
    }
    return rules.get(timeframe)

def _fetch_from_sources(symbol,timeframe):
    errors = []

    for source in _source_candidates(symbol,timeframe):
        try:
            data = _fetch_source(symbol,timeframe,source)

            if data is not None and len(data) >= 30:
                return data,source,None

            errors.append(f"{source}: insufficient data")

        except Exception as error:
            message = str(error)
            errors.append(f"{source}: {message}")

            _log_error_once(
                f"{symbol}:{timeframe}:{source}:{type(error).__name__}",
                f"Provider {source} failed for {symbol} {timeframe}: {message}"
            )

    return None,None,"; ".join(errors)

def _fetch_daily_for_custom(symbol):
    return _fetch_from_sources(symbol,"1d")

def _fetch_derived(symbol,base_timeframe,rule):
    base_info = fetch_timeframe_info(
        symbol,
        base_timeframe
    )

    data = base_info["data"]
    source = base_info["provider"]

    if data is None:
        return None,source,base_info["error"]

    result = _resample_data(
        data,
        rule,
        min_rows=30
    )

    if result is None or len(result) < 30:
        return None,source,"Insufficient history after resampling"

    return result,source,None

def fetch_timeframe_info(symbol,timeframe,force_refresh=False):
    normalized = _resolve_symbol(symbol)
    timeframe = str(timeframe).strip()

    if timeframe not in TIMEFRAMES:
        return {
            "data":None,
            "provider":None,
            "error":"Unsupported timeframe",
            "elapsed_seconds":0,
            "cached":False
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
            result = _resample_data(
                daily,
                rule,
                min_rows=3
            )

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

    derived = _derived_rule(timeframe)

    if derived:
        base_timeframe,derived_rule = derived

        result,source,error = _fetch_derived(
            normalized,
            base_timeframe,
            derived_rule
        )

        if result is not None:
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

        return {
            "data":None,
            "provider":source,
            "error":error or "Derived timeframe unavailable",
            "elapsed_seconds":round(time.time()-started,3),
            "cached":False
        }

    result,source,error = _fetch_from_sources(
        normalized,
        timeframe
    )

    if result is not None:
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

    return {
        "data":None,
        "provider":None,
        "error":error or "Data unavailable",
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

# ==========================================
# ICB LIVE PRICE ENGINE
# ==========================================

def _live_set_status(status,error=None):
    with _LIVE_LOCK:
        _LIVE_DATA["status"] = status
        _LIVE_DATA["error"] = error

def _live_on_open(ws):
    logger.info("ICB live websocket connected")
    _live_set_status("connected")

    subscription = {
        "action":"subscribe",
        "params":{
            "symbols":"XAU/USD"
        }
    }

    ws.send(json.dumps(subscription))

    def heartbeat():
        while not _LIVE_STOP.wait(10):
            try:
                if ws.sock and ws.sock.connected:
                    ws.send(json.dumps({
                        "action":"heartbeat"
                    }))
                else:
                    break
            except Exception as error:
                logger.warning("Heartbeat failed: %s",error)
                break

    global _LIVE_HEARTBEAT

    _LIVE_HEARTBEAT = threading.Thread(
        target=heartbeat,
        daemon=True
    )
    _LIVE_HEARTBEAT.start()

def _live_on_message(ws,message):
    try:
        payload = json.loads(message)

        event = payload.get("event")

        if event == "price":
            symbol = payload.get("symbol")
            price = _safe_number(payload.get("price"))

            if price is None or price <= 0:
                return

            if symbol and symbol.upper() not in [
                "XAU/USD","XAUUSD"
            ]:
                return

            timestamp = payload.get("timestamp")
            market_time = None

            if timestamp is not None:
                try:
                    market_time = datetime.fromtimestamp(
                        float(timestamp),
                        tz=timezone.utc
                    ).isoformat()
                except (TypeError,ValueError,OverflowError,OSError):
                    market_time = None

            received_at = datetime.now(
                timezone.utc
            ).isoformat()

            with _LIVE_LOCK:
                _LIVE_DATA["symbol"] = symbol or "XAU/USD"
                _LIVE_DATA["price"] = price
                _LIVE_DATA["timestamp"] = market_time
                _LIVE_DATA["received_at"] = received_at
                _LIVE_DATA["provider"] = "twelve"
                _LIVE_DATA["status"] = "connected"
                _LIVE_DATA["error"] = None

        elif payload.get("status") == "error":
            _live_set_status(
                "provider_error",
                str(payload.get("message",payload))
            )

    except Exception as error:
        logger.warning("Live message parsing error: %s",error)

def _live_on_error(ws,error):
    logger.warning("Live websocket error: %s",error)
    _live_set_status("error",str(error))

def _live_on_close(ws,code,message):
    logger.warning(
        "Live websocket closed: %s %s",
        code,
        message
    )

    if not _LIVE_STOP.is_set():
        _live_set_status("disconnected")

def _live_worker():
    global _LIVE_APP

    while not _LIVE_STOP.is_set():
        if not TWELVE_API_KEY:
            _live_set_status(
                "configuration_error",
                "TWELVE_DATA_API_KEY is missing"
            )
            return

        url = TWELVE_WS_URL + "?" + urlencode({
            "apikey":TWELVE_API_KEY
        })

        try:
            _LIVE_APP = websocket.WebSocketApp(
                url,
                on_open=_live_on_open,
                on_message=_live_on_message,
                on_error=_live_on_error,
                on_close=_live_on_close
            )

            _LIVE_APP.run_forever(
                ping_interval=20,
                ping_timeout=10
            )

        except Exception as error:
            logger.exception("Live websocket worker failed")
            _live_set_status("error",str(error))

        if not _LIVE_STOP.is_set():
            _live_set_status("reconnecting")
            _LIVE_STOP.wait(5)

def start_live_price():
    global _LIVE_THREAD

    if not TWELVE_API_KEY:
        _live_set_status(
            "configuration_error",
            "TWELVE_DATA_API_KEY is missing"
        )
        return False

    if _LIVE_THREAD and _LIVE_THREAD.is_alive():
        return True

    _LIVE_STOP.clear()

    _LIVE_THREAD = threading.Thread(
        target=_live_worker,
        daemon=True
    )

    _LIVE_THREAD.start()
    return True

def stop_live_price():
    _LIVE_STOP.set()

    if _LIVE_APP:
        try:
            _LIVE_APP.close()
        except Exception:
            pass

    _live_set_status("stopped")

def get_live_price():
    with _LIVE_LOCK:
        result = dict(_LIVE_DATA)

    received = result.get("received_at")

    if received:
        try:
            received_dt = datetime.fromisoformat(received)

            if received_dt.tzinfo is None:
                received_dt = received_dt.replace(
                    tzinfo=timezone.utc
                )

            age = (
                datetime.now(timezone.utc)-received_dt
            ).total_seconds()

        except (TypeError,ValueError,OverflowError):
            age = None
    else:
        age = None

    result["age_seconds"] = (
        round(age,2) if age is not None else None
    )

    result["is_fresh"] = (
        age is not None and 0 <= age <= 15
    )

    if age is not None and age > 15:
        result["status"] = "stale"

    return result

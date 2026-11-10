
import os
import json
import time
import logging
import threading
from datetime import datetime, timezone
from urllib.parse import urlencode

import websocket

logger = logging.getLogger(__name__)

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
SYMBOL = "XAU/USD"
WS_URL = "wss://ws.twelvedata.com/v1/quotes/price"

_lock = threading.Lock()
_stop_event = threading.Event()
_ws_app = None
_ws_thread = None
_heartbeat_thread = None

_latest = {
    "symbol": SYMBOL,
    "price": None,
    "timestamp": None,
    "received_at": None,
    "status": "disconnected",
    "error": None
}

def _update_status(status, error=None):
    with _lock:
        _latest["status"] = status
        _latest["error"] = error

def _on_open(ws):
    logger.info("ICB live connection opened")

    _update_status("connected")

    message = {
        "action": "subscribe",
        "params": {
            "symbols": SYMBOL
        }
    }

    ws.send(json.dumps(message))

    def heartbeat():
        while not _stop_event.wait(10):
            try:
                if ws.sock and ws.sock.connected:
                    ws.send(json.dumps({
                        "action": "heartbeat"
                    }))
                else:
                    break
            except Exception as error:
                logger.warning("Heartbeat error: %s", error)
                break

    global _heartbeat_thread

    _heartbeat_thread = threading.Thread(
        target=heartbeat,
        daemon=True
    )
    _heartbeat_thread.start()

def _on_message(ws, message):
    try:
        payload = json.loads(message)

        event = payload.get("event")

        if event == "price":
            symbol = payload.get("symbol")
            price = float(payload.get("price"))

            if symbol != SYMBOL or price <= 0:
                return

            timestamp = payload.get("timestamp")

            if timestamp is not None:
                market_time = datetime.fromtimestamp(
                    float(timestamp),
                    tz=timezone.utc
                ).isoformat()
            else:
                market_time = None

            received_time = datetime.now(
                timezone.utc
            ).isoformat()

            with _lock:
                _latest.update({
                    "symbol": symbol,
                    "price": price,
                    "timestamp": market_time,
                    "received_at": received_time,
                    "status": "live",
                    "error": None
                })

        elif event == "subscribe-status":
            logger.info(
                "ICB subscription status: %s",
                payload
            )

            if payload.get("fails"):
                _update_status(
                    "subscription_error",
                    str(payload.get("fails"))
                )

        elif payload.get("status") == "error":
            _update_status(
                "provider_error",
                str(payload.get("message", payload))
            )

    except Exception as error:
        logger.warning("Live message error: %s", error)

def _on_error(ws, error):
    logger.warning("Live websocket error: %s", error)
    _update_status("error", str(error))

def _on_close(ws, code, message):
    logger.warning(
        "Live websocket closed: %s %s",
        code,
        message
    )

    if not _stop_event.is_set():
        _update_status("disconnected")

def _connection_worker():
    global _ws_app

    while not _stop_event.is_set():
        if not API_KEY:
            _update_status(
                "configuration_error",
                "TWELVE_DATA_API_KEY is missing"
            )
            return

        url = WS_URL + "?" + urlencode({
            "apikey": API_KEY
        })

        try:
            _ws_app = websocket.WebSocketApp(
                url,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close
            )

            _ws_app.run_forever(
                ping_interval=20,
                ping_timeout=10
            )

        except Exception as error:
            logger.exception("Live connection failed")
            _update_status("error", str(error))

        if not _stop_event.is_set():
            _update_status("reconnecting")
            _stop_event.wait(5)

def start_live_price():
    global _ws_thread

    if not API_KEY:
        _update_status(
            "configuration_error",
            "TWELVE_DATA_API_KEY is missing"
        )
        return False

    if _ws_thread and _ws_thread.is_alive():
        return True

    _stop_event.clear()

    _ws_thread = threading.Thread(
        target=_connection_worker,
        daemon=True
    )

    _ws_thread.start()

    return True

def stop_live_price():
    _stop_event.set()

    if _ws_app:
        try:
            _ws_app.close()
        except Exception:
            pass

    _update_status("stopped")

def get_live_price():
    with _lock:
        result = dict(_latest)

    received = result.get("received_at")

    if received:
        received_dt = datetime.fromisoformat(received)
        age = (
            datetime.now(timezone.utc) - received_dt
        ).total_seconds()
    else:
        age = None

    result["age_seconds"] = (
        round(age, 2) if age is not None else None
    )

    result["is_fresh"] = (
        age is not None and age <= 15
    )

    if age is not None and age > 15:
        result["status"] = "stale"

    return result

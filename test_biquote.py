import requests

BASE = "https://biquote.io/api"

for symbol in ["XAUUSD", "XAGUSD", "BTCUSD"]:
    for interval in ["1h", "4h", "1d"]:
        try:
            r = requests.get(
                f"{BASE}/{symbol}/ohlc",
                params={"interval": interval, "limit": 10},
                timeout=20
            )
            print("\n", symbol, interval, "HTTP", r.status_code)
            data = r.json()
            bars = data.get("bars", [])
            closed = [b for b in bars if not b.get("isOpen", False)]
            print("Bars:", len(bars), "Closed:", len(closed))
            if closed:
                print("Latest:", closed[0])
        except Exception as e:
            print("ERROR:", symbol, interval, str(e))
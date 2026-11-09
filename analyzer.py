
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def analyze_confluence(df):
    neutral = {
        "bias": "Neutral ⚪",
        "entry": 0.0,
        "sl": 0.0,
        "tp": 0.0,
        "confidence": 0,
        "volatility": 0.0,
        "structure": "Insufficient data",
        "evidence": [],
        "warnings": ["Insufficient or invalid market data"]
    }

    try:
        if df is None or len(df) < 30:
            return neutral.copy()

        required = ["Open", "High", "Low", "Close"]

        if not all(col in df.columns for col in required):
            return neutral.copy()

        data = df.copy()

        for col in required:
            data[col] = pd.to_numeric(
                data[col],
                errors="coerce"
            )

        data = data.dropna(subset=required)

        if len(data) < 30:
            return neutral.copy()

        data = data.sort_index()

        open_price = data["Open"]
        high = data["High"]
        low = data["Low"]
        close = data["Close"]

        last_close = float(close.iloc[-1])

        if not np.isfinite(last_close) or last_close <= 0:
            return neutral.copy()

        previous_close = close.shift(1)

        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs()
            ],
            axis=1
        ).max(axis=1)

        atr_series = true_range.rolling(14).mean()
        atr = float(atr_series.iloc[-1])

        if not np.isfinite(atr) or atr <= 0:
            return neutral.copy()

        volatility_pct = (atr / last_close) * 100

        ema_fast = close.ewm(
            span=20,
            adjust=False
        ).mean()

        ema_slow = close.ewm(
            span=50,
            adjust=False
        ).mean()

        fast_value = float(ema_fast.iloc[-1])
        slow_value = float(ema_slow.iloc[-1])

        trend_up = fast_value > slow_value
        trend_down = fast_value < slow_value

        recent_high = float(high.iloc[-21:-1].max())
        recent_low = float(low.iloc[-21:-1].min())

        previous_high = float(high.iloc[-2])
        previous_low = float(low.iloc[-2])

        candle_open = float(open_price.iloc[-1])
        candle_high = float(high.iloc[-1])
        candle_low = float(low.iloc[-1])

        candle_range = candle_high - candle_low

        if candle_range > 0:
            upper_wick = candle_high - max(
                candle_open,
                last_close
            )

            lower_wick = min(
                candle_open,
                last_close
            ) - candle_low

            upper_wick_ratio = upper_wick / candle_range
            lower_wick_ratio = lower_wick / candle_range
            body_ratio = abs(last_close - candle_open) / candle_range
        else:
            upper_wick_ratio = 0
            lower_wick_ratio = 0
            body_ratio = 0

        bullish_points = 0
        bearish_points = 0

        evidence = []
        warnings = []

        if trend_up:
            bullish_points += 2
            evidence.append("EMA20 above EMA50")

        elif trend_down:
            bearish_points += 2
            evidence.append("EMA20 below EMA50")

        if last_close > fast_value:
            bullish_points += 1
            evidence.append("Price above EMA20")

        elif last_close < fast_value:
            bearish_points += 1
            evidence.append("Price below EMA20")

        if last_close > recent_high:
            bullish_points += 2
            evidence.append("Recent high breakout")

        elif last_close < recent_low:
            bearish_points += 2
            evidence.append("Recent low breakdown")

        if lower_wick_ratio > 0.45 and last_close > candle_open:
            bullish_points += 1
            evidence.append("Strong lower wick rejection")

        if upper_wick_ratio > 0.45 and last_close < candle_open:
            bearish_points += 1
            evidence.append("Strong upper wick rejection")

        if last_close > previous_high:
            bullish_points += 1
            evidence.append("Close above previous high")

        elif last_close < previous_low:
            bearish_points += 1
            evidence.append("Close below previous low")

        volume_confirmation = False

        if "Volume" in data.columns:
            volume = pd.to_numeric(
                data["Volume"],
                errors="coerce"
            ).fillna(0)

            avg_volume = float(volume.iloc[-21:-1].mean())
            current_volume = float(volume.iloc[-1])

            if avg_volume > 0 and current_volume > avg_volume * 1.2:
                volume_confirmation = True
                evidence.append("Volume above recent average")

        if bullish_points > bearish_points:
            bias = "Bullish 🟢"
            direction = 1
        elif bearish_points > bullish_points:
            bias = "Bearish 🔴"
            direction = -1
        else:
            bias = "Neutral ⚪"
            direction = 0

        total_points = bullish_points + bearish_points

        confidence = (
            abs(bullish_points - bearish_points) /
            max(total_points, 1)
        ) * 100

        confidence = round(
            min(confidence, 95),
            1
        )

        if volume_confirmation:
            confidence = min(
                confidence + 5,
                95
            )

        if direction == 0:
            warnings.append("Conflicting directional evidence")

        if volatility_pct > 5:
            warnings.append("High volatility detected")

        if body_ratio < 0.15:
            warnings.append("Small candle body")

        if direction == 0:
            entry = last_close
            sl = last_close
            tp = last_close

        else:
            entry = last_close

            if direction == 1:
                structural_stop = min(
                    recent_low,
                    candle_low
                )

                sl = min(
                    structural_stop,
                    last_close - atr
                )

                tp = last_close + (atr * 2)

            else:
                structural_stop = max(
                    recent_high,
                    candle_high
                )

                sl = max(
                    structural_stop,
                    last_close + atr
                )

                tp = last_close - (atr * 2)

        decimals = max(
            0,
            min(
                10,
                len(str(last_close).split(".")[-1])
                if "." in str(last_close)
                else 0
            )
        )

        entry = round(entry, decimals)
        sl = round(sl, decimals)
        tp = round(tp, decimals)

        return {
            "bias": bias,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "confidence": confidence,
            "volatility": round(volatility_pct, 3),
            "atr": round(atr, decimals),
            "structure": (
                "Bullish structure"
                if direction == 1
                else "Bearish structure"
                if direction == -1
                else "Unclear structure"
            ),
            "evidence": evidence,
            "warnings": warnings,
            "bullish_points": bullish_points,
            "bearish_points": bearish_points
        }

    except Exception:
        logger.exception("Analysis engine failed")
        return neutral.copy()

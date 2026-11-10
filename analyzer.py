
import logging
import math
import numpy as np
import pandas as pd

logger = logging.getLogger("ICB_ANALYZER")

TIMEFRAME_WEIGHTS = {
    "1m": 1,
    "3m": 1,
    "5m": 2,
    "15m": 3,
    "30m": 3,
    "45m": 3,
    "1h": 4,
    "2h": 4,
    "4h": 5,
    "6h": 5,
    "8h": 5,
    "12h": 6,
    "1d": 7,
    "3d": 8,
    "1w": 9,
    "1mo": 10,
    "45d": 10,
    "90d": 10,
    "144d": 10
}

TIMEFRAME_GROUPS = {
    "الرئيسي": ["144d", "90d", "45d", "1mo", "1w", "3d", "1d"],
    "المتوسط": ["12h", "8h", "6h", "4h", "2h", "1h"],
    "القصير": ["45m", "30m", "15m", "5m", "3m", "1m"]
}

GROUP_WEIGHTS = {
    "الرئيسي": 0.55,
    "المتوسط": 0.30,
    "القصير": 0.15
}

DIRECTION_THRESHOLD = 0.18


def _safe_float(value, default=0.0):
    try:
        result = float(value)
        if math.isfinite(result):
            return result
    except (TypeError, ValueError, OverflowError):
        pass
    return default


def _empty_result(timeframe, reason="بيانات غير كافية"):
    return {
        "timeframe": timeframe,
        "bias": "محايد",
        "confidence": 0.0,
        "signed_strength": 0.0,
        "last_close": None,
        "atr": None,
        "volatility_pct": None,
        "structure": "غير محدد",
        "evidence": [],
        "points": [],
        "support_candidates": [],
        "resistance_candidates": [],
        "last_time": None,
        "warning": reason
    }


def _prepare(data):
    if data is None:
        return None

    if isinstance(data, dict):
        try:
            data = pd.DataFrame(data)
        except Exception:
            return None

    if not isinstance(data, pd.DataFrame):
        return None

    if data.empty or len(data) < 30:
        return None

    frame = data.copy()
    frame.columns = [str(column).lower() for column in frame.columns]

    required = ["open", "high", "low", "close"]

    if any(column not in frame.columns for column in required):
        return None

    for column in required:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce"
        )

    if "volume" in frame.columns:
        frame["volume"] = pd.to_numeric(
            frame["volume"],
            errors="coerce"
        ).fillna(0)

    frame = frame.dropna(subset=required)

    frame = frame[
        (frame["high"] >= frame["low"]) &
        (frame["high"] >= frame["open"]) &
        (frame["high"] >= frame["close"]) &
        (frame["low"] <= frame["open"]) &
        (frame["low"] <= frame["close"])
    ]

    if len(frame) < 30:
        return None

    return frame.reset_index(drop=False)


def _calculate_atr(frame, period=14):
    high = frame["high"]
    low = frame["low"]
    close = frame["close"]

    previous_close = close.shift(1)

    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs()
        ],
        axis=1
    )

    true_range = ranges.max(axis=1)

    atr = true_range.rolling(
        window=period,
        min_periods=period
    ).mean()

    value = _safe_float(atr.iloc[-1])

    if value <= 0:
        value = _safe_float(
            (high - low).tail(period).mean()
        )

    return value


def _pivot_points(frame, left=3, right=3):
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)

    pivot_highs = []
    pivot_lows = []

    for index in range(left, len(frame) - right):
        high_window = highs[index-left:index+right+1]
        low_window = lows[index-left:index+right+1]

        if highs[index] == np.max(high_window):
            pivot_highs.append({
                "price": float(highs[index]),
                "index": int(index)
            })

        if lows[index] == np.min(low_window):
            pivot_lows.append({
                "price": float(lows[index]),
                "index": int(index)
            })

    return pivot_highs, pivot_lows


def _single_timeframe(data, timeframe):
    frame = _prepare(data)

    if frame is None:
        return _empty_result(timeframe)

    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    open_price = frame["open"]

    current = _safe_float(close.iloc[-1])

    if current <= 0:
        return _empty_result(timeframe, "السعر المرجعي غير صالح")

    atr = _calculate_atr(frame)

    if atr <= 0:
        return _empty_result(timeframe, "تعذر حساب التذبذب")

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    score = 0.0
    evidence = []

    if current > _safe_float(ema20.iloc[-1]):
        score += 0.15
        evidence.append("السعر أعلى المتوسط EMA20")

    elif current < _safe_float(ema20.iloc[-1]):
        score -= 0.15
        evidence.append("السعر أسفل المتوسط EMA20")

    if current > _safe_float(ema50.iloc[-1]):
        score += 0.20
        evidence.append("السعر أعلى المتوسط EMA50")

    elif current < _safe_float(ema50.iloc[-1]):
        score -= 0.20
        evidence.append("السعر أسفل المتوسط EMA50")

    if current > _safe_float(ema200.iloc[-1]):
        score += 0.25
        evidence.append("السعر أعلى المتوسط EMA200")

    elif current < _safe_float(ema200.iloc[-1]):
        score -= 0.25
        evidence.append("السعر أسفل المتوسط EMA200")

    if _safe_float(ema20.iloc[-1]) > _safe_float(ema50.iloc[-1]):
        score += 0.10
        evidence.append("ترتيب المتوسطات القصيرة إيجابي")

    elif _safe_float(ema20.iloc[-1]) < _safe_float(ema50.iloc[-1]):
        score -= 0.10
        evidence.append("ترتيب المتوسطات القصيرة سلبي")

    recent_high = _safe_float(high.iloc[-21:-1].max())
    recent_low = _safe_float(low.iloc[-21:-1].min())

    if current > recent_high:
        score += 0.20
        evidence.append("إغلاق أعلى نطاق القمم السابقة")

    elif current < recent_low:
        score -= 0.20
        evidence.append("إغلاق أسفل نطاق القيعان السابقة")

    candle_open = _safe_float(open_price.iloc[-1])
    candle_high = _safe_float(high.iloc[-1])
    candle_low = _safe_float(low.iloc[-1])

    candle_range = max(candle_high - candle_low, 0.00000001)
    body = abs(current - candle_open)

    upper_wick = candle_high - max(current, candle_open)
    lower_wick = min(current, candle_open) - candle_low

    if lower_wick > body * 1.5 and lower_wick > atr * 0.15:
        score += 0.10
        evidence.append("ذيل سفلي ملحوظ")

    if upper_wick > body * 1.5 and upper_wick > atr * 0.15:
        score -= 0.10
        evidence.append("ذيل علوي ملحوظ")

    score = max(-1.0, min(1.0, score))

    if score >= DIRECTION_THRESHOLD:
        bias = "صعودي"
    elif score <= -DIRECTION_THRESHOLD:
        bias = "هبوطي"
    else:
        bias = "محايد"

    confidence = abs(score)

    pivot_highs, pivot_lows = _pivot_points(frame)

    support_candidates = [
        item["price"]
        for item in pivot_lows
        if item["price"] <= current
    ]

    resistance_candidates = [
        item["price"]
        for item in pivot_highs
        if item["price"] >= current
    ]

    volatility_pct = (atr / current) * 100

    if current > _safe_float(ema50.iloc[-1]) and _safe_float(ema20.iloc[-1]) > _safe_float(ema50.iloc[-1]):
        structure = "بنية صاعدة نسبياً"

    elif current < _safe_float(ema50.iloc[-1]) and _safe_float(ema20.iloc[-1]) < _safe_float(ema50.iloc[-1]):
        structure = "بنية هابطة نسبياً"

    else:
        structure = "بنية مختلطة أو انتقالية"

    try:
        last_time = str(frame.iloc[-1]["index"])
    except Exception:
        last_time = None

    return {
        "timeframe": timeframe,
        "bias": bias,
        "confidence": round(confidence, 4),
        "signed_strength": round(score, 4),
        "last_close": current,
        "atr": atr,
        "volatility_pct": round(volatility_pct, 4),
        "structure": structure,
        "evidence": evidence,
        "points": [
            {
                "name": "EMA20",
                "value": _safe_float(ema20.iloc[-1])
            },
            {
                "name": "EMA50",
                "value": _safe_float(ema50.iloc[-1])
            },
            {
                "name": "EMA200",
                "value": _safe_float(ema200.iloc[-1])
            }
        ],
        "support_candidates": support_candidates,
        "resistance_candidates": resistance_candidates,
        "last_time": last_time,
        "warning": None
    }


def _cluster_levels(levels, tolerance):
    valid = sorted(
        _safe_float(level)
        for level in levels
        if _safe_float(level) > 0
    )

    if not valid:
        return []

    clusters = []

    for price in valid:
        if not clusters:
            clusters.append([price])
            continue

        center = float(np.mean(clusters[-1]))

        if abs(price - center) <= tolerance:
            clusters[-1].append(price)
        else:
            clusters.append([price])

    results = []

    for cluster in clusters:
        results.append({
            "price": float(np.mean(cluster)),
            "touches": len(cluster),
            "strength": round(
                min(1.0, len(cluster) / 5.0),
                3
            )
        })

    return results

def _calculate_group(group_name, per_frame):
    requested_frames = TIMEFRAME_GROUPS.get(group_name, [])
    results = []

    for timeframe in requested_frames:
        result = per_frame.get(timeframe)

        if isinstance(result, dict) and result.get("last_close") is not None:
            results.append(result)

    if not results:
        return {
            "name": group_name,
            "direction": "غير متاح",
            "score": 0.0,
            "agreement": 0.0,
            "available": 0,
            "requested": len(requested_frames),
            "bullish": 0,
            "bearish": 0,
            "neutral": 0,
            "timeframes": []
        }

    weighted_score = 0.0
    total_weight = 0.0
    bullish = 0
    bearish = 0
    neutral = 0

    for result in results:
        timeframe = result["timeframe"]
        weight = TIMEFRAME_WEIGHTS.get(timeframe, 1)
        strength = _safe_float(result.get("signed_strength"))

        weighted_score += strength * weight
        total_weight += weight

        if strength >= DIRECTION_THRESHOLD:
            bullish += 1
        elif strength <= -DIRECTION_THRESHOLD:
            bearish += 1
        else:
            neutral += 1

    score = weighted_score / total_weight if total_weight else 0.0

    if score >= DIRECTION_THRESHOLD:
        direction = "صعودي"
    elif score <= -DIRECTION_THRESHOLD:
        direction = "هبوطي"
    else:
        direction = "محايد"

    directional_count = bullish + bearish
    agreement = (
        max(bullish, bearish) / directional_count
        if directional_count else 0.0
    )

    return {
        "name": group_name,
        "direction": direction,
        "score": round(score, 4),
        "agreement": round(agreement, 4),
        "available": len(results),
        "requested": len(requested_frames),
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "timeframes": [
            result["timeframe"]
            for result in results
        ]
    }


def _classify_consensus(groups):
    weighted_score = 0.0
    total_weight = 0.0

    for group_name, group_weight in GROUP_WEIGHTS.items():
        group = groups.get(group_name, {})

        if not group or group.get("available", 0) == 0:
            continue

        weighted_score += (
            _safe_float(group.get("score")) * group_weight
        )

        total_weight += group_weight

    if total_weight == 0:
        return "غير متاح", 0.0, "بيانات غير كافية"

    final_score = weighted_score / total_weight

    if final_score >= DIRECTION_THRESHOLD:
        bias = "صعودي"
    elif final_score <= -DIRECTION_THRESHOLD:
        bias = "هبوطي"
    else:
        bias = "محايد"

    directions = [
        group.get("direction")
        for group in groups.values()
        if group.get("available", 0) > 0
    ]

    directional_groups = [
        direction
        for direction in directions
        if direction in ("صعودي", "هبوطي")
    ]

    if len(set(directional_groups)) > 1:
        state = "تعارض بين الأطر الزمنية"
    elif len(directional_groups) == 0:
        state = "توافق محايد"
    elif len(directional_groups) == 1 and len(directions) == 3:
        state = "توافق بين الأطر المتاحة"
    else:
        state = "توافق جزئي أو بيانات ناقصة"

    return bias, round(abs(final_score), 4), state


def _build_levels(pool, current_price, tolerance, side):
    if not pool or current_price <= 0:
        return []

    clustered = _cluster_levels(pool, tolerance)

    if side == "support":
        filtered = [
            item for item in clustered
            if item["price"] <= current_price
        ]

        filtered.sort(
            key=lambda item: current_price - item["price"]
        )

    else:
        filtered = [
            item for item in clustered
            if item["price"] >= current_price
        ]

        filtered.sort(
            key=lambda item: item["price"] - current_price
        )

    results = []

    for item in filtered[:8]:
        distance = abs(current_price - item["price"])

        results.append({
            "price": round(item["price"], 8),
            "touches": item["touches"],
            "strength": item["strength"],
            "distance_pct": round(
                distance / current_price * 100,
                4
            )
        })

    return results


def analyze_multitimeframe(bundle):
    if not isinstance(bundle, dict):
        return {
            "summary": {},
            "timeframes": {},
            "warnings": ["حزمة البيانات غير صالحة"]
        }

    per_frame = {}
    warnings = []

    for timeframe in TIMEFRAME_WEIGHTS:
        data = bundle.get(timeframe)

        if data is None:
            continue

        try:
            result = _single_timeframe(data, timeframe)
            per_frame[timeframe] = result

            if result.get("warning"):
                warnings.append(
                    f"{timeframe}: {result['warning']}"
                )

        except Exception as error:
            logger.exception(
                "Timeframe analysis failed: %s",
                timeframe
            )

            per_frame[timeframe] = _empty_result(
                timeframe,
                str(error)
            )

            warnings.append(
                f"{timeframe}: تعذر التحليل"
            )

    groups = {}

    for group_name in TIMEFRAME_GROUPS:
        groups[group_name] = _calculate_group(
            group_name,
            per_frame
        )

    bias, confidence, consensus_state = _classify_consensus(
        groups
    )

    valid_frames = [
        result
        for result in per_frame.values()
        if result.get("last_close") is not None
    ]

    daily_result = per_frame.get("1d")

    if daily_result and daily_result.get("last_close") is not None:
        current_price = _safe_float(
            daily_result.get("last_close")
        )
    elif valid_frames:
        current_price = _safe_float(
            valid_frames[0].get("last_close")
        )
        warnings.append(
            "السعر المرجعي مأخوذ من إطار بديل لعدم توفر إطار 1d."
        )
    else:
        current_price = 0.0

    support_pool = []
    resistance_pool = []

    for timeframe, result in per_frame.items():
        if result.get("last_close") is None:
            continue

        weight = TIMEFRAME_WEIGHTS.get(timeframe, 1)

        for level in result.get("support_candidates", []):
            support_pool.extend(
                [level] * max(1, min(weight, 3))
            )

        for level in result.get("resistance_candidates", []):
            resistance_pool.extend(
                [level] * max(1, min(weight, 3))
            )

    reference_atr = (
        _safe_float(daily_result.get("atr"))
        if daily_result else 0.0
    )

    if reference_atr <= 0 and valid_frames:
        reference_atr = _safe_float(
            valid_frames[0].get("atr")
        )

    tolerance = max(
        reference_atr * 0.25,
        current_price * 0.0001
    ) if current_price > 0 else 0.0

    support = _build_levels(
        support_pool,
        current_price,
        tolerance,
        "support"
    )

    resistance = _build_levels(
        resistance_pool,
        current_price,
        tolerance,
        "resistance"
    )

    bullish_count = sum(
        1 for result in valid_frames
        if result.get("bias") == "صعودي"
    )

    bearish_count = sum(
        1 for result in valid_frames
        if result.get("bias") == "هبوطي"
    )

    neutral_count = sum(
        1 for result in valid_frames
        if result.get("bias") == "محايد"
    )

    evidence = []

    for timeframe, result in per_frame.items():
        if result.get("last_close") is None:
            continue

        for item in result.get("evidence", []):
            evidence.append({
                "timeframe": timeframe,
                "evidence": item,
                "bias": result.get("bias")
            })

    main_direction = groups["الرئيسي"]["direction"]
    medium_direction = groups["المتوسط"]["direction"]
    short_direction = groups["القصير"]["direction"]

    conflict = (
        main_direction != medium_direction
        and main_direction not in ("غير متاح", "محايد")
        and medium_direction not in ("غير متاح", "محايد")
    )

    summary = {
        "bias": bias,
        "confidence": confidence,
        "score_type": "قوة نسبية داخلية وليست احتمال نجاح",
        "current_price_reference": current_price,
        "available_timeframes": len(valid_frames),
        "requested_timeframes": len(TIMEFRAME_WEIGHTS),
        "bullish_timeframes": bullish_count,
        "bearish_timeframes": bearish_count,
        "neutral_timeframes": neutral_count,
        "main_direction": main_direction,
        "medium_direction": medium_direction,
        "short_direction": short_direction,
        "consensus_state": consensus_state,
        "groups": groups,
        "conflict": conflict,
        "support": support,
        "resistance": resistance,
        "evidence": evidence,
        "warnings": warnings,
        "structure": (
            daily_result.get("structure")
            if daily_result else "غير محدد"
        )
    }

    return {
        "summary": summary,
        "timeframes": per_frame,
        "warnings": warnings
    }


def analyze_confluence(df):
    result = _single_timeframe(df, "1d")

    return {
        "bias": result.get("bias"),
        "confidence": result.get("confidence"),
        "signed_strength": result.get("signed_strength"),
        "evidence": result.get("evidence", []),
        "support": result.get("support_candidates", []),
        "resistance": result.get("resistance_candidates", []),
        "structure": result.get("structure")
    }

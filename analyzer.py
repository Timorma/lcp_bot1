import logging
import numpy as np
import pandas as pd
from fetcher import TIMEFRAMES

logger = logging.getLogger(__name__)

TIMEFRAME_WEIGHTS = {
    "1m": 0.5,
    "3m": 0.6,
    "5m": 0.7,
    "15m": 0.8,
    "30m": 0.9,
    "45m": 1.0,
    "1h": 1.1,
    "2h": 1.2,
    "4h": 1.4,
    "6h": 1.5,
    "8h": 1.6,
    "12h": 1.7,
    "1d": 2.0,
    "3d": 2.3,
    "1w": 2.7,
    "1mo": 3.0,
    "45d": 3.2,
    "90d": 3.5,
    "144d": 4.0
}


def _empty_result():
    return {
        "bias": "غير محدد",
        "confidence": 0.0,
        "last_close": None,
        "atr": None,
        "volatility_pct": None,
        "structure": "بيانات غير كافية",
        "support": [],
        "resistance": [],
        "evidence": [],
        "warnings": ["لا توجد بيانات كافية"]
    }


def _prepare(df):
    if df is None or len(df) < 30:
        return None

    required = [
        "Open",
        "High",
        "Low",
        "Close"
    ]

    if not all(c in df.columns for c in required):
        return None

    data = df.copy()

    for col in required:
        data[col] = pd.to_numeric(
            data[col],
            errors="coerce"
        )

    data = data.dropna(
        subset=required
    ).sort_index()

    if len(data) < 30:
        return None

    return data


def _single_timeframe(df, timeframe):
    data = _prepare(df)

    if data is None:
        return None

    o = data["Open"]
    h = data["High"]
    l = data["Low"]
    c = data["Close"]

    last = float(c.iloc[-1])
    prev = c.shift(1)

    tr = pd.concat(
        [
            h - l,
            (h - prev).abs(),
            (l - prev).abs()
        ],
        axis=1
    ).max(axis=1)

    atr = float(
        tr.rolling(14).mean().iloc[-1]
    )

    if (
        not np.isfinite(last)
        or last <= 0
        or not np.isfinite(atr)
        or atr <= 0
    ):
        return None

    ema20 = c.ewm(
        span=20,
        adjust=False
    ).mean()

    ema50 = c.ewm(
        span=50,
        adjust=False
    ).mean()

    ema200 = c.ewm(
        span=200,
        adjust=False
    ).mean()

    fast = float(ema20.iloc[-1])
    slow = float(ema50.iloc[-1])
    long_value = float(ema200.iloc[-1])

    points_up = 0.0
    points_down = 0.0
    evidence = []

    if fast > slow:
        points_up += 2
        evidence.append("EMA20 أعلى EMA50")

    elif fast < slow:
        points_down += 2
        evidence.append("EMA20 أسفل EMA50")

    if last > fast:
        points_up += 1
        evidence.append("الإغلاق أعلى EMA20")

    elif last < fast:
        points_down += 1
        evidence.append("الإغلاق أسفل EMA20")

    if last > long_value:
        points_up += 1
        evidence.append("الإغلاق أعلى EMA200")

    elif last < long_value:
        points_down += 1
        evidence.append("الإغلاق أسفل EMA200")

    prior_high = float(
        h.iloc[-21:-1].max()
    )

    prior_low = float(
        l.iloc[-21:-1].min()
    )

    if last > prior_high:
        points_up += 2
        evidence.append("إغلاق أعلى قمة آخر 20 شمعة")

    elif last < prior_low:
        points_down += 2
        evidence.append("إغلاق أسفل قاع آخر 20 شمعة")

    candle_range = max(
        float(h.iloc[-1] - l.iloc[-1]),
        1e-12
    )

    upper_wick = float(
        h.iloc[-1] - max(o.iloc[-1], c.iloc[-1])
    ) / candle_range

    lower_wick = float(
        min(o.iloc[-1], c.iloc[-1]) - l.iloc[-1]
    ) / candle_range

    if lower_wick >= 0.45 and c.iloc[-1] > o.iloc[-1]:
        points_up += 0.75
        evidence.append("رفض سعري بفتيل سفلي")

    if upper_wick >= 0.45 and c.iloc[-1] < o.iloc[-1]:
        points_down += 0.75
        evidence.append("رفض سعري بفتيل علوي")

    total = points_up + points_down

    if points_up > points_down:
        bias = "صاعد"

    elif points_down > points_up:
        bias = "هابط"

    else:
        bias = "محايد"

    # درجة توازن الأدلة وليست احتمال نجاح.
    confidence = (
        abs(points_up - points_down) /
        max(total, 1.0)
    ) * 100

    volatility = atr / last * 100

    window = min(
        160,
        len(data)
    )

    recent = data.iloc[-window:]

    lows = recent["Low"]
    highs = recent["High"]

    pivot_lows = []
    pivot_highs = []

    for i in range(2, len(recent) - 2):
        low_value = float(lows.iloc[i])
        high_value = float(highs.iloc[i])

        if (
            low_value <= float(lows.iloc[i-1])
            and low_value <= float(lows.iloc[i-2])
            and low_value < float(lows.iloc[i+1])
            and low_value < float(lows.iloc[i+2])
        ):
            pivot_lows.append(low_value)

        if (
            high_value >= float(highs.iloc[i-1])
            and high_value >= float(highs.iloc[i-2])
            and high_value > float(highs.iloc[i+1])
            and high_value > float(highs.iloc[i+2])
        ):
            pivot_highs.append(high_value)

    return {
        "timeframe": timeframe,
        "bias": bias,
        "confidence": round(float(confidence), 1),
        "last_close": last,
        "atr": atr,
        "volatility_pct": volatility,
        "structure": "قمم وقيعان مع اتجاه المتوسطات",
        "evidence": evidence,
        "bullish_points": points_up,
        "bearish_points": points_down,
        "support_candidates": pivot_lows[-25:],
        "resistance_candidates": pivot_highs[-25:],
        "last_time": data.index[-1].isoformat()
    }


def _cluster_levels(levels, tolerance):
    if not levels:
        return []

    values = sorted(
        float(x)
        for x in levels
        if np.isfinite(float(x)) and float(x) > 0
    )

    if not values:
        return []

    clusters = []
    current = [values[0]]

    for value in values[1:]:
        center = float(np.mean(current))

        if abs(value - center) <= tolerance:
            current.append(value)

        else:
            clusters.append(current)
            current = [value]

    clusters.append(current)

    return [
        {
            "price": round(float(np.mean(group)), 8),
            "touches": len(group)
        }
        for group in clusters
    ]


def analyze_multitimeframe(bundle):
    per_frame = {}
    support_pool = []
    resistance_pool = []

    weighted_up = 0.0
    weighted_down = 0.0
    total_weight = 0.0

    warnings = []
    available = 0

    for timeframe in TIMEFRAMES:
        item = bundle.get(timeframe, {})
        df = item.get("data")

        if df is None:
            warnings.append(
                f"{timeframe}: البيانات غير متاحة "
                f"({item.get('status', 'unknown')})"
            )
            continue

        result = _single_timeframe(
            df,
            timeframe
        )

        if result is None:
            warnings.append(
                f"{timeframe}: البيانات غير كافية للتحليل"
            )
            continue

        available += 1
        per_frame[timeframe] = result

        weight = TIMEFRAME_WEIGHTS.get(
            timeframe,
            1.0
        )

        total_weight += weight

        if result["bias"] == "صاعد":
            weighted_up += (
                weight *
                max(result["confidence"], 10) / 100
            )

        elif result["bias"] == "هابط":
            weighted_down += (
                weight *
                max(result["confidence"], 10) / 100
            )

        support_pool.extend([
            (x, weight, timeframe)
            for x in result["support_candidates"]
        ])

        resistance_pool.extend([
            (x, weight, timeframe)
            for x in result["resistance_candidates"]
        ])

    if available == 0:
        empty = _empty_result()
        empty["warnings"] = warnings or empty["warnings"]

        return {
            "summary": empty,
            "timeframes": {},
            "warnings": warnings
        }

    current_price = per_frame.get(
        "1d",
        next(iter(per_frame.values()))
    )["last_close"]

    daily_atr = per_frame.get(
        "1d",
        {}
    ).get("atr")

    tolerance = max(
        (daily_atr or current_price * 0.002) * 0.25,
        current_price * 0.0005
    )

    supports = _cluster_levels(
        [x[0] for x in support_pool],
        tolerance
    )

    resistances = _cluster_levels(
        [x[0] for x in resistance_pool],
        tolerance
    )

    def enrich(levels, pool):
        for level in levels:
            related = [
                (w, tf)
                for price, w, tf in pool
                if abs(price - level["price"]) <= tolerance
            ]

            level["timeframes"] = sorted(
                set(tf for _, tf in related)
            )

            level["strength"] = round(
                sum(w for w, _ in related),
                2
            )

        return sorted(
            levels,
            key=lambda x: x["strength"],
            reverse=True
        )

    supports = enrich(
        supports,
        support_pool
    )[:8]

    resistances = enrich(
        resistances,
        resistance_pool
    )[:8]

    net = weighted_up - weighted_down

    balance = (
        abs(net) /
        max(total_weight, 1.0)
    ) * 100

    if net > 0.08:
        final_bias = "الغلبة صاعدة"

    elif net < -0.08:
        final_bias = "الغلبة هابطة"

    else:
        final_bias = "متوازنة / متعارضة"

    bullish_frames = [
        tf
        for tf, r in per_frame.items()
        if r["bias"] == "صاعد"
    ]

    bearish_frames = [
        tf
        for tf, r in per_frame.items()
        if r["bias"] == "هابط"
    ]

    if bullish_frames and bearish_frames:
        conflict = True
        warnings.append(
            "يوجد تعارض بين بعض الفريمات؛ لا يجوز اختزاله في اتجاه واحد."
        )

    else:
        conflict = False

    evidence = [
        f"الفريمات المتاحة للتحليل: {available} من {len(TIMEFRAMES)}",
        f"الفريمات الصاعدة: {len(bullish_frames)}",
        f"الفريمات الهابطة: {len(bearish_frames)}",
        "وزن أعلى للفريمات الأكبر زمنيًا عند حساب الغلبة."
    ]

    summary = {
        "bias": final_bias,
        "confidence": round(balance, 1),
        "score_type": "توازن الأدلة الموزونة، وليس احتمال نجاح",
        "current_price_reference": current_price,
        "available_timeframes": available,
        "requested_timeframes": len(TIMEFRAMES),
        "bullish_timeframes": bullish_frames,
        "bearish_timeframes": bearish_frames,
        "conflict": conflict,
        "support": supports,
        "resistance": resistances,
        "evidence": evidence,
        "warnings": warnings,
        "structure": "متعدد الفريمات"
    }

    return {
        "summary": summary,
        "timeframes": per_frame,
        "warnings": warnings
    }


def analyze_confluence(df):
    """واجهة توافقية للتحليل بفريم واحد."""

    result = _single_timeframe(
        df,
        "1h"
    )

    if result is None:
        return _empty_result()

    return {
        "bias": result["bias"],
        "entry": None,
        "sl": None,
        "tp": None,
        "confidence": result["confidence"],
        "volatility": round(
            result["volatility_pct"],
            3
        ),
        "atr": result["atr"],
        "structure": result["structure"],
        "evidence": result["evidence"],
        "warnings": []
    }
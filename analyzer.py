
import logging
import math
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TIMEFRAME_WEIGHTS = {
"1m":1,"3m":1,"5m":2,"15m":3,"30m":3,"45m":3,
"1h":4,"2h":4,"4h":5,"6h":5,"8h":5,"12h":6,
"1d":7,"3d":8,"1w":9,"1mo":10,"45d":10,"90d":10,"144d":10
}

MAIN_GROUP = ["144d","90d","45d","1mo","1w","3d","1d"]
MEDIUM_GROUP = ["12h","8h","6h","4h","2h","1h"]
SHORT_GROUP = ["45m","30m","15m","5m","3m","1m"]

GROUP_WEIGHTS = {
"main":0.55,
"medium":0.30,
"short":0.15
}

MINIMUM_ROWS = 30
EMA_FAST = 20
EMA_MEDIUM = 50
EMA_SLOW = 200
ATR_LENGTH = 14
PIVOT_LENGTH = 5
CLUSTER_ATR_TOLERANCE = 0.35
MAX_LEVELS = 8

def _safe_float(value,default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError,ValueError,OverflowError):
        return default

def _empty_result(timeframe,error=None):
    return {
        "timeframe":timeframe,
        "available":False,
        "error":error,
        "bias":"neutral",
        "score":0.0,
        "confidence":0.0,
        "last_close":None,
        "atr":None,
        "volatility_pct":None,
        "structure":"unavailable",
        "ema":{},
        "support":[],
        "resistance":[],
        "evidence":[],
        "warnings":[error] if error else []
    }

def _prepare(data):
    if data is None:
        return None
    try:
        if isinstance(data,dict):
            data = data.get("data")
        if not isinstance(data,pd.DataFrame):
            data = pd.DataFrame(data)
        if data.empty:
            return None
        frame = data.copy()
        frame.columns = [str(c).lower().strip() for c in frame.columns]
        aliases = {
            "adj close":"close",
            "vol":"volume"
        }
        frame = frame.rename(columns=aliases)
        required = ["open","high","low","close"]
        if not all(c in frame.columns for c in required):
            return None
        if "volume" not in frame.columns:
            frame["volume"] = 0.0
        for column in required + ["volume"]:
            frame[column] = pd.to_numeric(frame[column],errors="coerce")
        frame = frame.replace([np.inf,-np.inf],np.nan)
        frame = frame.dropna(subset=required)
        frame = frame[
            (frame["high"] >= frame["low"]) &
            (frame["high"] >= frame["open"]) &
            (frame["high"] >= frame["close"]) &
            (frame["low"] <= frame["open"]) &
            (frame["low"] <= frame["close"])
        ]
        frame = frame.sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        return frame if len(frame) >= MINIMUM_ROWS else None
    except Exception:
        logger.exception("Data preparation failed")
        return None

def _calculate_atr(frame,length=ATR_LENGTH):
    high = frame["high"]
    low = frame["low"]
    close = frame["close"]
    previous_close = close.shift(1)
    ranges = pd.concat([
        high-low,
        (high-previous_close).abs(),
        (low-previous_close).abs()
    ],axis=1)
    true_range = ranges.max(axis=1)
    result = true_range.rolling(length,min_periods=length).mean()
    value = _safe_float(result.iloc[-1],0.0)
    return value if value > 0 else None

def _find_pivots(frame,length=PIVOT_LENGTH):
    high = frame["high"].to_numpy(dtype=float)
    low = frame["low"].to_numpy(dtype=float)
    pivot_highs = []
    pivot_lows = []
    for i in range(length,len(frame)-length):
        h = high[i]
        l = low[i]
        if h >= np.max(high[i-length:i+length+1]):
            pivot_highs.append((i,h))
        if l <= np.min(low[i-length:i+length+1]):
            pivot_lows.append((i,l))
    return pivot_highs,pivot_lows

def _structure(pivot_highs,pivot_lows):
    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return "insufficient_pivots",0.0
    previous_high,current_high = pivot_highs[-2][1],pivot_highs[-1][1]
    previous_low,current_low = pivot_lows[-2][1],pivot_lows[-1][1]
    high_change = current_high-previous_high
    low_change = current_low-previous_low
    if high_change > 0 and low_change > 0:
        return "higher_high_higher_low",1.0
    if high_change < 0 and low_change < 0:
        return "lower_high_lower_low",-1.0
    if high_change > 0 and low_change < 0:
        return "expanding_structure",0.0
    if high_change < 0 and low_change > 0:
        return "contracting_structure",0.0
    return "sideways_structure",0.0

def _candle_analysis(frame):
    last = frame.iloc[-1]
    candle_range = _safe_float(last["high"]-last["low"])
    if candle_range <= 0:
        return {
            "body_ratio":0.0,
            "upper_wick_ratio":0.0,
            "lower_wick_ratio":0.0,
            "candle_type":"flat"
        }
    body = abs(_safe_float(last["close"]-last["open"]))
    upper = _safe_float(last["high"]-max(last["open"],last["close"]))
    lower = _safe_float(min(last["open"],last["close"])-last["low"])
    body_ratio = body/candle_range
    upper_ratio = upper/candle_range
    lower_ratio = lower/candle_range
    candle_type = "balanced"
    if body_ratio >= 0.65:
        candle_type = "wide_body"
    elif lower_ratio >= 0.55:
        candle_type = "long_lower_wick"
    elif upper_ratio >= 0.55:
        candle_type = "long_upper_wick"
    elif body_ratio <= 0.15:
        candle_type = "small_body"
    return {
        "body_ratio":round(body_ratio,3),
        "upper_wick_ratio":round(upper_ratio,3),
        "lower_wick_ratio":round(lower_ratio,3),
        "candle_type":candle_type
    }

def _cluster_levels(candidates,atr,current_price,kind):
    if not candidates:
        return []
    tolerance = max(
        atr*CLUSTER_ATR_TOLERANCE if atr else current_price*0.001,
        current_price*0.0001
    )
    ordered = sorted(candidates,key=lambda x:x["price"])
    clusters = []
    for candidate in ordered:
        matched = next(
            (
                cluster for cluster in clusters
                if abs(candidate["price"]-cluster["weighted_price"]) <= tolerance
            ),
            None
        )
        if matched is None:
            clusters.append({
                "weighted_sum":candidate["price"]*candidate["weight"],
                "total_weight":candidate["weight"],
                "touches":1
            })
        else:
            matched["weighted_sum"] += candidate["price"]*candidate["weight"]
            matched["total_weight"] += candidate["weight"]
            matched["touches"] += 1
        for cluster in clusters:
            cluster["weighted_price"] = cluster["weighted_sum"]/cluster["total_weight"]
    output = []
    for cluster in clusters:
        price = cluster["weighted_price"]
        if kind == "support" and price >= current_price:
            continue
        if kind == "resistance" and price <= current_price:
            continue
        output.append({
            "price":round(price,8),
            "strength":round(cluster["total_weight"],2),
            "touches":cluster["touches"],
            "type":kind
        })
    output.sort(
        key=lambda x:(x["strength"],x["touches"]),
        reverse=True
    )
    return output[:MAX_LEVELS]

def _single_timeframe(data,timeframe):
    frame = _prepare(data)
    if frame is None:
        return _empty_result(timeframe,"Insufficient or invalid OHLC data")
    try:
        close = frame["close"]
        current = _safe_float(close.iloc[-1])
        if current <= 0:
            return _empty_result(timeframe,"Invalid current price")
        ema20 = close.ewm(span=EMA_FAST,adjust=False).mean()
        ema50 = close.ewm(span=EMA_MEDIUM,adjust=False).mean()
        ema200 = close.ewm(span=EMA_SLOW,adjust=False).mean()
        e20 = _safe_float(ema20.iloc[-1])
        e50 = _safe_float(ema50.iloc[-1])
        e200 = _safe_float(ema200.iloc[-1])
        score = 0.0
        evidence = []
        warnings = []
        comparisons = [
            (current,e20,0.20,"Price vs EMA20"),
            (current,e50,0.25,"Price vs EMA50"),
            (current,e200,0.25,"Price vs EMA200"),
            (e20,e50,0.15,"EMA20 vs EMA50"),
            (e50,e200,0.15,"EMA50 vs EMA200")
        ]
        for left,right,weight,label in comparisons:
            if left > right:
                score += weight
                evidence.append(label+": above")
            elif left < right:
                score -= weight
                evidence.append(label+": below")
        if len(frame) >= 21:
            prior_high = _safe_float(frame["high"].iloc[-21:-1].max())
            prior_low = _safe_float(frame["low"].iloc[-21:-1].min())
            if current > prior_high:
                score += 0.15
                evidence.append("Close above previous 20-bar high")
            elif current < prior_low:
                score -= 0.15
                evidence.append("Close below previous 20-bar low")
        atr = _calculate_atr(frame)
        candle = _candle_analysis(frame)
        pivot_highs,pivot_lows = _find_pivots(frame)
        structure,structure_score = _structure(pivot_highs,pivot_lows)
        score += structure_score*0.20
        if structure_score > 0:
            evidence.append("Higher-high and higher-low structure")
        elif structure_score < 0:
            evidence.append("Lower-high and lower-low structure")
        else:
            evidence.append("Structure is mixed or unclear")
        if candle["candle_type"] == "long_lower_wick":
            evidence.append("Long lower wick observed")
        elif candle["candle_type"] == "long_upper_wick":
            evidence.append("Long upper wick observed")
        volatility_pct = (
            atr/current*100
            if atr is not None and current > 0
            else None
        )
        if len(frame) < EMA_SLOW:
            warnings.append("EMA200 has limited historical warm-up")
        if atr is None:
            warnings.append("ATR unavailable")
        score = max(-1.0,min(1.0,score))
        bias = (
            "bullish" if score >= 0.18
            else "bearish" if score <= -0.18
            else "neutral"
        )
        support_candidates = [
            {"price":price,"weight":1.0}
            for _,price in pivot_lows
        ]
        resistance_candidates = [
            {"price":price,"weight":1.0}
            for _,price in pivot_highs
        ]
        if len(frame) >= 21:
            support_candidates.append({
                "price":_safe_float(frame["low"].iloc[-21:-1].min()),
                "weight":0.8
            })
            resistance_candidates.append({
                "price":_safe_float(frame["high"].iloc[-21:-1].max()),
                "weight":0.8
            })
        support = _cluster_levels(
            support_candidates,atr,current,"support"
        )
        resistance = _cluster_levels(
            resistance_candidates,atr,current,"resistance"
        )
        last_time = (
            frame.index[-1].isoformat()
            if hasattr(frame.index[-1],"isoformat")
            else str(frame.index[-1])
        )
        return {
            "timeframe":timeframe,
            "available":True,
            "error":None,
            "bias":bias,
            "score":round(score,4),
            "confidence":round(abs(score),4),
            "last_close":current,
            "last_time":last_time,
            "rows":len(frame),
            "atr":atr,
            "volatility_pct":round(volatility_pct,4) if volatility_pct is not None else None,
            "structure":structure,
            "ema":{
                "ema20":e20,
                "ema50":e50,
                "ema200":e200
            },
            "candle":candle,
            "support":support,
            "resistance":resistance,
            "evidence":evidence,
            "warnings":warnings
        }
    except Exception as error:
        logger.exception("Timeframe analysis failed: %s",timeframe)
        return _empty_result(timeframe,str(error))

def _calculate_group(results,timeframes):
    available = [
        results[tf] for tf in timeframes
        if tf in results and results[tf].get("available")
    ]
    if not available:
        return {
            "bias":"neutral",
            "score":0.0,
            "coverage":0.0,
            "count":0,
            "directions":{"bullish":0,"bearish":0,"neutral":0}
        }
    total_weight = sum(
        TIMEFRAME_WEIGHTS.get(item["timeframe"],1)
        for item in available
    )
    weighted_score = sum(
        item["score"]*TIMEFRAME_WEIGHTS.get(item["timeframe"],1)
        for item in available
    )
    score = weighted_score/total_weight if total_weight else 0.0
    coverage = len(available)/max(len(timeframes),1)
    directions = {
        "bullish":sum(item["bias"]=="bullish" for item in available),
        "bearish":sum(item["bias"]=="bearish" for item in available),
        "neutral":sum(item["bias"]=="neutral" for item in available)
    }
    bias = (
        "bullish" if score >= 0.18
        else "bearish" if score <= -0.18
        else "neutral"
    )
    return {
        "bias":bias,
        "score":round(score,4),
        "coverage":round(coverage,4),
        "count":len(available),
        "directions":directions
    }

def _classify_consensus(groups):
    active = [
        (name,group,GROUP_WEIGHTS[name])
        for name,group in groups.items()
        if group["count"] > 0
    ]
    if not active:
        return "neutral",0.0,0.0
    total_weight = sum(item[2] for item in active)
    score = sum(
        group["score"]*weight
        for _,group,weight in active
    )/total_weight
    coverage = sum(
        group["coverage"]*weight
        for _,group,weight in active
    )/total_weight
    bias = (
        "bullish" if score >= 0.18
        else "bearish" if score <= -0.18
        else "neutral"
    )
    return bias,round(score,4),round(coverage,4)

def _build_levels(results,current_price):
    support_candidates = []
    resistance_candidates = []
    for timeframe,result in results.items():
        if not result.get("available"):
            continue
        weight = TIMEFRAME_WEIGHTS.get(timeframe,1)
        for level in result.get("support",[]):
            support_candidates.append({
                "price":level["price"],
                "weight":weight
            })
        for level in result.get("resistance",[]):
            resistance_candidates.append({
                "price":level["price"],
                "weight":weight
            })
    atr_values = [
        result["atr"] for result in results.values()
        if result.get("available") and result.get("atr")
    ]
    reference_atr = float(np.median(atr_values)) if atr_values else None
    return (
        _cluster_levels(
            support_candidates,reference_atr,current_price,"support"
        ),
        _cluster_levels(
            resistance_candidates,reference_atr,current_price,"resistance"
        )
    )

def analyze_multitimeframe(bundle):
    if not isinstance(bundle,dict):
        bundle = {}
    results = {}
    warnings = []
    for timeframe in TIMEFRAME_WEIGHTS:
        entry = bundle.get(timeframe)
        if isinstance(entry,dict) and "data" in entry:
            data = entry.get("data")
            fetch_error = entry.get("error")
        else:
            data = entry
            fetch_error = None
        if data is None:
            result = _empty_result(
                timeframe,
                str(fetch_error) if fetch_error else "Data unavailable"
            )
        else:
            result = _single_timeframe(data,timeframe)
        results[timeframe] = result
        warnings.extend(
            [f"{timeframe}: {warning}" for warning in result.get("warnings",[])]
        )
        if result.get("error"):
            warnings.append(f"{timeframe}: {result['error']}")
    groups = {
        "main":_calculate_group(results,MAIN_GROUP),
        "medium":_calculate_group(results,MEDIUM_GROUP),
        "short":_calculate_group(results,SHORT_GROUP)
    }
    bias,score,coverage = _classify_consensus(groups)
    available_results = [
        result for result in results.values()
        if result.get("available")
    ]
    price_candidates = [
        result for result in available_results
        if result["timeframe"] in ["1d","4h","1h"]
    ]
    price_source = (
        price_candidates[0]
        if price_candidates
        else available_results[0] if available_results else None
    )
    current_price = price_source["last_close"] if price_source else None
    support,resistance = (
        _build_levels(results,current_price)
        if current_price is not None
        else ([],[])
    )
    bullish_count = sum(
        result["bias"]=="bullish" for result in available_results
    )
    bearish_count = sum(
        result["bias"]=="bearish" for result in available_results
    )
    neutral_count = sum(
        result["bias"]=="neutral" for result in available_results
    )
    group_directions = {
        name:group["bias"] for name,group in groups.items()
    }
    distinct_directions = set(
        value for value in group_directions.values()
        if value != "neutral"
    )
    if len(distinct_directions) > 1:
        warnings.append("Higher and lower timeframe groups disagree")
    if coverage < 0.50:
        warnings.append("Overall timeframe data coverage is limited")
    evidence = [
        f"{name} group: {group['bias']} ({group['score']})"
        for name,group in groups.items()
        if group["count"] > 0
    ]
    summary = {
        "bias":bias,
        "confidence":round(abs(score),4),
        "score":score,
        "score_type":"normalized_research_score_not_probability",
        "coverage":coverage,
        "current_price_reference":current_price,
        "price_reference_timeframe":(
            price_source["timeframe"] if price_source else None
        ),
        "available_timeframes":len(available_results),
        "total_timeframes":len(TIMEFRAME_WEIGHTS),
        "bullish_count":bullish_count,
        "bearish_count":bearish_count,
        "neutral_count":neutral_count,
        "group_directions":group_directions,
        "support":support,
        "resistance":resistance,
        "evidence":evidence,
        "warnings":warnings,
        "structure":"mixed"
    }
    return {
        "summary":summary,
        "timeframes":results,
        "groups":groups,
        "warnings":warnings
    }

def analyze_confluence(bundle):
    analysis = analyze_multitimeframe(bundle)
    summary = analysis["summary"]
    return {
        "bias":summary["bias"],
        "score":summary["score"],
        "confidence":summary["confidence"],
        "coverage":summary["coverage"],
        "groups":analysis["groups"],
        "support":summary["support"],
        "resistance":summary["resistance"],
        "warnings":summary["warnings"]
    }

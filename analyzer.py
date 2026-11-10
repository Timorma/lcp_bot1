
import logging
import numpy as np
import pandas as pd
from fetcher import TIMEFRAMES

logger = logging.getLogger(__name__)

TIMEFRAME_WEIGHTS = {
"1m":0.5,
"3m":0.6,
"5m":0.7,
"15m":0.8,
"30m":0.9,
"45m":1.0,
"1h":1.1,
"2h":1.2,
"4h":1.4,
"6h":1.5,
"8h":1.6,
"12h":1.7,
"1d":2.0,
"3d":2.3,
"1w":2.7,
"1mo":3.0,
"45d":3.2,
"90d":3.5,
"144d":4.0
}

TIMEFRAME_GROUPS = {
"الرئيسي":["144d","90d","45d","1mo","1w","3d","1d"],
"المتوسط":["12h","8h","6h","4h","2h","1h"],
"القصير":["45m","30m","15m","5m","3m","1m"]
}

GROUP_WEIGHTS = {
"الرئيسي":0.55,
"المتوسط":0.30,
"القصير":0.15
}

DIRECTION_THRESHOLD = 0.18


def _empty_result():
    return {
        "bias":"غير محدد",
        "confidence":0.0,
        "last_close":None,
        "atr":None,
        "volatility_pct":None,
        "structure":"بيانات غير كافية",
        "support":[],
        "resistance":[],
        "evidence":[],
        "warnings":["لا توجد بيانات كافية"]
    }


def _prepare(df):
    if df is None or len(df)<30:
        return None

    required=["Open","High","Low","Close"]

    if not all(c in df.columns for c in required):
        return None

    data=df.copy()

    for col in required:
        data[col]=pd.to_numeric(data[col],errors="coerce")

    data=data.dropna(subset=required).sort_index()

    data=data[
        (data["High"]>=data["Low"]) &
        (data["Close"]>0) &
        (data["Open"]>0)
    ]

    if len(data)<30:
        return None

    return data


def _single_timeframe(df,timeframe):
    data=_prepare(df)

    if data is None:
        return None

    o=data["Open"]
    h=data["High"]
    l=data["Low"]
    c=data["Close"]

    last=float(c.iloc[-1])
    prev=c.shift(1)

    tr=pd.concat([
        h-l,
        (h-prev).abs(),
        (l-prev).abs()
    ],axis=1).max(axis=1)

    atr_value=tr.rolling(14).mean().iloc[-1]

    if not np.isfinite(atr_value) or atr_value<=0:
        return None

    atr=float(atr_value)

    points_up=0.0
    points_down=0.0
    evidence=[]

    ema20=c.ewm(span=20,adjust=False).mean()
    ema50=c.ewm(span=50,adjust=False).mean()

    fast=float(ema20.iloc[-1])
    slow=float(ema50.iloc[-1])

    if fast>slow:
        points_up+=2
        evidence.append("EMA20 أعلى EMA50")

    elif fast<slow:
        points_down+=2
        evidence.append("EMA20 أسفل EMA50")

    if last>fast:
        points_up+=1
        evidence.append("الإغلاق أعلى EMA20")

    elif last<fast:
        points_down+=1
        evidence.append("الإغلاق أسفل EMA20")

    if len(data)>=200:
        ema200=c.ewm(span=200,adjust=False).mean()
        long_value=float(ema200.iloc[-1])

        if last>long_value:
            points_up+=1.5
            evidence.append("الإغلاق أعلى EMA200")

        elif last<long_value:
            points_down+=1.5
            evidence.append("الإغلاق أسفل EMA200")
    else:
        evidence.append("EMA200 مستبعد لعدم كفاية التاريخ")

    prior_high=float(h.iloc[-21:-1].max())
    prior_low=float(l.iloc[-21:-1].min())

    if last>prior_high:
        points_up+=2
        evidence.append("إغلاق أعلى قمة آخر 20 شمعة")

    elif last<prior_low:
        points_down+=2
        evidence.append("إغلاق أسفل قاع آخر 20 شمعة")

    candle_range=max(float(h.iloc[-1]-l.iloc[-1]),1e-12)

    upper_wick=float(
        h.iloc[-1]-max(o.iloc[-1],c.iloc[-1])
    )/candle_range

    lower_wick=float(
        min(o.iloc[-1],c.iloc[-1])-l.iloc[-1]
    )/candle_range

    if lower_wick>=0.45 and c.iloc[-1]>o.iloc[-1]:
        points_up+=0.75
        evidence.append("رفض سعري بفتيل سفلي")

    if upper_wick>=0.45 and c.iloc[-1]<o.iloc[-1]:
        points_down+=0.75
        evidence.append("رفض سعري بفتيل علوي")

    total=points_up+points_down

    if points_up>points_down:
        bias="صاعد"

    elif points_down>points_up:
        bias="هابط"

    else:
        bias="محايد"

    signed_strength=(
        (points_up-points_down)/max(total,1.0)
    )

    confidence=abs(signed_strength)*100

    volatility=atr/last*100

    window=min(160,len(data))
    recent=data.iloc[-window:]

    lows=recent["Low"]
    highs=recent["High"]

    pivot_lows=[]
    pivot_highs=[]

    for i in range(2,len(recent)-2):
        low_value=float(lows.iloc[i])
        high_value=float(highs.iloc[i])

        if (
            low_value<=float(lows.iloc[i-1])
            and low_value<=float(lows.iloc[i-2])
            and low_value<float(lows.iloc[i+1])
            and low_value<float(lows.iloc[i+2])
        ):
            pivot_lows.append(low_value)

        if (
            high_value>=float(highs.iloc[i-1])
            and high_value>=float(highs.iloc[i-2])
            and high_value>float(highs.iloc[i+1])
            and high_value>float(highs.iloc[i+2])
        ):
            pivot_highs.append(high_value)

    return {
        "timeframe":timeframe,
        "bias":bias,
        "confidence":round(float(confidence),1),
        "signed_strength":round(float(signed_strength),4),
        "last_close":last,
        "atr":atr,
        "volatility_pct":volatility,
        "structure":"قمم وقيعان مع اتجاه المتوسطات",
        "evidence":evidence,
        "bullish_points":points_up,
        "bearish_points":points_down,
        "support_candidates":pivot_lows[-25:],
        "resistance_candidates":pivot_highs[-25:],
        "last_time":data.index[-1].isoformat()
    }


def _cluster_levels(levels,tolerance):
    if not levels:
        return []

    values=sorted(
        float(x)
        for x in levels
        if np.isfinite(float(x)) and float(x)>0
    )

    if not values:
        return []

    clusters=[]
    current=[values[0]]

    for value in values[1:]:
        center=float(np.mean(current))

        if abs(value-center)<=tolerance:
            current.append(value)
        else:
            clusters.append(current)
            current=[value]

    clusters.append(current)

    return [
        {
            "price":round(float(np.mean(group)),8),
            "touches":len(group)
        }
        for group in clusters
    ]


def _calculate_group(group_name,per_frame):
    frames=TIMEFRAME_GROUPS[group_name]

    score=0.0
    total_weight=0.0
    bullish=[]
    bearish=[]
    neutral=[]
    used=[]

    for timeframe in frames:
        result=per_frame.get(timeframe)

        if result is None:
            continue

        weight=TIMEFRAME_WEIGHTS.get(timeframe,1.0)

        score+=result["signed_strength"]*weight
        total_weight+=weight
        used.append(timeframe)

        if result["bias"]=="صاعد":
            bullish.append(timeframe)

        elif result["bias"]=="هابط":
            bearish.append(timeframe)

        else:
            neutral.append(timeframe)

    normalized=score/max(total_weight,1e-12)

    if total_weight==0:
        direction="غير متاح"
        agreement=0.0
    elif normalized>=DIRECTION_THRESHOLD:
        direction="صاعد"
        agreement=normalized*100
    elif normalized<=-DIRECTION_THRESHOLD:
        direction="هابط"
        agreement=abs(normalized)*100
    else:
        direction="متوازن"
        agreement=abs(normalized)*100

    return {
        "name":group_name,
        "direction":direction,
        "score":round(float(normalized),4),
        "agreement":round(float(agreement),1),
        "available":len(used),
        "requested":len(frames),
        "bullish":bullish,
        "bearish":bearish,
        "neutral":neutral,
        "timeframes":used
    }


def _classify_consensus(groups):
    main=groups["الرئيسي"]
    medium=groups["المتوسط"]
    short=groups["القصير"]

    available=[
        (name,group,GROUP_WEIGHTS[name])
        for name,group in groups.items()
        if group["direction"]!="غير متاح"
    ]

    if not available:
        return "غير محدد",0.0,"غير متاح"

    weighted_score=sum(
        group["score"]*weight
        for name,group,weight in available
    )/sum(
        weight
        for name,group,weight in available
    )

    if main["direction"]=="غير متاح":
        if weighted_score>=DIRECTION_THRESHOLD:
            return "ميل صاعد غير مؤكد",abs(weighted_score)*100,"الرئيسي غير متاح"
        if weighted_score<=-DIRECTION_THRESHOLD:
            return "ميل هابط غير مؤكد",abs(weighted_score)*100,"الرئيسي غير متاح"
        return "توازن / تعارض",abs(weighted_score)*100,"الرئيسي غير متاح"

    if main["direction"]=="متوازن":
        return "الرئيسي متوازن",abs(weighted_score)*100,"لا يوجد اتجاه رئيسي واضح"

    main_direction=main["direction"]
    main_sign=1 if main_direction=="صاعد" else -1

    medium_aligned=(
        medium["direction"]==main_direction
    )

    medium_opposed=(
        medium["direction"] in ["صاعد","هابط"]
        and not medium_aligned
    )

    short_aligned=(
        short["direction"]==main_direction
    )

    short_opposed=(
        short["direction"] in ["صاعد","هابط"]
        and not short_aligned
    )

    if medium_opposed:
        label="الرئيسي "+main_direction+" مع تعارض متوسط"
        state="تعارض متوسط"

    elif medium_aligned and short_opposed:
        label="الرئيسي "+main_direction+" مع تصحيح قصير محتمل"
        state="توافق رئيسي ومتوسط"

    elif medium_aligned and short_aligned:
        label="توافق صاعد قوي" if main_sign>0 else "توافق هابط قوي"
        state="توافق الطبقات الثلاث"

    elif medium_aligned:
        label="توافق رئيسي ومتوسط"
        state="توافق رئيسي ومتوسط"

    else:
        label="الرئيسي "+main_direction+" دون تأكيد متوسط"
        state="تأكيد متوسط غائب"

    return label,abs(weighted_score)*100,state


def _build_levels(pool,current_price,tolerance,side):
    valid=[]

    for price,weight,timeframe in pool:
        if side=="support" and price<=current_price:
            valid.append((price,weight,timeframe))

        elif side=="resistance" and price>=current_price:
            valid.append((price,weight,timeframe))

    levels=_cluster_levels(
        [x[0] for x in valid],
        tolerance
    )

    for level in levels:
        related=[
            (weight,timeframe)
            for price,weight,timeframe in valid
            if abs(price-level["price"])<=tolerance
        ]

        level["timeframes"]=sorted(
            set(tf for weight,tf in related)
        )

        level["strength"]=round(
            sum(weight for weight,tf in related),
            2
        )

        level["distance_pct"]=round(
            abs(level["price"]-current_price)/current_price*100,
            3
        )

    return sorted(
        levels,
        key=lambda x:(x["distance_pct"],-x["strength"])
    )[:8]


def analyze_multitimeframe(bundle):
    per_frame={}
    support_pool=[]
    resistance_pool=[]
    warnings=[]
    available=0

    for timeframe in TIMEFRAMES:
        item=bundle.get(timeframe,{})
        df=item.get("data")

        if df is None:
            warnings.append(
                f"{timeframe}: البيانات غير متاحة "
                f"({item.get('status','unknown')})"
            )
            continue

        result=_single_timeframe(df,timeframe)

        if result is None:
            warnings.append(
                f"{timeframe}: البيانات غير كافية للتحليل"
            )
            continue

        available+=1
        per_frame[timeframe]=result

        weight=TIMEFRAME_WEIGHTS.get(timeframe,1.0)

        support_pool.extend(
            (x,weight,timeframe)
            for x in result["support_candidates"]
        )

        resistance_pool.extend(
            (x,weight,timeframe)
            for x in result["resistance_candidates"]
        )

    if available==0:
        empty=_empty_result()
        empty["warnings"]=warnings or empty["warnings"]

        return {
            "summary":empty,
            "timeframes":{},
            "warnings":warnings
        }

    reference=per_frame.get("1d")

    if reference is None:
        reference=next(iter(per_frame.values()))

    current_price=reference["last_close"]

    daily_atr=reference.get("atr")

    tolerance=max(
        (daily_atr or current_price*0.002)*0.25,
        current_price*0.0005
    )

    supports=_build_levels(
        support_pool,
        current_price,
        tolerance,
        "support"
    )

    resistances=_build_levels(
        resistance_pool,
        current_price,
        tolerance,
        "resistance"
    )

    groups={
        name:_calculate_group(name,per_frame)
        for name in TIMEFRAME_GROUPS
    }

    final_bias,confidence,consensus_state=_classify_consensus(groups)

    bullish_frames=[
        tf for tf,result in per_frame.items()
        if result["bias"]=="صاعد"
    ]

    bearish_frames=[
        tf for tf,result in per_frame.items()
        if result["bias"]=="هابط"
    ]

    neutral_frames=[
        tf for tf,result in per_frame.items()
        if result["bias"]=="محايد"
    ]

    conflict=(
        bool(bullish_frames and bearish_frames)
    )

    main_direction=groups["الرئيسي"]["direction"]
    medium_direction=groups["المتوسط"]["direction"]
    short_direction=groups["القصير"]["direction"]

    if conflict:
        warnings.append(
            "يوجد اختلاف بين بعض الفريمات؛ تم قياسه حسب الطبقات الزمنية."
        )

    if groups["الرئيسي"]["available"]<3:
        warnings.append(
            "عدد الفريمات الرئيسية المتاحة قليل؛ الثقة في الاتجاه الرئيسي محدودة."
        )

    if groups["المتوسط"]["available"]<3:
        warnings.append(
            "عدد الفريمات المتوسطة المتاحة قليل."
        )

    if groups["القصير"]["available"]<2:
        warnings.append(
            "عدد الفريمات القصيرة المتاحة قليل."
        )

    evidence=[
        f"الفريمات المتاحة: {available} من {len(TIMEFRAMES)}",
        f"الصاعدة: {len(bullish_frames)}",
        f"الهابطة: {len(bearish_frames)}",
        f"المحايدة: {len(neutral_frames)}",
        f"الطبقة الرئيسية: {main_direction}",
        f"الطبقة المتوسطة: {medium_direction}",
        f"الطبقة القصيرة: {short_direction}",
        f"حالة التوافق: {consensus_state}"
    ]

    summary={
        "bias":final_bias,
        "confidence":round(confidence,1),
        "score_type":"قوة الميل المركب وليست احتمال نجاح",
        "current_price_reference":current_price,
        "available_timeframes":available,
        "requested_timeframes":len(TIMEFRAMES),
        "bullish_timeframes":bullish_frames,
        "bearish_timeframes":bearish_frames,
        "neutral_timeframes":neutral_frames,
        "main_direction":main_direction,
        "medium_direction":medium_direction,
        "short_direction":short_direction,
        "consensus_state":consensus_state,
        "groups":groups,
        "conflict":conflict,
        "support":supports,
        "resistance":resistances,
        "evidence":evidence,
        "warnings":warnings,
        "structure":"توافق متعدد الطبقات الزمنية"
    }

    return {
        "summary":summary,
        "timeframes":per_frame,
        "warnings":warnings
    }


def analyze_confluence(df):
    result=_single_timeframe(df,"1h")

    if result is None:
        return _empty_result()

    return {
        "bias":result["bias"],
        "entry":None,
        "sl":None,
        "tp":None,
        "confidence":result["confidence"],
        "volatility":round(result["volatility_pct"],3),
        "atr":result["atr"],
        "structure":result["structure"],
        "evidence":result["evidence"],
        "warnings":[]
    }

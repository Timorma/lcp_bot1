
import logging
import io
import math
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from matplotlib.gridspec import GridSpec

logger = logging.getLogger(__name__)

CHART_BARS = 100
CHART_DPI = 130
FIGURE_SIZE = (15,9)

TIMEFRAME_PRIORITY = [
"1d","4h","1h","1w","12h","8h","6h",
"4h","2h","30m","15m","5m","1mo"
]

def _safe_float(value,default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError,ValueError,OverflowError):
        return default

def _normalize_frame(data):
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
        frame = frame.rename(columns={
            "adj close":"close",
            "vol":"volume"
        })
        required = ["open","high","low","close"]
        if not all(c in frame.columns for c in required):
            return None
        if "volume" not in frame.columns:
            frame["volume"] = 0.0
        for column in required + ["volume"]:
            frame[column] = pd.to_numeric(
                frame[column],
                errors="coerce"
            )
        frame = frame.replace([np.inf,-np.inf],np.nan)
        frame = frame.dropna(subset=required)
        frame = frame[
            (frame["high"] >= frame["low"]) &
            (frame["high"] >= frame["open"]) &
            (frame["high"] >= frame["close"]) &
            (frame["low"] <= frame["open"]) &
            (frame["low"] <= frame["close"])
        ]
        if not isinstance(frame.index,pd.DatetimeIndex):
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
        frame = frame.sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        return frame
    except Exception:
        logger.exception("Chart dataframe normalization failed")
        return None

def _extract_bundle(bundle):
    if not isinstance(bundle,dict):
        return {}
    output = {}
    for timeframe,entry in bundle.items():
        if isinstance(entry,dict) and "data" in entry:
            frame = _normalize_frame(entry.get("data"))
        else:
            frame = _normalize_frame(entry)
        if frame is not None and not frame.empty:
            output[str(timeframe)] = frame
    return output

def _select_timeframe(frames,preferred=None):
    if preferred and preferred in frames:
        return preferred
    for timeframe in TIMEFRAME_PRIORITY:
        if timeframe in frames:
            return timeframe
    return next(iter(frames),None)

def _extract_levels(analysis,kind):
    if not isinstance(analysis,dict):
        return []
    summary = analysis.get("summary",{})
    if not isinstance(summary,dict):
        return []
    levels = summary.get(kind,[])
    if not isinstance(levels,list):
        return []
    output = []
    for level in levels:
        if isinstance(level,dict):
            price = _safe_float(level.get("price"))
            strength = _safe_float(level.get("strength"),0.0)
            if price is not None and price > 0:
                output.append({
                    "price":price,
                    "strength":strength
                })
    return output

def _format_price(value):
    if value is None:
        return "N/A"
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")

def _draw_candles(axis,frame):
    dates = mdates.date2num(frame.index.to_pydatetime())
    if len(dates) > 1:
        spacing = float(np.median(np.diff(dates)))
        width = max(spacing*0.65,0.0001)
    else:
        width = 0.02
    for date_value,(_,row) in zip(dates,frame.iterrows()):
        opening = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        rising = close >= opening
        candle_color = "#18a878" if rising else "#df5252"
        axis.vlines(
            date_value,
            low,
            high,
            color=candle_color,
            linewidth=0.9,
            alpha=0.95
        )
        bottom = min(opening,close)
        height = abs(close-opening)
        if height == 0:
            height = max(abs(close)*0.00001,0.0000001)
        axis.add_patch(
            Rectangle(
                (date_value-width/2,bottom),
                width,
                height,
                facecolor=candle_color,
                edgecolor=candle_color,
                linewidth=0.7,
                alpha=0.9
            )
        )

def _draw_emas(axis,frame):
    close = frame["close"]
    ema20 = close.ewm(span=20,adjust=False).mean()
    ema50 = close.ewm(span=50,adjust=False).mean()
    ema200 = close.ewm(span=200,adjust=False).mean()
    axis.plot(
        frame.index,
        ema20,
        label="EMA 20",
        linewidth=1.1,
        color="#e5a52b"
    )
    axis.plot(
        frame.index,
        ema50,
        label="EMA 50",
        linewidth=1.1,
        color="#4b9bd8"
    )
    if len(frame) >= 200:
        axis.plot(
            frame.index,
            ema200,
            label="EMA 200",
            linewidth=1.2,
            color="#9b75c9"
        )

def _draw_levels(axis,levels,label,color):
    for level in levels:
        price = level["price"]
        strength = level["strength"]
        axis.axhline(
            price,
            color=color,
            linewidth=0.9,
            linestyle="--",
            alpha=0.65
        )
        axis.annotate(
            f"{label} {_format_price(price)}",
            xy=(1,price),
            xycoords=("axes fraction","data"),
            xytext=(-5,3),
            textcoords="offset points",
            ha="right",
            va="bottom",
            fontsize=7,
            color=color
        )

def _draw_volume(axis,frame):
    volume = frame["volume"].fillna(0)
    if volume.empty or float(volume.max()) <= 0:
        axis.text(
            0.5,
            0.5,
            "Volume unavailable",
            transform=axis.transAxes,
            ha="center",
            va="center",
            fontsize=8
        )
        return
    rising = frame["close"] >= frame["open"]
    colors = np.where(rising,"#18a878","#df5252")
    axis.bar(
        frame.index,
        volume,
        color=colors,
        width=0.7,
        alpha=0.55
    )
    axis.set_ylabel("Volume",fontsize=8)

def _chart_title(symbol,timeframe,analysis,frame):
    summary = (
        analysis.get("summary",{})
        if isinstance(analysis,dict)
        else {}
    )
    bias = summary.get("bias","unavailable")
    score = summary.get("score","N/A")
    current = _safe_float(frame["close"].iloc[-1])
    return (
        f"ICB RESEARCH | {symbol} | {timeframe}\n"
        f"Reference: {_format_price(current)} | "
        f"Consensus: {bias} | Score: {score}"
    )

def _create_chart(symbol,timeframe,frame,analysis):
    frame = frame.tail(CHART_BARS).copy()
    if frame.empty:
        return None
    figure = plt.figure(
        figsize=FIGURE_SIZE,
        dpi=CHART_DPI,
        facecolor="#111827"
    )
    grid = GridSpec(
        5,
        1,
        figure=figure,
        hspace=0.08,
        height_ratios=[4.5,1]
    )
    price_axis = figure.add_subplot(grid[:4,0])
    volume_axis = figure.add_subplot(
        grid[4,0],
        sharex=price_axis
    )
    for axis in [price_axis,volume_axis]:
        axis.set_facecolor("#111827")
        axis.tick_params(colors="#d1d5db",labelsize=8)
        axis.grid(
            True,
            color="#374151",
            alpha=0.35,
            linewidth=0.5
        )
        for spine in axis.spines.values():
            spine.set_color("#374151")
    _draw_candles(price_axis,frame)
    _draw_emas(price_axis,frame)
    support = _extract_levels(analysis,"support")
    resistance = _extract_levels(analysis,"resistance")
    _draw_levels(
        price_axis,
        support[:5],
        "Support",
        "#32b88a"
    )
    _draw_levels(
        price_axis,
        resistance[:5],
        "Resistance",
        "#e06b6b"
    )
    _draw_volume(volume_axis,frame)
    price_axis.set_title(
        _chart_title(symbol,timeframe,analysis,frame),
        color="white",
        fontsize=11,
        loc="left",
        pad=12
    )
    price_axis.set_ylabel("Price",color="#d1d5db")
    price_axis.legend(
        loc="upper left",
        fontsize=7,
        facecolor="#1f2937",
        edgecolor="#374151",
        labelcolor="white"
    )
    price_axis.ticklabel_format(
        axis="y",
        style="plain",
        useOffset=False
    )
    price_axis.yaxis.set_major_formatter(
        plt.FuncFormatter(
            lambda value,position:_format_price(value)
        )
    )
    volume_axis.xaxis.set_major_formatter(
        mdates.DateFormatter("%Y-%m-%d")
    )
    volume_axis.xaxis.set_major_locator(
        mdates.AutoDateLocator(minticks=4,maxticks=8)
    )
    plt.setp(
        price_axis.get_xticklabels(),
        visible=False
    )
    volume_axis.set_xlabel(
        "Time (UTC)",
        color="#d1d5db",
        fontsize=8
    )
    figure.text(
        0.01,
        0.012,
        "ICB | Educational Research Chart | Not a trading instruction",
        color="#9ca3af",
        fontsize=7
    )
    figure.autofmt_xdate()
    output = io.BytesIO()
    figure.savefig(
        output,
        format="png",
        dpi=CHART_DPI,
        bbox_inches="tight",
        facecolor=figure.get_facecolor()
    )
    plt.close(figure)
    output.seek(0)
    output.name = f"ICB_{symbol}_{timeframe}.png"
    return output

def generate_timeframe_chart(*args,**kwargs):
    try:
        symbol = kwargs.get("symbol","ICB")
        bundle = kwargs.get("bundle")
        analysis = kwargs.get("analysis",{})
        preferred = kwargs.get("timeframe")
        if len(args) >= 1:
            if isinstance(args[0],str):
                symbol = args[0]
                if len(args) >= 2:
                    bundle = args[1]
                if len(args) >= 3:
                    analysis = args[2]
                if len(args) >= 4:
                    preferred = args[3]
            else:
                bundle = args[0]
                if len(args) >= 2:
                    analysis = args[1]
                if len(args) >= 3:
                    symbol = args[2]
                if len(args) >= 4:
                    preferred = args[3]
        if bundle is None:
            logger.error("Chart generation: bundle is missing")
            return None
        frames = _extract_bundle(bundle)
        if not frames:
            logger.error("Chart generation: no valid market data")
            return None
        timeframe = _select_timeframe(frames,preferred)
        if timeframe is None:
            return None
        return _create_chart(
            str(symbol),
            timeframe,
            frames[timeframe],
            analysis or {}
        )
    except Exception:
        logger.exception("Chart generation failed")
        return None

def generate_all_timeframe_charts(
    symbol,
    bundle,
    analysis=None,
    timeframes=None
):
    frames = _extract_bundle(bundle)
    selected = list(timeframes or frames.keys())
    charts = {}
    for timeframe in selected:
        if timeframe not in frames:
            continue
        try:
            charts[timeframe] = _create_chart(
                str(symbol),
                timeframe,
                frames[timeframe],
                analysis or {}
            )
        except Exception:
            logger.exception(
                "Failed to create chart for %s",
                timeframe
            )
    return charts


import io
import logging
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

logger = logging.getLogger(__name__)

GROUP_NAMES = ["الرئيسي", "المتوسط", "القصير"]


def _get_summary(analysis):
    if not isinstance(analysis, dict):
        return {}
    summary = analysis.get("summary", analysis)
    return summary if isinstance(summary, dict) else {}


def _safe_price(value):
    try:
        number = float(value)
        return number if pd.notna(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_text(value, default="غير محدد"):
    if value is None:
        return default
    return str(value)


def _format_group(group):
    if not isinstance(group, dict):
        return "غير متاح"
    direction = _safe_text(group.get("direction"))
    strength = group.get("strength", group.get("agreement"))
    if strength is None:
        return direction
    try:
        return f"{direction} | قوة الميل {float(strength):.1f}%"
    except (TypeError, ValueError, OverflowError):
        return direction


def _level_label(level, label):
    if not isinstance(level, dict):
        return None
    price = _safe_price(level.get("price"))
    if price is None:
        return None
    strength = level.get("strength", 0)
    distance = level.get("distance_pct")
    text = f"{label} {price:.6g} | قوة {strength}"
    try:
        if distance is not None:
            text += f" | بُعد {float(distance):.2f}%"
    except (TypeError, ValueError, OverflowError):
        pass
    return text


def _get_levels(summary, key):
    levels = summary.get(key, [])
    if not isinstance(levels, (list, tuple)):
        return []
    return [level for level in levels if isinstance(level, dict)]


def _get_group_lines(summary):
    groups = summary.get("groups", {})
    if not isinstance(groups, dict):
        groups = {}
    return [
        f"{name}: {_format_group(groups.get(name))}"
        for name in GROUP_NAMES
    ]


def generate_chart(df, analysis, symbol="ASSET", timeframe="1d"):
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    fig = None
    try:
        if "Close" not in df.columns:
            logger.error("Chart data has no Close column")
            return None
        data = df.tail(220).copy()
        data = data.sort_index()
        data = data.dropna(subset=["Close"])
        if data.empty:
            return None
        summary = _get_summary(analysis)
        fig, axes = plt.subplots(
            2,
            1,
            figsize=(14, 9),
            dpi=130,
            gridspec_kw={"height_ratios": [3.5, 1.3]}
        )
        ax = axes[0]
        info_ax = axes[1]
        close_values = pd.to_numeric(data["Close"], errors="coerce")
        valid = close_values.notna()
        data = data.loc[valid]
        close_values = close_values.loc[valid]
        if data.empty:
            return None
        ax.plot(
            data.index,
            close_values,
            label=f"{symbol} close ({timeframe})",
            linewidth=1.8,
            color="#2463a6"
        )
        supports = _get_levels(summary, "support")
        resistances = _get_levels(summary, "resistance")
        for level in supports[:5]:
            price = _safe_price(level.get("price"))
            label = _level_label(level, "Support")
            if price is not None and label:
                ax.axhline(
                    price,
                    linestyle="--",
                    linewidth=1.0,
                    alpha=0.75,
                    color="#16845b",
                    label=label
                )
        for level in resistances[:5]:
            price = _safe_price(level.get("price"))
            label = _level_label(level, "Resistance")
            if price is not None and label:
                ax.axhline(
                    price,
                    linestyle=":",
                    linewidth=1.0,
                    alpha=0.8,
                    color="#c34b4b",
                    label=label
                )
        current = _safe_price(summary.get("current_price_reference"))
        if current is None:
            current = _safe_price(close_values.iloc[-1])
        if current is not None:
            ax.axhline(
                current,
                color="#d69e2e",
                linewidth=1.2,
                alpha=0.8,
                label=f"Reference close {current:.6g}"
            )
        bias = _safe_text(summary.get("bias"))
        ax.set_title(
            f"ICB Multi-Timeframe Research | {symbol} | {timeframe}\n{bias}",
            fontsize=12,
            fontweight="bold"
        )
        ax.set_ylabel("Price")
        ax.grid(True, linestyle="--", alpha=0.25)
        if isinstance(data.index, pd.DatetimeIndex):
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            ax.tick_params(axis="x", rotation=25)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            unique = dict(zip(labels, handles))
            ax.legend(
                unique.values(),
                unique.keys(),
                loc="best",
                fontsize=7
            )
        info_ax.axis("off")
        group_lines = _get_group_lines(summary)
        consensus = _safe_text(
            summary.get("consensus_state"),
            "حالة التوافق غير متاحة"
        )
        main_direction = _safe_text(summary.get("main_direction"))
        medium_direction = _safe_text(summary.get("medium_direction"))
        short_direction = _safe_text(summary.get("short_direction"))
        info_text = (
            "ICB | MULTI-TIMEFRAME CONSENSUS\n"
            + "\n".join(group_lines)
            + "\n\n"
            + f"الحالة العامة: {consensus}\n"
            + f"الرئيسي: {main_direction} | "
            + f"المتوسط: {medium_direction} | "
            + f"القصير: {short_direction}"
        )
        info_ax.text(
            0.02,
            0.95,
            info_text,
            transform=info_ax.transAxes,
            fontsize=10,
            verticalalignment="top",
            horizontalalignment="left",
            bbox={
                "boxstyle": "round,pad=0.7",
                "facecolor": "#eef3f8",
                "edgecolor": "#9aaabd",
                "alpha": 0.95
            }
        )
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        return buf
    except Exception:
        logger.exception("Chart generation failed")
        return None
    finally:
        if fig is not None:
            plt.close(fig)


def generate_timeframe_chart(bundle, analysis, symbol):
    if not isinstance(bundle, dict) or not bundle:
        return None
    daily_entry = bundle.get("1d")
    if isinstance(daily_entry, dict):
        daily = daily_entry.get("data")
        if isinstance(daily, pd.DataFrame) and not daily.empty:
            return generate_chart(
                daily,
                analysis,
                symbol=symbol,
                timeframe="1d"
            )
    for timeframe in reversed(list(bundle.keys())):
        entry = bundle.get(timeframe)
        if not isinstance(entry, dict):
            continue
        data = entry.get("data")
        if isinstance(data, pd.DataFrame) and not data.empty:
            return generate_chart(
                data,
                analysis,
                symbol=symbol,
                timeframe=timeframe
            )
    return None

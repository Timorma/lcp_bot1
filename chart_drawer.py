
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
    except (TypeError, ValueError):
        return None


def _format_group(group):
    if not isinstance(group, dict):
        return "غير متاح"
    direction = group.get("direction", "غير محدد")
    strength = group.get("strength", group.get("agreement"))
    if strength is None:
        return str(direction)
    try:
        return f"{direction} | قوة الميل {float(strength):.1f}%"
    except (TypeError, ValueError):
        return str(direction)


def _level_label(level, label):
    price = _safe_price(level.get("price"))
    if price is None:
        return None
    strength = level.get("strength", 0)
    distance = level.get("distance_pct")
    text = f"{label} {price:.6g} | قوة {strength}"
    if distance is not None:
        try:
            text += f" | بُعد {float(distance):.2f}%"
        except (TypeError, ValueError):
            pass
    return text


def generate_chart(df, analysis, symbol="ASSET", timeframe="1d"):
    if df is None or df.empty:
        return None

    fig = None

    try:
        data = df.tail(220).copy()
        data = data.sort_index()
        data = data.dropna(subset=["Close"])

        if data.empty:
            return None

        summary = _get_summary(analysis)
        fig, (ax, info_ax) = plt.subplots(
            2,
            1,
            figsize=(14, 9),
            dpi=130,
            gridspec_kw={"height_ratios": [3.5, 1.3]}
        )

        ax.plot(
            data.index,
            data["Close"],
            label=f"{symbol} close ({timeframe})",
            linewidth=1.8,
            color="#2463a6"
        )

        supports = summary.get("support", [])
        resistances = summary.get("resistance", [])

        for level in supports[:5]:
            if not isinstance(level, dict):
                continue
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
            if not isinstance(level, dict):
                continue
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

        current = _safe_price(
            summary.get("current_price_reference")
        )

        if current is not None:
            ax.axhline(
                current,
                color="#d69e2e",
                linewidth=1.2,
                alpha=0.8,
                label=f"Reference close {current:.6g}"
            )

        ax.set_title(
            f"ICB Multi-Timeframe Research | {symbol} | {timeframe}\n"
            f"{summary.get('bias', 'غير محدد')}",
            fontsize=12,
            fontweight="bold"
        )

        ax.set_ylabel("Price")
        ax.grid(True, linestyle="--", alpha=0.25)
        ax.xaxis.set_major_formatter(
            mdates.DateFormatter("%Y-%m-%d")
        )
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

        groups = summary.get("groups", {})
        if not isinstance(groups, dict):
            groups = {}

        group_lines = [
            f"{name}: {_format_group(groups.get(name))}"
            for name in GROUP_NAMES
        ]

        consensus = summary.get(
            "consensus_state",
            "حالة التوافق غير متاحة"
        )

        main_direction = summary.get(
            "main_direction",
            "غير محدد"
        )

        medium_direction = summary.get(
            "medium_direction",
            "غير محدد"
        )

        short_direction = summary.get(
            "short_direction",
            "غير محدد"
        )

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
        fig.savefig(
            buf,
            format="png",
            bbox_inches="tight"
        )
        buf.seek(0)
        return buf

    except Exception:
        logger.exception("Chart generation failed")
        return None

    finally:
        if fig is not None:
            plt.close(fig)


def generate_timeframe_chart(bundle, analysis, symbol):
    daily = bundle.get("1d", {}).get("data")

    if daily is not None and not daily.empty:
        return generate_chart(
            daily,
            analysis,
            symbol=symbol,
            timeframe="1d"
        )

    for timeframe in reversed(list(bundle.keys())):
        data = bundle[timeframe].get("data")
        if data is not None and not data.empty:
            return generate_chart(
                data,
                analysis,
                symbol=symbol,
                timeframe=timeframe
            )

    return None

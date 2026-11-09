import io
import logging
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

logger = logging.getLogger(__name__)


def generate_chart(
    df: pd.DataFrame,
    analysis: dict,
    symbol="ASSET",
    timeframe="1d"
):
    if df is None or df.empty:
        return None

    fig = None

    try:
        data = df.tail(220).copy()

        fig, ax = plt.subplots(
            figsize=(13, 7),
            dpi=130
        )

        ax.plot(
            data.index,
            data["Close"],
            label=f"{symbol} close ({timeframe})",
            linewidth=1.8,
            color="#2463a6"
        )

        summary = analysis.get(
            "summary",
            analysis
        )

        current = summary.get(
            "current_price_reference"
        )

        for level in summary.get("support", [])[:5]:
            price = level.get("price")

            if price is not None:
                ax.axhline(
                    price,
                    linestyle="--",
                    linewidth=1.0,
                    alpha=0.8,
                    color="#16845b",
                    label=(
                        f"Support {price:.6g} | "
                        f"{level.get('strength', 0)}"
                    )
                )

        for level in summary.get("resistance", [])[:5]:
            price = level.get("price")

            if price is not None:
                ax.axhline(
                    price,
                    linestyle=":",
                    linewidth=1.0,
                    alpha=0.8,
                    color="#c34b4b",
                    label=(
                        f"Resistance {price:.6g} | "
                        f"{level.get('strength', 0)}"
                    )
                )

        if current is not None:
            ax.axhline(
                current,
                color="#d69e2e",
                linewidth=1.0,
                alpha=0.7,
                label=f"Reference close {current:.6g}"
            )

        ax.set_title(
            f"ICB Multi-Timeframe Research | {symbol} | {timeframe}\n"
            f"{summary.get('bias', 'غير محدد')}",
            fontsize=12,
            fontweight="bold"
        )

        ax.set_ylabel("Price")

        ax.grid(
            True,
            linestyle="--",
            alpha=0.25
        )

        ax.xaxis.set_major_formatter(
            mdates.DateFormatter("%Y-%m-%d")
        )

        ax.tick_params(
            axis="x",
            rotation=25
        )

        handles, labels = ax.get_legend_handles_labels()

        if handles:
            unique = dict(
                zip(labels, handles)
            )

            ax.legend(
                unique.values(),
                unique.keys(),
                loc="best",
                fontsize=8
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

        if fig is not None:
            plt.close(fig)

        return None

    finally:
        if fig is not None:
            plt.close(fig)


def generate_timeframe_chart(
    bundle,
    analysis,
    symbol
):
    daily = bundle.get(
        "1d",
        {}
    ).get("data")

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
import logging
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALIASES = {
    "XAUUSD": ["GC=F"],
    "GOLD": ["GC=F"],
    "GC": ["GC=F"],
    "XAGUSD": ["SI=F"],
    "SILVER": ["SI=F"],
    "SI": ["SI=F"],
    "OIL": ["CL=F"],
    "WTI": ["CL=F"],
    "CL": ["CL=F"],
}

def resolve_symbols(symbol):
    sym = str(symbol).strip().upper()

    if not sym:
        return []

    if sym in ALIASES:
        return ALIASES[sym]

    if "/" in sym:
        return [sym.replace("/", "") + "=X", sym.replace("/", "-")]

    if len(sym) == 6 and sym.isalpha():
        return [sym + "=X", sym]

    if sym.endswith("USDT"):
        base = sym[:-4]
        return [base + "-USD", sym]

    return [sym]


def normalize_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        price_fields = {"Open", "High", "Low", "Close", "Volume"}
        selected = None

        for level in range(df.columns.nlevels):
            values = set(df.columns.get_level_values(level))
            if {"Open", "High", "Low", "Close"}.issubset(values):
                selected = level
                break

        if selected is None:
            return None

        df.columns = df.columns.get_level_values(selected)

    df = df.loc[:, ~df.columns.duplicated()]

    return df


def validate_data(df):
    if df is None or df.empty:
        return None

    required = ["Open", "High", "Low", "Close"]

    if not all(col in df.columns for col in required):
        return None

    df = df.copy()

    if "Volume" not in df.columns:
        df["Volume"] = 0

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required)
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    valid_prices = (
        (df["Open"] > 0) &
        (df["High"] > 0) &
        (df["Low"] > 0) &
        (df["Close"] > 0) &
        (df["High"] >= df["Low"]) &
        (df["High"] >= df["Open"]) &
        (df["High"] >= df["Close"]) &
        (df["Low"] <= df["Open"]) &
        (df["Low"] <= df["Close"])
    )

    df = df.loc[valid_prices]

    if len(df) < 20:
        return None

    return df[["Open", "High", "Low", "Close", "Volume"]]


def fetch_market_data(symbol, period="60d", interval="1h"):
    candidates = resolve_symbols(symbol)

    if not candidates:
        logger.warning("Empty symbol received")
        return None

    for candidate in candidates:
        try:
            logger.info("Fetching %s", candidate)

            df = yf.download(
                candidate,
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=False
            )

            df = normalize_columns(df)

            df = validate_data(df)

            if df is not None and not df.empty:
                df.attrs["requested_symbol"] = str(symbol).upper()
                df.attrs["source_symbol"] = candidate
                df.attrs["interval"] = interval
                df.attrs["period"] = period

                logger.info(
                    "Loaded %s rows for %s from %s",
                    len(df),
                    symbol,
                    candidate
                )

                return df

        except Exception:
            logger.exception("Failed fetching %s", candidate)

    logger.warning("No valid data found for %s", symbol)
    return None
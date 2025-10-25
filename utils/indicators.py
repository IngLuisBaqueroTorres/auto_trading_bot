import pandas as pd

def calculate_rsi(series: pd.Series, window: int = 14):
    from ta.momentum import RSIIndicator
    return RSIIndicator(close=series, window=window).rsi()


def calculate_ema(series: pd.Series, window: int):
    return series.ewm(span=window, adjust=False).mean()


def calculate_bollinger_bands(series: pd.Series, window: int = 20, std_dev: int = 2):
    from ta.volatility import BollingerBands
    indicator_bb = BollingerBands(close=series, window=window, window_dev=std_dev)
    return indicator_bb.bollinger_hband(), indicator_bb.bollinger_lband()

def calculate_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Calcula el Average True Range (ATR) para medir volatilidad."""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(window=window, min_periods=1).mean()
    atr.name = 'atr'
    atr.index = df.index  # 🔥 asegura alineación con el DataFrame
    return atr

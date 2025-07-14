import pandas as pd
import ta  # usando la librería ta (más estable que ta-lib)

def calculate_rsi(series: pd.Series, window: int = 14):
    from ta.momentum import RSIIndicator
    return RSIIndicator(close=series, window=window).rsi()

def calculate_ema(series: pd.Series, window: int):
    return series.ewm(span=window, adjust=False).mean()

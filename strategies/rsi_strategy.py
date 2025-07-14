from utils.indicators import calculate_rsi
import pandas as pd

def rsi_strategy(df: pd.DataFrame) -> str | None:
    if len(df) < 15:
        return None  # No hay suficientes velas para RSI 14

    df['rsi'] = calculate_rsi(df['close'], window=14)
    latest = df.iloc[-1]

    if latest['rsi'] < 30:
        return "BUY"
    elif latest['rsi'] > 70:
        return "SELL"
    
    return None

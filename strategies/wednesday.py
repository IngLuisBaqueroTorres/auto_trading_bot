from utils.indicators import calculate_rsi, calculate_ema
import pandas as pd

from utils.logger import setup_logger
logger = setup_logger()

def wednesday_strategy(df: pd.DataFrame) -> str | None:
    # Calcula los indicadores
    df['rsi'] = calculate_rsi(df['close'], window=14)
    df['ema5'] = calculate_ema(df['close'], window=5)
    df['ema20'] = calculate_ema(df['close'], window=20)

    if len(df) < 21:
        return None  # no hay suficientes datos

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # Condición de cruce de medias
    crossed_up = prev['ema5'] < prev['ema20'] and latest['ema5'] > latest['ema20']
    crossed_down = prev['ema5'] > prev['ema20'] and latest['ema5'] < latest['ema20']

    # Última vela alcista o bajista
    bullish_candle = latest['close'] > latest['open']
    bearish_candle = latest['close'] < latest['open']

    
    # RSI extremos
    logger.debug(f"  RSI: {latest['rsi']:.2f}")
    logger.debug(f"  Cruce EMA: {crossed_up}")
    logger.debug(f"  Vela alcista: {bullish_candle}")
    if latest['rsi'] < 30 and crossed_up and bullish_candle: 
        return "BUY"
    
    if latest['rsi'] > 70 and crossed_down and bearish_candle: 
        return "SELL"

    return None

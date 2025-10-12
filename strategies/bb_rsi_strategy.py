import pandas as pd
from utils.indicators import calculate_rsi, calculate_bollinger_bands, calculate_ema, calculate_atr
from utils.logger import setup_logger

logger = setup_logger()

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Añade todos los indicadores necesarios al DataFrame."""
    df['rsi'] = calculate_rsi(df['close'], window=14)
    df['bb_high'], df['bb_low'] = calculate_bollinger_bands(df['close'], window=20)
    df['ema200'] = calculate_ema(df['close'], window=200)
    df['atr'] = calculate_atr(df, window=14)
    return df


def bb_rsi_strategy(df: pd.DataFrame, last_signal: str | None = None) -> str | None:
    """
    Estrategia BB-RSI Pro v2
    Condiciones:
    - BUY: Precio > EMA200 y RSI cruza al alza 30, confirmando fuerza alcista y cierre por encima de BB baja.
    - SELL: Precio < EMA200 y RSI cruza a la baja 70, confirmando fuerza bajista y cierre por debajo de BB alta.
    - No operar si:
        * El precio está dentro del 0.2% de la EMA200 (zona neutral).
        * La volatilidad (ancho de bandas o ATR) está muy baja.
        * Hay una señal igual consecutiva.
    """

    if len(df) < 201:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # --- Filtro: zona neutral cerca de EMA200 ---
    ema_margin = latest['ema200'] * 0.002  # 0.2%
    if abs(latest['close'] - latest['ema200']) < ema_margin:
        logger.debug("🟨 Zona neutral - Precio cerca de EMA200, sin operar.")
        return None

    # --- Filtro: volatilidad mínima (mercado plano) ---
    bb_width = (latest['bb_high'] - latest['bb_low']) / latest['close']
    if bb_width < 0.004:  # 0.4%
        logger.debug("📏 Volatilidad muy baja (mercado lateral).")
        return None

    # --- Determinar tendencia ---
    is_uptrend = latest['close'] > latest['ema200']
    is_downtrend = latest['close'] < latest['ema200']

    # --- Confirmación RSI (momentum) ---
    rsi_cross_up = prev['rsi'] < 30 and latest['rsi'] > 30
    rsi_cross_down = prev['rsi'] > 70 and latest['rsi'] < 70

    # --- Confirmación de cierre respecto a Bollinger ---
    close_above_bb_low = latest['close'] > latest['bb_low']
    close_below_bb_high = latest['close'] < latest['bb_high']

    # --- Señales (con control de reentrada) ---
    if is_uptrend and rsi_cross_up and close_above_bb_low:
        if last_signal != "BUY":
            logger.info(f"📈 BUY señal confirmada | RSI={latest['rsi']:.2f} | Cierre={latest['close']:.5f} | ATR={latest['atr']:.5f}")
            return "BUY"
        else:
            logger.debug("🚫 BUY ignorada (ya estábamos comprados).")

    if is_downtrend and rsi_cross_down and close_below_bb_high:
        if last_signal != "SELL":
            logger.info(f"📉 SELL señal confirmada | RSI={latest['rsi']:.2f} | Cierre={latest['close']:.5f} | ATR={latest['atr']:.5f}")
            return "SELL"
        else:
            logger.debug("🚫 SELL ignorada (ya estábamos vendidos).")

    return None

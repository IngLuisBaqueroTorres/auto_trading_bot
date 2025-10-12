# strategies/bb_rsi_otc.py
"""
bb_rsi_otc.py
Versión relajada pero inteligente de bb_rsi_strategy:
- Usa scoring (varias condiciones suman puntos) en vez de AND estrictos.
- Mantiene los mismos indicadores (rsi, bb_high, bb_low, ema200, atr).
- Ajustes y pesos fáciles de modificar.
- Devuelve "BUY", "SELL" o None (compatible con tu loop principal que usa BUY/SELL).
"""

from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from utils.indicators import calculate_rsi, calculate_bollinger_bands, calculate_ema, calculate_atr
from utils.logger import setup_logger

logger = setup_logger()

# ----------------- PARÁMETROS -----------------
# thresholds (relajados, pensados para OTC)
RSI_OVERSOLD = 35        # punto "fuerte" de sobreventa
RSI_OVERBOUGHT = 65      # punto "fuerte" de sobrecompra
RSI_NEAR = 50            # centro para momentum
MIN_SCORE_TO_ENTER = 0.9

# pesos de las condiciones
WEIGHTS = {
    "trend_ema": 0.8,           # estar por encima/por debajo de EMA200
    "rsi_overshoot": 0.9,       # rsi claramente en zona
    "rsi_momentum": 0.5,        # rsi subiendo/bajando
    "bb_confirmation": 0.6,     # cierre relativo a bandas
    "candle_body": 0.4,         # vela con cuerpo decente
    "atr_filter": 0.3,          # volatilidad mínima
}

# filtros adicionales
EMA_NEUTRAL_MARGIN_PCT = 0.002   # 0.2% como zona neutral (pero no bloquea totalmente)
MIN_BB_WIDTH = 0.003             # 0.3% ancho mínimo banda
MIN_ATR = 1e-8                   # evitar división por cero
FALLBACK_SCORE_MARGIN = 0.25     # si score >= MIN_SCORE - margin podemos fallback

# ------------------------------------------------

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Añade indicadores esperados por esta estrategia si no existen.
    Usa tus utilidades ya presentes en utils.indicators.
    """
    df = df.copy()
    if 'rsi' not in df.columns:
        df['rsi'] = calculate_rsi(df['close'], window=14)
    if 'bb_high' not in df.columns or 'bb_low' not in df.columns:
        bb_high, bb_low = calculate_bollinger_bands(df['close'], window=20)
        df['bb_high'] = bb_high
        df['bb_low'] = bb_low
    if 'ema200' not in df.columns:
        df['ema200'] = calculate_ema(df['close'], window=200)
    if 'atr' not in df.columns:
        df['atr'] = calculate_atr(df, window=14)
    # body & avg_body for candle strength
    df['body'] = (df['close'] - df['open']).abs()
    df['avg_body'] = df['body'].rolling(20, min_periods=1).mean()
    return df

def evaluate_score(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calcula un score para BUY o SELL basado en la última vela y varias condiciones.
    Devuelve dict con keys: side ('buy'|'sell'|None), score, reasons, last_row
    """
    if len(df) < 60:
        return {"side": None, "score": 0.0, "reasons": ["insufficient_data"], "last": None}

    last = df.iloc[-1]
    prev = df.iloc[-2]
    score_buy = 0.0
    score_sell = 0.0
    reasons_buy = []
    reasons_sell = []

    # --- volatilidad (BB width) ---
    bb_width = (last['bb_high'] - last['bb_low']) / (last['close'] + 1e-12)
    if bb_width >= MIN_BB_WIDTH:
        score_buy += WEIGHTS['atr_filter']
        score_sell += WEIGHTS['atr_filter']
        reasons_buy.append(f"bb_width_ok({bb_width:.4f})")
    else:
        reasons_buy.append(f"bb_width_low({bb_width:.4f})")
        reasons_sell.append(f"bb_width_low({bb_width:.4f})")

    # --- tendencia con EMA200 ---
    ema_margin = last['ema200'] * EMA_NEUTRAL_MARGIN_PCT
    if last['close'] > last['ema200'] + ema_margin:
        score_buy += WEIGHTS['trend_ema']
        reasons_buy.append("above_ema200")
    elif last['close'] < last['ema200'] - ema_margin:
        score_sell += WEIGHTS['trend_ema']
        reasons_sell.append("below_ema200")
    else:
        # si está en zona neutral, no penalizamos fuerte (solo no añadimos puntos)
        reasons_buy.append("near_ema200")
        reasons_sell.append("near_ema200")

    # --- RSI: oversold/overbought y momentum ---
    # BUY conditions
    if last['rsi'] <= RSI_OVERSOLD:
        score_buy += WEIGHTS['rsi_overshoot']
        reasons_buy.append(f"rsi_oversold({last['rsi']:.1f})")
    elif last['rsi'] < RSI_NEAR and last['rsi'] > prev['rsi']:
        # RSI below mid but rising -> momentum
        score_buy += WEIGHTS['rsi_momentum']
        reasons_buy.append(f"rsi_rising({prev['rsi']:.1f}->{last['rsi']:.1f})")
    elif last['rsi'] <= RSI_NEAR:
        # slight credit if near center
        score_buy += WEIGHTS['rsi_momentum'] * 0.25
        reasons_buy.append(f"rsi_near({last['rsi']:.1f})")

    # SELL conditions
    if last['rsi'] >= RSI_OVERBOUGHT:
        score_sell += WEIGHTS['rsi_overshoot']
        reasons_sell.append(f"rsi_overbought({last['rsi']:.1f})")
    elif last['rsi'] > RSI_NEAR and last['rsi'] < prev['rsi']:
        score_sell += WEIGHTS['rsi_momentum']
        reasons_sell.append(f"rsi_falling({prev['rsi']:.1f}->{last['rsi']:.1f})")
    elif last['rsi'] >= RSI_NEAR:
        score_sell += WEIGHTS['rsi_momentum'] * 0.25
        reasons_sell.append(f"rsi_near({last['rsi']:.1f})")

    # --- Bollinger confirmation: cierre relativo a bandas ---
    # For BUY we prefer close > bb_low (but allow slightly below if other scores strong)
    if last['close'] >= last['bb_low']:
        score_buy += WEIGHTS['bb_confirmation']
        reasons_buy.append("close_above_bb_low")
    else:
        # if slightly below, give partial credit
        dist_to_bb_low = (last['bb_low'] - last['close']) / (last['close'] + 1e-12)
        if dist_to_bb_low < 0.0025:  # 0.25%
            score_buy += WEIGHTS['bb_confirmation'] * 0.4
            reasons_buy.append(f"close_just_below_bb_low({dist_to_bb_low:.4f})")
        else:
            reasons_buy.append(f"close_below_bb_low({dist_to_bb_low:.4f})")

    # For SELL we prefer close <= bb_high
    if last['close'] <= last['bb_high']:
        score_sell += WEIGHTS['bb_confirmation']
        reasons_sell.append("close_below_bb_high")
    else:
        dist_to_bb_high = (last['close'] - last['bb_high']) / (last['close'] + 1e-12)
        if dist_to_bb_high < 0.0025:
            score_sell += WEIGHTS['bb_confirmation'] * 0.4
            reasons_sell.append(f"close_just_above_bb_high({dist_to_bb_high:.4f})")
        else:
            reasons_sell.append(f"close_above_bb_high({dist_to_bb_high:.4f})")

    # --- Candle body strength (in direction) ---
    body_ratio = last['body'] / (last['avg_body'] + 1e-12)
    if last['close'] > last['open'] and body_ratio >= 0.4:
        score_buy += WEIGHTS['candle_body'] * min(1.0, body_ratio)
        reasons_buy.append(f"bull_body({body_ratio:.2f})")
    elif last['close'] < last['open'] and body_ratio >= 0.4:
        score_sell += WEIGHTS['candle_body'] * min(1.0, body_ratio)
        reasons_sell.append(f"bear_body({body_ratio:.2f})")
    else:
        reasons_buy.append(f"weak_body({body_ratio:.2f})")
        reasons_sell.append(f"weak_body({body_ratio:.2f})")

    # Normalize scores roughly (not necessary exact)
    # Decide side: whichever score is higher and above MIN_SCORE_TO_ENTER (or fallback)
    result_side = None
    result_score = 0.0
    result_reasons = []

    if score_buy > score_sell:
        result_side = "BUY"
        result_score = score_buy
        result_reasons = reasons_buy
    elif score_sell > score_buy:
        result_side = "SELL"
        result_score = score_sell
        result_reasons = reasons_sell
    else:
        result_side = None
        result_score = max(score_buy, score_sell)
        result_reasons = reasons_buy if score_buy >= score_sell else reasons_sell

    return {"side": result_side, "score": float(result_score), "reasons": result_reasons, "last": last, "bb_width": float(bb_width)}

def bb_rsi_otc(df: pd.DataFrame, last_signal: Optional[str] = None) -> Optional[str]:
    """
    Interfaz principal — compatible con tu loop.
    - df: DataFrame con velas (puede no tener indicadores; la función los añade).
    - last_signal: "BUY"/"SELL" o None (evita reentrada inmediata)
    Retorna "BUY"/"SELL" o None.
    """
    # aseguramos indicadores
    df = add_indicators(df).dropna()
    eval_res = evaluate_score(df)
    side = eval_res['side']
    score = eval_res['score']
    reasons = eval_res['reasons']
    last = eval_res['last']
    bb_width = eval_res.get('bb_width', 0.0)

    if last is None:
        return None

    logger.debug(f"[OTC-EVAL] side={side} score={score:.2f} reasons={reasons} rsi={last['rsi']:.2f} bbw={bb_width:.4f} atr={last['atr']:.6f}")

    # No operar si volatilidad es prácticamente nula
    if bb_width < MIN_BB_WIDTH:
        logger.debug("🔍 OTC: BB width too low, skipping.")
        return None

    # Si hay side decidido y score suficiente -> evaluar reentrada y retornarlo
    if side is not None and score >= MIN_SCORE_TO_ENTER:
        # evitar re-entradas iguales (control externo en tu loop ya maneja tiempo, pero chequeamos igual)
        if last_signal == side:
            logger.debug(f"🚫 OTC: señal {side} ignorada porque ya es last_signal.")
            return None
        logger.info(f"✅ OTC SIGNAL: {side} | score={score:.2f} | reasons={reasons} | rsi={last['rsi']:.2f}")
        return side

    # Fallback: si score está cercano al umbral y vela confirmatoria -> permitir entrada reducida
    if side is not None and score >= (MIN_SCORE_TO_ENTER - FALLBACK_SCORE_MARGIN):
        # Reglas de fallback: vela en dirección + momentum RSI coherente
        bullish = last['close'] > last['open'] and last['rsi'] >= (prev_rsi := df.iloc[-2]['rsi'])
        bearish = last['close'] < last['open'] and last['rsi'] <= prev_rsi

        if side == "BUY" and bullish and last_signal != "BUY":
            logger.info(f"⚠️ OTC FALLBACK BUY allowed | score={score:.2f} | reasons={reasons}")
            return "BUY"
        if side == "SELL" and bearish and last_signal != "SELL":
            logger.info(f"⚠️ OTC FALLBACK SELL allowed | score={score:.2f} | reasons={reasons}")
            return "SELL"

    # Si llega aquí, no operar
    return None

# Optional: small test harness if executed directly
if __name__ == "__main__":
    # mock test data
    import numpy as np
    import pandas as pd
    rng = pd.date_range(end=pd.Timestamp.utcnow(), periods=300, freq='T')
    price = 1.1000 + np.cumsum(np.random.normal(0, 0.0003, size=len(rng)))
    df = pd.DataFrame({
        'timestamp': rng,
        'open': price + np.random.normal(0, 0.0001, len(rng)),
        'high': price + np.abs(np.random.normal(0, 0.0002, len(rng))),
        'low': price - np.abs(np.random.normal(0, 0.0002, len(rng))),
        'close': price + np.random.normal(0, 0.0001, len(rng)),
        'volume': np.random.randint(1, 20, len(rng))
    })
    df = add_indicators(df).dropna()
    signal = bb_rsi_otc(df, last_signal=None)
    logger.info(f"TEST SIGNAL: {signal}")

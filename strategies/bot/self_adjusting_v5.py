import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np

from utils.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_atr
)

logger = logging.getLogger("TradingBot")

# --- GESTIÓN DE ESTADO Y CONFIGURACIÓN DINÁMICA ---
FULL_CONFIG = None
CURRENT_PARAMS = None
INACTIVITY_COUNTER = 0
IS_RELAXED = False


# === CARGA DE CONFIGURACIÓN ===
def load_config():
    """Carga los parámetros de la estrategia desde un archivo JSON."""
    global FULL_CONFIG, CURRENT_PARAMS
    config_path = os.path.join("strategies", "bot", "self_adjusting_v5_config.json")
    with open(config_path, "r") as f:
        FULL_CONFIG = json.load(f)
        # Corregido: Usar "NORMAL_PARAMS" que es la clave correcta en el JSON
        CURRENT_PARAMS = FULL_CONFIG["NORMAL_PARAMS"]
    logger.info(f"✅ Configuración cargada desde {config_path}")


# === ACTUALIZACIÓN DINÁMICA DE PARÁMETROS ===
def update_params_for_session(current_hour: int):
    """Ajusta los parámetros según la hora o condiciones dinámicas."""
    global CURRENT_PARAMS, FULL_CONFIG

    if FULL_CONFIG is None:
        load_config()

    sessions = FULL_CONFIG.get("sessions", {})
    if not sessions:
        return

    # Ejemplo: adaptar entre horarios normales o nocturnos
    if 22 <= current_hour or current_hour < 5:
        CURRENT_PARAMS = sessions.get("night", CURRENT_PARAMS)
    else:
        CURRENT_PARAMS = sessions.get("day", CURRENT_PARAMS)


# === INDICADORES ===
def add_indicators(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """Agrega los indicadores técnicos al DataFrame."""
    # Ajustado para usar las claves en minúsculas que vienen del backtester
    df["rsi"] = calculate_rsi(df["close"], params["rsi_period"])
    df["ema_fast"] = calculate_ema(df["close"], params["ema_fast_period"])
    df["ema_slow"] = calculate_ema(df["close"], params["ema_slow_period"])
    df["ema_extra"] = calculate_ema(df["close"], params["ema_extra_period"]) # 1. EMA extra
    df["atr"] = calculate_atr(df, params["atr_period"])
    # Corregido: Desempaquetar la tupla devuelta por la función
    df["boll_upper"], df["boll_lower"] = calculate_bollinger_bands(df["close"], params["bb_window"], params["bb_stddev"])
    df["ema_slope"] = df["ema_fast"].diff(periods=params["ema_slope_lookback"]) # 2. Pendiente de EMA
    df["atr_mean"] = df["atr"].rolling(window=params["atr_mean_period"]).mean() # 5. Media de ATR
    return df


# === LÓGICA PRINCIPAL ===
def analyze(df: pd.DataFrame, current_hour: Optional[int] = None, params_from_backtest: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Analiza la tendencia y genera señales de compra/venta.
    Compatible tanto con runtime como con backtest.
    """
    global INACTIVITY_COUNTER, IS_RELAXED, CURRENT_PARAMS
    
    # Corregido: Asegurarse de que la configuración completa siempre se cargue
    if FULL_CONFIG is None:
        load_config()

    # Determinar qué parámetros usar
    if params_from_backtest:
        # El backtester está en control, usamos sus parámetros (en minúsculas)
        # y fusionamos con la configuración de filtros que no viene del backtester
        active_params = {**params_from_backtest, **FULL_CONFIG.get("FILTERS", {})}
    else:
        # En ejecución normal (main.py), cargamos y gestionamos la config
        if FULL_CONFIG is None or CURRENT_PARAMS is None:
            load_config()
        if current_hour is not None:
            update_params_for_session(current_hour)
        active_params = {**CURRENT_PARAMS, **FULL_CONFIG.get("FILTERS", {})}
    
    # Los indicadores se añaden aquí, usando los parámetros correctos
    df = add_indicators(df.copy(), active_params)
    
    # Corregido: Asegurarse de que hay suficientes datos para comparar velas
    if len(df) < active_params["ema_extra_period"]:
        return None
    last = df.iloc[-1]
    
    # --- 5. Filtro de Volatilidad (ATR) ---
    # Propuesta 2: Filtro de volatilidad más agresivo
    if active_params.get("AVOID_LOW_VOLATILITY", False):
        if last["atr"] < last["atr_mean"] * 0.85:
            logger.debug(f"📉 Volatilidad baja (ATR < 85% de la media). Descartado. ATR: {last['atr']:.5f}, Media: {last['atr_mean']:.5f}")
            return None
    
    # --- Sistema de Confirmaciones ---
    confirmations_call = 0
    confirmations_put = 0
    reasons = []
    
    # Confirmación 1: Cruce de EMAs (rápida/lenta)
    if last["ema_fast"] > last["ema_slow"]: confirmations_call += 1; reasons.append("ema_cross")
    if last["ema_fast"] < last["ema_slow"]: confirmations_put += 1; reasons.append("ema_cross")

    # Confirmación 2: Posición RSI
    if last["rsi"] < active_params["rsi_oversold"]: confirmations_call += 1; reasons.append("rsi_os")
    if last["rsi"] > active_params["rsi_overbought"]: confirmations_put += 1; reasons.append("rsi_ob")

    # Confirmación 3: Toque de Bandas de Bollinger
    if last["close"] <= last["boll_lower"]: confirmations_call += 1; reasons.append("bb_touch")
    if last["close"] >= last["boll_upper"]: confirmations_put += 1; reasons.append("bb_touch")

    # Propuesta 1: Ponderación de confirmaciones
    # Confirmación 4: Tendencia General (EMA Extra) - Cuenta doble
    if active_params.get("REQUIRE_EMA_EXTRA_ALIGNMENT", False):
        if last["close"] > last["ema_extra"]: confirmations_call += 2; reasons.append("ema_extra_trend(x2)")
        if last["close"] < last["ema_extra"]: confirmations_put += 2; reasons.append("ema_extra_trend(x2)")

    # Confirmación 5: Momentum (Pendiente de EMA) - Cuenta doble
    if active_params.get("REQUIRE_MOMENTUM", False):
        if last["ema_slope"] > 0: confirmations_call += 2; reasons.append("ema_slope_up(x2)")
        if last["ema_slope"] < 0: confirmations_put += 2; reasons.append("ema_slope_down(x2)")
    
    # --- Decisión de Señal ---
    direction = None
    required_confirmations = active_params.get("confirmations_to_enter", 3)

    if confirmations_call >= required_confirmations:
        direction = "call"
    elif confirmations_put >= required_confirmations:
        direction = "put"

    # --- 3. Ajuste adaptativo por inactividad ---
    if direction:
        INACTIVITY_COUNTER = 0
        IS_RELAXED = False
    else:
        INACTIVITY_COUNTER += 1
        if INACTIVITY_COUNTER > FULL_CONFIG["INACTIVITY_THRESHOLD_L1"]:
            active_params.update(FULL_CONFIG["RELAXED_PARAMS_L1"])
            IS_RELAXED = True
            logger.info("🧘 Modo Relajado L1 activado.")
    
    # Propuesta 4: Lógica de modo relajado más segura
    if IS_RELAXED and not direction:
        if last["rsi"] < active_params["rsi_oversold"] and last["close"] > last["ema_extra"]:
            direction = "call"
        elif last["rsi"] > active_params["rsi_overbought"] and last["close"] < last["ema_extra"]:
            direction = "put"

    if direction:
        logger.info(f"🔍 Señal detectada: {direction.upper()} | Confirmaciones: {max(confirmations_call, confirmations_put)}/{required_confirmations} | Razones: {reasons}")
        return {"direction": direction, "strength": abs(last["ema_fast"] - last["ema_slow"])}
    
    return None


# === INTERFAZ PARA BACKTEST ===
def self_adjusting_strategy_v5(df: pd.DataFrame, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Función wrapper para ser llamada por el backtester."""
    return analyze(df, params_from_backtest=params)

def get_params() -> Dict[str, Any]:
    """Devuelve los parámetros actuales del bot."""
    global CURRENT_PARAMS
    if CURRENT_PARAMS is None:
        load_config()
    return CURRENT_PARAMS


def get_name() -> str:
    """Devuelve el nombre del bot para reportes."""
    return "BOT_v5_(Híbrido_Adaptativo)"
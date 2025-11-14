# strategies/bot/self_adjusting_markI.py
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time
import logging
import os
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

# === Logger ===
logger = logging.getLogger("MarkI")

# === RUTAS DE ARCHIVOS ===
MODEL_PATH = "models/markI_model.pkl"
SCALER_PATH = "models/markI_scaler.pkl"
LOG_PATH = "data/markI_log.csv"

os.makedirs("models", exist_ok=True)
os.makedirs("data", exist_ok=True)

# === CLASE DEL BOT MARK I ===
class MarkIBot:
    def __init__(self):
        self.model = LogisticRegression(max_iter=1000)
        self.scaler = StandardScaler()
        self.X = []
        self.y = []
        self.is_trained = False
        self.min_samples = 50
        self.prob_threshold = 0.75
        self.load_model()

    def load_model(self):
        """Carga modelo y scaler si existen"""
        try:
            if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
                self.model = joblib.load(MODEL_PATH)
                self.scaler = joblib.load(SCALER_PATH)
                self.is_trained = True
                logger.info("Modelo Mark I cargado desde disco.")
        except Exception as e:
            logger.warning(f"No se pudo cargar modelo: {e}")

    def save_model(self):
        """Guarda modelo y scaler"""
        try:
            joblib.dump(self.model, MODEL_PATH)
            joblib.dump(self.scaler, SCALER_PATH)
            logger.info("Modelo Mark I guardado.")
        except Exception as e:
            logger.error(f"Error guardando modelo: {e}")

    def extract_features(self, df, signal):
        """Extrae características para ML"""
        last = df.iloc[-1]
        prev = df.iloc[-2]
        now = datetime.now()

        return np.array([[
            signal["rsi"],
            last["atr"],
            abs(last["close"] - last["open"]) / (last["atr"] + 1e-6),
            last["ema_fast"] - last["ema_slow"],
            last["close"] - last["ema_trend"],
            now.hour,
            now.weekday(),
            df["close"].pct_change().tail(5).std(),
            (last["high"] - last["low"]) / last["atr"] if last["atr"] > 0 else 0
        ]])

    def predict(self, df, signal):
        """Predice probabilidad de ganar"""
        if not self.is_trained or len(self.y) < self.min_samples:
            return None  # Aún aprendiendo

        X_new = self.extract_features(df, signal)
        X_scaled = self.scaler.transform(X_new)
        prob = self.model.predict_proba(X_scaled)[0][1]
        return prob

    def update(self, df, signal, result):
        """Actualiza el modelo con el resultado real"""
        X_new = self.extract_features(df, signal)
        self.X.append(X_new[0])
        self.y.append(1 if result == "win" else 0)

        # Guardar log
        log_df = pd.DataFrame([{
            "timestamp": datetime.now(timezone.utc),
            "direction": signal["direction"],
            "result": result,
            "prob": signal.get("ml_prob", 0),
            "rsi": signal["rsi"],
            "atr": signal["atr"]
        }])
        log_df.to_csv(LOG_PATH, mode='a', header=not os.path.exists(LOG_PATH), index=False)

        # Reentrenar cada 20 operaciones nuevas
        if len(self.y) >= self.min_samples and len(self.y) % 20 == 0:
            X_scaled = self.scaler.fit_transform(self.X)
            self.model.fit(X_scaled, self.y)
            self.save_model()
            logger.info(f"Mark I reentrenado con {len(self.y)} muestras.")


# === Instancia global del bot ML ===
mark_i_bot = MarkIBot()


# === FUNCIÓN DE ESTRATEGIA (para tu main.py) ===
def self_adjusting_strategy_markI(df: pd.DataFrame, last_signal=None, **kwargs):
    """
    BOT MARK I - Machine Learning 24/7
    - Base: EMA + RSI + ATR
    - ML: Predice probabilidad de ganar
    - Solo opera si >75% probabilidad
    """
    pair = kwargs.get("PAIR", "EURUSD")
    config = kwargs.get("config", {})

    # === 1. Indicadores base (como v6.5) ===
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_ = df["open"].values

    df["ema_fast"] = pd.Series(close).ewm(span=5, adjust=False).mean()
    df["ema_slow"] = pd.Series(close).ewm(span=21, adjust=False).mean()
    df["ema_trend"] = pd.Series(close).ewm(span=50, adjust=False).mean()
    df["rsi"] = calc_rsi(close, 14)
    df["atr"] = calc_atr(df, 14)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # === 2. Filtros robustos (como v6.5) ===
    atr_current = last["atr"]
    atr_avg = df["atr"].rolling(20).mean().iloc[-1]
    if atr_current < 0.6 * atr_avg:
        return None

    body = abs(last["close"] - last["open"])
    range_candle = high[-1] - low[-1]
    if range_candle == 0 or body < 0.3 * range_candle:
        return None

    ema_cross_up = (prev["ema_fast"] <= prev["ema_slow"]) and (last["ema_fast"] > last["ema_slow"])
    ema_cross_down = (prev["ema_fast"] >= prev["ema_slow"]) and (last["ema_fast"] < last["ema_slow"])

    rsi = last["rsi"]
    if ema_cross_up and (rsi < 55 or last["close"] <= last["open"] or last["close"] < last["ema_trend"]):
        return None
    if ema_cross_down and (rsi > 45 or last["close"] >= last["open"] or last["close"] > last["ema_trend"]):
        return None

    if not (ema_cross_up or ema_cross_down):
        return None

    direction = "call" if ema_cross_up else "put"

    # === 3. PREDICCIÓN ML ===
    temp_signal = {
        "direction": direction,
        "rsi": float(rsi),
        "atr": float(atr_current),
        "ema_fast": float(last["ema_fast"]),
        "ema_slow": float(last["ema_slow"]),
        "ema_trend": float(last["ema_trend"])
    }

    prob = mark_i_bot.predict(df, temp_signal)
    if prob is not None and prob < 0.75:
        return None  # ML dice: "No operar"

    # === 4. SEÑAL FINAL ===
    signal = {
        **temp_signal,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "pair": pair,
        "confidence": "ML ALTA" if prob is not None else "ALTA",
        "ml_prob": round(prob, 3) if prob is not None else 0.0
    }

    return signal


# === Actualizar modelo después de cada operación (llamar desde main.py) ===
def markI_update_result(df, signal, result):
    """Llamar después de cada operación cerrada"""
    if signal and "ml_prob" in signal:
        mark_i_bot.update(df, signal, result)


# === Indicadores auxiliares ===
def calc_rsi(close, period=14):
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=period, min_periods=1).mean()
    avg_loss = pd.Series(loss).rolling(window=period, min_periods=1).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    padding = [50.0] * max(0, period - 1)
    rsi_values = padding + rsi.tolist()
    return np.clip(np.array(rsi_values[-len(close):]), 0, 100)

def calc_atr(df, period=14):
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    tr0 = np.abs(high[1:] - low[1:])
    tr1 = np.abs(high[1:] - close[:-1])
    tr2 = np.abs(low[1:] - close[:-1])
    tr = np.maximum.reduce([tr0, tr1, tr2])
    atr = pd.Series(tr).rolling(window=period, min_periods=1).mean()
    padding = [atr.iloc[0]] * max(0, period - 1)
    atr_values = padding + atr.tolist()
    return np.clip(np.array(atr_values[-len(df):]), 1e-6, None)
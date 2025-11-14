# strategies/bot/self_adjusting_markII.py COMPLETO (copia y pega todo este archivo tal cual, sobrescribe el viejo)
import os
import time
import joblib
import logging
from collections import deque
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

# ---------------- Logger ----------------
logger = logging.getLogger("MarkII")

# ---------------- Rutas ----------------
MODEL_DIR = "models"
os.makedirs(MODEL_DIR, exist_ok=True)
MODEL_PATH = os.path.join(MODEL_DIR, "markII_clf.pkl")
SCALER_PATH = os.path.join(MODEL_DIR, "markII_scaler.pkl")
STATE_PATH = os.path.join(MODEL_DIR, "markII_state.pkl")
LOG_PATH = "data/markII_log.csv"
os.makedirs("data", exist_ok=True)

# ---------------- Hyperparams ----------------
INITIAL_BASE_THRESHOLD = 0.65
MIN_THRESHOLD = 0.6
MAX_THRESHOLD = 0.88
HISTORY_LEN = 200          # historial para métricas dinámicas
DYNAMIC_STD_MULT = 0.08    # cómo afecta la varianza al threshold
PARTIAL_BATCH = 1          # cuántas muestras procesar en cada update (1 = online)
CLASSES = np.array([0, 1])  # 0 = loss, 1 = win

# ---------------- Helper utils ----------------
def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))

def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# ---------------- Mark II Bot ----------------
class MarkIIBot:
    def __init__(self):
        # Clasificador incremental (SGD con loss log): aprendizaje online
        self.clf = SGDClassifier(loss="log_loss", max_iter=1000, tol=1e-4)
        self.scaler = StandardScaler()
        self.trained = False  # indica si ya se hizo al menos un partial_fit
        # Historials para threshold dinámico y métricas (SOLO de trades ejecutados)
        self.recent_results = deque(maxlen=HISTORY_LEN)   # 0/1 outcomes
        self.recent_probs = deque(maxlen=HISTORY_LEN)     # probabilidades USADAS en trades
        # Guardar contadores para estado persistente
        self.num_samples = 0
        # Intentar cargar estado
        self._load_state()

    # ---------- persistencia ----------
    def _save_state(self):
        try:
            joblib.dump(self.clf, MODEL_PATH)
            joblib.dump(self.scaler, SCALER_PATH)
            joblib.dump({
                "trained": self.trained,
                "recent_results": list(self.recent_results),
                "recent_probs": list(self.recent_probs),
                "num_samples": self.num_samples
            }, STATE_PATH)
            logger.info(f"✅ Mark II ESTADO GUARDADO → {MODEL_PATH} | {SCALER_PATH} | {STATE_PATH} | muestras: {self.num_samples}")
        except Exception as e:
            logger.error(f"❌ ERROR AL GUARDAR Mark II: {e}")

    def _load_state(self):
        try:
            if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH) and os.path.exists(STATE_PATH):
                self.clf = joblib.load(MODEL_PATH)
                self.scaler = joblib.load(SCALER_PATH)
                state = joblib.load(STATE_PATH)
                self.trained = state.get("trained", False)
                self.recent_results = deque(state.get("recent_results", []), maxlen=HISTORY_LEN)
                self.recent_probs = deque(state.get("recent_probs", []), maxlen=HISTORY_LEN)
                self.num_samples = state.get("num_samples", 0)
                logger.info(f"✅ Mark II CARGADO → muestras: {self.num_samples} | winrate reciente: {np.mean(self.recent_results):.1% if self.recent_results else 'N/A'}")
        except Exception as e:
            logger.warning(f"Mark II: no se pudo cargar estado (ok en primer run): {e}")

    # ---------- features ----------
    def _extract_features(self, df):
        """
        Extrae una fila de features a partir del DataFrame completo.
        Retorna un array 1D con las features (float).
        """
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last

        close = df["close"].values
        atr = calc_atr(df, 14)
        ema_fast = pd.Series(close).ewm(span=5, adjust=False).mean().iloc[-1]
        ema_slow = pd.Series(close).ewm(span=21, adjust=False).mean().iloc[-1]
        ema_trend = pd.Series(close).ewm(span=50, adjust=False).mean().iloc[-1]

        # base features (como Mark I)
        f_rsi = float(calc_rsi(close, 14)[-1])
        f_atr = float(atr[-1])
        f_body_rel = float(abs(last["close"] - last["open"]) / (f_atr + 1e-6))
        f_ema_diff = float(ema_fast - ema_slow)
        f_trend_dev = float(last["close"] - ema_trend)
        f_hour = float(datetime.now().hour)
        f_weekday = float(datetime.now().weekday())
        f_vol_std5 = float(pd.Series(close).pct_change().tail(5).std())
        f_range_rel = float((last["high"] - last["low"]) / (f_atr + 1e-6))

        # features extra
        f_ema_fast_over_trend = float(ema_fast / (ema_trend + 1e-9))
        f_recent_dir = float(np.sign(last["close"] - prev["close"]))
        f_mean10_minus_trend = float(pd.Series(close).tail(10).mean() - ema_trend)

        features = np.array([
            f_rsi, f_atr, f_body_rel, f_ema_diff, f_trend_dev,
            f_hour, f_weekday, f_vol_std5, f_range_rel,
            f_ema_fast_over_trend, f_recent_dir, f_mean10_minus_trend
        ], dtype=float)

        return features.reshape(1, -1)

    # ---------- predicción (probabilidad) ----------
    def predict_prob(self, df):
        """
        Retorna probabilidad (0..1). Si el modelo NO está entrenado,
        devuelve una heurística basada en reglas (para empezar a operar desde 0).
        NOTA: NO appendea a recent_probs aquí (solo en update para trades ejecutados)
        """
        X = self._extract_features(df)

        # Si scaler tiene datos, escalar.
        try:
            Xs = self.scaler.transform(X)
        except Exception:
            Xs = X

        if self.trained:
            try:
                # preferimos predict_proba
                if hasattr(self.clf, "predict_proba"):
                    prob = float(self.clf.predict_proba(Xs)[0][1])
                else:
                    score = float(self.clf.decision_function(Xs)[0])
                    prob = float(sigmoid(score))
            except Exception as e:
                logger.warning(f"Mark II: error en predict_proba, usando heurística: {e}")
                prob = self._heuristic_prob(df)
        else:
            prob = self._heuristic_prob(df)

        return float(np.clip(prob, 0.0, 1.0))

    def _heuristic_prob(self, df):
        """
        Heurística corregida: calcula EMAs previos correctamente para detectar cross real.
        """
        if len(df) < 2:
            return 0.5

        close = df["close"].values
        last = df.iloc[-1]
        atr = float(calc_atr(df, 14)[-1])
        body = abs(last["close"] - last["open"])
        rsi = float(calc_rsi(close, 14)[-1])

        # Calcular series completas para prev
        ema_fast_series = pd.Series(close).ewm(span=5, adjust=False).mean()
        ema_slow_series = pd.Series(close).ewm(span=21, adjust=False).mean()
        ema_fast = ema_fast_series.iloc[-1]
        ema_slow = ema_slow_series.iloc[-1]
        ema_fast_prev = ema_fast_series.iloc[-2]
        ema_slow_prev = ema_slow_series.iloc[-2]

        score = 0.5

        # EMA cross bonus (corregido)
        ema_cross_up = (ema_fast_prev <= ema_slow_prev) and (ema_fast > ema_slow)
        ema_cross_down = (ema_fast_prev >= ema_slow_prev) and (ema_fast < ema_slow)
        if ema_cross_up or ema_cross_down:
            score += 0.12

        # RSI confirmation bonus
        if ema_cross_up and rsi > 50:
            score += (rsi - 50) / 500.0
        if ema_cross_down and rsi < 50:
            score += (50 - rsi) / 500.0

        # body relative bonus
        score += min(0.12, (body / (atr + 1e-6)) * 0.02)

        return float(np.clip(score, 0.05, 0.95))

    # ---------- threshold dinámico ----------
    def compute_dynamic_threshold(self):
        """
        Umbral dinámico basado en varianza de resultados RECIENTES (solo trades ejecutados).
        """
        if len(self.recent_results) < 5:
            return INITIAL_BASE_THRESHOLD
        arr = np.array(self.recent_results)
        mean = arr.mean()
        std = arr.std()
        # Si inestable (alta std) → subir threshold (más conservador)
        adjustment = std * DYNAMIC_STD_MULT
        dynamic = INITIAL_BASE_THRESHOLD + adjustment if std > 0.2 else INITIAL_BASE_THRESHOLD - adjustment * 0.5
        return float(np.clip(dynamic, MIN_THRESHOLD, MAX_THRESHOLD))

    # ---------- update online ----------
    def update(self, df, signal, result):
        """
        Actualiza modelo SOLO con trades ejecutados (win/loss).
        """
        y = 1 if result == "win" else 0

        X = self._extract_features(df)

        # Actualizar scaler
        self.scaler.partial_fit(X)
        Xs = self.scaler.transform(X)

        # Partial fit clf
        try:
            if not self.trained:
                self.clf.partial_fit(Xs, [y], classes=CLASSES)
                self.trained = True
            else:
                self.clf.partial_fit(Xs, [y])
        except Exception as e:
            logger.warning(f"Mark II partial_fit falló: {e}")
            return

        # Append a historiales (SOLO trades ejecutados)
        self.recent_results.append(y)
        ml_prob_used = signal.get("ml_prob", 0.5)
        self.recent_probs.append(ml_prob_used)
        self.num_samples += 1

        # Log CSV detallado
        log_df = pd.DataFrame([{
            "timestamp": now_utc_str(),
            "pair": signal.get("pair", "UNKNOWN"),
            "direction": signal.get("direction", "UNK"),
            "result": result,
            "ml_prob_used": ml_prob_used,
            "threshold_was": signal.get("threshold", "N/A"),
            "winrate_recent": np.mean(self.recent_results)
        }])
        log_df.to_csv(LOG_PATH, mode='a', header=not os.path.exists(LOG_PATH), index=False)

        # Guardar cada 10, o flush() lo fuerza
        if self.num_samples % 10 == 0:
            self._save_state()

    def flush(self):
        """Fuerza guardado inmediato."""
        self._save_state()

# ---------------- API pública ----------------
mark_ii_bot = MarkIIBot()

def self_adjusting_strategy_markII(df: pd.DataFrame, last_signal=None, **kwargs):
    """
    Estrategia principal: filtros robustos + ML prob > dynamic threshold.
    """
    pair = kwargs.get("PAIR", "EURUSD")

    # Indicadores base en df
    close = df["close"].values
    df["ema_fast"] = pd.Series(close).ewm(span=5, adjust=False).mean()
    df["ema_slow"] = pd.Series(close).ewm(span=21, adjust=False).mean()
    df["ema_trend"] = pd.Series(close).ewm(span=50, adjust=False).mean()
    df["rsi"] = pd.Series(calc_rsi(close, 14))
    df["atr"] = calc_atr(df, 14)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Filtros robustos
    atr_current = last["atr"]
    atr_avg = df["atr"].rolling(20).mean().iloc[-1]
    if atr_avg > 0 and atr_current < 0.6 * atr_avg:
        return None

    body = abs(last["close"] - last["open"])
    range_candle = last["high"] - last["low"]
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

    temp_signal = {
        "direction": direction,
        "rsi": float(rsi),
        "atr": float(atr_current),
        "ema_fast": float(last["ema_fast"]),
        "ema_slow": float(last["ema_slow"]),
        "ema_trend": float(last["ema_trend"]),
        "pair": pair
    }

    # ML prediction
    prob = mark_ii_bot.predict_prob(df)
    threshold = mark_ii_bot.compute_dynamic_threshold()

    if prob < threshold:
        logger.debug(f"Mark II: prob {prob:.3f} < threshold {threshold:.3f} → señal rechazada")
        return None

    signal = {
        **temp_signal,
        "timestamp": now_utc_str(),
        "confidence": "ML ALTA",
        "ml_prob": round(prob, 3),
        "threshold": round(threshold, 3)
    }

    logger.info(f"✅ Mark II SEÑAL → {direction.upper()} | prob: {prob:.3f} > {threshold:.3f}")
    return signal

def markII_update_result(df, signal, result):
    """
    Llamar DESPUÉS de cada trade ejecutado.
    """
    if result not in ("win", "loss"):
        logger.info(f"Mark II: draw → NO actualiza modelo")
        return

    threshold = mark_ii_bot.compute_dynamic_threshold()
    prob_used = signal.get("ml_prob", "N/A")
    logger.info(f"🔄 Mark II UPDATE → {result.upper()} | prob usada: {prob_used} | threshold: {threshold:.3f} | muestras: {mark_ii_bot.num_samples}")
    
    mark_ii_bot.update(df, signal, result)
    mark_ii_bot.flush()  # GUARDA INMEDIATAMENTE

# ---------------- Indicadores auxiliares ----------------
def calc_rsi(close, period=14):
    if len(close) < period:
        return np.full(len(close), 50.0)
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=period, min_periods=1).mean()
    avg_loss = pd.Series(loss).rolling(window=period, min_periods=1).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    padding = np.full(max(0, period - 1), 50.0)
    rsi_values = np.concatenate([padding, rsi.values])
    return np.clip(rsi_values[-len(close):], 0, 100)

def calc_atr(df, period=14):
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    if len(close) < 2:
        return np.full(len(close), 1e-6)
    tr0 = np.abs(high[1:] - low[1:])
    tr1 = np.abs(high[1:] - close[:-1])
    tr2 = np.abs(low[1:] - close[:-1])
    tr = np.maximum.reduce([tr0, tr1, tr2])
    atr = pd.Series(tr).rolling(window=period, min_periods=1).mean()
    padding = np.full(max(0, period - 1), atr.iloc[0])
    atr_values = np.concatenate([padding, atr.values])
    return np.clip(atr_values[-len(df):], 1e-6, None)
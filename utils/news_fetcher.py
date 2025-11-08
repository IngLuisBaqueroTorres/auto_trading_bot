import requests
import time
from datetime import datetime, timezone
import logging

logger = logging.getLogger("TradingBot")

_last_fetch = 0
_cached_events = []
CACHE_MINUTES = 7
API_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def parse_time(date_str, time_str=None):
    """
    Intenta interpretar la fecha y hora del evento en diferentes formatos,
    incluyendo ISO8601 con zona horaria (ej: 2025-11-06T07:00:00-05:00)
    Retorna SIEMPRE un datetime con tzinfo UTC.
    """
    if not date_str:
        return None

    # 1️⃣ ISO con zona horaria
    if "T" in date_str:
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

    # 2️⃣ Fecha + hora separadas
    if time_str:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

    # 3️⃣ Solo fecha
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        logger.warning(f"Error parseando fecha: {date_str} ({e})")
        return None


def fetch_high_impact_news():
    """
    Obtiene eventos de alto impacto desde el feed JSON de ForexFactory,
    usando caché local por 7 minutos para evitar exceso de requests.
    Todas las fechas se normalizan a UTC-aware.
    """
    global _last_fetch, _cached_events
    now = time.time()

    # Cache local
    if now - _last_fetch < CACHE_MINUTES * 60:
        return _cached_events

    events = []
    try:
        response = requests.get(API_URL, timeout=10)
        data = response.json()
        utc_now = datetime.now(timezone.utc)

        for item in data:
            try:
                if item.get("impact", "").lower() == "high":
                    event_time = parse_time(item.get("date"), item.get("time"))
                    if not event_time:
                        continue

                    # Solo próximos 48h
                    diff = abs((event_time - utc_now).total_seconds())
                    if diff < 48 * 3600:
                        events.append({
                            "title": item.get("title", "Unknown"),
                            "currency": item.get("country", "").upper(),
                            "time": event_time,  # tz-aware
                            "impact": item.get("impact", "High"),
                        })
            except Exception as inner_err:
                logger.warning(f"⚠️ Error procesando evento: {inner_err}")

        _cached_events = events
        _last_fetch = now

        if events:
            logger.info(f"📰 Noticias de alto impacto detectadas: {len(events)} (cache {CACHE_MINUTES} min)")
        else:
            logger.info("✅ Sin noticias de alto impacto próximas.")

        return events

    except Exception as e:
        logger.warning(f"⚠️ No se pudo obtener el calendario de ForexFactory: {e}")
        return _cached_events or []


def is_relevant_for_pair(events, pair="EURUSD"):
    """Filtra noticias relacionadas con las divisas del par actual."""
    base, quote = pair[:3].upper(), pair[3:].upper()
    return [e for e in events if e["currency"] in [base, quote, "USD", "EUR"]]


def is_news_time(now, events, before=30, after=15):
    """
    Determina si hay una noticia dentro de un rango de tiempo antes o después del momento actual.
    Se asegura de que ambas fechas sean UTC-aware.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    for e in events:
        event_time = e.get("time")
        if event_time:
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            diff = (event_time - now).total_seconds() / 60
            if -after <= diff <= before:
                return True
    return False

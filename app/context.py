"""Contexto humano: hora local, feriados y clima opcional."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from .config import settings

logger = logging.getLogger(__name__)
BOLIVIA_TZ = timezone(timedelta(hours=-4))
_WEATHER_CACHE: tuple[datetime, str] | None = None


def now_local() -> datetime:
    return datetime.now(BOLIVIA_TZ)


def greeting(now: datetime | None = None) -> str:
    hour = (now or now_local()).hour
    if 5 <= hour < 12:
        return "Buenos días"
    if 12 <= hour < 19:
        return "Buenas tardes"
    return "Buenas noches"


def _load_holidays() -> dict[str, str]:
    path = Path(settings.knowledge_dir) / "feriados.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in raw.items()}
    except (OSError, ValueError):
        logger.exception("No se pudo leer %s", path)
        return {}


def holiday_today(day: date | None = None) -> str | None:
    day = day or now_local().date()
    holidays = _load_holidays()
    return holidays.get(day.isoformat()) or holidays.get(day.strftime("%m-%d"))


def _weather_label(code: int) -> str:
    if code == 0:
        return "despejado"
    if code in {1, 2, 3}:
        return "parcialmente nublado"
    if code in {45, 48}:
        return "con neblina"
    if 51 <= code <= 67:
        return "con lluvia"
    if 71 <= code <= 77:
        return "con nieve"
    if 80 <= code <= 82:
        return "con chubascos"
    if 95 <= code <= 99:
        return "con tormenta"
    return "con clima variable"


async def weather_text() -> str:
    global _WEATHER_CACHE
    if not settings.weather_enabled:
        return ""
    now = datetime.now(timezone.utc)
    if _WEATHER_CACHE and now - _WEATHER_CACHE[0] < timedelta(minutes=30):
        return _WEATHER_CACHE[1]
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": settings.weather_latitude,
                    "longitude": settings.weather_longitude,
                    "current": "temperature_2m,weather_code",
                    "timezone": "America/La_Paz",
                },
            )
            response.raise_for_status()
            current = response.json().get("current", {})
            temperature = current.get("temperature_2m")
            code = int(current.get("weather_code") or 0)
        if temperature is None:
            return ""
        text = (
            f"{settings.weather_city}: {round(float(temperature))}°C, "
            f"{_weather_label(code)}"
        )
    except Exception:  # noqa: BLE001 - el clima nunca debe romper el chat
        logger.warning("No se pudo obtener el clima", exc_info=True)
        return ""
    _WEATHER_CACHE = (now, text)
    return text


async def context_line() -> str:
    now = now_local()
    parts = [
        f"Fecha y hora local: {now.strftime('%Y-%m-%d %H:%M')}",
        f"Saludo adecuado: {greeting(now)}",
    ]
    holiday = holiday_today(now.date())
    if holiday:
        parts.append(f"Feriado hoy: {holiday}")
    weather = await weather_text()
    if weather:
        parts.append(f"Clima actual: {weather}")
    return "; ".join(parts)

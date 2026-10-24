"""Detecta la URL actual de Cloudflare Quick Tunnel y actualiza Meta.

Uso puntual:
    python -m scripts.refresh_tunnel

Vigilar cambios:
    python -m scripts.refresh_tunnel --watch

Requiere:
- cloudflared con logfile (por defecto %TEMP%/cloudflared-roho.log)
- WA_ACCESS_TOKEN y WA_APP_SECRET
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import tempfile
import time
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger("refresh_tunnel")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
LOG_DEFAULT = Path(tempfile.gettempdir()) / "cloudflared-roho.log"


def latest_url(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    matches = URL_RE.findall(text)
    return matches[-1] if matches else None


def update_env(env_path: Path, url: str) -> None:
    if not env_path.exists():
        raise SystemExit(f"No existe {env_path}")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    updated = False
    for index, line in enumerate(lines):
        if line.startswith("PUBLIC_BASE_URL="):
            lines[index] = f"PUBLIC_BASE_URL={url}"
            updated = True
            break
    if not updated:
        lines.append(f"PUBLIC_BASE_URL={url}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_url(env_path: Path) -> str:
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("PUBLIC_BASE_URL="):
            return line.split("=", 1)[1].strip()
    return ""


def app_id() -> str:
    response = httpx.get(
        "https://graph.facebook.com/v21.0/debug_token",
        params={
            "input_token": settings.wa_access_token,
            "access_token": settings.wa_access_token,
        },
        timeout=20,
    )
    response.raise_for_status()
    value = response.json().get("data", {}).get("app_id")
    if not value:
        raise SystemExit("No se pudo obtener el app_id de Meta")
    return str(value)


def verify_public_webhook(base_url: str) -> None:
    response = httpx.get(
        f"{base_url}/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.wa_verify_token,
            "hub.challenge": "tunnel-check",
        },
        timeout=20,
    )
    if response.status_code != 200 or response.text != "tunnel-check":
        raise RuntimeError(
            f"El webhook público no responde al challenge: "
            f"{response.status_code} {response.text[:200]}"
        )


def update_meta(base_url: str) -> None:
    app = app_id()
    token = f"{app}|{settings.wa_app_secret}"
    response = httpx.post(
        f"https://graph.facebook.com/v21.0/{app}/subscriptions",
        data={
            "object": "whatsapp_business_account",
            "callback_url": f"{base_url}/webhooks/whatsapp",
            "verify_token": settings.wa_verify_token,
            "fields": "messages",
            "access_token": token,
        },
        timeout=30,
    )
    response.raise_for_status()
    logger.info("Meta actualizado: %s", response.text[:300])


def refresh(
    log_path: Path, env_path: Path, *, dry_run: bool, force: bool = True
) -> str | None:
    url = latest_url(log_path)
    if not url:
        logger.warning("No encontré URL en %s", log_path)
        return None
    health = httpx.get(f"{url}/health", timeout=20)
    if health.status_code != 200:
        logger.warning("La URL %s no responde: %s", url, health.status_code)
        return None
    verify_public_webhook(url)
    logger.info("URL activa: %s", url)
    if dry_run:
        return url
    if not force and url == _env_url(env_path):
        # Sin cambios: no hace falta volver a registrar el webhook.
        return url
    update_env(env_path, url)
    update_meta(url)
    logger.info("PUBLIC_BASE_URL actualizado. Reiniciá la API para links de pago.")
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default=str(LOG_DEFAULT))
    parser.add_argument("--env", default=".env")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log_path = Path(args.log)
    env_path = Path(args.env)
    last = None
    while True:
        try:
            # La primera vuelta siempre registra: tras un reinicio el .env puede
            # coincidir con la URL nueva y Meta seguir apuntando a la vieja.
            current = refresh(
                log_path,
                env_path,
                dry_run=args.dry_run,
                force=(last is None),
            )
            if current and current != last:
                last = current
                print(json.dumps({"public_base_url": current}))
        except Exception:  # noqa: BLE001 - seguir vigilando
            logger.exception("No se pudo refrescar el túnel")
        if not args.watch:
            break
        time.sleep(max(args.interval, 15))


if __name__ == "__main__":
    main()

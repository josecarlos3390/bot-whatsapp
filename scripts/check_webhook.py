"""Chequea que el webhook público y el bot estén vivos.

Uso:
    python -m scripts.check_webhook
    python -m scripts.check_webhook --alert-webhook https://...
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from app.config import settings

# El servidor resuelve IPv4 pero su DNS IPv6 falla: getaddrinfo devuelve
# "11001" y ninguna llamada al túnel salía. Se fuerza IPv4 en este proceso.
import socket as _socket

_getaddrinfo_original = _socket.getaddrinfo


def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _getaddrinfo_original(
        host, port, _socket.AF_INET, type, proto, flags
    )


_socket.getaddrinfo = _getaddrinfo_ipv4




def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument(
        "--alert-webhook",
        default="",
        help="URL opcional para avisar si falla",
    )
    args = parser.parse_args()
    base = settings.public_base_url.rstrip("/")
    result = {"base_url": base, "ok": False, "checks": {}}
    try:
        health = httpx.get(f"{base}/health", timeout=args.timeout)
        result["checks"]["health"] = {
            "status": health.status_code,
            "body": health.text[:300],
        }
        if health.status_code == 200:
            status = httpx.get(
                f"{base}/admin/webhook/status",
                headers={"X-Admin-Token": settings.admin_token},
                timeout=args.timeout,
            )
            result["checks"]["webhook_status"] = {
                "status": status.status_code,
                "body": status.json() if status.status_code == 200 else status.text[:500],
            }
            result["ok"] = status.status_code == 200
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"] and args.alert_webhook:
        try:
            httpx.post(
                args.alert_webhook,
                json={"event": "webhook.unhealthy", **result},
                timeout=args.timeout,
            )
        except Exception:  # noqa: BLE001
            pass
    if not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

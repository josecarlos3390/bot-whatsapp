from __future__ import annotations

from pathlib import Path

from scripts.refresh_tunnel import latest_url, update_env


def test_latest_tunnel_url(tmp_path: Path):
    log = tmp_path / "cloudflared.log"
    log.write_text(
        "https://old-one.trycloudflare.com\n"
        "https://new-two.trycloudflare.com\n",
        encoding="utf-8",
    )
    assert latest_url(log) == "https://new-two.trycloudflare.com"


def test_update_env_replaces_public_url(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "APP_ENV=local\nPUBLIC_BASE_URL=https://old.trycloudflare.com\n",
        encoding="utf-8",
    )
    update_env(env, "https://new.trycloudflare.com")
    text = env.read_text(encoding="utf-8")
    assert "PUBLIC_BASE_URL=https://new.trycloudflare.com" in text
    assert "APP_ENV=local" in text
    assert "https://old.trycloudflare.com" not in text

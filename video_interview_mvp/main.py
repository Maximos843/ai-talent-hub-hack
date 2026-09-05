"""Canonical entrypoint for the Talent Interview MVP.

Normal local/Docker startup is intentionally one command:

    python main.py

The server starts on HTTPS. For local development, a short-lived self-signed
certificate is generated automatically on first start. Production can provide
TLS_CERT_FILE / TLS_KEY_FILE instead.
"""
from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import legacy_main
from legacy_main import _manager_can_view
from legacy_main import app as _legacy_app

app = _legacy_app

# Replace only the legacy routes whose contracts are now canonicalized. This
# keeps the rest of the battle-tested MVP business flow untouched.
_replaced = {
    ("/api/questions", "GET"),
    ("/api/interviews/{session_id}/complete", "POST"),
    ("/api/reports/{session_id}", "GET"),
}
_legacy_app.router.routes = [
    route
    for route in _legacy_app.router.routes
    if not any(
        getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set())
        for path, method in _replaced
    )
]

# Register DB-backed question bank and schema-safe scoring routes before the
# business app is mounted by the auth gateway.
from question_bank_routes import load_question_bank_snapshot, router as question_bank_router
from scoring_routes import router as scoring_router

legacy_main._load_question_bank = load_question_bank_snapshot
_legacy_app.include_router(question_bank_router)
_legacy_app.include_router(scoring_router)

# app.py imports ``main`` while constructing the gateway. In that case expose
# only the legacy surface to avoid recursion. On a normal ``import main`` we
# replace it with the complete gateway app.
if "app" not in sys.modules:
    from app import app as app


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CERT_DIR = BASE_DIR / ".certs"
DEFAULT_CERT_FILE = DEFAULT_CERT_DIR / "localhost-cert.pem"
DEFAULT_KEY_FILE = DEFAULT_CERT_DIR / "localhost-key.pem"


def _tls_alt_name(host: str) -> str:
    try:
        ipaddress.ip_address(host)
        return f"IP.2={host}"
    except ValueError:
        return f"DNS.2={host}"


def ensure_tls_certificate() -> tuple[Path, Path]:
    """Resolve configured TLS files or generate a local development pair."""
    configured_cert = os.getenv("TLS_CERT_FILE", "").strip()
    configured_key = os.getenv("TLS_KEY_FILE", "").strip()
    if configured_cert or configured_key:
        if not configured_cert or not configured_key:
            raise RuntimeError("Укажите одновременно TLS_CERT_FILE и TLS_KEY_FILE")
        cert_file = Path(configured_cert).expanduser().resolve()
        key_file = Path(configured_key).expanduser().resolve()
        if not cert_file.is_file() or not key_file.is_file():
            raise RuntimeError("TLS_CERT_FILE/TLS_KEY_FILE не найдены")
        return cert_file, key_file

    if DEFAULT_CERT_FILE.is_file() and DEFAULT_KEY_FILE.is_file():
        return DEFAULT_CERT_FILE, DEFAULT_KEY_FILE

    DEFAULT_CERT_DIR.mkdir(parents=True, exist_ok=True)
    tls_host = os.getenv("TLS_HOST", "localhost").strip() or "localhost"
    config = f"""[req]
prompt = no
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = {tls_host}

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
{_tls_alt_name(tls_host)}
"""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cnf", encoding="utf-8", delete=False) as handle:
            handle.write(config)
            config_path = Path(handle.name)
        subprocess.run(
            [
                "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
                "-sha256", "-days", "30",
                "-keyout", str(DEFAULT_KEY_FILE),
                "-out", str(DEFAULT_CERT_FILE),
                "-config", str(config_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Для первого HTTPS-запуска нужен openssl. Установите openssl или задайте TLS_CERT_FILE/TLS_KEY_FILE."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Не удалось создать локальный HTTPS-сертификат: {exc.stderr.strip()}") from exc
    finally:
        if "config_path" in locals():
            config_path.unlink(missing_ok=True)

    return DEFAULT_CERT_FILE, DEFAULT_KEY_FILE


if __name__ == "__main__":
    import uvicorn

    cert_file, key_file = ensure_tls_certificate()
    print("Talent Interview: https://localhost:8000/login")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ssl_certfile=str(cert_file),
        ssl_keyfile=str(key_file),
    )

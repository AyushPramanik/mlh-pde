"""
Fire-drill script — triggers both alert conditions so you can verify
email delivery without waiting for a real incident.

Usage:
    uv run python fire_drill.py [--service-down] [--high-error-rate]

Flags
-----
--service-down     Fires the "Service Down" alert by temporarily pointing
                   the alert manager at a non-existent DB host.
--high-error-rate  Fires the "High Error Rate" alert by injecting 5xx
                   entries directly into the metrics store.

If no flags are given, both drills are run.
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

# Ensure the app directory is importable
sys.path.insert(0, os.path.dirname(__file__))

from app.alerting import AlertManager, EmailNotifier, _COOLDOWN
from app.metrics_store import MetricsStore


def _print(msg: str) -> None:
    print(f"[fire-drill] {msg}", flush=True)


def drill_service_down() -> None:
    _print("=== DRILL: Service Down ===")
    notifier = EmailNotifier()
    bad_db = {
        "host": "127.0.0.1",
        "port": 19999,   # nothing listening here
        "name": "does_not_exist",
        "user": "nobody",
        "password": "wrong",
    }
    ms = MetricsStore()
    mgr = AlertManager(notifier, ms, bad_db)

    _print("Running one check cycle against an unreachable DB…")
    mgr._check_service_down()

    if notifier.configured:
        _print(f"Alert email sent to {notifier.to_addr} — check your inbox.")
    else:
        _print("SMTP not configured (SMTP_USER / ALERT_EMAIL_TO not set).")
        _print("Alert would have fired — state: " + str(mgr._states["service_down"].firing))

    # Simulate recovery
    _print("Simulating recovery (good DB)…")
    good_db = {
        "host": os.environ.get("DATABASE_HOST", "localhost"),
        "port": int(os.environ.get("DATABASE_PORT", 5432)),
        "name": os.environ.get("DATABASE_NAME", "hackathon_db"),
        "user": os.environ.get("DATABASE_USER", "postgres"),
        "password": os.environ.get("DATABASE_PASSWORD", "postgres"),
    }
    mgr._db = good_db
    mgr._check_service_down()
    _print("Recovery check done.\n")


def drill_high_error_rate() -> None:
    _print("=== DRILL: High Error Rate ===")
    notifier = EmailNotifier()
    ms = MetricsStore(window_seconds=120)

    # Inject 8 errors out of 10 requests → 80% error rate (well above 10% threshold)
    for _ in range(2):
        ms.record(200)
    for _ in range(8):
        ms.record(500)

    snap = ms.snapshot()
    _print(f"Injected metrics: {snap['errors']}/{snap['total']} errors ({snap['error_rate']:.0%})")

    mgr = AlertManager(notifier, ms, {})
    mgr._check_high_error_rate()

    if notifier.configured:
        _print(f"Alert email sent to {notifier.to_addr} — check your inbox.")
    else:
        _print("SMTP not configured (SMTP_USER / ALERT_EMAIL_TO not set).")
        _print("Alert would have fired — state: " + str(mgr._states["high_error_rate"].firing))

    # Simulate recovery
    _print("Simulating recovery (inject clean traffic)…")
    ms2 = MetricsStore(window_seconds=120)
    for _ in range(10):
        ms2.record(200)
    mgr._metrics = ms2
    mgr._check_high_error_rate()
    _print("Recovery check done.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-down", action="store_true")
    parser.add_argument("--high-error-rate", action="store_true")
    args = parser.parse_args()

    run_all = not args.service_down and not args.high_error_rate

    if args.service_down or run_all:
        drill_service_down()

    if args.high_error_rate or run_all:
        drill_high_error_rate()

    _print("Fire drill complete.")

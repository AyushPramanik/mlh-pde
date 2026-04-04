"""
Alert manager: evaluates alert rules on a background thread and sends email
notifications when thresholds are breached.

Supported alerts
----------------
service_down    — DB unreachable for one full check cycle
high_error_rate — >ALERT_ERROR_RATE_THRESHOLD of requests are 5xx
                  (requires at least ALERT_MIN_REQUESTS in the window)

Configuration (env vars)
------------------------
SMTP_HOST                 default: smtp.gmail.com
SMTP_PORT                 default: 587
SMTP_USER                 Gmail / SMTP username  (required to send)
SMTP_PASSWORD             Gmail app-password     (required to send)
ALERT_EMAIL_FROM          defaults to SMTP_USER
ALERT_EMAIL_TO            recipient address      (required to send)
ALERT_CHECK_INTERVAL      seconds between checks, default 30
ALERT_COOLDOWN_SECONDS    min seconds between repeat alerts, default 300
ALERT_ERROR_RATE_THRESHOLD  0.0–1.0, default 0.10 (10 %)
ALERT_MIN_REQUESTS        min requests in window before error-rate fires, default 5
"""

import logging
import os
import smtplib
import threading
import time
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("app.alerting")

# --- tunables (read once at import time; restart required to change) ----------
_CHECK_INTERVAL = int(os.environ.get("ALERT_CHECK_INTERVAL", "30"))
_COOLDOWN = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "300"))
_ERROR_RATE_THRESHOLD = float(os.environ.get("ALERT_ERROR_RATE_THRESHOLD", "0.10"))
_MIN_REQUESTS = int(os.environ.get("ALERT_MIN_REQUESTS", "5"))


# ---------------------------------------------------------------------------
# Alert state
# ---------------------------------------------------------------------------

@dataclass
class AlertState:
    name: str
    cooldown: int = _COOLDOWN
    _firing: bool = field(default=False, init=False, repr=False)
    _last_fired: float = field(default=0.0, init=False, repr=False)

    def fire(self) -> bool:
        """Mark as firing. Returns True only on a *new* fire (respects cooldown)."""
        if time.time() - self._last_fired > self.cooldown:
            self._firing = True
            self._last_fired = time.time()
            return True
        return False

    def resolve(self) -> bool:
        """Mark as resolved. Returns True if state actually changed."""
        if self._firing:
            self._firing = False
            return True
        return False

    @property
    def firing(self) -> bool:
        return self._firing


# ---------------------------------------------------------------------------
# Email notifier
# ---------------------------------------------------------------------------

class EmailNotifier:
    def __init__(self):
        self.smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SMTP_USER", "")
        self.smtp_password = os.environ.get("SMTP_PASSWORD", "")
        self.from_addr = os.environ.get("ALERT_EMAIL_FROM", self.smtp_user)
        self.to_addr = os.environ.get("ALERT_EMAIL_TO", "")

    @property
    def configured(self) -> bool:
        return bool(self.smtp_user and self.to_addr)

    def send(self, subject: str, body: str) -> None:
        if not self.configured:
            logger.warning("alert_email_skipped", extra={"reason": "SMTP_USER or ALERT_EMAIL_TO not set"})
            return

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(self.smtp_user, self.smtp_password)
                smtp.sendmail(self.from_addr, [self.to_addr], msg.as_string())
            logger.info("alert_email_sent", extra={"subject": subject, "to": self.to_addr})
        except Exception as e:
            logger.error("alert_email_failed", extra={"error": str(e)})


# ---------------------------------------------------------------------------
# Alert manager
# ---------------------------------------------------------------------------

class AlertManager:
    def __init__(self, notifier: EmailNotifier, metrics_store, db_config: dict):
        self._notifier = notifier
        self._metrics = metrics_store
        self._db = db_config
        self._states = {
            "service_down": AlertState("service_down"),
            "high_error_rate": AlertState("high_error_rate"),
        }
        self._stop = threading.Event()

    def start(self) -> None:
        t = threading.Thread(target=self._loop, daemon=True, name="alert-manager")
        t.start()
        logger.info(
            "alert_manager_started",
            extra={
                "check_interval": _CHECK_INTERVAL,
                "cooldown": _COOLDOWN,
                "error_rate_threshold": _ERROR_RATE_THRESHOLD,
                "email_configured": self._notifier.configured,
            },
        )

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        snap = self._metrics.snapshot()
        return {
            "alerts": {
                name: {"firing": state.firing}
                for name, state in self._states.items()
            },
            "thresholds": {
                "error_rate": _ERROR_RATE_THRESHOLD,
                "min_requests_in_window": _MIN_REQUESTS,
                "check_interval_seconds": _CHECK_INTERVAL,
                "cooldown_seconds": _COOLDOWN,
            },
            "current_metrics": snap,
            "email_configured": self._notifier.configured,
        }

    # -----------------------------------------------------------------------
    # Background loop
    # -----------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.wait(_CHECK_INTERVAL):
            try:
                self._check_service_down()
                self._check_high_error_rate()
            except Exception as e:
                logger.error("alert_check_error", extra={"error": str(e)})

    def _check_service_down(self) -> None:
        state = self._states["service_down"]
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=self._db.get("host", "localhost"),
                port=self._db.get("port", 5432),
                dbname=self._db.get("name", "hackathon_db"),
                user=self._db.get("user", "postgres"),
                password=self._db.get("password", "postgres"),
                connect_timeout=5,
            )
            conn.close()
            if state.resolve():
                self._notifier.send(
                    "[RESOLVED] Service Back Up",
                    f"The database connection has been restored.\n\nTime: {_now()}",
                )
                logger.info("alert_resolved", extra={"alert": "service_down"})
        except Exception as e:
            logger.warning("db_check_failed", extra={"error": str(e)})
            if state.fire():
                self._notifier.send(
                    "[ALERT] Service Down — DB Unreachable",
                    (
                        "The application cannot reach the database.\n\n"
                        f"Error : {e}\n"
                        f"Time  : {_now()}\n\n"
                        "Action required: check the database and application status.\n"
                        "Logs available at: GET /logs"
                    ),
                )
                logger.error("alert_fired", extra={"alert": "service_down", "error": str(e)})

    def _check_high_error_rate(self) -> None:
        state = self._states["high_error_rate"]
        snap = self._metrics.snapshot()
        rate = snap["error_rate"]
        total = snap["total"]
        is_high = rate > _ERROR_RATE_THRESHOLD and total >= _MIN_REQUESTS

        if is_high:
            if state.fire():
                self._notifier.send(
                    f"[ALERT] High Error Rate: {rate:.0%}",
                    (
                        f"Error rate has exceeded the {_ERROR_RATE_THRESHOLD:.0%} threshold.\n\n"
                        f"Current rate : {rate:.1%}\n"
                        f"Errors       : {snap['errors']} / {total} requests "
                        f"(last {snap['window_seconds']}s)\n"
                        f"Time         : {_now()}\n\n"
                        "Action required: inspect recent errors at GET /logs"
                    ),
                )
                logger.error("alert_fired", extra={"alert": "high_error_rate", **snap})
        else:
            if state.resolve():
                self._notifier.send(
                    "[RESOLVED] Error Rate Normal",
                    f"Error rate has returned to normal: {rate:.1%}\n\nTime: {_now()}",
                )
                logger.info("alert_resolved", extra={"alert": "high_error_rate", **snap})


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

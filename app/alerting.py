"""
Alert manager: evaluates alert rules on a background thread and sends
email and Discord notifications when thresholds are breached.

Supported alerts
----------------
service_down    — DB unreachable for one full check cycle
high_error_rate — >ALERT_ERROR_RATE_THRESHOLD of requests are 5xx
                  (requires at least ALERT_MIN_REQUESTS in the window)

Configuration (env vars)
------------------------
SMTP_HOST                   default: smtp.gmail.com
SMTP_PORT                   default: 587
SMTP_USER                   Gmail / SMTP username  (required to send)
SMTP_PASSWORD               Gmail app-password     (required to send)
ALERT_EMAIL_FROM            defaults to SMTP_USER
ALERT_EMAIL_TO              recipient address      (required to send)
DISCORD_WEBHOOK_URL         Discord webhook URL    (required for Discord)
ALERT_CHECK_INTERVAL        seconds between checks, default 30
ALERT_COOLDOWN_SECONDS      min seconds between repeat alerts, default 300
ALERT_ERROR_RATE_THRESHOLD  0.0-1.0, default 0.10 (10%)
ALERT_MIN_REQUESTS          min requests in window before error-rate fires, default 5
"""

import json
import logging
import os
import smtplib
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("app.alerting")

# --- tunables ----------------------------------------------------------------
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
        if time.time() - self._last_fired > self.cooldown:
            self._firing = True
            self._last_fired = time.time()
            return True
        return False

    def resolve(self) -> bool:
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
# Discord notifier
# ---------------------------------------------------------------------------

class DiscordNotifier:
    def __init__(self):
        self.webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url)
    def send(self, subject: str, body: str) -> None:
        if not self.configured:
            logger.warning("discord_alert_skipped", extra={"reason": "DISCORD_WEBHOOK_URL not set"})
            return
        payload = json.dumps({"content": f"**{subject}**\n{body}"}).encode("utf-8")
        try:
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "mlh-pde/1.0",
            }
            req = urllib.request.Request(
                self.webhook_url,
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            logger.info("discord_alert_sent", extra={"subject": subject})
        except urllib.error.HTTPError as e:
            try:
                resp_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                resp_body = "<unreadable response body>"
            logger.error(
                "discord_alert_failed",
                extra={
                    "error": f"HTTP {e.code} {getattr(e, 'reason', '')}",
                    "status": getattr(e, 'code', None),
                    "response": resp_body,
                    "webhook": self._masked_webhook(),
                },
            )
        except urllib.error.URLError as e:
            logger.error("discord_alert_failed", extra={"error": f"URL error: {getattr(e, 'reason', e)}"})
        except Exception as e:
            logger.error("discord_alert_failed", extra={"error": str(e)})

    def _masked_webhook(self) -> str:
        if not self.webhook_url:
            return ""
        try:
            parts = self.webhook_url.split("/")
            if len(parts) >= 2:
                token = parts[-1]
                if len(token) > 8:
                    token_mask = token[:4] + "..." + token[-4:]
                else:
                    token_mask = "****"
                return "/".join(parts[:-1]) + "/" + token_mask
        except Exception:
            pass
        return "<masked>"


# ---------------------------------------------------------------------------
# Alert manager
# ---------------------------------------------------------------------------

class AlertManager:
    def __init__(self, notifiers: list, metrics_store, db_config: dict):
        self._notifiers = notifiers
        self._metrics = metrics_store
        self._db = db_config
        self._states = {
            "service_down": AlertState("service_down"),
            "high_error_rate": AlertState("high_error_rate"),
        }
        self._stop = threading.Event()

    def _notify(self, subject: str, body: str) -> None:
        for notifier in self._notifiers:
            notifier.send(subject, body)

    def start(self) -> None:
        t = threading.Thread(target=self._loop, daemon=True, name="alert-manager")
        t.start()
        logger.info(
            "alert_manager_started",
            extra={
                "check_interval": _CHECK_INTERVAL,
                "cooldown": _COOLDOWN,
                "error_rate_threshold": _ERROR_RATE_THRESHOLD,
                "email_configured": any(
                    isinstance(n, EmailNotifier) and n.configured
                    for n in self._notifiers
                ),
                "discord_configured": any(
                    isinstance(n, DiscordNotifier) and n.configured
                    for n in self._notifiers
                ),
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
            "notifiers": {
                "email_configured": any(
                    isinstance(n, EmailNotifier) and n.configured
                    for n in self._notifiers
                ),
                "discord_configured": any(
                    isinstance(n, DiscordNotifier) and n.configured
                    for n in self._notifiers
                ),
            },
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
                self._notify(
                    "[RESOLVED] Service Back Up",
                    f"The database connection has been restored.\n\nTime: {_now()}",
                )
                logger.info("alert_resolved", extra={"alert": "service_down"})
        except Exception as e:
            logger.warning("db_check_failed", extra={"error": str(e)})
            if state.fire():
                self._notify(
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
                self._notify(
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
                self._notify(
                    "[RESOLVED] Error Rate Normal",
                    f"Error rate has returned to normal: {rate:.1%}\n\nTime: {_now()}",
                )
                logger.info("alert_resolved", extra={"alert": "high_error_rate", **snap})


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
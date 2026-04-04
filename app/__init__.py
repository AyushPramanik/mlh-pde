import json
import os
import socket
import time

import psutil
from flask import Flask, g, jsonify, render_template, request
from dotenv import load_dotenv
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.database import init_db
from app.logging_config import LOG_FILE, configure_logging
from app.prometheus_metrics import (
    REGISTRY,
    active_requests,
    http_request_duration_seconds,
    http_requests_total,
    process_cpu_percent,
    process_memory_bytes,
)
from app.routes import register_routes

# normalise dynamic path segments so Prometheus cardinality stays bounded
_PARAM_PATTERNS = [
    # /urls/123  → /urls/<id>
    ("/urls/", "id"),
    ("/users/", "id"),
    ("/events/", "id"),
]


def _normalise(path: str) -> str:
    for prefix, label in _PARAM_PATTERNS:
        if path.startswith(prefix):
            rest = path[len(prefix):]
            if rest and rest.split("/")[0].isdigit():
                suffix = rest[rest.find("/"):] if "/" in rest else ""
                return f"{prefix}<{label}>{suffix}"
    return path


def create_app():
    load_dotenv()

    logger = configure_logging()

    app = Flask(__name__)

    init_db(app)

    from app import models  # noqa: F401 - registers models with Peewee

    from app.models.user import User
    from app.models.url import URL
    from app.models.event import Event
    from app.database import db
    try:
        opened = db.connect()
        db.create_tables([User, URL, Event], safe=True)
        if opened:
            db.close()
    except Exception:
        pass  # DB unavailable at startup; tables expected to exist on first request

    register_routes(app)

    # ------------------------------------------------------------------
    # Alerting — start background monitor (skip in test mode)
    # ------------------------------------------------------------------

    from app.metrics_store import store as metrics_store
    from app.alerting import AlertManager, EmailNotifier

    if not app.config.get("TESTING"):
        db_config = {
            "host": os.environ.get("DATABASE_HOST", "localhost"),
            "port": int(os.environ.get("DATABASE_PORT", 5432)),
            "name": os.environ.get("DATABASE_NAME", "hackathon_db"),
            "user": os.environ.get("DATABASE_USER", "postgres"),
            "password": os.environ.get("DATABASE_PASSWORD", "postgres"),
        }
        alert_manager = AlertManager(EmailNotifier(), metrics_store, db_config)
        alert_manager.start()
        app.alert_manager = alert_manager

    # ------------------------------------------------------------------
    # Request / response logging + metrics recording
    # ------------------------------------------------------------------

    @app.before_request
    def _before():
        g.start_time = time.perf_counter()
        active_requests.inc()

    @app.after_request
    def _after(response):
        start = getattr(g, "start_time", None)
        duration = (time.perf_counter() - start) if start else 0
        duration_ms = round(duration * 1000, 2)

        endpoint = _normalise(request.path)

        # Prometheus
        active_requests.dec()
        http_requests_total.labels(
            method=request.method,
            endpoint=endpoint,
            status=str(response.status_code),
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(duration)

        # Sliding-window store (used by alert manager)
        metrics_store.record(response.status_code)

        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "remote_addr": request.remote_addr,
            },
        )
        return response

    # ------------------------------------------------------------------
    # Built-in routes
    # ------------------------------------------------------------------

    @app.route("/health")
    def health():
        return {"status": "ok", "hostname": socket.gethostname()}

    @app.route("/metrics")
    def metrics():
        proc = psutil.Process()
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)

        # update saturation gauges so /prometheus reflects latest values
        process_cpu_percent.set(cpu)
        process_memory_bytes.set(proc.memory_info().rss)

        snap = metrics_store.snapshot()
        return jsonify(
            {
                "cpu_percent": cpu,
                "memory": {
                    "total_mb": round(mem.total / 1024 / 1024, 2),
                    "used_mb": round(mem.used / 1024 / 1024, 2),
                    "available_mb": round(mem.available / 1024 / 1024, 2),
                    "percent": mem.percent,
                },
                "requests": snap,
                "hostname": socket.gethostname(),
            }
        )

    @app.route("/prometheus")
    def prometheus():
        """Prometheus scrape endpoint (text/plain exposition format)."""
        proc = psutil.Process()
        process_cpu_percent.set(psutil.cpu_percent(interval=None))
        process_memory_bytes.set(proc.memory_info().rss)
        return generate_latest(REGISTRY), 200, {"Content-Type": CONTENT_TYPE_LATEST}

    @app.route("/alert-status")
    def alert_status():
        mgr = getattr(app, "alert_manager", None)
        if mgr is None:
            return jsonify({"error": "alerting not running (test mode)"}), 503
        return jsonify(mgr.status())

    @app.route("/logs")
    def logs():
        limit = request.args.get("limit", 100, type=int)
        try:
            with open(LOG_FILE) as f:
                lines = f.readlines()
            recent = lines[-limit:]
            return jsonify([json.loads(line) for line in recent if line.strip()])
        except FileNotFoundError:
            return jsonify([])

    @app.route("/dashboard")
    def dashboard():
        return render_template("dashboard.html")

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(e):
        logger.warning("not_found", extra={"path": request.path})
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        logger.warning(
            "method_not_allowed",
            extra={"method": request.method, "path": request.path},
        )
        return jsonify({"error": "method not allowed"}), 405

    @app.errorhandler(500)
    def internal_error(e):
        logger.error("internal_server_error", exc_info=e)
        return jsonify({"error": "internal server error"}), 500

    return app

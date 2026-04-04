import json
import socket
import time

import psutil
from flask import Flask, g, jsonify, request
from dotenv import load_dotenv

from app.database import init_db
from app.logging_config import LOG_FILE, configure_logging
from app.routes import register_routes


def create_app():
    load_dotenv()

    logger = configure_logging()

    app = Flask(__name__)

    init_db(app)

    from app import models  # noqa: F401 - registers models with Peewee

    # Create tables if they don't exist (safe=True is a no-op when they do)
    from app.models.user import User
    from app.models.url import URL
    from app.models.event import Event
    from app.database import db
    try:
        opened = db.connect()          # returns True if a new connection was opened
        db.create_tables([User, URL, Event], safe=True)
        if opened:
            db.close()
    except Exception:
        pass  # DB unavailable at startup; tables expected to exist on first request

    register_routes(app)

    # ------------------------------------------------------------------
    # Request / response logging
    # ------------------------------------------------------------------

    @app.before_request
    def _before():
        g.start_time = time.perf_counter()

    @app.after_request
    def _after(response):
        start = getattr(g, "start_time", None)
        duration_ms = round((time.perf_counter() - start) * 1000, 2) if start else None
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
        return {
            "status": "ok",
            "hostname": socket.gethostname(),
        }

    @app.route("/metrics")
    def metrics():
        mem = psutil.virtual_memory()
        return jsonify(
            {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory": {
                    "total_mb": round(mem.total / 1024 / 1024, 2),
                    "used_mb": round(mem.used / 1024 / 1024, 2),
                    "available_mb": round(mem.available / 1024 / 1024, 2),
                    "percent": mem.percent,
                },
                "hostname": socket.gethostname(),
            }
        )

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

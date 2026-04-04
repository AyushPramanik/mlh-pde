<<<<<<< HEAD
import json
import logging
import sys
import time
from flask import Flask, jsonify, g, request
=======
import socket
>>>>>>> e17869cdf4243851c2218c52ead0c22089157e00
from dotenv import load_dotenv
from app.database import init_db
from app.routes import register_routes

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


def create_app():
    load_dotenv()

    setup_logging()
    logger = logging.getLogger(__name__)


    app = Flask(__name__)

    @app.before_request
    def before_request():
        g.start_time = time.time()
        logger.info(f"Request started: {request.method} {request.path}")

    @app.after_request
    def after_request(response):
        duration = round((time.time() - g.start_time) * 1000, 2)
        logger.info(f"Request finished: {request.method} {request.path} status={response.status_code} duration={duration}ms")
        return response


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

    @app.route("/health")
    def health():
        return {
            "status": "ok",
            "hostname": socket.gethostname(),
        }

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "method not allowed"}), 405

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "internal server error"}), 500

    return app

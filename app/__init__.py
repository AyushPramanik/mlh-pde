import socket
from dotenv import load_dotenv
from flask import Flask, jsonify

from app.database import init_db
from app.routes import register_routes


def create_app():
    load_dotenv()

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

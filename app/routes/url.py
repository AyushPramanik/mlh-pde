import json
import random
import string
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.models.url import URL
from app.models.event import Event

url_bp = Blueprint("url", __name__)


def generate_code(length=6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@url_bp.route("/urls", methods=["GET"])
def list_urls():
    urls = list(URL.select().dicts())
    return jsonify(urls)


@url_bp.route("/shorten", methods=["POST"])
def shorten():
    data = request.get_json(force=True, silent=True)
    if not data or "url" not in data:
        return jsonify({"error": "url is required"}), 400

    now = datetime.now(timezone.utc)
    short_code = generate_code()
    url = URL.create(
        original_url=data["url"],
        short_code=short_code,
        title=data.get("title"),
        user_id=data.get("user_id"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    Event.create(
        url_id=url.id,
        user_id=data.get("user_id"),
        event_type="created",
        timestamp=now,
        details=json.dumps({"short_code": short_code, "original_url": data["url"]}),
    )
    return jsonify({"short_code": short_code, "original_url": url.original_url}), 201


@url_bp.route("/<short_code>", methods=["GET"])
def redirect_url(short_code):
    try:
        url = URL.get((URL.short_code == short_code) & (URL.is_active == True))
        return jsonify({"original_url": url.original_url}), 200
    except URL.DoesNotExist:
        return jsonify({"error": "not found"}), 404

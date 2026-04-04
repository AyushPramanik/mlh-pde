import json
import random
import string
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request
from peewee import IntegrityError

from app.models.event import Event
from app.models.url import URL

url_bp = Blueprint("url", __name__)

_MAX_RETRIES = 5


def generate_code(length=6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def is_valid_url(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


@url_bp.route("/urls", methods=["GET"])
def list_urls():
    urls = list(URL.select().dicts())
    return jsonify(urls)


@url_bp.route("/urls/<int:url_id>", methods=["GET"])
def get_url(url_id):
    try:
        url = URL.get_by_id(url_id)
        return jsonify(url.__data__)
    except URL.DoesNotExist:
        return jsonify({"error": "not found"}), 404


@url_bp.route("/shorten", methods=["POST"])
def shorten():
    data = request.get_json(force=True, silent=True)
    if not data or "url" not in data:
        return jsonify({"error": "url is required"}), 400
    if not is_valid_url(data["url"]):
        return jsonify({"error": "invalid url"}), 400

    now = datetime.now(timezone.utc)
    for _ in range(_MAX_RETRIES):
        try:
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
            break
        except IntegrityError:
            continue
    else:
        return jsonify({"error": "could not generate unique short code"}), 500

    Event.create(
        url_id=url.id,
        user_id=data.get("user_id"),
        event_type="created",
        timestamp=now,
        details=json.dumps({"short_code": short_code, "original_url": data["url"]}),
    )
    return jsonify({"short_code": short_code, "original_url": url.original_url}), 201


@url_bp.route("/urls/<int:url_id>", methods=["PATCH"])
def update_url(url_id):
    try:
        url = URL.get_by_id(url_id)
    except URL.DoesNotExist:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    changes = {}

    if "original_url" in data:
        if not is_valid_url(data["original_url"]):
            return jsonify({"error": "invalid url"}), 400
        changes["original_url"] = data["original_url"]

    if "title" in data:
        changes["title"] = data["title"]

    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            return jsonify({"error": "is_active must be a boolean"}), 400
        changes["is_active"] = data["is_active"]

    if not changes:
        return jsonify({"error": "no valid fields to update"}), 400

    now = datetime.now(timezone.utc)
    changes["updated_at"] = now
    URL.update(changes).where(URL.id == url_id).execute()

    Event.create(
        url_id=url_id,
        user_id=data.get("user_id"),
        event_type="updated",
        timestamp=now,
        details=json.dumps(changes, default=str),
    )
    return jsonify({"id": url_id, **changes}), 200


@url_bp.route("/urls/<int:url_id>", methods=["DELETE"])
def delete_url(url_id):
    try:
        url = URL.get_by_id(url_id)
    except URL.DoesNotExist:
        return jsonify({"error": "not found"}), 404

    now = datetime.now(timezone.utc)
    URL.update({"is_active": False, "updated_at": now}).where(URL.id == url_id).execute()

    Event.create(
        url_id=url_id,
        user_id=None,
        event_type="deleted",
        timestamp=now,
        details=json.dumps({"short_code": url.short_code}),
    )
    return jsonify({"message": "deleted"}), 200


@url_bp.route("/<short_code>", methods=["GET"])
def redirect_url(short_code):
    try:
        url = URL.get((URL.short_code == short_code) & (URL.is_active == True))
        return jsonify({"original_url": url.original_url}), 200
    except URL.DoesNotExist:
        return jsonify({"error": "not found"}), 404

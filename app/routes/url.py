import csv
import json
import os
import random
import string
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, jsonify, redirect, request
from peewee import IntegrityError

from app.models.event import Event
from app.models.url import URL

url_bp = Blueprint("url", __name__)

_MAX_RETRIES = 5
_SEED_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "seed")
)


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


def _url_dict(url):
    return {
        "id": url.id,
        "user_id": url.user_id,
        "short_code": url.short_code,
        "original_url": url.original_url,
        "title": url.title,
        "is_active": url.is_active,
        "created_at": str(url.created_at),
        "updated_at": str(url.updated_at),
    }


# ---------------------------------------------------------------------------
# GET /urls  — list with optional filters (?user_id=, ?is_active=, ?page=, ?per_page=)
# ---------------------------------------------------------------------------

@url_bp.route("/urls", methods=["GET"])
def list_urls():
    user_id = request.args.get("user_id", type=int)
    is_active_param = request.args.get("is_active")
    page = request.args.get("page", type=int)
    per_page = request.args.get("per_page", type=int)

    query = URL.select()

    if user_id is not None:
        query = query.where(URL.user_id == user_id)

    if is_active_param is not None:
        query = query.where(URL.is_active == (is_active_param.lower() == "true"))

    if page is not None and per_page is not None:
        query = query.paginate(page, per_page)

    return jsonify([_url_dict(u) for u in query])


# ---------------------------------------------------------------------------
# POST /urls  — create a short URL (accepts original_url field)
# POST /shorten — legacy alias (accepts url field)
# ---------------------------------------------------------------------------

def _create_url(original_url, title=None, user_id=None):
    """Shared logic for both POST /urls and POST /shorten."""
    now = datetime.now(timezone.utc)
    for _ in range(_MAX_RETRIES):
        try:
            short_code = generate_code()
            url = URL.create(
                original_url=original_url,
                short_code=short_code,
                title=title,
                user_id=user_id,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            break
        except IntegrityError:
            continue
    else:
        return None, None

    Event.create(
        url_id=url.id,
        user_id=user_id,
        event_type="created",
        timestamp=now,
        details=json.dumps({"short_code": short_code, "original_url": original_url}),
    )
    return url, short_code


@url_bp.route("/urls", methods=["POST"])
def create_url():
    data = request.get_json(force=True, silent=True)
    if not data or "original_url" not in data:
        return jsonify({"error": "original_url is required"}), 400
    if not is_valid_url(data["original_url"]):
        return jsonify({"error": "invalid url"}), 400

    url, short_code = _create_url(
        data["original_url"],
        title=data.get("title"),
        user_id=data.get("user_id"),
    )
    if url is None:
        return jsonify({"error": "could not generate unique short code"}), 500

    return jsonify(_url_dict(url)), 201


@url_bp.route("/shorten", methods=["POST"])
def shorten():
    data = request.get_json(force=True, silent=True)
    if not data or "url" not in data:
        return jsonify({"error": "url is required"}), 400
    if not is_valid_url(data["url"]):
        return jsonify({"error": "invalid url"}), 400

    url, short_code = _create_url(
        data["url"],
        title=data.get("title"),
        user_id=data.get("user_id"),
    )
    if url is None:
        return jsonify({"error": "could not generate unique short code"}), 500

    return jsonify({"short_code": short_code, "original_url": url.original_url}), 201


# ---------------------------------------------------------------------------
# POST /urls/bulk  — seed URLs from a CSV in the seed/ directory
# ---------------------------------------------------------------------------

@url_bp.route("/urls/bulk", methods=["POST"])
def bulk_load_urls():
    data = request.get_json(force=True, silent=True) or {}
    filename = data.get("file", "urls.csv")

    if os.path.sep in filename or filename.startswith("."):
        return jsonify({"error": "invalid filename"}), 400

    filepath = os.path.join(_SEED_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": f"{filename} not found"}), 404

    with open(filepath, newline="") as f:
        rows = [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "short_code": r["short_code"],
                "original_url": r["original_url"],
                "title": r["title"],
                "is_active": r["is_active"].lower() == "true",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in csv.DictReader(f)
        ]

    from app.database import db
    with db.atomic():
        for batch in _chunks(rows, 100):
            URL.insert_many(batch).on_conflict_ignore().execute()

    return jsonify({"loaded": len(rows)}), 201


# ---------------------------------------------------------------------------
# GET /urls/<id>
# ---------------------------------------------------------------------------

@url_bp.route("/urls/<int:url_id>", methods=["GET"])
def get_url(url_id):
    try:
        return jsonify(_url_dict(URL.get_by_id(url_id)))
    except URL.DoesNotExist:
        return jsonify({"error": "url not found"}), 404


# ---------------------------------------------------------------------------
# PUT /urls/<id>  — update title, original_url, or is_active; also accepts PATCH
# ---------------------------------------------------------------------------

@url_bp.route("/urls/<int:url_id>", methods=["PUT", "PATCH"])
def update_url(url_id):
    try:
        url = URL.get_by_id(url_id)
    except URL.DoesNotExist:
        return jsonify({"error": "url not found"}), 404

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
    return jsonify(_url_dict(URL.get_by_id(url_id)))


# ---------------------------------------------------------------------------
# DELETE /urls/<id>  — soft delete (sets is_active=False)
# ---------------------------------------------------------------------------

@url_bp.route("/urls/<int:url_id>", methods=["DELETE"])
def delete_url(url_id):
    try:
        url = URL.get_by_id(url_id)
    except URL.DoesNotExist:
        return jsonify({"error": "url not found"}), 404

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


# ---------------------------------------------------------------------------
# GET /urls/<id>/events  — audit log for a URL
# ---------------------------------------------------------------------------

@url_bp.route("/urls/<int:url_id>/events", methods=["GET"])
def get_url_events(url_id):
    try:
        URL.get_by_id(url_id)
    except URL.DoesNotExist:
        return jsonify({"error": "url not found"}), 404
    events = list(Event.select().where(Event.url_id == url_id).dicts())
    return jsonify(events)


# ---------------------------------------------------------------------------
# GET /<short_code>  — 302 redirect to original URL
# ---------------------------------------------------------------------------

@url_bp.route("/<short_code>", methods=["GET"])
def redirect_url(short_code):
    try:
        url = URL.get((URL.short_code == short_code) & (URL.is_active == True))
        return redirect(url.original_url, code=302)
    except URL.DoesNotExist:
        return jsonify({"error": "not found"}), 404


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

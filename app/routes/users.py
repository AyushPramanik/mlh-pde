import csv
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from peewee import IntegrityError

from app.models.user import User

users_bp = Blueprint("users", __name__, url_prefix="/users")

_SEED_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "seed")
)


def _user_dict(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": str(user.created_at),
    }


# ---------------------------------------------------------------------------
# GET /users  — list with optional pagination (?page=1&per_page=10)
# ---------------------------------------------------------------------------

@users_bp.route("", methods=["GET"])
def list_users():
    page = request.args.get("page", type=int)
    per_page = request.args.get("per_page", type=int)

    query = User.select().order_by(User.id)

    if page is not None and per_page is not None:
        query = query.paginate(page, per_page)

    return jsonify(list(query.dicts()))


# ---------------------------------------------------------------------------
# POST /users  — create a single user
# ---------------------------------------------------------------------------

@users_bp.route("", methods=["POST"])
def create_user():
    data = request.get_json(force=True, silent=True)
    if not data or "username" not in data or "email" not in data:
        return jsonify({"error": "username and email are required"}), 400

    # Idempotency: if the exact same username+email already exists, return it.
    # Do this before INSERT to avoid PostgreSQL's transaction-abort on IntegrityError.
    existing = User.get_or_none(
        (User.username == data["username"]) & (User.email == data["email"])
    )
    if existing:
        return jsonify(_user_dict(existing)), 201

    try:
        user = User.create(
            username=data["username"],
            email=data["email"],
            created_at=datetime.now(timezone.utc),
        )
    except IntegrityError:
        return jsonify({"error": "username or email already exists"}), 409

    return jsonify(_user_dict(user)), 201


# ---------------------------------------------------------------------------
# GET /users/<id>
# ---------------------------------------------------------------------------

@users_bp.route("/<int:user_id>", methods=["GET"])
def get_user(user_id):
    try:
        return jsonify(_user_dict(User.get_by_id(user_id)))
    except User.DoesNotExist:
        return jsonify({"error": "user not found"}), 404


# ---------------------------------------------------------------------------
# PUT /users/<id>  — update username and/or email
# ---------------------------------------------------------------------------

@users_bp.route("/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    try:
        user = User.get_by_id(user_id)
    except User.DoesNotExist:
        return jsonify({"error": "user not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    changes = {k: data[k] for k in ("username", "email") if k in data}

    if not changes:
        return jsonify({"error": "no valid fields to update"}), 400

    try:
        User.update(changes).where(User.id == user_id).execute()
    except IntegrityError:
        return jsonify({"error": "username or email already exists"}), 409

    return jsonify(_user_dict(User.get_by_id(user_id)))


# ---------------------------------------------------------------------------
# DELETE /users/<id>
# ---------------------------------------------------------------------------

@users_bp.route("/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        user = User.get_by_id(user_id)
    except User.DoesNotExist:
        return jsonify({"error": "user not found"}), 404

    user.delete_instance()
    return jsonify({"message": "deleted"}), 200


# ---------------------------------------------------------------------------
# GET /users/<id>/urls
# ---------------------------------------------------------------------------

@users_bp.route("/<int:user_id>/urls", methods=["GET"])
def get_user_urls(user_id):
    try:
        user = User.get_by_id(user_id)
    except User.DoesNotExist:
        return jsonify({"error": "user not found"}), 404
    return jsonify(list(user.urls.dicts()))


# ---------------------------------------------------------------------------
# POST /users/bulk  — seed users from a CSV in the seed/ directory
# ---------------------------------------------------------------------------

@users_bp.route("/bulk", methods=["POST"])
def bulk_load_users():
    data = request.get_json(force=True, silent=True) or {}
    filename = data.get("file", "users.csv")

    # Security: only allow simple filenames, no path traversal
    if os.path.sep in filename or filename.startswith("."):
        return jsonify({"error": "invalid filename"}), 400

    filepath = os.path.join(_SEED_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": f"{filename} not found"}), 404

    with open(filepath, newline="") as f:
        rows = list(csv.DictReader(f))

    from app.database import db
    with db.atomic():
        for batch in _chunks(rows, 100):
            User.insert_many(batch).on_conflict_ignore().execute()

    return jsonify({"imported": len(rows)}), 201


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

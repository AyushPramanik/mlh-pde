from flask import Blueprint, jsonify

from app.models.user import User

users_bp = Blueprint("users", __name__, url_prefix="/users")


@users_bp.route("/", methods=["GET"])
def list_users():
    users = list(User.select().dicts())
    return jsonify(users)


@users_bp.route("/<int:user_id>", methods=["GET"])
def get_user(user_id):
    try:
        user = User.get_by_id(user_id)
        return jsonify({"id": user.id, "username": user.username, "email": user.email, "created_at": str(user.created_at)})
    except User.DoesNotExist:
        return jsonify({"error": "not found"}), 404


@users_bp.route("/<int:user_id>/urls", methods=["GET"])
def get_user_urls(user_id):
    try:
        User.get_by_id(user_id)
    except User.DoesNotExist:
        return jsonify({"error": "not found"}), 404
    urls = list(User.get_by_id(user_id).urls.dicts())
    return jsonify(urls)

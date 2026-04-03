import random
import string

from flask import Blueprint, jsonify, request
from app.models.url import URL

url_bp = Blueprint("url", __name__)


def generate_code(length=6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@url_bp.route("/shorten", methods=["POST"])
def shorten():
    data = request.get_json(force=True, silent=True)
    if not data or "url" not in data:
        return jsonify({"error": "url is required"}), 400

    short_code = generate_code()
    url = URL.create(original_url=data["url"], short_code=short_code)
    return jsonify({"short_code": short_code, "original_url": url.original_url}), 201


@url_bp.route("/<short_code>", methods=["GET"])
def redirect_url(short_code):
    try:
        url = URL.get(URL.short_code == short_code)
        return jsonify({"original_url": url.original_url}), 200
    except URL.DoesNotExist:
        return jsonify({"error": "not found"}), 404

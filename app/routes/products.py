from flask import Blueprint, jsonify

from app.models.products import Product

products_bp = Blueprint("products", __name__, url_prefix="/products")


@products_bp.route("/", methods=["GET"])
def get_products():
    products = list(Product.select().dicts())
    return jsonify(products)

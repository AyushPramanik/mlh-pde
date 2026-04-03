def register_routes(app):
    from app.routes.products import products_bp
    app.register_blueprint(products_bp)

    from app.routes.url import url_bp
    app.register_blueprint(url_bp)

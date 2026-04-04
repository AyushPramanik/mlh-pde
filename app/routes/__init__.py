def register_routes(app):
    from app.routes.url import url_bp
    app.register_blueprint(url_bp)

    from app.routes.users import users_bp
    app.register_blueprint(users_bp)

    from app.routes.events import events_bp
    app.register_blueprint(events_bp)

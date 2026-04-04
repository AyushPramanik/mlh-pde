import os
import time

from app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    # Retry DB connection on startup so the container survives a docker kill
    # and comes back up cleanly once PostgreSQL is ready.
    for attempt in range(10):
        try:
            from app.database import db
            db.connect()
            db.close()
            break
        except Exception as e:
            print(f"DB not ready (attempt {attempt + 1}/10): {e} — retrying in 2s")
            time.sleep(2)

    app.run(host=host, port=port, debug=debug)

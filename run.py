import logging
import os
import time

from app import create_app
from app.logging_config import configure_logging

logger = configure_logging()

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("FLASK_PORT") or 5000)
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    # Retry DB connection on startup
    for attempt in range(10):
        try:
            from app.database import db
            db.connect()
            db.close()
            logger.info("db_connected", extra={"attempt": attempt + 1})
            break
        except Exception as e:
            logger.warning(
                "db_not_ready",
                extra={"attempt": attempt + 1, "max_attempts": 10, "error": str(e)},
            )
            time.sleep(2)

    app.run(host=host, port=port, debug=debug)

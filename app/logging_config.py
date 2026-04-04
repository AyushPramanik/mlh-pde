import json
import logging
import os
from datetime import datetime, timezone

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
LOG_FILE = os.path.join(LOGS_DIR, "app.log")

# Standard LogRecord attributes to exclude from extra fields
_STANDARD_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


class JSONFormatter(logging.Formatter):
    def format(self, record):
        record.message = record.getMessage()
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }
        # Include any extra fields passed via extra={}
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                log_record[key] = value
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def configure_logging():
    os.makedirs(LOGS_DIR, exist_ok=True)

    formatter = JSONFormatter()

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    if not root.handlers:  # avoid duplicate handlers on reload
        root.setLevel(logging.INFO)
        root.addHandler(file_handler)
        root.addHandler(stream_handler)

    # Suppress werkzeug's noisy default request lines — we log requests ourselves
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    return logging.getLogger("app")

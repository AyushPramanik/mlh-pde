"""
Prometheus metric definitions.

Imported once at module level — Python's import system prevents double-
registration across repeated calls to create_app() in tests.
"""
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

# Use a dedicated registry so tests that call create_app() multiple times
# don't trigger "Duplicated timeseries" errors from the default registry.
REGISTRY = CollectorRegistry(auto_describe=True)

# --- Traffic + Errors --------------------------------------------------------
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests by method, endpoint and status code",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)

# --- Latency -----------------------------------------------------------------
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=REGISTRY,
)

# --- Saturation --------------------------------------------------------------
process_cpu_percent = Gauge(
    "process_cpu_percent",
    "Process CPU usage percent (sampled)",
    registry=REGISTRY,
)

process_memory_bytes = Gauge(
    "process_memory_bytes",
    "Process RSS memory in bytes",
    registry=REGISTRY,
)

active_requests = Gauge(
    "http_active_requests",
    "Number of HTTP requests currently being processed",
    registry=REGISTRY,
)

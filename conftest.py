import contextlib
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Every module that does `from app.cache import ...` needs its own patches —
# patching app.cache directly won't affect already-bound local references.
_CACHE_TARGETS = [
    "app.routes.users",
    "app.routes.url",
]


@pytest.fixture(autouse=True)
def _mock_cache():
    """Disable Redis for all tests — cache is a no-op, no network calls."""
    with contextlib.ExitStack() as stack:
        for mod in _CACHE_TARGETS:
            stack.enter_context(patch(f"{mod}.get_cache", return_value=None))
            stack.enter_context(patch(f"{mod}.set_cache"))
            stack.enter_context(patch(f"{mod}.delete_cache"))
            stack.enter_context(patch(f"{mod}.delete_cache_pattern"))
        yield

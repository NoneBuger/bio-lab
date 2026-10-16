"""Celery application configuration."""

import os
from urllib.parse import urlsplit, urlunsplit

from celery import Celery


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


def _is_truthy(value: str | None) -> bool:
    """Return whether an environment value means true.

    Supported truthy values are ``true``, ``1``, ``yes``, and ``on``;
    matching is case-insensitive and ignores surrounding whitespace.
    """
    return str(value or "").strip().lower() in {"true", "1", "yes", "on"}


def _redis_db_url(redis_url: str, database: int) -> str:
    """Use a Redis host URL while assigning a predictable logical database."""
    parsed = urlsplit(redis_url.rstrip("/"))
    base_url = urlunsplit((parsed.scheme, parsed.netloc, "", parsed.query, parsed.fragment))
    return f"{base_url}/{database}"


ALWAYS_EAGER = _is_truthy(os.getenv("CELERY_TASK_ALWAYS_EAGER"))
BROKER_URL = os.getenv("CELERY_BROKER_URL", _redis_db_url(REDIS_URL, 0))
if ALWAYS_EAGER:
    # This backend is process-local and is intentionally limited to eager
    # development/test runs. Production must use eager=false with Redis.
    RESULT_BACKEND = "cache+memory://"
else:
    RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", _redis_db_url(REDIS_URL, 1))

celery_app = Celery(
    "bio_lab",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["backend.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    result_expires=86400,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=ALWAYS_EAGER,
    # Keep eager failures in the result backend so callers can observe
    # FAILURE instead of receiving an exception with a permanently PENDING
    # result. Non-eager workers retain normal exception propagation semantics.
    task_eager_propagates=not ALWAYS_EAGER,
    task_store_eager_result=ALWAYS_EAGER,
    result_backend_max_entries=10000 if ALWAYS_EAGER else None,
)

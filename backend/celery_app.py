"""Celery application configuration."""

import os
from urllib.parse import urlsplit, urlunsplit

from celery import Celery


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


def _redis_db_url(redis_url: str, database: int) -> str:
    """Use a Redis host URL while assigning a predictable logical database."""
    parsed = urlsplit(redis_url.rstrip("/"))
    base_url = urlunsplit((parsed.scheme, parsed.netloc, "", parsed.query, parsed.fragment))
    return f"{base_url}/{database}"


celery_app = Celery(
    "bio_lab",
    broker=os.getenv("CELERY_BROKER_URL", _redis_db_url(REDIS_URL, 0)),
    backend=os.getenv("CELERY_RESULT_BACKEND", _redis_db_url(REDIS_URL, 1)),
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
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true",
    task_eager_propagates=True,
)

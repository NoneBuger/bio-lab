"""Celery application configuration."""

import os

from celery import Celery


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
celery_app = Celery(
    "bio_lab",
    broker=os.getenv("CELERY_BROKER_URL", f"{REDIS_URL}/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", f"{REDIS_URL}/1"),
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

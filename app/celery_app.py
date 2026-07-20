from celery import Celery
from app.config import settings

# Initialize Celery app
celery_app = Celery(
    "iped_lxc_wrapper",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"]
)

# Update configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
    enable_utc=True,
    task_track_started=True,
)

if __name__ == "__main__":
    celery_app.start()

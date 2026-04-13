from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import LiveTask


def _run_live_task(task_id: str) -> None:
    from app.services.live_service import execute_live_task

    execute_live_task(task_id)


class SchedulerManager:
    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.scheduler.start()
        self._started = True

    def shutdown(self) -> None:
        if not self._started:
            return
        self.scheduler.shutdown(wait=False)
        self._started = False

    def is_running(self) -> bool:
        return self._started

    def job_count(self) -> int:
        return len(self.scheduler.get_jobs())

    def schedule_live_task(self, task_id: str, cadence_seconds: int) -> None:
        self.start()
        self.scheduler.add_job(
            _run_live_task,
            trigger=IntervalTrigger(seconds=cadence_seconds, timezone=settings.scheduler_timezone),
            args=[task_id],
            id=self._job_id(task_id),
            replace_existing=True,
            coalesce=settings.scheduler_coalesce,
            max_instances=1,
        )

    def restore_live_tasks(self) -> None:
        self.start()
        with SessionLocal() as db:
            tasks = db.scalars(select(LiveTask).where(LiveTask.status == "active")).all()
            for task in tasks:
                self.schedule_live_task(task.id, task.cadence_seconds)

    @staticmethod
    def _job_id(task_id: str) -> str:
        return f"live-task:{task_id}"


scheduler_manager = SchedulerManager()

"""Background jobs with visible progress: every long action (start-up, sync, upload, ask, enhance) is a Job.

The UI polls /api/jobs and shows state, the current step, a progress bar and any error. Agents that call the
REST API synchronously never see jobs; they simply wait for the result.
"""
from __future__ import annotations

import itertools
import threading
import time
import traceback
from collections import OrderedDict
from typing import Callable

_ids = itertools.count(1)
_lock = threading.Lock()
JOBS: "OrderedDict[int, Job]" = OrderedDict()
KEEP = 200


class Job:
    def __init__(self, kind: str, title: str):
        self.id, self.kind, self.title = next(_ids), kind, title
        self.state = "running"            # running | done | error
        self.step, self.progress, self.steps = "", None, []
        self.result, self.error = None, None
        self.started, self.finished = time.time(), None

    def log(self, step: str, progress: float | None = None) -> None:
        self.step = step
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        self.steps.append({"t": round(time.time() - self.started, 2), "msg": step})
        del self.steps[:-100]

    def view(self, full: bool = False) -> dict:
        d = {"id": self.id, "kind": self.kind, "title": self.title, "state": self.state, "step": self.step,
             "progress": self.progress, "error": self.error, "started": self.started, "finished": self.finished,
             "seconds": round((self.finished or time.time()) - self.started, 1)}
        if full:
            d.update(steps=self.steps, result=self.result)
        return d


def start(kind: str, title: str, fn: Callable[[Job], object], background: bool = True) -> Job:
    """Run fn(job) and record its outcome. background=False runs inline and re-raises errors."""
    job = Job(kind, title)
    with _lock:
        JOBS[job.id] = job
        while len(JOBS) > KEEP:
            JOBS.popitem(last=False)

    def run():
        try:
            job.result = fn(job)
            job.state, job.progress = "done", 1.0
        except Exception as exc:  # recorded for the UI; inline callers get it re-raised
            job.state, job.error = "error", f"{type(exc).__name__}: {exc}"
            job.steps.append({"t": round(time.time() - job.started, 2), "msg": traceback.format_exc(limit=3)})
            if not background:
                raise
        finally:
            job.finished = time.time()
    if background:
        threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
    else:
        run()
    return job


def get(job_id: int) -> Job | None:
    return JOBS.get(job_id)


def recent(limit: int = 50, kind: str | None = None) -> list[dict]:
    with _lock:
        items = [j for j in reversed(JOBS.values()) if kind is None or j.kind == kind]
    return [j.view() for j in items[:limit]]


def running(kind: str) -> Job | None:
    with _lock:
        return next((j for j in JOBS.values() if j.kind == kind and j.state == "running"), None)

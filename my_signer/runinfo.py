"""In-memory adapter result. Scheduling belongs to Qinglong."""
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, auto


class RunStatus(IntEnum):
    CATAGORY = auto()
    PENDING = auto()
    INITIALIZING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    NONEED = auto()
    FAIL = auto()
    CANCELLED = auto()
    ERROR = auto()
    SKIP = auto()
    IGNORE = auto()
    RESCHEDULE = auto()


@dataclass
class RunContext:
    description: str = ""
    status: RunStatus = RunStatus.PENDING
    status_info: str = ""
    next_time: datetime | None = None
    reschedule: int = 0

    @classmethod
    def prepare(cls, description="", **kwargs):
        return cls(description=description)

    def bind_logger(self, log):
        return log

    def start(self, status=RunStatus.RUNNING):
        self.status = status

    def finish(self, status=None, status_info=None):
        if status is not None:
            self.status = status
        if status_info:
            self.status_info = status_info
        return self

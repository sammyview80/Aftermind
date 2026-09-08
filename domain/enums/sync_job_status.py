from enum import Enum


class SyncJobStatus(str, Enum):
    PENDING = "pending"  # waiting to be claimed (first attempt or retry due)
    RUNNING = "running"  # claimed by a worker; reset to PENDING on restart if left here
    DONE = "done"
    DEAD = "dead"  # exhausted max_attempts; needs manual retry

from enum import Enum


class ReconciliationAction(str, Enum):
    """Decision made when reconciling a candidate against existing memory."""

    IGNORE = "ignore"        # not worth persisting
    CREATE = "create"        # new memory, no related existing memory
    UPDATE = "update"        # revises fields on an existing memory in place
    MERGE = "merge"          # combines candidate with an existing memory
    SUPERSEDE = "supersede"  # existing memory is outdated, replaced outright

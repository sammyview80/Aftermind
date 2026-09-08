from typing import ContextManager, Protocol


class UnitOfWork(Protocol):
    """A transaction boundary spanning several stores that share one
    backing database. Inside `transaction()`, every store write joins
    the same transaction and commits together on exit — or rolls back
    together if the block raises. This is what makes "write memory +
    enqueue its sync job" atomic rather than two separately-committed
    steps with a crash window between them."""

    def transaction(self) -> ContextManager[None]: ...

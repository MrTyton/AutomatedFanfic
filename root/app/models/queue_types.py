"""Queue protocol definitions and type aliases for AutomatedFanfic.

Provides structural protocols for queue operations satisfied by:
- stdlib queue.Queue
- multiprocessing.Queue
- multiprocessing.Manager().Queue() (AutoProxy)
- test mocks and stubs

Using protocols instead of concrete multiprocessing.queues.Queue allows
seamless interoperability across real processes, threads, and unit tests
without losing static type checking or resorting to `Any`.
"""

from typing import Any, Mapping, Protocol, TypeVar

from models.fanfic_info import FanficInfo

T = TypeVar("T")


class QueueProtocol(Protocol[T]):
    """Structural protocol for FIFO queues across thread and process boundaries."""

    def put(
        self, obj: T, /, block: bool = True, timeout: float | None = None
    ) -> None: ...
    def get(self, block: bool = True, timeout: float | None = None) -> T: ...
    def put_nowait(self, obj: T, /) -> None: ...
    def get_nowait(self) -> T: ...
    def qsize(self) -> int: ...
    def empty(self) -> bool: ...


# Type aliases for specific domain queues
WorkerTask = FanficInfo | None
WorkerQueue = QueueProtocol[WorkerTask]
WorkerQueues = Mapping[str, WorkerQueue]

# Ingress queue handles fanfic downloads, worker completion signals, and poison pills
IngressItem = FanficInfo | tuple[Any, ...] | None
IngressQueue = QueueProtocol[IngressItem]

# Waiting queue handles fanfics undergoing exponential backoff retries and poison pills
WaitingQueue = QueueProtocol[WorkerTask]

# History queue passes event payload dictionaries to the HistoryWriter
HistoryQueue = QueueProtocol[dict[str, Any]]

# Log queue passes structured log entries cross-process to the web server
LogQueue = QueueProtocol[dict[str, Any]]

# Scale queue notifies worker pool of scaling requests
ScaleQueue = QueueProtocol[str | None]

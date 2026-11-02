"""Models and state containers for the AutomatedFanfic coordinator."""

import collections
from dataclasses import dataclass, field
from enum import Enum


class SignalType(Enum):
    """Types of signals that can be sent to the coordinator."""

    WORKER_IDLE = "WORKER_IDLE"
    WORKER_STOPPED = "WORKER_STOPPED"
    SHUTDOWN = "SHUTDOWN"


@dataclass
class WorkerSignal:
    """Represents a signal from a worker to the coordinator."""

    signal_type: SignalType
    worker_id: str
    site: str | None = None

    @classmethod
    def from_tuple(cls, signal_tuple: tuple) -> "WorkerSignal | None":
        """Create WorkerSignal from legacy tuple format."""
        if not isinstance(signal_tuple, tuple) or len(signal_tuple) < 2:
            return None

        signal_str = signal_tuple[0]
        if signal_str == "WORKER_IDLE" and len(signal_tuple) == 3:
            return cls(
                signal_type=SignalType.WORKER_IDLE,
                worker_id=signal_tuple[1],
                site=signal_tuple[2],
            )
        if signal_str == "WORKER_STOPPED" and len(signal_tuple) >= 2:
            return cls(
                signal_type=SignalType.WORKER_STOPPED,
                worker_id=signal_tuple[1],
                site=signal_tuple[2] if len(signal_tuple) > 2 else None,
            )
        return None


@dataclass
class CoordinatorState:
    """Encapsulates the internal state of the coordinator.

    Groups related state variables together for clearer state management and easier testing.
    """

    backlog: dict[str, collections.deque] = field(
        default_factory=lambda: collections.defaultdict(collections.deque)
    )
    assignments: dict[str, str] = field(default_factory=dict)
    idle_workers: set[str] = field(default_factory=set)
    dormant_workers: set[str] = field(default_factory=set)
    qsize_supported: bool = True  # Cache whether queue.qsize() is supported

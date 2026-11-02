"""Worker package for parallel fanfiction downloading and Calibre integration."""

from models.context import WorkerContext
from workers.fff_runner import FanFicFareResult, execute_fanficfare_direct
from workers.handlers import handle_failure, process_fanfic_addition
from workers.pipeline import url_worker

__all__ = [
    "url_worker",
    "WorkerContext",
    "execute_fanficfare_direct",
    "FanFicFareResult",
    "handle_failure",
    "process_fanfic_addition",
]

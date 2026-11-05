"""Thread-local context and process-wide flags for ff_logging."""

import threading


class _LoggingFlag:
    """Lightweight process-local boolean flag providing a .value attribute."""

    def __init__(self, value: bool = False) -> None:
        self.value = bool(value)

    def __bool__(self) -> bool:
        return bool(self.value)

    def __repr__(self) -> str:
        return f"_LoggingFlag({self.value})"


# Process-local variables for global verbose and web logging control
verbose = _LoggingFlag(False)
web_enabled = _LoggingFlag(True)

# Thread-local storage for worker-specific logging context
_thread_local = threading.local()


def set_verbose(value: bool) -> None:
    """Sets the global verbose logging flag for debug output control."""
    verbose.value = value


def is_verbose() -> bool:
    """Returns the current state of the global verbose logging flag."""
    return bool(verbose.value)


def set_web_enabled(value: bool) -> None:
    """Sets whether the web UI is enabled for ring-buffer and debug log capture."""
    web_enabled.value = bool(value)


def is_web_enabled() -> bool:
    """Returns whether web UI log buffering is enabled."""
    return bool(web_enabled.value)


def set_thread_color(ansi_code: str) -> None:
    """Sets the color for the current thread's log output."""
    _thread_local.color = ansi_code


def get_thread_color() -> str | None:
    """Gets the color for the current thread's log output, if set."""
    return getattr(_thread_local, "color", None)


def set_thread_site(site: str | None) -> None:
    """Sets (or clears) the site tag for the current thread's log output."""
    _thread_local.site = site
    if site is None:
        _thread_local.story_url = None
        _thread_local.story_title = None
        _thread_local.worker_id = None
        _thread_local.attempt_id = None
        _thread_local.task_id = None


def set_thread_task(
    site: str | None,
    story_url: str | None = None,
    story_title: str | None = None,
    worker_id: str | None = None,
    attempt_id: str | None = None,
    task_id: str | None = None,
) -> None:
    """Sets the execution task context for the current worker thread's log output."""
    _thread_local.site = site
    _thread_local.story_url = story_url
    _thread_local.story_title = story_title
    _thread_local.worker_id = worker_id
    _thread_local.attempt_id = attempt_id
    _thread_local.task_id = task_id


def set_thread_story_title(title: str | None) -> None:
    """Updates the story title for the current worker thread."""
    _thread_local.story_title = title


def clear_thread_task() -> None:
    """Clears all task context for the current worker thread."""
    _thread_local.site = None
    _thread_local.story_url = None
    _thread_local.story_title = None
    _thread_local.worker_id = None
    _thread_local.attempt_id = None
    _thread_local.task_id = None


def get_thread_context() -> dict[str, object]:
    """Retrieves all thread-local context attributes as a dictionary."""
    ctx: dict[str, object] = {}
    if hasattr(_thread_local, "color"):
        ctx["thread_color"] = _thread_local.color
    if getattr(_thread_local, "site", None) is not None:
        ctx["thread_site"] = _thread_local.site
    if getattr(_thread_local, "story_url", None) is not None:
        ctx["story_url"] = _thread_local.story_url
    if getattr(_thread_local, "story_title", None) is not None:
        ctx["story_title"] = _thread_local.story_title
    if getattr(_thread_local, "worker_id", None) is not None:
        ctx["worker_id"] = _thread_local.worker_id
    if getattr(_thread_local, "attempt_id", None) is not None:
        ctx["attempt_id"] = _thread_local.attempt_id
    if getattr(_thread_local, "task_id", None) is not None:
        ctx["task_id"] = _thread_local.task_id
    return ctx

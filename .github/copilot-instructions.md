# AutomatedFanfic AI Agent Instructions

## Project Overview
AutomatedFanfic is a Python 3.13+ multiprocessing fanfiction downloader that monitors email (IMAP) for fanfiction URLs, processes them via FanFicFare CLI across 100+ sites, manages e-books through Calibre (calibredb), and sends notifications via Apprise. The architecture uses ProcessManager for lifecycle coordination, a Supervisor process hosting Email Watcher/Waiter/Coordinator as threads, and site-specific url_worker processes with domain locking.

**📘 For detailed architecture documentation, see [`project_architecture.md`](project_architecture.md)** - covers data flows, sequence diagrams, lifecycle patterns, and the "Domain Locking" politeness policy.

## Architecture Patterns

### Process Structure
- **Main Process**: Launches ProcessManager, registers all services/workers, handles signals (SIGTERM/SIGINT)
- **Supervisor Process**: Single process hosting 3 threads (EmailWatcher, Waiter, Coordinator) for memory efficiency
- **Worker Processes**: Site-specific `url_worker` processes (e.g., "ao3-worker", "ffnet-worker") for parallel downloads
- **ProcessManager**: Centralized lifecycle manager with health monitoring, auto-restart (max 3 attempts), monitoring thread

### Communication Flow
- **ingress_queue**: Unified task ingress point - receives FanficInfo tasks from email/retries AND worker signals ('WORKER_IDLE', worker_id, site)
- **worker_queues**: Dict[site, mp.Queue] - site-specific queues for coordinator → worker task distribution
- **waiting_queue**: Delayed retry queue for failed downloads (exponential backoff: 1min, 2min, 3min...)
- **active_urls**: Dict[url, FanficInfo] - shared memory tracking of in-flight downloads

### Key Design Principles
1. **Domain Locking**: Coordinator ensures no two workers process same site simultaneously
2. **Unified Ingress**: Workers requeue failed tasks to ingress_queue, not worker_queues directly
3. **Thread Coloring**: Each process/thread has color-coded logging (e.g., Supervisor=green, workers=cyan)
4. **Defensive Programming**: All queue operations wrapped in try/except, check `qsize()` support on startup
5. **Signal Safety**: All processes register SIGTERM/SIGINT handlers for Docker compatibility

## Configuration & Models

### TOML Configuration (Pydantic)
- **config_models.py**: Pydantic BaseModel classes for validation (EmailConfig, CalibreConfig, RetryConfig, AppConfig)
- **Special Fields**:
  - `update_method`: "update" | "update_always" | "force" | "update_no_force" (controls FanFicFare -u/-U/--force flags)
  - `metadata_preservation_mode`: "remove_add" | "preserve_metadata" | "add_format" (Calibre metadata handling)
  - `hail_mary_enabled`: bool (enable 12-hour final retry after 11 normal attempts)
  - `max_normal_retries`: int (1-50, default 11) - exponential backoff attempts before Hail-Mary
- **Validation**: Use `@field_validator` for custom checks (e.g., email format, server trimming)

### Core Data Models
- **FanficInfo** (`models/fanfic_info.py`): Primary data structure passed between workers
  - Fields: url, site, title, calibre_id, behavior ("update"|"force"), repeat_count, last_status
  - Methods: `increment_repeat()`, `__eq__/__hash__` based on (url, site, calibre_id)
- **FailureAction** (`models/retry_types.py`): Enum for retry decisions (REQUEUE, HAIL_MARY, FAIL)
- **ProcessInfo** (`process_management/state.py`): Process tracking with state, start_time, restart_count

## Critical Workflows

### Testing Commands (MUST activate venv)
```powershell
# ALWAYS activate venv first - required for each new shell
& c:/Users/Joshua/Documents/GitHub/AutomatedFanfic/.venv/Scripts/Activate.ps1

# Full test suite with coverage
python -m pytest root/tests/ --cov=root/app --cov-report=term-missing --tb=line -q

# Integration tests only (31 tests, slower)
python -m pytest root/tests/integration/ -v

# Unit tests only (501 tests, fast)
python -m pytest root/tests/unit/ -v

# Coverage HTML report
python -m pytest root/tests/ --cov=root/app --cov-report=html
```

### Retry Protocol (11+1 System)
1. **Normal Retries**: 11 attempts with exponential backoff (1min, 2min, 3min... 11min)
2. **Hail-Mary**: After 11 failures, wait `hail_mary_wait_hours` (default 12.0), then 1 final attempt with force
3. **Auto-Force Detection**: System automatically triggers force on chapter count mismatch or metadata bugs
4. **Force Precedence**: `update_no_force` always ignores force requests → normal retry failures trigger special notification

### Worker Idle Signal Pattern
```python
# Workers signal coordinator when finishing a site:
ingress_queue.put(('WORKER_IDLE', worker_id, finished_site))

# Coordinator processes signals:
signal_tuple = ingress_queue.get(timeout=5)
if isinstance(signal_tuple, tuple) and signal_tuple[0] == 'WORKER_IDLE':
    worker_id, finished_site = signal_tuple[1], signal_tuple[2]
    # Remove site assignment, mark worker idle
```

### ProcessManager Health Monitoring
```python
# Health check signature (note: name comes BEFORE process_info)
def _health_check_process(self, name: str, process_info: ProcessInfo, current_time: float) -> bool:
    # Check if process alive, restart if crashed (max 3 attempts)
    # Monitoring thread runs every process_config.health_check_interval_seconds
```

## Common Patterns & Conventions

### Logging with Context
```python
# Site-based logging (workers)
ff_logging.log(f"({site}) Processing {fanfic.url}")
ff_logging.log_debug(f"\t({site}) Extracted title: {title}")
ff_logging.log_failure(f"({site}) Failed to download: {error}")

# Structured logging (services)
ff_logging.log("Supervisor: Starting helper services...")
ff_logging.log_debug("ProcessManager: Registered process: ao3-worker")
```

### Queue Safety
```python
# ALWAYS wrap queue operations
try:
    task = queue.get(timeout=5)
except Empty:
    continue  # Normal timeout
except OSError:
    # Queue closed - graceful shutdown
    ff_logging.log_debug("Queue closed, shutting down")
    break

# Check qsize() support once at startup
try:
    queue.qsize()
    self.qsize_supported = True
except NotImplementedError:
    self.qsize_supported = False  # macOS doesn't support qsize()
```

### Temporary Directories (Workers)
```python
from utils import system_utils

# ALWAYS use context manager for worker processing
with system_utils.temporary_directory() as temp_dir:
    # Download/update story in temp_dir
    # Cleanup automatic on exit
```

### Testing Process Manager
```python
# Use register_process (NOT add_process - deprecated)
manager.register_process("test_proc", target=dummy_target, args=(arg1,))
manager.start_process("test_proc")

# Health check requires (name, process_info, current_time)
manager._health_check_process("test_proc", proc_info, time.time())
```

## Integration Points

### FanFicFare CLI
- **Location**: External Python package, invoked via subprocess
- **Command Construction**: `command.construct_fanficfare_command(calibre_info, fanfic, path_or_url)`
- **Flags**: `-u` (update), `-U` (update always), `--force` (force download), `--update-cover` (calibre mode)
- **Output Parsing**: `regex_parsing.py` extracts chapter counts, error messages from stderr/stdout

### Calibre Integration
- **calibredb CLI**: All operations via subprocess (add, remove, export, set_metadata)
- **Version Detection**: `get_calibre_version()` parses "calibredb (calibre X.Y.Z)"
- **Metadata Preservation**:
  - "remove_add": Remove old + add new (LOSES custom columns)
  - "preserve_metadata": Export custom columns → remove → add → restore
  - "add_format": Replace EPUB file only (PRESERVES all metadata)
- **ID Parsing**: `add_story()` extracts `Added book ids: 123` from stdout

### Apprise Notifications
- **Automatic Pushbullet**: [pushbullet] config auto-converted to Apprise URL
- **Multi-Service**: urls list supports Discord, Email, secondary Pushbullet accounts
- **Notification Types**: Success, failure, retry exhausted, Hail-Mary attempts

## Edge Cases & Defensive Checks

### Known Uncovered Areas (9% remaining)
- **Error Logging**: Many `ff_logging.log_failure()` calls in exception handlers (hard to trigger)
- **Platform-Specific**: `queue.qsize()` NotImplementedError on macOS (rarely tested)
- **Deep State Paths**: Coordinator backlog management with complex site assignment chains
- **Signal Handlers**: SIGTERM/SIGINT handlers in worker processes (integration test territory)

### Tests NOT to Write
- **Hanging Worker Tests**: Avoid mocking worker loop exceptions that catch KeyboardInterrupt
- **Deep Mock Chains**: Tests requiring 5+ nested mocks often indicate over-testing private methods
- **Queue Exhaustion**: Tests that exhaust queue.get() side_effects can hang indefinitely

## Development Best Practices

1. **Always Read Method Signatures**: Check parameter order before calling internal methods (e.g., `_health_check_process`)
2. **Test Public APIs**: Focus on `register_process()`, `start_process()`, `stop_process()` - avoid testing removed private methods
3. **Coordinator Complexity**: Coordinator has deep state management - prefer integration tests over unit tests for complex flows
4. **Worker Isolation**: Workers use temporary directories, never share state beyond active_urls dict
5. **Configuration First**: Load config.toml → validate with Pydantic → pass AppConfig to ProcessManager
6. **Graceful Shutdown**: All long-running loops check `shutdown_event.is_set()` or handle SIGTERM

## Quick Reference

### File Structure
- `root/app/fanficdownload.py` - Entry point, argument parsing
- `root/app/services/supervisor.py` - Supervisor process hosting threads
- `root/app/services/coordinator.py` - Task distribution with domain locking
- `root/app/workers/pipeline.py` - Worker processing loop
- `root/app/process_management/manager.py` - ProcessManager lifecycle
- `root/app/models/` - Pydantic config, FanficInfo, retry types
- `root/tests/unit/` - 501 unit tests (fast, mocked)
- `root/tests/integration/` - 31 integration tests (slow, real processes)

### Key Dependencies
- Python 3.13.5, pytest 8.3.5, pytest-cov 7.0.0
- FanFicFare (external), Calibre (calibredb CLI), Apprise (notifications)
- Pydantic for config validation, multiprocessing for concurrency

### Coverage Status (91% overall)
- calibredb_utils: 98%, manager: 89%, calibre_info: 89%, pipeline: 93%
- coordinator: 74% (deep state paths), ff_logging: 62% (error branches)

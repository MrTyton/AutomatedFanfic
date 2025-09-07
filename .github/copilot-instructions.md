# AutomatedFanfic - AI Coding Agent Instructions

## Project Overview

AutomatedFanfic is a Python multiprocessing application that automates fanfiction downloading using FanFicFare CLI with Docker containerization. The application monitors email for fanfiction URLs, downloads/updates stories via Calibre integration, and provides notification capabilities.

**Core Architecture**: Multiprocessing-based with centralized ProcessManager coordination, email monitoring, URL parsing workers, and notification systems.

## Key Architecture Patterns

### 1. Multiprocessing & Worker Management
- **Primary Pattern**: `ProcessManager` (process_manager.py) coordinates worker processes with health monitoring
- **Worker Types**: Email monitoring (`url_ingester.py`) and site-specific URL processors (`url_worker.py`)
- **Queue-Based Communication**: Multiprocessing queues for inter-process data flow
- **Graceful Shutdown**: Signal handling (SIGTERM/SIGINT) with coordinated cleanup via shutdown events

### 2. Configuration Management
- **Pydantic Models**: Type-safe configuration with validation (`config_models.py`)
- **TOML-Based**: Primary config in `config.toml`, with defaults and validation
- **Hierarchical Structure**: Email, Calibre, Pushbullet, Apprise, and Process configurations
- **Hot Reload**: Some configs (INI files) reload without restart; TOML requires restart

### 3. URL Processing & Site Recognition
- **Auto-Generated Parsers**: `auto_url_parsers.py` dynamically generates regex patterns from FanFicFare adapters
- **Site-Specific Queues**: Each major fanfiction site gets its own processing queue (fanfiction.net, archiveofourown.org, etc.)
- **Fallback Queue**: "other" queue handles unrecognized sites
- **URL Patterns**: Algorithmic generation eliminates manual regex maintenance

### 4. Error Handling & Retry Logic
- **Exponential Backoff**: Failures wait progressively (1min, 2min, 3min... up to 11 attempts)
- **Hail-Mary Protocol**: Final attempt waits 12 hours before retry
- **Force Update Logic**: Automatic force detection for chapter mismatches, with `update_no_force` override
- **Behavior Tracking**: Stories track retry count, force requests, and failure states

## Critical Workflows

### Application Startup
1. Parse command-line arguments (`--config`, `--verbose`)
2. Load TOML configuration with Pydantic validation
3. Initialize ProcessManager with app config
4. Create notification wrapper and Calibre connection
5. Register email watcher and site-specific workers
6. Start all processes with health monitoring
7. Wait for completion or signal interruption

### Email Monitoring Loop
1. Connect to IMAP server with configured credentials
2. Poll mailbox for unread emails at `sleep_time` interval
3. Extract URLs using FanFicFare's `geturls()` function
4. Route URLs to appropriate site queues based on regex matching
5. Special handling: FFNet URLs trigger notifications only if `ffnet_disable=true`

### Story Processing Workflow
1. Worker receives FanficInfo from queue
2. Check if story exists in Calibre database
3. Determine update method based on configuration and story state
4. Execute FanFicFare with appropriate flags (`-u`, `-U`, `--force`)
5. Handle success: Add/update Calibre, send notification
6. Handle failure: Increment retry count, apply exponential backoff, check for Hail-Mary

### Signal Handling (Important!)
- **Deduplication**: Shutdown event prevents multiple signal handler executions
- **Coordinated Exit**: Main process waits for all workers to terminate
- **Docker Compatibility**: Prevents 30-second SIGTERM timeouts by ensuring main process exits
- **Clean Shutdown**: ProcessManager stops all workers before main process termination

## Testing Conventions

### Test Structure
- **Unit Tests**: `root/tests/unit/` - Fast, isolated component testing
- **Integration Tests**: `root/tests/integration/` - Multi-component interaction testing
- **Manual Tests**: `root/tests/manual_signal_test.py` - Interactive verification scripts

### Parameterized Testing
- **Pattern**: Extensive use of `@parameterized.expand()` for data-driven tests
- **Test Cases**: Named tuples for structured test case definitions (e.g., `URLPatternTestCase`, `HandleFailureTestCase`)
- **Edge Cases**: Comprehensive coverage of URL variations, error conditions, and configuration combinations

### Mocking Strategy
- **Mock External Dependencies**: FanFicFare, Calibre, email servers, notifications
- **Preserve Core Logic**: Mock I/O boundaries but test business logic
- **Process Testing**: Mock multiprocessing components for unit tests, real processes for integration

## Configuration Reference

### Critical Settings
```toml
[email]
email = "username_or_full_email"  # Username only OR full email address (provider dependent)
password = "app_password"  # Not account password
server = "imap.gmail.com"
mailbox = "INBOX"
sleep_time = 60
ffnet_disable = true  # true = notify only, false = process

[calibre]
path = "/path/to/library"  # Local path OR server URL
update_method = "update"  # "update"|"update_always"|"force"|"update_no_force"

[process]
health_check_interval = 60.0
shutdown_timeout = 30.0
restart_threshold = 3
```

### Update Method Behavior
- **`"update"`**: Normal FanFicFare `-u` flag, respects force requests
- **`"update_always"`**: Always uses `-U` flag for full refresh
- **`"force"`**: Always uses `--force` flag
- **`"update_no_force"`**: Uses `-u` flag, **ignores all force requests** (important!)

## Important Gotchas & Patterns

### Multiprocessing Context
- **mp.Process**: Used for worker isolation, not threading
- **Queue Communication**: All inter-process data must be serializable
- **Shared State**: Avoid shared memory; use message passing patterns
- **Process Lifecycle**: Always use ProcessManager for consistent startup/shutdown

### Docker Integration
- **Signal Propagation**: Container signals reach main process correctly
- **Volume Mapping**: Config and Calibre library directories must be mapped
- **Network Access**: Email (IMAP) and Calibre server connections required
- **Graceful Shutdown**: Critical for preventing data corruption and timeout issues

### FanFicFare Integration
- **CLI Wrapper**: Application shells out to FanFicFare command-line tool
- **Output Parsing**: Regex patterns in `regex_parsing.py` interpret FanFicFare output
- **Adapter Updates**: `auto_url_parsers.py` automatically syncs with FanFicFare's site support
- **Error Detection**: Multiple regex patterns detect specific failure modes

### Development Patterns
- **Logging**: Use `ff_logging` module for consistent formatting and levels
- **Error Handling**: Distinguish between retryable failures and permanent errors
- **Configuration Changes**: TOML changes require restart; INI files reload automatically
- **Testing**: Run full test suite with `pytest root/tests/` from project root

## Common Operations

### Adding New Site Support
1. Site should be automatically detected via FanFicFare adapters
2. Add site-specific queue in `fanficdownload.py` if needed for performance
3. Test URL recognition in `test_auto_url_parsers.py`
4. Verify integration in `test_regex_parsing.py`

### Debugging Processing Issues
1. Enable verbose logging with `--verbose` flag
2. Check ProcessManager health monitoring logs
3. Verify queue depths and worker responsiveness
4. Test individual components with unit tests
5. Use manual signal test for shutdown behavior verification

### Configuration Validation
1. Use Pydantic model validation for type safety
2. Test edge cases in `test_config_models.py`
3. Verify TOML parsing and error handling
4. Ensure backward compatibility for existing configs

This document captures the essential patterns, workflows, and conventions that make AutomatedFanfic work effectively. Focus on multiprocessing coordination, configuration management, and robust error handling when making changes.

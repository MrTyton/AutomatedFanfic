# AI Coding Agent Instructions for AutomatedFanfic

## Project Overview

AutomatedFanfic is a Docker-based automation system for downloading and managing fanfiction using FanFicFare CLI and Calibre. The system monitors email for story updates, downloads fanfiction through site-specific workers, and manages ebooks with notifications.

### Core Architecture
- **Multi-processing**: Site-specific worker processes with shared queues
- **Email Integration**: IMAP monitoring for fanfiction update notifications  
- **Docker Deployment**: Multi-platform support (linux/amd64, linux/arm64)
- **Configuration Management**: Type-safe Pydantic v2 models with TOML files
- **Notification System**: Apprise integration with Pushbullet support
- **Testing Infrastructure**: Comprehensive parameterized test suite (145+ tests)

## Configuration Management Patterns

### Pydantic Configuration Models (`config_models.py`)

**Always use the ConfigManager pattern** for configuration access:

```python
# Correct - Use ConfigManager
from config_models import ConfigManager, get_config

config = get_config()  # Global singleton access
email_config = config.email
calibre_config = config.calibre
```

**Key Configuration Classes:**
- `AppConfig`: Root configuration with email, calibre, pushbullet, apprise sections
- `EmailConfig`: IMAP settings with validation
- `CalibreConfig`: Database path and authentication 
- `PushbulletConfig`: API key and enabled status
- `AppriseConfig`: Notification URLs list

**Configuration Loading Pattern:**
```python
# Load from TOML file
config = load_config(Path("config.toml"))

# Set as global singleton (done once at startup)
ConfigManager.set_instance(config)

# Access globally throughout application
config = get_config()
```

### Testing Configuration Models

**Always use parameterized tests** for comprehensive coverage:

```python
from parameterized import parameterized
from unittest.mock import patch

class TestConfigModel(unittest.TestCase):
    @parameterized.expand([
        ("valid_email", "user@example.com", True),
        ("invalid_email", "not-an-email", False),
    ])
    def test_email_validation(self, name, email, should_pass):
        with patch.object(ConfigManager, 'get_instance'):
            if should_pass:
                config = AppConfig(email=EmailConfig(email=email, ...))
                self.assertEqual(config.email.email, email)
            else:
                with self.assertRaises(ValidationError):
                    AppConfig(email=EmailConfig(email=email, ...))
```

**ConfigManager Mocking Pattern:**
```python
# Mock ConfigManager for isolated testing
with patch.object(ConfigManager, 'get_instance') as mock_get:
    mock_config = AppConfig(...)
    mock_get.return_value = mock_config
    
    # Test code using get_config()
    result = function_under_test()
```

## Process Management Architecture

### ProcessManager Class (`process_manager.py`)

**AutomatedFanfic uses a robust ProcessManager** for all multiprocessing needs:

```python
# Correct - Use ProcessManager with dependency injection
from process_manager import ProcessManager
from config_models import AppConfig

# Initialize with configuration
with ProcessManager(config=config) as process_manager:
    # Register processes
    process_manager.register_process("worker", worker_function, args=(arg1, arg2))
    
    # Start all processes
    process_manager.start_all()
    
    # Wait for completion
    process_manager.wait_for_all()
    # Context manager handles graceful shutdown
```

**Key ProcessManager Features:**
- **Dependency Injection**: No global state, clean configuration passing
- **Process Registration**: Simple API for adding processes with arguments/kwargs
- **Lifecycle Management**: Start, stop, restart individual or all processes
- **Health Monitoring**: Background monitoring with configurable intervals
- **Graceful Shutdown**: SIGTERM → SIGKILL escalation with timeouts
- **Signal Handling**: Automatic SIGINT/SIGTERM handling for production
- **Process Waiting**: `wait_for_all()` method for proper completion handling

### Process Configuration (`config_models.py`)

**ProcessConfig class** provides type-safe process management settings:

```python
class ProcessConfig(BaseModel):
    shutdown_timeout: float = Field(default=10.0, ge=1.0, le=300.0)
    health_check_interval: float = Field(default=30.0, ge=0.1, le=3600.0)
    auto_restart: bool = Field(default=True)
    max_restart_attempts: int = Field(default=3, ge=0, le=10)
    restart_delay: float = Field(default=5.0, ge=0.1, le=60.0)
    enable_monitoring: bool = Field(default=True)
```

### Signal Handling Pattern

**ProcessManager handles signals automatically:**

```python
# In ProcessManager.__enter__()
def setup_signal_handlers(self):
    def signal_handler(signum, frame):
        signal_name = signal.Signals(signum).name
        ff_logging.log(f"Received signal {signal_name}, initiating graceful shutdown...")
        self.stop_all()  # Gracefully terminate all child processes
        # Return to allow main application to handle the flow
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
```

**Main application waits for processes:**

```python
try:
    process_manager.wait_for_all()  # Wait indefinitely for normal completion
except KeyboardInterrupt:
    # Signal handler already called stop_all()
    # Wait with timeout for graceful shutdown completion
    if not process_manager.wait_for_all(timeout=300.0):
        ff_logging.log_failure("Timeout - forcing shutdown")
```

### Main Application Pattern (`fanficdownload.py`)

**Use ProcessManager instead of manual multiprocessing:**

```python
# Load configuration
config = ConfigManager.load_config(args.config)

# Use ProcessManager for robust process handling
with ProcessManager(config=config) as process_manager:
    # Register all needed processes
    process_manager.register_process("email_watcher", email_watcher_func, args=(...))
    process_manager.register_process("waiting_watcher", waiting_processor_func, args=(...))
    
    # Register worker processes for each site
    for site in sites:
        process_manager.register_process(f"worker_{site}", worker_func, args=(...))
    
    # Start all processes
    process_manager.start_all()
    
    # Wait for completion with proper signal handling
    try:
        process_manager.wait_for_all()
    except KeyboardInterrupt:
        # ProcessManager handles graceful shutdown
        if not process_manager.wait_for_all(timeout=300.0):
            ff_logging.log_failure("Timeout - forcing shutdown")
```

### Worker Process Pattern (`url_worker.py`)

**Site-specific worker architecture:**
- Each worker handles specific fanfiction sites
- Shared queues for task distribution
- Process-safe logging and error handling

```python
def url_worker(site_queue, calibre_info, notification_info, waiting_queue):
    """Worker function that ProcessManager will run in separate process."""
    while True:
        try:
            # Process items from queue
            item = site_queue.get(timeout=30)
            # ... process the item
        except queue.Empty:
            continue
        except Exception as e:
            ff_logging.log_failure(f"Worker error: {e}")
```

## URL Processing and Site Support

### Regex Parsing (`regex_parsing.py`)

**Site-specific URL patterns:**
- Centralized regex patterns for different fanfiction sites
- Error handling for unsupported URLs
- Validation before worker assignment

```python
def parse_fanfiction_url(url):
    """Parse URL and determine appropriate site handler."""
    for site_pattern in SITE_PATTERNS:
        if site_pattern.matches(url):
            return site_pattern.site_name
    raise UnsupportedSiteError(f"URL not supported: {url}")
```

### Worker Assignment (`url_worker.py`)

**Distribution logic:**
- URLs routed to appropriate site workers
- Error handling for processing failures
- Retry mechanisms for transient failures

## Testing Patterns

### Parameterized Testing Strategy

**Always use @parameterized.expand** for multiple test scenarios:

```python
@parameterized.expand([
    ("scenario_1", input1, expected1),
    ("scenario_2", input2, expected2),
    ("edge_case", input3, expected3),
])
def test_function(self, name, input_value, expected):
    result = function_under_test(input_value)
    self.assertEqual(result, expected)
```

**Benefits:**
- Single test method covers multiple scenarios
- Clear test case names for debugging
- Improved coverage with minimal code duplication

### ProcessManager Testing Patterns

**Use dependency injection for clean tests:**

```python
class TestProcessManager(unittest.TestCase):
    def setUp(self):
        """Set up test configuration."""
        self.config = AppConfig(
            email=EmailConfig(email="test@example.com", ...),
            calibre=CalibreConfig(path="/test/path"),
            process=ProcessConfig(
                shutdown_timeout=2.0,
                health_check_interval=1.0,
                auto_restart=True
            )
        )
        
        # Always provide config to ProcessManager
        self.manager = ProcessManager(config=self.config)
```

**Test process lifecycle:**

```python
def test_process_lifecycle(self):
    """Test complete process lifecycle."""
    # Register a test process
    self.manager.register_process("test", dummy_worker)
    
    # Start and verify
    self.assertTrue(self.manager.start_process("test"))
    self.assertEqual(self.manager.processes["test"].state, ProcessState.RUNNING)
    
    # Stop and verify
    self.assertTrue(self.manager.stop_process("test"))
    self.assertEqual(self.manager.processes["test"].state, ProcessState.STOPPED)
```

**Test signal handling:**

```python
def test_signal_handler_calls_stop_all(self):
    """Test signal handler integration."""
    with patch.object(self.manager, 'stop_all') as mock_stop_all:
        self.manager.setup_signal_handlers()
        
        # Test that signal handlers are properly configured
        self.assertTrue(self.manager._signal_handlers_set)
        
        # Verify stop_all functionality
        self.manager.stop_all()
        mock_stop_all.assert_called_once()
```

**Test wait_for_all functionality:**

```python
def test_wait_for_all_timeout(self):
    """Test wait_for_all with timeout."""
    # Mock a running process
    mock_process_info = MagicMock()
    mock_process_info.is_alive.return_value = True
    self.manager.processes["test"] = mock_process_info
    
    # Should timeout quickly
    result = self.manager.wait_for_all(timeout=0.1)
    self.assertFalse(result)
```

### Validation Error Testing

**For Pydantic models, always test ValidationError:**

```python
from pydantic import ValidationError

def test_invalid_configuration(self):
    with self.assertRaises(ValidationError) as context:
        AppConfig(email=EmailConfig(email="invalid"))
    
    # Verify specific validation failure
    self.assertIn("email", str(context.exception))
```

### Mock Configuration Patterns

**Never use global state or test detection in production code:**

```python
# WRONG - Don't do this in production code
if "test" in sys.modules or os.getenv("TESTING"):
    config = load_test_config()

# RIGHT - Use dependency injection
class ProcessManager:
    def __init__(self, config: AppConfig):
        self.config = config  # Always require explicit config
```

**Use proper mocking in tests:**

```python
@patch.object(ConfigManager, 'get_instance')
def test_with_mocked_config(self, mock_get):
    # Create test configuration
    test_config = AppConfig(
        email=EmailConfig(email="test@example.com", ...),
        process=ProcessConfig(shutdown_timeout=2.0, ...)
    )
    mock_get.return_value = test_config
    
    # Test function that uses get_config()
    result = function_using_config()
    self.assertEqual(result.some_property, "expected_value")
```

## Docker and Deployment

### Multi-Platform Support

**Docker configuration supports:**
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM64/AArch64)

**Environment variables for configuration:**
- Mount config files to `/config/`
- Use environment variable overrides for sensitive data

### CI/CD Integration

**GitHub Actions workflows:**
- `python-app.yml`: Runs test suite with pytest
- `docker-image.yml`: Builds and publishes multi-platform images
- `update-dependencies.yml`: Automated dependency updates

**Testing requirements:**
- All tests must pass (181+ tests including ProcessManager)
- Flake8 linting compliance
- Test results uploaded as artifacts
- ProcessManager integration tests included

## Error Handling Patterns

### Configuration Errors

**Graceful configuration failure handling:**

```python
try:
    config = load_config(config_path)
except ValidationError as e:
    logger.error(f"Configuration validation failed: {e}")
    sys.exit(1)
except FileNotFoundError:
    logger.error(f"Configuration file not found: {config_path}")
    sys.exit(1)
```

### Worker Process Errors

**Process-safe error handling:**
- Log errors with process identification
- Queue error messages for main process
- Implement retry logic for transient failures

### FanFicFare Integration Errors

**CLI integration error handling:**
- Validate FanFicFare installation
- Handle unsupported site errors
- Process timeout management

## File Organization

### Project Structure
```
root/app/                    # Main application code
├── fanficdownload.py       # Main entry point
├── config_models.py        # Pydantic configuration models
├── url_worker.py           # Worker process implementation
├── regex_parsing.py        # URL parsing and site detection
├── *_test.py              # Comprehensive test suite
└── test_config.py         # Configuration testing utility

config.default/             # Default configuration templates
├── config.toml            # Main configuration file
├── defaults.ini           # FanFicFare defaults
└── personal.ini           # Personal preferences

.github/workflows/          # CI/CD automation
├── python-app.yml         # Testing pipeline
├── docker-image.yml       # Docker builds
└── update-dependencies.yml # Dependency updates
```

### Import Patterns

**Use relative imports within app directory:**
```python
# Within root/app/
from config_models import ConfigManager, get_config
from regex_parsing import parse_fanfiction_url
from url_worker import UrlWorker
```

**Add app directory to path for tests:**
```python
# In test files
sys.path.insert(0, str(Path(__file__).parent))
from config_models import ConfigManager
```

## Best Practices for AI Agents

### Before Making Changes

1. **Understand the ProcessManager system** - Always use ProcessManager for multiprocessing
2. **Check existing tests** - Follow parameterized testing patterns
3. **Validate with existing test suite** - Run all 181+ tests before committing
4. **Consider signal handling implications** - Ensure graceful shutdown works

### When Adding Features

1. **Add configuration options** to appropriate Pydantic models
2. **Create parameterized tests** covering multiple scenarios
3. **Test ProcessManager integration** if adding new processes
4. **Update Docker configuration** if needed for new dependencies
5. **Document in README.md** for user-facing changes

### When Fixing Bugs

1. **Write tests that reproduce the bug** first
2. **Use existing error handling patterns**
3. **Ensure ProcessManager compatibility** for process-related changes
4. **Test signal handling** if modifying process lifecycle
5. **Ensure compatibility** with Docker deployment
6. **Test configuration validation** for related settings

### Code Quality Standards

- **Type hints**: Use throughout for better IDE support
- **Docstrings**: Document complex functions and classes
- **Error handling**: Use try/except blocks with specific exceptions
- **Logging**: Use structured logging with appropriate levels
- **Testing**: Aim for comprehensive coverage with parameterized tests

## Common Pitfalls to Avoid

1. **Don't bypass ProcessManager** - Always use ProcessManager for multiprocessing needs
2. **Don't skip parameterized tests** - They provide significantly better coverage
3. **Don't ignore ValidationError** - Test Pydantic validation explicitly
4. **Don't hardcode paths** - Use configuration management
5. **Don't assume single-threading** - Code must be process-safe
6. **Don't modify core FanFicFare behavior** - Use configuration files instead
7. **Don't use manual signal handling** - ProcessManager handles signals automatically
8. **Don't call exit() in signal handlers** - Let ProcessManager manage shutdown flow
9. **Don't forget timeout handling** - Always use timeouts for process operations

## Integration Points

### Email Monitoring
- IMAP connection management with configuration
- Error handling for connection failures
- Email parsing for fanfiction update notifications

### Calibre Integration
- Database path validation and access
- Command-line interface integration
- Ebook format management and conversion

### Notification System
- Apprise URL configuration and validation
- Pushbullet API integration
- Error notification for failed downloads

This document should guide AI coding agents in understanding and maintaining the AutomatedFanfic codebase effectively while following established patterns and best practices.

## Recent Architecture Improvements (September 2025)

### ProcessManager Implementation
- **Replaced scattered multiprocessing code** with centralized ProcessManager class
- **Added robust signal handling** with SIGTERM/SIGINT support for graceful shutdown
- **Implemented process health monitoring** with automatic restart capabilities
- **Created comprehensive test suite** with 30+ ProcessManager-specific tests
- **Added process waiting mechanism** with `wait_for_all()` method and timeout support

### Key Architectural Benefits
- **Centralized process management** instead of scattered code across multiple functions
- **Production-ready signal handling** compatible with Docker, systemd, and manual termination
- **Automatic error recovery** via health monitoring and configurable restart policies
- **Clean shutdown guarantees** preventing zombie processes and resource leaks
- **Type-safe configuration** with Pydantic validation for all process settings
- **Comprehensive observability** with detailed process status and metrics

### Migration from Legacy Patterns
- **Removed manual process creation** functions (`create_processes`, `start_processes`, etc.)
- **Replaced manual signal handlers** with ProcessManager's integrated signal handling
- **Eliminated manual process joining** with ProcessManager's `wait_for_all()` method
- **Upgraded from basic Pool usage** to sophisticated process lifecycle management

When working with this codebase, always use ProcessManager for any new multiprocessing needs and follow the established patterns for configuration, testing, and error handling.

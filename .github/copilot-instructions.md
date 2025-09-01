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

## Multi-Processing Architecture

### Worker Process Pattern (`url_worker.py`)

**Site-specific worker architecture:**
- Each worker handles specific fanfiction sites
- Shared queues for task distribution
- Process-safe logging and error handling

```python
def create_worker_processes(sites, shared_queue):
    """Create worker processes for each supported site."""
    processes = []
    for site in sites:
        process = Process(target=worker_function, args=(site, shared_queue))
        processes.append(process)
    return processes
```

### Main Application Entry (`fanficdownload.py`)

**Orchestration patterns:**
- Command-line argument parsing with argparse
- Signal handling for graceful shutdown
- Queue management for inter-process communication

```python
# Command-line integration
parser = argparse.ArgumentParser()
parser.add_argument('--config', help='Configuration file path')
args = parser.parse_args()

# Load and set global config
config = load_config(Path(args.config))
ConfigManager.set_instance(config)
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

**Use ConfigManager mocking for isolated tests:**

```python
@patch.object(ConfigManager, 'get_instance')
def test_with_mocked_config(self, mock_get):
    # Create test configuration
    test_config = AppConfig(
        email=EmailConfig(email="test@example.com", ...),
        calibre=CalibreConfig(path="/test/path", ...)
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
- All tests must pass (145+ tests)
- Flake8 linting compliance
- Test results uploaded as artifacts

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

1. **Understand the configuration system** - Always use ConfigManager patterns
2. **Check existing tests** - Follow parameterized testing patterns
3. **Validate with existing test suite** - Run all 145+ tests before committing
4. **Consider multi-processing implications** - Ensure thread/process safety

### When Adding Features

1. **Add configuration options** to appropriate Pydantic models
2. **Create parameterized tests** covering multiple scenarios
3. **Update Docker configuration** if needed for new dependencies
4. **Document in README.md** for user-facing changes

### When Fixing Bugs

1. **Write tests that reproduce the bug** first
2. **Use existing error handling patterns**
3. **Ensure compatibility** with Docker deployment
4. **Test configuration validation** for related settings

### Code Quality Standards

- **Type hints**: Use throughout for better IDE support
- **Docstrings**: Document complex functions and classes
- **Error handling**: Use try/except blocks with specific exceptions
- **Logging**: Use structured logging with appropriate levels
- **Testing**: Aim for comprehensive coverage with parameterized tests

## Common Pitfalls to Avoid

1. **Don't bypass ConfigManager** - Always use get_config() for global access
2. **Don't skip parameterized tests** - They provide significantly better coverage
3. **Don't ignore ValidationError** - Test Pydantic validation explicitly
4. **Don't hardcode paths** - Use configuration management
5. **Don't assume single-threading** - Code must be process-safe
6. **Don't modify core FanFicFare behavior** - Use configuration files instead

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

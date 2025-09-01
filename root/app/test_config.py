"""
Test script for the new configuration management system.
"""

import sys
from pathlib import Path

# Add the app directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from config_models import ConfigManager, load_config, get_config


def test_config_loading():
    """Test loading configuration from the default config file."""
    try:
        # Test with the default config
        config_path = Path("../config.default/config.toml")
        if not config_path.exists():
            print(f"Config file not found at {config_path.absolute()}")
            return False

        # Load configuration
        config = load_config(config_path)

        print("✅ Configuration loaded successfully!")
        print(f"📧 Email: {config.email.email}")
        print(f"📚 Calibre Path: {config.calibre.path}")
        print(f"🔧 Max Workers: {config.max_workers}")
        print(f"📱 Pushbullet Enabled: {config.pushbullet.enabled}")
        print(f"📢 Apprise URLs: {len(config.apprise.urls)} configured")

        # Test getting global config
        global_config = get_config()
        assert global_config is not None, "Global config should be available"
        assert (
            global_config.email.email == config.email.email
        ), "Global config should match loaded config"

        print("✅ Global configuration access working!")

        return True

    except Exception as e:
        print(f"❌ Configuration loading failed: {e}")
        return False


if __name__ == "__main__":
    success = test_config_loading()
    sys.exit(0 if success else 1)

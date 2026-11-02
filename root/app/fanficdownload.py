"""AutomatedFanfic main application module."""

import argparse
import multiprocessing as mp
import sys

if sys.version_info < (3, 15):
    raise RuntimeError("AutomatedFanfic requires Python 3.15 or newer.")

from config import AppConfig, ConfigError, ConfigManager, ConfigValidationError
import ff_logging
from process_management import ProcessManager
from services import bootstrap

lazy from parsers import url_patterns

__version__ = "6.16.2"


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments for the AutomatedFanfic application."""
    parser = argparse.ArgumentParser(description="Process input arguments.")
    parser.add_argument(
        "--config",
        default="../config.default/config.toml",
        help="The location of the config.toml file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    """Configures application logging based on verbosity settings."""
    ff_logging.set_verbose(verbose)


def load_configuration(config_path: str) -> AppConfig:
    """Loads and validates the application configuration from a TOML file."""
    try:
        return ConfigManager.load_config(config_path)
    except ConfigError as e:
        ff_logging.log_failure(f"Configuration error: {e}")
        sys.exit(1)
    except ConfigValidationError as e:
        ff_logging.log_failure(f"Configuration validation failed: {e}")
        sys.exit(1)
    except Exception as e:
        ff_logging.log_failure(f"Unexpected error loading configuration: {e}")
        sys.exit(1)


def main() -> None:
    """Main application entry point."""
    if sys.platform == "linux" and mp.get_start_method(allow_none=True) is None:
        mp.set_start_method("forkserver")

    args = parse_arguments()
    setup_logging(args.verbose)
    config = load_configuration(args.config)

    bootstrap.log_configuration_details(config, args, version=__version__)

    with ProcessManager(config=config) as process_manager:
        with mp.Manager() as manager:
            ff_logging.log("Generating URL parsers from FanFicFare adapters...")
            url_parsers = url_patterns.generate_url_parsers_from_fanficfare()
            ff_logging.log(
                f"Generated {len(url_parsers)} URL parsers for site recognition"
            )

            bootstrap.register_processes(
                process_manager, config, args, manager, url_parsers
            )

            ff_logging.log("Starting all processes...")
            process_manager.start_all()
            ff_logging.log("All processes started successfully")
            ff_logging.log("Processes running. Press Ctrl+C to stop gracefully.")

            try:
                process_manager.wait_for_all()
                ff_logging.log("All processes completed normally")

            except KeyboardInterrupt:
                ff_logging.log(
                    "KeyboardInterrupt caught - signal handler may not have handled shutdown",
                    "WARNING",
                )
                if not process_manager._shutdown_event.is_set():
                    ff_logging.log(
                        "Initiating manual shutdown due to KeyboardInterrupt"
                    )
                    process_manager.stop_all()

                if not process_manager.wait_for_all(timeout=30.0):
                    ff_logging.log_failure(
                        "Timeout waiting for processes after manual shutdown"
                    )
                else:
                    ff_logging.log("Manual shutdown completed successfully")
            finally:
                history_writer = getattr(process_manager, "_history_writer", None)
                if history_writer is not None:
                    history_writer.stop()

    ff_logging.log("Application shutdown complete")


if __name__ == "__main__":
    main()

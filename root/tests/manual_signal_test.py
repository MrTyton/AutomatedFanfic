#!/usr/bin/env python3
"""
Manual test script for verifying signal handling improvements.

This script simulates the main fanficdownload.py behavior and can be used
to manually verify that:
1. Only one SIGTERM message is logged
2. Shutdown happens quickly
3. No "Force killing process" messages appear
4. No duplicate signal handling occurs

Usage:
    python manual_signal_test.py

Then send SIGTERM to the process (e.g., via Docker stop, kill, or Ctrl+C)
and observe the output.
"""

import sys
import os
import time

# Add the app directory to the path
current_dir = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.join(os.path.dirname(current_dir), "app")
sys.path.insert(0, app_dir)

from config_models import (  # noqa: E402
    AppConfig,
    ProcessConfig,
    EmailConfig,
    CalibreConfig,
    PushbulletConfig,
    AppriseConfig,
)
from process_manager import ProcessManager  # noqa: E402


def simple_worker(worker_id, duration=60):
    """Simple worker that prints periodically."""
    print(f"Worker {worker_id} started (PID: {os.getpid()})")
    start_time = time.time()

    while time.time() - start_time < duration:
        print(f"Worker {worker_id} working...")
        time.sleep(2)

    print(f"Worker {worker_id} finished")


def main():
    """Main function that simulates fanficdownload.py behavior."""
    print("=== Manual Signal Handling Test ===")
    print(f"Main process PID: {os.getpid()}")
    print("Send SIGTERM to this process to test signal handling")
    print("Expected: Single SIGTERM message, fast shutdown, no duplicates")
    print()

    # Create minimal config
    config = AppConfig(
        email=EmailConfig(),
        calibre=CalibreConfig(),
        pushbullet=PushbulletConfig(),
        apprise=AppriseConfig(),
        process=ProcessConfig(
            enable_monitoring=False,
            auto_restart=False,
            shutdown_timeout=3.0,
        ),
        max_workers=2,
    )

    # Use ProcessManager with signal handling (simulating fanficdownload.py)
    with ProcessManager(config=config) as process_manager:
        # Register some worker processes
        for i in range(3):
            process_manager.register_process(
                f"worker_{i}",
                simple_worker,
                args=(i, 60),  # Run for 60 seconds if not interrupted
            )

        # Start all processes
        print("Starting worker processes...")
        process_manager.start_all()
        print("All processes started successfully")
        print()

        # Show process status
        status = process_manager.get_status()
        for name, info in status.items():
            print(f"Process {name}: PID={info['pid']}, alive={info['alive']}")
        print()

        print("Processes running. Send SIGTERM (or press Ctrl+C) to test shutdown...")
        print("Monitoring for signal handling behavior...")
        print()

        # Keep the main thread alive while processes run
        start_time = time.time()
        try:
            # This simulates the wait behavior in fanficdownload.py
            result = (
                process_manager.wait_for_all()
            )  # Wait indefinitely for normal completion

            if result:
                elapsed = time.time() - start_time
                print(f"Clean shutdown completed in {elapsed:.2f} seconds")
            else:
                print("Shutdown with timeout")

        except KeyboardInterrupt:
            # This should be handled by the signal handler now
            print("KeyboardInterrupt caught in main thread")
            elapsed = time.time() - start_time
            print(f"Shutdown took {elapsed:.2f} seconds after interrupt")

    print("=== Test Complete ===")


if __name__ == "__main__":
    main()

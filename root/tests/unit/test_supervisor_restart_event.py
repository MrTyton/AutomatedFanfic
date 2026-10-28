"""Unit tests for ProcessManager supervisor restart event handling."""

import threading
from typing import cast
import unittest
from unittest.mock import patch

from multiprocessing.synchronize import Event as MpEvent
from models.config_models import AppConfig, CalibreConfig, EmailConfig
from process_management.manager import ProcessManager
from process_management.state import ProcessInfo, ProcessState


class TestSupervisorRestartEvent(unittest.TestCase):
    """Tests that ProcessManager checks and reacts to supervisor_restart_event."""

    def setUp(self) -> None:
        self.config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="test.server.com",
            ),
            calibre=CalibreConfig(path="/test/path"),
        )
        self.manager = ProcessManager(self.config)

    def test_check_supervisor_restart_event_when_set(self) -> None:
        event = threading.Event()
        event.set()
        self.manager.set_supervisor_restart_event(cast(MpEvent, event))

        proc_info = ProcessInfo(name="supervisor", target=lambda: None)
        proc_info.state = ProcessState.RUNNING
        proc_info.restart_count = 2
        self.manager.processes["supervisor"] = proc_info

        with patch.object(self.manager, "restart_process") as mock_restart:
            self.manager._check_supervisor_restart_event()
            self.assertFalse(event.is_set())
            self.assertEqual(proc_info.restart_count, 0)
            mock_restart.assert_called_once_with("supervisor")

    def test_check_supervisor_restart_event_when_not_set(self) -> None:
        event = threading.Event()
        self.manager.set_supervisor_restart_event(cast(MpEvent, event))

        proc_info = ProcessInfo(name="supervisor", target=lambda: None)
        proc_info.state = ProcessState.RUNNING
        self.manager.processes["supervisor"] = proc_info

        with patch.object(self.manager, "restart_process") as mock_restart:
            self.manager._check_supervisor_restart_event()
            mock_restart.assert_not_called()

    def test_check_supervisor_restart_event_when_event_is_none(self) -> None:
        with patch.object(self.manager, "restart_process") as mock_restart:
            self.manager._check_supervisor_restart_event()
            mock_restart.assert_not_called()

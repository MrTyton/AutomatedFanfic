import multiprocessing as mp
import unittest
from unittest.mock import MagicMock

from models.context import SharedIPCContext
from web.dependencies import WebState


class TestMcpIpcFoundation(unittest.TestCase):
    def test_shared_ipc_context_has_coordinator_status(self):
        with mp.Manager() as manager:
            coord_dict = manager.dict()
            ctx = SharedIPCContext(
                ingress_queue=manager.Queue(),
                waiting_queue=manager.Queue(),
                worker_queues={},
                active_urls=manager.dict(),
                history_recorder=MagicMock(),
                config_store=MagicMock(),
                scale_queue=manager.Queue(),
                shutdown_event=manager.Event(),
                coordinator_status=coord_dict,
            )
            self.assertIs(ctx.coordinator_status, coord_dict)

    def test_web_state_has_coordinator_status(self):
        state = WebState(coordinator_status={"assignments": {"ao3": "worker_0"}})
        self.assertEqual(state.coordinator_status, {"assignments": {"ao3": "worker_0"}})

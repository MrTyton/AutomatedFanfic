import threading
import unittest
from unittest.mock import MagicMock

from models.fanfic_info import FanficInfo
from services.coordinator import Coordinator


class TestCoordinatorStatePublishing(unittest.TestCase):
    def test_publish_state_exports_assignments_idle_and_backlog(self):
        status_dict = {}
        coord = Coordinator(
            ingress_queue=MagicMock(),
            worker_queues={},
            shutdown_event=MagicMock(),
            active_urls={},
            history_recorder=MagicMock(),
            url_parsers={},
            config_store=MagicMock(),
            scale_queue=MagicMock(),
            coordinator_status=status_dict,
            verbose=False,
        )
        coord.state.assignments = {"archiveofourown.org": "worker_0"}
        coord.state.idle_workers = {"worker_1"}
        coord.state.dormant_workers = set()
        coord.state.backlog["archiveofourown.org"].append(
            FanficInfo(
                url="https://archiveofourown.org/works/123",
                site="archiveofourown",
                behavior="update",
            )
        )
        coord._publish_state()

        self.assertEqual(
            status_dict["assignments"], {"archiveofourown.org": "worker_0"}
        )
        self.assertEqual(status_dict["idle_workers"], ["worker_1"])
        self.assertEqual(status_dict["dormant_workers"], [])
        self.assertEqual(len(status_dict["backlog"]["archiveofourown.org"]), 1)
        self.assertEqual(
            status_dict["backlog"]["archiveofourown.org"][0]["url"],
            "https://archiveofourown.org/works/123",
        )

    def test_publish_state_none_status_is_safe_noop(self):
        coord = Coordinator(
            ingress_queue=MagicMock(),
            worker_queues={},
            shutdown_event=MagicMock(),
            active_urls={},
            history_recorder=MagicMock(),
            url_parsers={},
            config_store=MagicMock(),
            scale_queue=MagicMock(),
            coordinator_status=None,
            verbose=False,
        )
        # Should not raise exception
        coord._publish_state()

    def test_coordinator_lifecycle_publishes_state_transitions(self):
        status_dict = {}
        ingress_q = MagicMock()
        worker_q = MagicMock()
        worker_queues = {"worker_0": worker_q}
        coord = Coordinator(
            ingress_queue=ingress_q,
            worker_queues=worker_queues,
            shutdown_event=threading.Event(),
            active_urls={},
            history_recorder=MagicMock(),
            url_parsers={},
            config_store=MagicMock(),
            scale_queue=MagicMock(),
            coordinator_status=status_dict,
            verbose=False,
        )

        # Initially idle
        self.assertEqual(status_dict["idle_workers"], ["worker_0"])
        self.assertEqual(status_dict["assignments"], {})

        # Task arrives
        fic = FanficInfo(
            url="https://archiveofourown.org/works/456", site="archiveofourown"
        )
        coord._handle_new_task(fic)

        # Worker_0 gets assigned site
        self.assertEqual(status_dict["assignments"], {"archiveofourown": "worker_0"})
        self.assertEqual(status_dict["idle_workers"], [])

        # Worker finishes and reports idle
        coord._handle_worker_idle("worker_0", "archiveofourown")
        self.assertEqual(status_dict["assignments"], {})
        self.assertEqual(status_dict["idle_workers"], ["worker_0"])

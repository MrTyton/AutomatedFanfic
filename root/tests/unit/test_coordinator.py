import unittest
import multiprocessing as mp
from unittest.mock import MagicMock, patch
from queue import Empty

from services.coordinator import Coordinator, start_coordinator
from models.fanfic_info import FanficInfo


class TestCoordinatorIntegration(unittest.TestCase):
    """Integration-style tests using real multiprocessing queues."""

    def setUp(self):
        self.ingress_queue = mp.Queue()
        self.worker_queues = {"worker_0": mp.Queue(), "worker_1": mp.Queue()}
        self.coordinator = Coordinator(self.ingress_queue, self.worker_queues)

    def test_direct_assignment_same_site(self):
        """Test that multiple tasks for the same site are pushed directly to the assigned worker."""
        fic1 = FanficInfo(url="http://site1.com/1", site="site1")
        fic2 = FanficInfo(url="http://site1.com/2", site="site1")

        self.ingress_queue.put(fic1)
        self.ingress_queue.put(fic2)

        # Process first item
        self.coordinator._process_single_ingress_item(timeout=0.1)

        # Determine who got site1
        worker_id = self.coordinator.assignments.get("site1")
        self.assertIsNotNone(worker_id)

        # Verify first task is in queue
        task1 = self.worker_queues[worker_id].get()
        self.assertEqual(task1, fic1)

        # Process second item (should be direct push)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        # Verify second task is in SAME queue
        task2 = self.worker_queues[worker_id].get()
        self.assertEqual(task2, fic2)

        # Verify assignment persists
        self.assertEqual(self.coordinator.assignments["site1"], worker_id)

    def test_parallel_processing_different_sites(self):
        """Test that tasks for different sites are assigned to different workers."""
        fic1 = FanficInfo(url="http://site1.com/1", site="site1")
        fic2 = FanficInfo(url="http://site2.com/1", site="site2")

        self.ingress_queue.put(fic1)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        worker1 = self.coordinator.assignments["site1"]

        self.ingress_queue.put(fic2)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        worker2 = self.coordinator.assignments["site2"]

        # Verify different workers
        self.assertNotEqual(worker1, worker2)

        # Verify tasks in respective queues
        self.assertEqual(self.worker_queues[worker1].get(), fic1)
        self.assertEqual(self.worker_queues[worker2].get(), fic2)

    def test_idle_signal_releases_lock(self):
        """Test that WORKER_IDLE signal releases the site assignment."""
        fic1 = FanficInfo(url="http://site1.com/1", site="site1")
        self.ingress_queue.put(fic1)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        worker_id = self.coordinator.assignments["site1"]

        # Simulate worker idle signal
        self.ingress_queue.put(("WORKER_IDLE", worker_id, "site1"))
        self.coordinator._process_single_ingress_item(timeout=0.1)

        # Verify lock released
        self.assertNotIn("site1", self.coordinator.assignments)
        self.assertIn(worker_id, self.coordinator.idle_workers)

    def test_backlog_draining(self):
        """Test that backlog items are assigned when a worker becomes idle."""
        # 1. Busy all workers
        workers = list(self.worker_queues.keys())

        # Assign site1 to worker0
        self.coordinator.assignments["site1"] = workers[0]
        self.coordinator.idle_workers.remove(workers[0])

        # Assign site2 to worker1
        self.coordinator.assignments["site2"] = workers[1]
        self.coordinator.idle_workers.remove(workers[1])

        # 2. Add task for site3 (goes to backlog)
        fic3 = FanficInfo(url="http://site3.com/1", site="site3")
        self.ingress_queue.put(fic3)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        self.assertIn("site3", self.coordinator.backlog)
        self.assertEqual(self.coordinator.backlog["site3"][0], fic3)

        # 3. Worker 0 signals idle (finished site1)
        self.ingress_queue.put(("WORKER_IDLE", workers[0], "site1"))
        self.coordinator._process_single_ingress_item(timeout=0.1)

        # 4. Verify Worker 0 is assigned site3
        self.assertEqual(self.coordinator.assignments.get("site3"), workers[0])
        self.assertEqual(self.worker_queues[workers[0]].get(), fic3)
        self.assertNotIn("site3", self.coordinator.backlog)


class TestCoordinatorEdgeCases(unittest.TestCase):
    """Unit tests using mocks for edge cases and error handling."""

    def setUp(self):
        self.mock_ingress = MagicMock()
        self.mock_worker_queues = {"worker_0": MagicMock(), "worker_1": MagicMock()}
        self.coordinator = Coordinator(self.mock_ingress, self.mock_worker_queues)

    def test_shutdown_signal(self):
        """Test processing of shutdown signal (None)."""
        self.mock_ingress.get.return_value = None

        self.coordinator._process_single_ingress_item(timeout=1.0)

        self.assertFalse(self.coordinator.running)

    @patch("services.coordinator.ff_logging")
    def test_invalid_ingress_item(self, mock_logging):
        """Test handling of invalid item type in ingress queue."""
        self.mock_ingress.get.return_value = "invalid_string_item"

        self.coordinator._process_single_ingress_item(timeout=1.0)

        mock_logging.log_failure.assert_called_with(
            "Coordinator: Received invalid item type <class 'str'>"
        )
        self.assertTrue(self.coordinator.running)

    @patch("services.coordinator.ff_logging")
    def test_ingress_queue_exception(self, mock_logging):
        """Test exception handling during queue get."""
        self.mock_ingress.get.side_effect = Exception("Queue Error")

        self.coordinator._process_single_ingress_item(timeout=1.0)

        mock_logging.log_failure.assert_called()
        self.assertIn("Queue Error", str(mock_logging.log_failure.call_args))

    def test_ingress_queue_empty(self):
        """Test that Empty exception is ignored (normal timeout)."""
        self.mock_ingress.get.side_effect = Empty

        # Should not raise exception
        self.coordinator._process_single_ingress_item(timeout=1.0)

    @patch("services.coordinator.ff_logging")
    def test_worker_idle_mismatch(self, mock_logging):
        """Test warning when worker claims finished site assigned to another."""
        # Setup: site1 assigned to worker_0
        self.coordinator.assignments["site1"] = "worker_0"
        self.coordinator.idle_workers.remove("worker_0")

        # Action: worker_1 claims finish for site1
        self.mock_ingress.get.return_value = ("WORKER_IDLE", "worker_1", "site1")

        self.coordinator._process_single_ingress_item(timeout=1.0)

        # Verify warning
        mock_logging.log.assert_called_with(
            "Coordinator: Worker worker_1 claimed finish for site1 but assigned to worker_0",
            "WARNING",
        )
        # Verify worker_1 added to idle (it is currently free)
        self.assertIn("worker_1", self.coordinator.idle_workers)
        # Verify assignment NOT removed
        self.assertEqual(self.coordinator.assignments["site1"], "worker_0")

    @patch("services.coordinator.Coordinator")
    @patch("services.coordinator.ff_logging")
    def test_start_coordinator(self, mock_logging, mock_coord_cls):
        """Test entry point logic."""
        mock_instance = mock_coord_cls.return_value

        start_coordinator(self.mock_ingress, self.mock_worker_queues, verbose=True)

        mock_logging.set_verbose.assert_called_with(True)
        mock_coord_cls.assert_called_once()
        mock_instance.run.assert_called_once()

    @patch("services.coordinator.Coordinator")
    @patch("services.coordinator.ff_logging")
    def test_start_coordinator_interrupt(self, mock_logging, mock_coord_cls):
        """Test KeyboardInterrupt in start_coordinator."""
        mock_instance = mock_coord_cls.return_value
        mock_instance.run.side_effect = KeyboardInterrupt

        start_coordinator(self.mock_ingress, self.mock_worker_queues)

        mock_logging.log.assert_called_with("Coordinator stopped by KeyboardInterrupt")

    @patch("services.coordinator.Coordinator")
    @patch("services.coordinator.ff_logging")
    def test_start_coordinator_crash(self, mock_logging, mock_coord_cls):
        """Test generic exception in start_coordinator."""
        mock_instance = mock_coord_cls.return_value
        mock_instance.run.side_effect = Exception("Crash")

        start_coordinator(self.mock_ingress, self.mock_worker_queues)

        mock_logging.log_failure.assert_called()

    def test_assign_work_no_idle_workers(self):
        """Test _assign_work_if_possible returns early if no idle workers."""
        self.coordinator.idle_workers = set()

        # Add to backlog
        self.coordinator.backlog["site1"].append(MagicMock())

        self.coordinator._assign_work_if_possible()

        # Verify nothing assigned
        self.assertNotIn("site1", self.coordinator.assignments)

    def test_assign_work_no_backlog(self):
        """Test _assign_work_if_possible does nothing if backlog empty."""
        # Workers available, but no backlog
        self.coordinator._assign_work_if_possible()

        # Verify nothing assigned
        self.assertEqual(len(self.coordinator.assignments), 0)

    @patch("services.coordinator.ff_logging")
    def test_assign_work_queue_pos_error(self, mock_logging):
        """Test that assignment works even if qsize() raises NotImplementedError."""
        # Setup backlog
        task = FanficInfo(url="url", site="site1")
        self.coordinator.backlog["site1"].append(task)

        # Setup worker queue to fail qsize
        self.mock_worker_queues["worker_0"].qsize.side_effect = NotImplementedError

        # Force worker_0 to be the only available worker to ensure deterministic assignment
        self.coordinator.idle_workers = {"worker_0"}

        self.coordinator._assign_work_if_possible()

        # Verify assigned
        self.assertEqual(self.coordinator.assignments["site1"], "worker_0")
        # Verify queue put was called
        self.mock_worker_queues["worker_0"].put.assert_called_with(task)


if __name__ == "__main__":
    unittest.main()


class TestCoordinator(unittest.TestCase):
    def setUp(self):
        self.ingress_queue = mp.Queue()
        self.worker_queues = {"worker_0": mp.Queue(), "worker_1": mp.Queue()}
        self.coordinator = Coordinator(self.ingress_queue, self.worker_queues)

    def test_direct_assignment_same_site(self):
        """Test that multiple tasks for the same site are pushed directly to the assigned worker."""
        fic1 = FanficInfo(url="http://site1.com/1", site="site1")
        fic2 = FanficInfo(url="http://site1.com/2", site="site1")

        self.ingress_queue.put(fic1)
        self.ingress_queue.put(fic2)

        # Process first item
        self.coordinator._process_single_ingress_item(timeout=0.1)

        # Determine who got site1
        worker_id = self.coordinator.assignments.get("site1")
        self.assertIsNotNone(worker_id)

        # Verify first task is in queue
        task1 = self.worker_queues[worker_id].get()
        self.assertEqual(task1, fic1)

        # Process second item (should be direct push)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        # Verify second task is in SAME queue
        task2 = self.worker_queues[worker_id].get()
        self.assertEqual(task2, fic2)

        # Verify assignment persists
        self.assertEqual(self.coordinator.assignments["site1"], worker_id)

    def test_parallel_processing_different_sites(self):
        """Test that tasks for different sites are assigned to different workers."""
        fic1 = FanficInfo(url="http://site1.com/1", site="site1")
        fic2 = FanficInfo(url="http://site2.com/1", site="site2")

        self.ingress_queue.put(fic1)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        worker1 = self.coordinator.assignments["site1"]

        self.ingress_queue.put(fic2)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        worker2 = self.coordinator.assignments["site2"]

        # Verify different workers
        self.assertNotEqual(worker1, worker2)

        # Verify tasks in respective queues
        self.assertEqual(self.worker_queues[worker1].get(), fic1)
        self.assertEqual(self.worker_queues[worker2].get(), fic2)

    def test_idle_signal_releases_lock(self):
        """Test that WORKER_IDLE signal releases the site assignment."""
        fic1 = FanficInfo(url="http://site1.com/1", site="site1")
        self.ingress_queue.put(fic1)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        worker_id = self.coordinator.assignments["site1"]

        # Simulate worker idle signal
        self.ingress_queue.put(("WORKER_IDLE", worker_id, "site1"))
        self.coordinator._process_single_ingress_item(timeout=0.1)

        # Verify lock released
        self.assertNotIn("site1", self.coordinator.assignments)
        self.assertIn(worker_id, self.coordinator.idle_workers)

    def test_backlog_draining(self):
        """Test that backlog items are assigned when a worker becomes idle."""
        # 1. Busy all workers
        # Assuming 2 workers from setUp
        workers = list(self.worker_queues.keys())

        # Assign site1 to worker0
        self.coordinator.assignments["site1"] = workers[0]
        self.coordinator.idle_workers.remove(workers[0])

        # Assign site2 to worker1
        self.coordinator.assignments["site2"] = workers[1]
        self.coordinator.idle_workers.remove(workers[1])

        # 2. Add task for site3 (goes to backlog)
        fic3 = FanficInfo(url="http://site3.com/1", site="site3")
        self.ingress_queue.put(fic3)
        self.coordinator._process_single_ingress_item(timeout=0.1)

        self.assertIn("site3", self.coordinator.backlog)
        self.assertEqual(self.coordinator.backlog["site3"][0], fic3)

        # 3. Worker 0 signals idle (finished site1)
        self.ingress_queue.put(("WORKER_IDLE", workers[0], "site1"))
        self.coordinator._process_single_ingress_item(timeout=0.1)

        # 4. Verify Worker 0 is assigned site3
        self.assertEqual(self.coordinator.assignments.get("site3"), workers[0])
        self.assertEqual(self.worker_queues[workers[0]].get(), fic3)
        self.assertNotIn("site3", self.coordinator.backlog)


if __name__ == "__main__":
    unittest.main()

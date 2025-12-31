import unittest
import multiprocessing as mp
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))

from coordinator import Coordinator  # noqa: E402
from fanfic_info import FanficInfo  # noqa: E402


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

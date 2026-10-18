# Worker Auto-Scaling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement dynamic worker auto-scaling with a 60-second idle timeout, keeping 1 permanent baseline worker (`worker_0`) and scaling up extra workers (`worker_1`..`worker_N`) on demand during multi-site bursts.

**Architecture:** The Coordinator manages `idle_workers` (active threads waiting for work) and `dormant_workers` (unspawned thread slots). When all idle workers are busy and a new site arrives, the Coordinator assigns the task to a dormant slot and pushes `worker_id` to a new `scale_queue`. The `worker_pool` process listens on `scale_queue`, instantly spawns the requested worker thread (<0.1ms), and when that thread sits idle with an empty queue for 60 seconds, it signals `WORKER_STOPPED`, calls `reclaim_memory()`, and exits cleanly.

**Tech Stack:** Python 3.15, multiprocessing (`mp.Queue`), threading (`threading.Thread`), pytest.

---

### Task 1: Add `scale_queue` to `SharedIPCContext` and Process Wiring

**Files:**
- Modify: `root/app/models/context.py`
- Modify: `root/app/fanficdownload.py`
- Test: `root/tests/unit/test_context.py`

**Step 1: Write the failing test**

In `root/tests/unit/test_context.py`:
```python
def test_shared_ipc_context_includes_scale_queue():
    from models.context import SharedIPCContext
    import multiprocessing as mp

    q = mp.Queue()
    ctx = SharedIPCContext(
        ingress_queue=q,
        waiting_queue=q,
        worker_queues={},
        active_urls={},
        history_recorder=None,
        config_store=None,
        log_queue=None,
        verbose=False,
        scale_queue=q,
    )
    assert ctx.scale_queue is q
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest root/tests/unit/test_context.py -k test_shared_ipc_context_includes_scale_queue -v`
Expected: FAIL with `unexpected keyword argument 'scale_queue'`

**Step 3: Write minimal implementation**

1. In `root/app/models/context.py`:
   - Add `scale_queue: IngressQueue | None = None` to `SharedIPCContext`.
2. In `root/app/fanficdownload.py`:
   - Create `scale_queue = mp.Queue()` in `register_processes()`.
   - Pass `scale_queue=scale_queue` in `SharedIPCContext`.
   - Pass `scale_queue` to `Coordinator`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest root/tests/unit/test_context.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add root/app/models/context.py root/app/fanficdownload.py root/tests/unit/test_context.py
git commit -m "feat(ipc): add scale_queue to SharedIPCContext and process wiring"
```

---

### Task 2: Worker Idle Timeout & `WORKER_STOPPED` in `pipeline.py`

**Files:**
- Modify: `root/app/workers/pipeline.py`
- Test: `root/tests/unit/test_pipeline.py`

**Step 1: Write the failing test**

In `root/tests/unit/test_pipeline.py`:
```python
def test_worker_idle_timeout_terminates_non_permanent_worker():
    """Worker with idle_timeout set exits when idle time exceeds threshold."""
    mock_queue = MagicMock()
    mock_queue.get.side_effect = Empty
    mock_ctx = MagicMock()

    with patch("time.monotonic", side_effect=[0.0, 0.0, 10.0, 70.0]):
        # Worker with 60s idle timeout should exit after 70s idle
        pipeline.url_worker(
            mock_queue, mock_ctx, "worker_1", verbose=False, idle_timeout=60.0
        )

    # Must signal WORKER_STOPPED to ingress_queue
    mock_ctx.ingress_queue.put.assert_any_call(("WORKER_STOPPED", "worker_1", None))
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest root/tests/unit/test_pipeline.py -k test_worker_idle_timeout_terminates_non_permanent_worker -v`
Expected: FAIL with `unexpected keyword argument 'idle_timeout'`

**Step 3: Write minimal implementation**

In `root/app/workers/pipeline.py`:
- Update `url_worker` signature to accept `idle_timeout: float | None = None`.
- Track `last_active_time = time.monotonic()`.
- When `fanfic` task is processed, update `last_active_time = time.monotonic()`.
- In `except Empty:` when `current_site is None`:
  - If `idle_timeout is not None and (time.monotonic() - last_active_time >= idle_timeout)`:
    - Send `ingress_queue.put(('WORKER_STOPPED', worker_id, None))`.
    - Call `system_utils.reclaim_memory()`.
    - `break` out of the loop.

**Step 4: Run test to verify it passes**

Run: `python -m pytest root/tests/unit/test_pipeline.py -k test_worker_idle_timeout -v`
Expected: PASS

**Step 5: Commit**

```bash
git add root/app/workers/pipeline.py root/tests/unit/test_pipeline.py
git commit -m "feat(worker): implement 60s idle timeout and WORKER_STOPPED signal"
```

---

### Task 3: Coordinator Worker Lifecycle (`dormant_workers`, `scale_queue`, `WORKER_STOPPED`)

**Files:**
- Modify: `root/app/services/coordinator.py`
- Test: `root/tests/unit/test_coordinator.py`

**Step 1: Write the failing test**

In `root/tests/unit/test_coordinator.py`:
```python
def test_coordinator_spawns_dormant_worker_via_scale_queue():
    """When idle workers are exhausted, coordinator activates a dormant worker via scale_queue."""
    scale_queue = MagicMock()
    coordinator = Coordinator(
        ingress_queue=MagicMock(),
        worker_queues={"worker_0": MagicMock(), "worker_1": MagicMock()},
        shutdown_event=threading.Event(),
        active_urls={},
        history_recorder=None,
        url_parsers={},
        config_store=None,
        scale_queue=scale_queue,
    )
    # worker_0 is busy, worker_1 is dormant
    coordinator.state.idle_workers = set()
    coordinator.state.dormant_workers = {"worker_1"}

    task = FanficInfo(url="https://ffnet.com/s/1", site="ffnet")
    coordinator._handle_new_task(task)

    # Coordinator should have popped worker_1 and notified scale_queue
    scale_queue.put.assert_called_once_with("worker_1")
    assert "worker_1" not in coordinator.state.dormant_workers
    assert coordinator.state.assignments.get("ffnet") == "worker_1"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest root/tests/unit/test_coordinator.py -k test_coordinator_spawns_dormant_worker_via_scale_queue -v`
Expected: FAIL with `unexpected keyword argument 'scale_queue'` or attribute error

**Step 3: Write minimal implementation**

In `root/app/services/coordinator.py`:
1. Add `SignalType.WORKER_STOPPED = "WORKER_STOPPED"`.
2. Update `WorkerSignal.from_tuple` to recognize `WORKER_STOPPED`.
3. In `CoordinatorState`:
   - `dormant_workers: set[str] = field(default_factory=set)`
4. In `Coordinator.__init__`:
   - Accept `scale_queue: IngressQueue | None = None`.
   - Set `self.scale_queue = scale_queue`.
   - Set `self.state.idle_workers = {"worker_0"}` (if in `worker_queues`).
   - Set `self.state.dormant_workers = {w for w in worker_queues if w != "worker_0"}`.
5. In `_assign_work_if_possible`:
   - If `not self.state.idle_workers` and `self.state.dormant_workers`:
     - If there is an unassigned site in backlog:
       - Pop `worker_id` from `dormant_workers`.
       - Assign site to `worker_id`.
       - Drain backlog into `self.worker_queues[worker_id]`.
       - If `self.scale_queue is not None`:
         - `self.scale_queue.put(worker_id)`.
6. In `_handle_worker_stopped(self, worker_id: str)`:
   - Discard `worker_id` from `idle_workers`.
   - Discard `worker_id` from `assignments` if present.
   - Add `worker_id` to `dormant_workers`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest root/tests/unit/test_coordinator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add root/app/services/coordinator.py root/tests/unit/test_coordinator.py
git commit -m "feat(coordinator): manage dormant workers and signal scale_queue"
```

---

### Task 4: Pool Runner Dynamic Thread Spawning & Lifecycle

**Files:**
- Modify: `root/app/workers/pool_runner.py`
- Test: `root/tests/unit/test_pool_runner.py`

**Step 1: Write the failing test**

In `root/tests/unit/test_pool_runner.py`:
```python
def test_pool_runner_spawns_worker_0_and_scales_worker_1_on_signal():
    """Pool runner boots worker_0 permanently and starts worker_1 upon scale_queue signal."""
    # Test that run_worker_pool spawns worker_0 initially, then spawns worker_1 when scale_queue yields 'worker_1'
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest root/tests/unit/test_pool_runner.py -k test_pool_runner_spawns_worker_0_and_scales_worker_1_on_signal -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `root/app/workers/pool_runner.py`:
- In `run_worker_pool`:
  - `active_threads: dict[str, threading.Thread] = {}`
  - Spawn `worker_0` initially:
    ```python
    if "worker_0" in worker_queues:
        active_threads["worker_0"] = _spawn_worker_thread(
            "worker_0", worker_queues["worker_0"], worker_ctx, verbose, idle_timeout=None
        )
    ```
  - In main loop `while not shutdown_event.is_set():`:
    - Check `ipc.scale_queue`:
      ```python
      try:
          if ipc.scale_queue is not None:
              target_worker = ipc.scale_queue.get(timeout=0.2)
              if target_worker and target_worker in worker_queues:
                  if target_worker not in active_threads or not active_threads[target_worker].is_alive():
                      active_threads[target_worker] = _spawn_worker_thread(
                          target_worker, worker_queues[target_worker], worker_ctx, verbose, idle_timeout=60.0
                      )
      except Empty:
          pass
      ```
    - Clean up non-alive threads in `active_threads` (except restart `worker_0` if it died unexpectedly).

**Step 4: Run test to verify it passes**

Run: `python -m pytest root/tests/unit/test_pool_runner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add root/app/workers/pool_runner.py root/tests/unit/test_pool_runner.py
git commit -m "feat(pool_runner): implement dynamic thread spawning via scale_queue"
```

---

### Task 5: End-to-End Suite Verification

**Files:**
- Test all unit tests: `python -m pytest root/tests/unit/ -q`
- Test all integration tests: `python -m pytest root/tests/integration/ -q`
- Linter: `ruff check root/app/`

**Step 1: Run complete verification**

Run:
```powershell
& c:/Users/Joshua/Documents/GitHub/AutomatedFanfic/.venv/Scripts/Activate.ps1
python -m pytest root/tests/unit/ -q
python -m pytest root/tests/integration/ -q
ruff check root/app/
```
Expected: All 898+ unit tests pass, 35 integration tests pass, ruff check is clean.

**Step 2: Commit**

```bash
git commit --allow-empty -m "chore: verify complete test suite and linter pass"
```

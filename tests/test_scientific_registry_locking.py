from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from scientific_research.closed_loop_registry import ClosedLoopRegistry
from scientific_research.phase3_registry import Phase3Registry
from scientific_research.phase63_registry import RegistryCorruptionError
from scientific_research.registry_io import (
    RegistryLockTimeoutError,
    append_jsonl_object,
    json_array_transaction,
    registry_lock,
)


def _write_candidates(root: str, worker_id: int, count: int) -> None:
    registry = Phase3Registry(root)
    for sequence in range(count):
        registry.save_candidate(
            {
                "candidate_id": f"worker-{worker_id:02d}-candidate-{sequence:02d}",
                "worker_id": worker_id,
                "sequence": sequence,
            }
        )


def _hold_registry_lock(path: str, ready: object, release: object) -> None:
    with registry_lock(Path(path), timeout=2.0):
        ready.set()
        release.wait(5.0)


def _consume_one_task(root: str, worker_id: int) -> None:
    ClosedLoopRegistry(root).consume_budget(
        "plan-concurrency",
        "TASK",
        1.0,
        "Concurrent test consumption.",
        f"task-{worker_id:02d}",
    )


def _append_audit_rows(path: str, worker_id: int, count: int) -> None:
    for sequence in range(count):
        append_jsonl_object(
            Path(path),
            {"worker_id": worker_id, "sequence": sequence},
            RegistryCorruptionError,
        )


class ScientificRegistryLockingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_concurrent_upserts_preserve_every_unique_record(self) -> None:
        # SRB persistence is POSIX-only (fcntl); fork keeps this stress test
        # independent from unrelated heavyweight Streamlit imports in the full suite.
        context = multiprocessing.get_context("fork")
        process_count = 4
        writes_per_process = 8
        processes = [
            context.Process(
                target=_write_candidates,
                args=(str(self.root), worker_id, writes_per_process),
            )
            for worker_id in range(process_count)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(20.0)

        for process in processes:
            self.assertFalse(process.is_alive(), "Concurrent registry writer did not terminate.")
            self.assertEqual(process.exitcode, 0)

        rows = Phase3Registry(self.root).list_candidates()
        identities = {str(row.get("candidate_id") or "") for row in rows}
        expected = {
            f"worker-{worker_id:02d}-candidate-{sequence:02d}"
            for worker_id in range(process_count)
            for sequence in range(writes_per_process)
        }
        self.assertEqual(identities, expected)
        self.assertEqual(len(rows), process_count * writes_per_process)

    def test_lock_contention_times_out_without_mutating_registry(self) -> None:
        context = multiprocessing.get_context("fork")
        path = self.root / "phase3_transmutation_candidates.json"
        path.write_text('[{"candidate_id": "prior"}]\n', encoding="utf-8")
        before = path.read_bytes()
        ready = context.Event()
        release = context.Event()
        holder = context.Process(
            target=_hold_registry_lock,
            args=(str(path), ready, release),
        )
        holder.start()
        try:
            self.assertTrue(ready.wait(5.0), "Lock holder did not acquire the registry lock.")
            with self.assertRaises(RegistryLockTimeoutError):
                with json_array_transaction(
                    path,
                    RegistryCorruptionError,
                    timeout=0.05,
                ) as rows:
                    rows.append({"candidate_id": "must-not-persist"})
            self.assertEqual(path.read_bytes(), before)
        finally:
            release.set()
            holder.join(10.0)
            if holder.is_alive():
                holder.terminate()
                holder.join(5.0)

        self.assertEqual(holder.exitcode, 0)

    def test_concurrent_budget_consumption_cannot_overspend_or_lose_events(self) -> None:
        registry = ClosedLoopRegistry(self.root)
        registry.save_budget(
            {
                "ledger_id": "ledger-concurrency",
                "plan_id": "plan-concurrency",
                "max_tasks": 4,
                "used_tasks": 0,
            }
        )
        context = multiprocessing.get_context("fork")
        processes = [
            context.Process(target=_consume_one_task, args=(str(self.root), worker_id))
            for worker_id in range(4)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(20.0)
            self.assertFalse(process.is_alive(), "Concurrent budget consumer did not terminate.")
            self.assertEqual(process.exitcode, 0)

        ledger = registry.ledger_for_plan("plan-concurrency")
        self.assertIsNotNone(ledger)
        self.assertEqual(float((ledger or {}).get("used_tasks") or 0), 4.0)
        self.assertEqual(len(registry.list_budget_events()), 4)
        with self.assertRaisesRegex(ValueError, "Budget exhausted"):
            registry.consume_budget(
                "plan-concurrency",
                "TASK",
                1.0,
                "Must fail closed.",
                "task-over-budget",
            )

    def test_concurrent_jsonl_appends_remain_complete_and_parseable(self) -> None:
        path = self.root / "audit.jsonl"
        context = multiprocessing.get_context("fork")
        process_count = 4
        writes_per_process = 6
        processes = [
            context.Process(
                target=_append_audit_rows,
                args=(str(path), worker_id, writes_per_process),
            )
            for worker_id in range(process_count)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(20.0)
            self.assertFalse(process.is_alive(), "Concurrent audit writer did not terminate.")
            self.assertEqual(process.exitcode, 0)

        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        identities = {(int(row["worker_id"]), int(row["sequence"])) for row in rows}
        expected = {
            (worker_id, sequence)
            for worker_id in range(process_count)
            for sequence in range(writes_per_process)
        }
        self.assertEqual(identities, expected)
        self.assertEqual(len(rows), process_count * writes_per_process)

    def test_audit_append_refuses_to_extend_corrupt_jsonl(self) -> None:
        path = self.root / "audit.jsonl"
        path.write_text('{"event": "valid"}\n{"truncated":', encoding="utf-8")
        before = path.read_bytes()

        with self.assertRaisesRegex(RegistryCorruptionError, path.name):
            append_jsonl_object(
                path,
                {"event": "must-not-persist"},
                RegistryCorruptionError,
            )

        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

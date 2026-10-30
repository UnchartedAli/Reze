"""Persistent workflows: simulation, idempotency, retries and recovery."""

import json
import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.automation.simulator import SimulationError, parse_steps, render, simulate
from reze.automation.workflow import (
    WorkflowError,
    WorkflowService,
    WorkflowUnavailable,
)
from reze.database import db
from reze.features import features

OWNER = 4242


def _reset():
    db.execute("DELETE FROM workflow_steps")
    db.execute("DELETE FROM workflow_runs")
    db.execute("DELETE FROM workflows")
    db.execute("DELETE FROM feature_state")
    features.invalidate()


class SimulatorTests(unittest.TestCase):
    def test_valid_workflow_is_described_without_side_effects(self):
        report = simulate(
            [
                {"action": "log", "message": "hello {date}"},
                {"action": "wait", "seconds": 0},
            ],
            {"date": "2026-10-30"},
        )
        self.assertTrue(report.valid)
        self.assertEqual([step.status for step in report.steps], ["ok", "ok"])
        self.assertIn("Dry run", "\n".join(report.lines()))

    def test_unknown_action_and_fields_are_rejected(self):
        with self.assertRaises(SimulationError):
            parse_steps([{"action": "run_shell", "command": "ls"}])
        with self.assertRaises(SimulationError):
            parse_steps([{"action": "log", "message": "x", "shell": "ls"}])
        with self.assertRaises(SimulationError):
            parse_steps([{"action": "log"}])

    def test_empty_and_oversized_workflows_are_rejected(self):
        self.assertFalse(simulate([]).valid)
        many = [{"action": "log", "message": "x"} for _ in range(21)]
        with self.assertRaises(SimulationError):
            parse_steps(many)

    def test_invalid_step_parameters(self):
        self.assertFalse(simulate([{"action": "wait", "seconds": 999}]).valid)
        self.assertFalse(simulate([{"action": "add_reminder", "text": "x", "minutes": 0}]).valid)
        self.assertFalse(simulate([{"action": "send_message", "chat_id": 1, "text": "  "}]).valid)

    def test_templates_keep_unknown_placeholders_visible(self):
        self.assertEqual(render("hi {name}", {"name": "Ali"}), "hi Ali")
        self.assertEqual(render("hi {missing}", {}), "hi {missing}")
        self.assertEqual(render("{broken", {}), "{broken")


class WorkflowServiceTests(unittest.TestCase):
    def setUp(self):
        _reset()
        features.enable("workflows", confirmed=True)
        self.service = WorkflowService()

    def tearDown(self):
        _reset()

    def test_workflows_are_off_by_default(self):
        features.disable("workflows")
        with self.assertRaises(WorkflowUnavailable):
            self.service.create("daily", [{"action": "log", "message": "x"}])
        with self.assertRaises(WorkflowUnavailable):
            support.run(self.service.run("daily", manual=True))

    def test_new_workflow_is_disabled_by_default(self):
        workflow_id = self.service.create("daily", [{"action": "log", "message": "x"}])
        row = self.service.get(workflow_id)
        self.assertEqual(row["enabled"], 0)
        with self.assertRaises(WorkflowError):
            support.run(self.service.run(workflow_id))

    def test_enable_and_manual_run(self):
        workflow_id = self.service.create("daily", [{"action": "log", "message": "hello"}])
        self.assertTrue(self.service.set_enabled(workflow_id, True))
        result = support.run(self.service.run(workflow_id))
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["run"]["status"], "done")
        row = self.service.get(workflow_id)
        self.assertEqual(row["run_count"], 1)
        steps = db.query(
            "SELECT status FROM workflow_steps WHERE run_id = ? ORDER BY step_index",
            (result["run"]["id"],),
        )
        self.assertEqual([step["status"] for step in steps], ["done"])

    def test_idempotency_key_prevents_duplicate_runs(self):
        workflow_id = self.service.create("daily", [{"action": "log", "message": "once"}])
        first = support.run(self.service.run(workflow_id, idempotency_key="same-key", manual=True))
        second = support.run(self.service.run(workflow_id, idempotency_key="same-key", manual=True))
        self.assertEqual(first["status"], "done")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(first["run"]["id"], second["run"]["id"])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM workflow_runs")["n"], 1)

    def test_invalid_trigger_configuration_is_rejected(self):
        with self.assertRaises(WorkflowError):
            self.service.create(
                "interval", [{"action": "log", "message": "x"}],
                trigger_type="interval", trigger_config={"seconds": 10},
            )
        with self.assertRaises(WorkflowError):
            self.service.create(
                "daily", [{"action": "log", "message": "x"}],
                trigger_type="daily", trigger_config={"at": "25:90"},
            )
        workflow_id = self.service.create(
            "every-hour", [{"action": "log", "message": "x"}],
            trigger_type="interval", trigger_config={"seconds": 3600},
        )
        self.assertEqual(json.loads(self.service.get(workflow_id)["trigger_config"]), {"seconds": 3600})

    def test_scheduler_only_runs_due_enabled_workflows(self):
        workflow_id = self.service.create(
            "ticker", [{"action": "log", "message": "tick"}],
            trigger_type="interval", trigger_config={"seconds": 60}, cooldown_seconds=0,
        )
        self.assertEqual(support.run(self.service.tick()), [])
        self.service.set_enabled(workflow_id, True)
        db.execute("UPDATE workflows SET last_run = NULL WHERE id = ?", (workflow_id,))
        started = support.run(self.service.tick())
        self.assertEqual(started, ["ticker:done"])
        # Not due again immediately.
        self.assertEqual(support.run(self.service.tick()), [])

    def test_retryable_failure_is_retried_then_succeeds(self):
        workflow_id = self.service.create("flaky", [{"action": "log", "message": "x"}])
        original = self.service._execute_step
        attempts = {"count": 0}

        async def flaky(step, context, workflow):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("temporary network hiccup")
            return "ok"

        self.service._execute_step = flaky
        try:
            result = support.run(self.service.run(workflow_id, manual=True))
        finally:
            self.service._execute_step = original
        self.assertEqual(result["status"], "done")
        step = db.query_one(
            "SELECT attempts, status FROM workflow_steps WHERE run_id = ?", (result["run"]["id"],)
        )
        self.assertEqual(step["attempts"], 2)
        self.assertEqual(step["status"], "done")

    def test_interrupted_runs_are_marked_and_resumed_explicitly(self):
        workflow_id = self.service.create("resume", [{"action": "log", "message": "x"}])
        run_id = db.execute(
            "INSERT INTO workflow_runs (workflow_id, status, idempotency_key, context, attempts) "
            "VALUES (?, 'running', 'interrupted-run', '{}', 1)",
            (workflow_id,),
        )
        self.assertEqual(support.run(self.service.recover()), 1)
        self.assertEqual(
            db.query_one("SELECT status FROM workflow_runs WHERE id = ?", (run_id,))["status"],
            "interrupted",
        )
        # Nothing resumed automatically.
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM workflow_steps")["n"], 0)
        result = support.run(self.service.resume(run_id))
        self.assertEqual(result["status"], "done")
        self.assertEqual(
            db.query_one("SELECT status FROM workflow_runs WHERE id = ?", (run_id,))["status"],
            "done",
        )

    def test_resume_rejects_completed_runs_and_retry_limit(self):
        workflow_id = self.service.create("resume", [{"action": "log", "message": "x"}])
        done_id = db.execute(
            "INSERT INTO workflow_runs (workflow_id, status, idempotency_key, context) "
            "VALUES (?, 'done', 'done-run', '{}')",
            (workflow_id,),
        )
        with self.assertRaises(WorkflowError):
            support.run(self.service.resume(done_id))
        exhausted = db.execute(
            "INSERT INTO workflow_runs (workflow_id, status, idempotency_key, context, attempts) "
            "VALUES (?, 'failed', 'exhausted', '{}', 3)",
            (workflow_id,),
        )
        with self.assertRaises(WorkflowError):
            support.run(self.service.resume(exhausted))

    def test_cancel_marks_an_active_run(self):
        workflow_id = self.service.create("cancel", [{"action": "log", "message": "x"}])
        run_id = db.execute(
            "INSERT INTO workflow_runs (workflow_id, status, idempotency_key, context) "
            "VALUES (?, 'running', 'cancel-me', '{}')",
            (workflow_id,),
        )
        self.assertTrue(self.service.cancel(run_id))
        self.assertEqual(
            db.query_one("SELECT status FROM workflow_runs WHERE id = ?", (run_id,))["status"],
            "cancelled",
        )
        self.assertFalse(self.service.cancel(run_id))

    def test_delete_removes_definition_and_its_runs(self):
        workflow_id = self.service.create("gone", [{"action": "log", "message": "x"}])
        result = support.run(self.service.run(workflow_id, manual=True))
        self.assertTrue(self.service.delete(workflow_id))
        self.assertIsNone(self.service.get(workflow_id))
        # Deleting a definition is explicit and takes its run history with it.
        self.assertIsNone(
            db.query_one("SELECT * FROM workflow_runs WHERE id = ?", (result["run"]["id"],))
        )


if __name__ == "__main__":
    unittest.main()

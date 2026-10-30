"""AI tool allowlists, approval gates and auditability."""

import json
import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.ai.tools.registry import TOOLS, ToolError, tool_registry, validate_args
from reze.database import db
from reze.features import features

OWNER = 4242


def _reset():
    db.execute("DELETE FROM feature_state")
    db.execute("DELETE FROM ai_approvals")
    db.execute("DELETE FROM ai_tool_audit")
    db.execute("DELETE FROM memories")
    db.execute("DELETE FROM search_index WHERE kind = 'memory'")
    features.invalidate()


class ToolValidationTests(unittest.TestCase):
    def test_unknown_fields_are_rejected(self):
        tool = TOOLS["memory.save"]
        with self.assertRaises(ToolError):
            validate_args(tool, {"content": "x", "shell": "rm -rf /"})

    def test_types_and_required_fields(self):
        tool = TOOLS["memory.save"]
        with self.assertRaises(ToolError):
            validate_args(tool, {"content": "x", "tags": ["not", "a", "string"]})
        with self.assertRaises(ToolError):
            validate_args(tool, {"tags": "no content"})
        cleaned = validate_args(tool, {"content": "  hello  ", "tags": "t"})
        self.assertEqual(cleaned["content"], "hello")

    def test_integer_coercion_and_rejection(self):
        tool = TOOLS["task.add"]
        cleaned = validate_args(tool, {"title": "write", "priority": "2"})
        self.assertEqual(cleaned["priority"], 2)
        with self.assertRaises(ToolError):
            validate_args(tool, {"title": "write", "priority": "high"})

    def test_tool_allowlist_is_static(self):
        for name, tool in TOOLS.items():
            self.assertIs(tool, TOOLS[name])
        # No dynamic Python execution tool exists in the allowlist.
        self.assertNotIn("python", TOOLS)
        self.assertNotIn("shell", TOOLS)
        self.assertNotIn("exec", TOOLS)


class ApprovalGateTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_proposal_requires_ai_agent_feature(self):
        with self.assertRaises(ToolError):
            tool_registry.propose("memory.save", {"content": "x"}, actor=OWNER)

    def test_proposal_requires_tool_feature(self):
        features.enable("ai_agent", confirmed=True)
        with self.assertRaises(ToolError) as raised:
            tool_registry.propose("memory.save", {"content": "x"}, actor=OWNER)
        self.assertIn("memory", str(raised.exception))

    def test_only_the_owner_can_propose_or_approve(self):
        features.enable("ai_agent", confirmed=True)
        features.enable("memory")
        with self.assertRaises(ToolError):
            tool_registry.propose("memory.save", {"content": "x"}, actor=999)
        proposal = tool_registry.propose("memory.save", {"content": "x"}, actor=OWNER)
        with self.assertRaises(ToolError):
            support.run(tool_registry.approve(proposal["code"], actor=999))
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM memories")["n"], 0)

    def test_propose_then_deny_writes_nothing(self):
        features.enable("ai_agent", confirmed=True)
        features.enable("memory")
        proposal = tool_registry.propose(
            "memory.save", {"content": "should not exist", "tags": "test"}, actor=OWNER
        )
        self.assertRegex(proposal["code"], r"^\d{6}$")
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM memories")["n"], 0)
        self.assertTrue(tool_registry.deny(proposal["code"], actor=OWNER))
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM memories")["n"], 0)
        self.assertIsNone(tool_registry.get_approval(proposal["code"]))
        statuses = [row["status"] for row in tool_registry.history(limit=5)]
        self.assertIn("denied", statuses)

    def test_wrong_code_cannot_approve(self):
        features.enable("ai_agent", confirmed=True)
        features.enable("memory")
        proposal = tool_registry.propose("memory.save", {"content": "x"}, actor=OWNER)
        wrong = "000000" if proposal["code"] != "000000" else "111111"
        with self.assertRaises(ToolError):
            support.run(tool_registry.approve(wrong, actor=OWNER))
        self.assertIsNotNone(tool_registry.get_approval(proposal["code"]))

    def test_approve_executes_exactly_once(self):
        features.enable("ai_agent", confirmed=True)
        features.enable("memory")
        proposal = tool_registry.propose(
            "memory.save", {"content": "remember this", "tags": "approval-test"}, actor=OWNER
        )
        result = support.run(tool_registry.approve(proposal["code"], actor=OWNER))
        self.assertEqual(result["tool"], "memory.save")
        self.assertIn("Saved memory", result["result"])
        rows = db.query("SELECT * FROM memories WHERE source = 'ai_tool'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "remember this")
        # A code is single-use.
        with self.assertRaises(ToolError):
            support.run(tool_registry.approve(proposal["code"], actor=OWNER))
        audit = db.query("SELECT status FROM ai_tool_audit ORDER BY id")
        self.assertEqual([row["status"] for row in audit], ["proposed", "executed"])

    def test_expired_approval_is_rejected(self):
        features.enable("ai_agent", confirmed=True)
        features.enable("memory")
        approval_id = db.execute(
            "INSERT INTO ai_approvals (code, tool, args, chat_id, user_id, expires_at, status) "
            "VALUES ('123456', 'memory.save', ?, 0, ?, '2000-01-01 00:00:00', 'pending')",
            (json.dumps({"content": "expired"}), OWNER),
        )
        with self.assertRaises(ToolError) as raised:
            support.run(tool_registry.approve("123456", actor=OWNER))
        self.assertIn("expired", str(raised.exception))
        row = db.query_one("SELECT status FROM ai_approvals WHERE id = ?", (approval_id,))
        self.assertEqual(row["status"], "expired")
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM memories")["n"], 0)

    def test_revoking_the_feature_invalidates_pending_approval(self):
        features.enable("ai_agent", confirmed=True)
        features.enable("memory")
        proposal = tool_registry.propose("memory.save", {"content": "x"}, actor=OWNER)
        features.disable("memory")
        with self.assertRaises(ToolError):
            support.run(tool_registry.approve(proposal["code"], actor=OWNER))
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM memories")["n"], 0)


if __name__ == "__main__":
    unittest.main()

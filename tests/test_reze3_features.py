"""REZE 3 default-off policy, feature store and service registry."""

import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.core.migrations import run_migrations
from reze.core.registry import Service, ServiceRegistry
from reze.database import db
from reze.features import (
    FEATURES,
    FeatureConfirmationRequired,
    FeatureStore,
    UnknownFeature,
    feature_spec,
    features,
)
from reze.migrations import MIGRATIONS


def _clear_feature_state():
    db.execute("DELETE FROM feature_state")
    features.invalidate()


class FeatureStoreTests(unittest.TestCase):
    def setUp(self):
        _clear_feature_state()

    def tearDown(self):
        _clear_feature_state()

    def test_every_feature_is_off_on_a_fresh_state(self):
        for spec in FEATURES:
            self.assertFalse(features.is_enabled(spec.key), f"{spec.key} must default to OFF")
        self.assertEqual(features.enabled_keys(), [])
        self.assertTrue(features.summary()["all_off"])

    def test_missing_row_and_unknown_key_resolve_to_off(self):
        self.assertFalse(features.is_enabled("memory"))
        self.assertFalse(features.is_enabled("does-not-exist"))
        self.assertFalse(features.is_enabled(""))
        self.assertEqual(features.disabled_keys(), [f.key for f in FEATURES])

    def test_sensitive_feature_needs_explicit_confirmation(self):
        spec = feature_spec("vault")
        self.assertTrue(spec.sensitive)
        with self.assertRaises(FeatureConfirmationRequired):
            features.enable("vault")
        self.assertFalse(features.is_enabled("vault"))
        self.assertIsNone(db.query_one("SELECT * FROM feature_state WHERE key = 'vault'"))

        self.assertTrue(features.enable("vault", confirmed=True))
        self.assertTrue(features.is_enabled("vault"))

    def test_standard_feature_does_not_require_confirmation(self):
        self.assertFalse(feature_spec("memory").sensitive)
        self.assertTrue(features.enable("memory", actor=4242))
        self.assertTrue(features.is_enabled("memory"))

    def test_enabling_one_feature_never_cascades(self):
        features.enable("memory")
        self.assertTrue(features.is_enabled("memory"))
        for spec in FEATURES:
            if spec.key != "memory":
                self.assertFalse(features.is_enabled(spec.key), f"{spec.key} was enabled implicitly")
        self.assertEqual(features.enabled_keys(), ["memory"])

    def test_state_survives_a_restart(self):
        features.enable("memory")
        # A new process starts with an empty cache and must read the same state.
        restarted = FeatureStore()
        self.assertTrue(restarted.is_enabled("memory"))
        self.assertFalse(restarted.is_enabled("crm"))

    def test_state_survives_migrations(self):
        features.enable("memory")
        with db.get_connection() as conn:
            applied = run_migrations(conn, MIGRATIONS)
        self.assertEqual(applied, [])
        features.invalidate()
        self.assertTrue(features.is_enabled("memory"))
        self.assertFalse(features.is_enabled("vault"))

    def test_disable_wins_even_when_sensitive(self):
        features.enable("vault", confirmed=True)
        self.assertTrue(features.disable("vault"))
        self.assertFalse(features.is_enabled("vault"))

    def test_unknown_feature_is_rejected(self):
        with self.assertRaises(UnknownFeature):
            features.enable("not_a_feature")
        with self.assertRaises(UnknownFeature):
            feature_spec("not_a_feature")

    def test_audit_log_records_enable_and_disable(self):
        features.enable("memory", actor=4242)
        features.disable("memory", actor=4242)
        rows = db.query(
            "SELECT action, target, actor FROM audit_log WHERE target = 'memory' ORDER BY id"
        )
        self.assertEqual([row["action"] for row in rows], ["feature.enable", "feature.disable"])
        self.assertEqual(rows[0]["actor"], 4242)

    def test_snapshot_reports_on_off_in_both_languages(self):
        features.enable("memory")
        english = {row["key"]: row for row in features.snapshot("en")}
        persian = {row["key"]: row for row in features.snapshot("fa")}
        self.assertEqual(english["memory"]["state"], "ON")
        self.assertEqual(english["crm"]["state"], "OFF")
        self.assertEqual(persian["memory"]["label"], feature_spec("memory").label_fa)
        self.assertNotEqual(persian["memory"]["label"], english["memory"]["label"])


class RegistryGatingTests(unittest.TestCase):
    def setUp(self):
        _clear_feature_state()

    def tearDown(self):
        _clear_feature_state()

    def test_start_all_skips_disabled_features(self):
        registry = ServiceRegistry()
        core = Service()
        core.name = "core"
        gated = Service()
        gated.name = "gated"
        gated.feature = "vault"
        registry.register(core)
        registry.register(gated)

        started = support.run(registry.start_all())
        self.assertEqual(started, ["core"])
        self.assertEqual(gated.status, "disabled")
        self.assertEqual(core.status, "running")
        support.run(registry.stop_all())

    def test_enabling_a_feature_starts_only_its_service(self):
        registry = ServiceRegistry()
        gated = Service()
        gated.name = "gated"
        gated.feature = "vault"
        other = Service()
        other.name = "other"
        other.feature = "memory"
        registry.register(gated)
        registry.register(other)

        features.enable("vault", confirmed=True)
        started = support.run(registry.start_all())
        self.assertEqual(started, ["gated"])
        self.assertEqual(gated.status, "running")
        self.assertEqual(other.status, "disabled")
        support.run(registry.stop_all())

    def test_restart_does_not_auto_enable_a_disabled_feature(self):
        registry = ServiceRegistry()
        gated = Service()
        gated.name = "gated"
        gated.feature = "workflows"
        registry.register(gated)
        self.assertEqual(support.run(registry.start_all()), [])
        self.assertEqual(gated.status, "disabled")


if __name__ == "__main__":
    unittest.main()

"""REZE 4.0: offline Docker Compose checker (Cloady and VPS rules)."""

import os
import shutil
import tempfile
import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.deploy import compose_check as cc

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _base(**service_overrides):
    service = {
        "build": {"context": "."},
        "ports": ["${PORT:-8080}:${PORT:-8080}"],
        "volumes": ["reze_data:/app/data"],
        "env_file": [{"path": ".env", "required": False}],
        "environment": {"REZE_WEB_HOST": "0.0.0.0", "REZE_DATA_DIR": "/app/data"},
        "healthcheck": {"test": ["CMD", "python", "scripts/healthcheck.py"]},
    }
    service.update(service_overrides)
    return {"services": {"reze": service}, "volumes": {"reze_data": None}}


def _codes(report, level=None):
    return {f.code for f in report.findings if level is None or f.level == level}


class ComposeRuleTests(unittest.TestCase):
    """Rules are checked on dictionaries, so these tests need no YAML library."""

    def test_clean_configuration_passes(self):
        report = cc.check(_base())
        self.assertTrue(report.ok, report.to_text())
        self.assertEqual(_codes(report, cc.ERROR), set())

    def test_bind_mount_is_rejected_with_cloady_wording(self):
        data = _base(volumes=["./data:/app/data"])
        report = cc.check(data)
        self.assertFalse(report.ok)
        self.assertIn("VOLUME-BIND", _codes(report, cc.ERROR))
        message = next(f.message for f in report.findings if f.code == "VOLUME-BIND")
        self.assertIn("volumes must mount a declared named volume, as volume:/path", message)

    def test_long_form_bind_mount_is_rejected(self):
        data = _base(volumes=[{"type": "bind", "source": "./data", "target": "/app/data"}])
        self.assertIn("VOLUME-BIND", _codes(cc.check(data), cc.ERROR))

    def test_undeclared_named_volume_is_rejected(self):
        data = _base(volumes=["reze_data:/app/data"])
        data["volumes"] = {}
        self.assertIn("VOLUME-UNDECLARED", _codes(cc.check(data), cc.ERROR))

    def test_anonymous_volume_is_rejected(self):
        data = _base(volumes=["/app/data"])
        self.assertIn("VOLUME-ANONYMOUS", _codes(cc.check(data), cc.ERROR))

    def test_declared_volume_without_size_gets_an_info_note(self):
        report = cc.check(_base())
        self.assertIn("VOLUME-SIZE-DEFAULT", _codes(report, cc.INFO))
        self.assertTrue(report.ok)

    def test_fixed_host_port_warns_and_interpolated_port_does_not(self):
        fixed = cc.check(_base(ports=["8080:8080"]))
        self.assertIn("PORT-FIXED", _codes(fixed, cc.WARNING))
        self.assertNotIn("PORT-FIXED", _codes(cc.check(_base())))

    def test_interpolated_port_is_not_mistaken_for_a_loopback_address(self):
        self.assertNotIn("PORT-LOOPBACK", _codes(cc.check(_base())))

    def test_literal_dollar_sign_must_be_escaped(self):
        report = cc.check(_base(environment={"REZE_PANEL_PASSWORD_HASH": "salt$hash"}))
        self.assertIn("DOLLAR-ESCAPE", _codes(report, cc.WARNING))
        escaped = cc.check(_base(environment={"REZE_PANEL_PASSWORD_HASH": "$${SECRET}"}))
        self.assertNotIn("DOLLAR-ESCAPE", _codes(escaped))

    def test_published_port_without_app_port_is_flagged(self):
        report = cc.check(_base(ports=["${PORT:-8080}:${PORT:-8080}"], environment={"REZE_WEB_HOST": "0.0.0.0"}))
        self.assertIn("PORT-NOT-PASSED", _codes(report, cc.WARNING))

    def test_matching_port_environment_is_accepted(self):
        report = cc.check(_base(ports=["${PORT:-8080}:${PORT:-8080}"], environment={"PORT": "${PORT:-8080}"}))
        self.assertNotIn("PORT-NOT-PASSED", _codes(report))

    def test_fixed_port_needs_no_port_environment(self):
        report = cc.check(_base(ports=["8080:8080"], environment={"REZE_WEB_HOST": "0.0.0.0"}))
        self.assertNotIn("PORT-NOT-PASSED", _codes(report))

    def test_loopback_binding_warns(self):
        report = cc.check(_base(ports=["127.0.0.1:8080:8080"]))
        self.assertIn("PORT-LOOPBACK", _codes(report, cc.WARNING))

    def test_no_port_warns(self):
        report = cc.check(_base(ports=[]))
        self.assertIn("PORT-NONE", _codes(report, cc.WARNING))

    def test_literal_secret_is_an_error_but_interpolation_is_not(self):
        bad = cc.check(_base(environment={"REZE_SESSION_STRING": "1BVtsOJ..."}))
        self.assertIn("SECRET-LITERAL", _codes(bad, cc.ERROR))
        self.assertFalse(bad.ok)
        good = cc.check(_base(environment={"REZE_SESSION_STRING": "${REZE_SESSION_STRING}"}))
        self.assertNotIn("SECRET-LITERAL", _codes(good))
        self.assertIn("ENV-INTERPOLATED", _codes(good, cc.INFO))

    def test_secret_in_list_style_environment_is_detected(self):
        report = cc.check(_base(environment=["REZE_PANEL_PASSWORD_HASH=salt$hash"]))
        self.assertIn("SECRET-LITERAL", _codes(report, cc.ERROR))

    def test_depends_on_is_warned_as_ignored(self):
        report = cc.check(_base(depends_on=["db"]))
        self.assertIn("DEPENDS-ON-IGNORED", _codes(report, cc.WARNING))

    def test_more_than_one_replica_is_rejected_for_reze(self):
        report = cc.check(_base(deploy={"replicas": 2}))
        self.assertIn("REPLICAS-NOT-ONE", _codes(report, cc.ERROR))
        self.assertNotIn("REPLICAS-NOT-ONE", _codes(cc.check(_base(deploy={"replicas": 2}), single_instance=False)))

    def test_missing_healthcheck_is_informational(self):
        data = _base()
        del data["services"]["reze"]["healthcheck"]
        report = cc.check(data)
        self.assertIn("HEALTHCHECK-MISSING", _codes(report, cc.INFO))
        self.assertTrue(report.ok)

    def test_non_mapping_service_is_a_clear_error(self):
        with self.assertRaises(cc.ComposeCheckError):
            cc.check({"services": {"reze": "oops"}})


class ComposeFileTests(unittest.TestCase):
    """Checks that need files on disk: env files, build contexts, .gitignore."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="reze-compose-check-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, text=""):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_missing_dotenv_is_informational_for_cloady(self):
        self._write("Dockerfile", "FROM python:3.12-slim\n")
        report = cc.check(_base(), base_dir=self.tmp)
        self.assertIn("ENVFILE-MISSING-LOCAL", _codes(report, cc.INFO))
        self.assertTrue(report.ok)

    def test_missing_other_env_file_is_an_error(self):
        data = _base(env_file=["settings.env"])
        self.assertIn("ENVFILE-MISSING", _codes(cc.check(data, base_dir=self.tmp), cc.ERROR))

    def test_missing_build_context_is_an_error(self):
        data = _base(build={"context": "./nowhere"})
        self.assertIn("BUILD-CONTEXT", _codes(cc.check(data, base_dir=self.tmp), cc.ERROR))

    def test_missing_dockerfile_is_an_error(self):
        data = _base(build={"context": "."})
        self.assertIn("BUILD-DOCKERFILE", _codes(cc.check(data, base_dir=self.tmp), cc.ERROR))

    def test_env_file_committed_without_gitignore_entry_is_an_error(self):
        self._write(".env", "REZE_API_ID=1\n")
        self._write(".gitignore", "__pycache__/\n")
        report = cc.check(_base(), base_dir=self.tmp)
        self.assertIn("ENV-NOT-IGNORED", _codes(report, cc.ERROR))

    def test_env_file_ignored_by_gitignore_is_accepted(self):
        self._write(".env", "REZE_API_ID=1\n")
        self._write(".gitignore", "__pycache__/\n.env\n")
        self.assertNotIn("ENV-NOT-IGNORED", _codes(cc.check(_base(), base_dir=self.tmp)))

    def test_dockerfile_plus_compose_prints_the_deploy_path_note(self):
        self._write("Dockerfile", "FROM python:3.12-slim\n")
        self.assertIn("DEPLOY-PATH-AMBIGUOUS", _codes(cc.check(_base(), base_dir=self.tmp), cc.INFO))


class RepositoryComposeTests(unittest.TestCase):
    """The compose file shipped in this repository must pass its own checker."""

    def test_shipped_docker_compose_passes(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML is not installed (pip install -r requirements-dev.txt)")
        report = cc.check_file(os.path.join(REPO, "docker-compose.yml"))
        self.assertTrue(report.ok, report.to_text())
        self.assertNotIn("PORT-FIXED", _codes(report))
        self.assertNotIn("VOLUME-BIND", _codes(report))


if __name__ == "__main__":
    unittest.main()

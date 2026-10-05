import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "repository_hygiene", Path(__file__).with_name("check_repository_hygiene.py")
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class RepositoryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def track(self, path, content="test fixture\n"):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
        subprocess.run(["git", "add", "-f", "--", path], cwd=self.root, check=True)

    def test_runtime_environment_files_are_rejected(self):
        for path in [".env", ".env.vercel", "app/.env.production", "app/.env.local"]:
            self.track(path)
        self.assertEqual(len(guard.check(self.root)), 4)

    def test_reviewed_environment_examples_are_allowed(self):
        for path in [".env.example", ".env.facebook.example", "app/.env.template"]:
            self.track(path)
        self.assertEqual(guard.check(self.root), [])

    def test_dependencies_and_root_output_are_rejected(self):
        for path in ["app/node_modules/a/index.js", ".venv/config", "dist/index.html"]:
            self.track(path)
        self.assertEqual(len(guard.check(self.root)), 3)

    def test_credentials_are_rejected(self):
        self.track(".netrc")
        self.assertEqual(len(guard.check(self.root)), 1)

    def test_private_key_is_rejected_without_printing_its_value(self):
        header = "-----BEGIN " + "PRIVATE KEY-----"
        self.track("assets/unexpected.txt", header + "\nfixture-secret-value\n")
        result = guard.check(self.root)
        self.assertEqual(len(result), 1)
        self.assertNotIn("fixture-secret-value", str(result))

    def test_untracked_environment_is_not_source(self):
        (self.root / ".env").write_text("LOCAL=fixture\n")
        self.assertEqual(guard.check(self.root), [])

    def test_real_scientific_data_and_vendor_assets_are_allowed(self):
        self.track("data/model.csv")
        self.track("vendor/plotly.min.js")
        self.assertEqual(guard.check(self.root), [])

    def test_cli_returns_nonzero_on_a_tracked_environment(self):
        self.track(".env.vercel")
        result = subprocess.run(
            [sys.executable, str(Path(guard.__file__).resolve()), "--root", str(self.root)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(".env.vercel", result.stdout)


if __name__ == "__main__":
    unittest.main()

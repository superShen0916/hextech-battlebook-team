from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from check_repository import inspect


class RepositoryQualityTests(unittest.TestCase):
    def sample(self, root):
        files = {'README.md': '[Guide](docs/guide.md)', 'AGENTS.md': 'Development rules',
                 'LICENSE': 'MIT License', 'docs/guide.md': '# Guide'}
        for name, content in files.items():
            p = root/name; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
        return list(files)

    def test_data_free_documentation_and_broken_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); names = self.sample(root)
            self.assertEqual(inspect(root, names), [])
            (root/'README.md').write_text('[Missing](docs/missing.md)', encoding='utf-8')
            self.assertTrue(any('broken documentation link' in e for e in inspect(root, names)))

    def test_private_data_and_secret_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); names = self.sample(root)
            for name, content in [('data/mayhem.sqlite', b'database'),
                                  ('client.py', ('ghp_'+'A'*36).encode())]:
                p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(content)
                names.append(name)
            errors = inspect(root, names)
            self.assertTrue(any('local data' in e for e in errors))
            self.assertTrue(any('credential marker' in e for e in errors))
            self.assertNotIn('ghp_'+'A'*36, '\n'.join(errors))

    def test_mutable_actions_and_privileged_pull_requests_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); names = self.sample(root)
            p = root/'.github/workflows/unsafe.yml'; p.parent.mkdir(parents=True)
            p.write_text('on:\n  pull_request_target:\njobs:\n  check:\n    steps:\n      - uses: actions/checkout@v4\n')
            names.append('.github/workflows/unsafe.yml')
            errors = inspect(root, names)
            self.assertTrue(any('immutable' in e for e in errors))
            self.assertTrue(any('privileged' in e for e in errors))

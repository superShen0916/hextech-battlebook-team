from contextlib import redirect_stdout
from pathlib import Path
import io
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import check_repository
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

    def test_privileged_event_spellings_and_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); names = self.sample(root)
            p = root/'.github/workflows/events.yml'; p.parent.mkdir(parents=True)
            names.append('.github/workflows/events.yml')
            for event in ('on:\n  pull_request_target:\n',
                          'on: [push, pull_request_target]\n',
                          'on: pull_request_target\n',
                          'on:\n  - push\n  - pull_request_target\n'):
                with self.subTest(event=event):
                    p.write_text(event, encoding='utf-8')
                    self.assertTrue(any('privileged' in e for e in inspect(root, names)))
            p.write_text('on: pull_request # pull_request_target is forbidden\n'
                         '# on: pull_request_target\n', encoding='utf-8')
            self.assertEqual(inspect(root, names), [])

    def test_git_enumeration_failure_in_real_checkout_fails_the_check(self):
        """真实 checkout 里 Git 枚举失败时不得降级：已跟踪的禁用路径仍需被拒。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.sample(root)
            (root/'.git').mkdir()
            tracked_forbidden = root/'outputs/token.txt'
            tracked_forbidden.parent.mkdir(parents=True)
            tracked_forbidden.write_text('ghp_'+'A'*36, encoding='utf-8')
            out = io.StringIO()
            with mock.patch.object(check_repository.subprocess, 'check_output',
                                   side_effect=OSError('git unavailable')):
                with mock.patch.object(sys, 'argv', ['check_repository.py', '--root', str(root)]):
                    with redirect_stdout(out):
                        code = check_repository.main()
            self.assertNotEqual(code, 0)
            self.assertIn('"ok": false', out.getvalue())
            self.assertNotIn('ghp_'+'A'*36, out.getvalue())

    def test_unpacked_directory_without_git_metadata_falls_back_to_tree_walk(self):
        """解包出来、没有 Git 元数据的目录仍按目录遍历工作。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.sample(root)
            (root/'outputs').mkdir()
            (root/'outputs/token.txt').write_text('placeholder', encoding='utf-8')
            with mock.patch.object(check_repository.subprocess, 'check_output',
                                   side_effect=OSError('git unavailable')):
                names = check_repository.tracked_names(root)
            self.assertIn('README.md', names)
            self.assertNotIn('outputs/token.txt', names)

    def test_archive_inside_another_worktree_does_not_borrow_parent_index(self):
        """归档解包在别人的工作树里时，不能拿父仓库的索引当自己的清单。"""
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory)
            (outer/'.git').mkdir()
            archive = outer/'archive'; archive.mkdir()
            self.sample(archive)
            with mock.patch.object(check_repository.subprocess, 'check_output',
                                   side_effect=AssertionError('git must not run for an unpacked archive')):
                names = check_repository.tracked_names(archive)
            self.assertIn('README.md', names)
            self.assertEqual(check_repository.inspect(archive, names), [])

    def test_broken_git_symlink_still_counts_as_a_checkout(self):
        """损坏的 .git 符号链接说明这是 checkout，不能当成无元数据的归档。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.sample(root)
            try:
                (root/'.git').symlink_to(root/'missing-git-dir')
            except (OSError, NotImplementedError):
                self.skipTest('this platform cannot create symlinks without extra privileges')
            self.assertTrue(check_repository.has_git_metadata(root))
            with mock.patch.object(check_repository.subprocess, 'check_output',
                                   side_effect=OSError('git unavailable')):
                with self.assertRaises(check_repository.TrackedFilesUnavailable):
                    check_repository.tracked_names(root)

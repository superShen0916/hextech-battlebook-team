"""Team entry point. No hosting actions and no automatic Git pull."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('setup', 'download', 'install', 'pack', 'publish', 'source'))
    args, rest = parser.parse_known_args()
    if args.command == 'setup':
        from node_runtime import resolve_node, node_environment
        node, version = resolve_node()
        npm = Path(node).parent / 'node_modules/npm/bin/npm-cli.js'
        # Unix installations usually keep npm's entry point behind a symlink.
        if not npm.exists():
            import shutil
            executable = shutil.which('npm')
            if executable:
                npm = Path(executable).resolve()
        if not npm.is_file():
            raise RuntimeError('npm_missing: install the official pinned Node distribution')
        for relative in ('work/players-preview-20261022', 'tools/browser'):
            subprocess.run([node, str(npm), 'ci', '--ignore-scripts', *rest], cwd=ROOT/relative,
                           env=node_environment(node), check=True)
        print(json.dumps({'ok': True, 'node': version, 'next': 'Team.cmd download'}, ensure_ascii=False))
    elif args.command == 'source':
        from team_source import main as export
        export(rest)
    else:
        from team_data import main as data
        data([args.command, *rest])


if __name__ == '__main__':
    main()

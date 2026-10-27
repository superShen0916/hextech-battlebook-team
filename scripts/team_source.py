"""Export a clean current-source baseline without local Git or discussion history."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FRONT = 'work/players-preview-20261022'
COLLECTOR = 'work/gopher-pilot-20261021/scripts/'
DOCS = {'README.md', 'TEAM-GUIDE.md', 'TEAM-PUBLISHING.md', 'ARCHITECTURE.md', 'MAINTENANCE.md',
        'FEATURE-PARITY.md', 'ACHIEVEMENTS.md', 'RECAP-SHARING.md', 'MATCH-REVIEW.md',
        'VERSION-INTEL.md', 'HEXDATA-INTEGRATION.md', 'DATA-WORKFLOW.md',
        'PUBLIC-SITE.md', 'WORKFLOW.md', 'WEEKLY-EXPERIENCE.md'}
COLLECT = {'sync_new_matches.py', 'list_teammates_pilot.py', 'collect_gopher_pilot.py',
           'collect_account_pilot.py', 'fix_all_attribution.py', 'check_all_attribution.py',
           'register_cached_player.py', 'owner_roster.py'}
ROOT_FILES = {'README.md', 'CONTRIBUTING.md', '.gitignore', 'Team.cmd', 'Run-Python.cmd',
              'Run-Node.cmd', 'Workflow.cmd', 'Start-Dashboard.cmd', 'Public-Site.cmd',
              'Share-Card.cmd', 'Sync-History.cmd', 'Update-Battlebook.cmd',
              'Update-Public-Site.cmd', 'Rebuild-Public-Site.cmd', 'Recover-Missing.cmd',
              'THIRD-PARTY-NOTICES.md'}


def selected(name):
    p = Path(name)
    if any(x in p.parts for x in ('.git','node_modules','__pycache__','_archive')) or p.suffix == '.pyc' or '.bak-' in p.name:
        return False
    # 本地私密配置一律不出库，只保留空模板 .env.example
    if p.name.startswith('.env') and p.name != '.env.example':
        return False
    if name in ROOT_FILES or name.startswith(('app/','tests/','examples/','.github/')):
        return True
    if name.startswith('scripts/'):
        return p.suffix == '.py'
    if name.startswith('config/'):
        return name == 'config/runtime.json'
    if name.startswith('tools/browser/'):
        return p.name in ('package.json','package-lock.json')
    if name.startswith('docs/'):
        return name == 'docs/'+p.name and p.name in DOCS
    if name.startswith('haido/'):
        return p.name in ('rating_lp.py','README.md')
    if name.startswith(COLLECTOR):
        return p.name in COLLECT
    if name.startswith(FRONT+'/'):
        relative = p.relative_to(FRONT)
        if relative.parts[0] in ('src','lib'):
            return True
        if relative.parts[0] == 'public':
            return relative.as_posix() in ('public/favicon.svg','public/review.html','public/share/index.html')
        return len(relative.parts) == 1 and (p.suffix in ('.ts','.mjs','.html','.py') or
                    p.name in ('package.json','package-lock.json','tsconfig.json','.env.example'))
    return False


TEAM_AGENTS = '''# 团队维护约定

先读 README.md、docs/TEAM-GUIDE.md、docs/TEAM-PUBLISHING.md 和 haido/README.md。
源码只有一份，唯一运行库为 data/mayhem.sqlite。真实游戏数据从公开 Release 下载，不提交数据库、身份配置、评分生成物、令牌或发布凭据。
修改使用 Workflow.cmd plan --files <文件>，完成后 prepare；prepare 仅在本机测试构建，不代表网站上线。
正式站由原 WorkBuddy 应用发布；普通成员不要创建替代站或发布 GitHub Pages。发布者必须 ready → 原应用托管 → online。
评分规则对所有玩家一致；不得按账号、昵称或目标排名单独加减分。冻结基准不是缓存，不得删除重建；算法与基准迁移需先经维护者审阅。
保留全部历史、荣誉、雷达、十人战报、回顾和分享功能。禁止时间轴/逐帧采集。
协作检出可以放任意目录；原发布机器项目和发布目录的绝对路径不得改变。
新修改通过分支和 PR 合并。测试使用合成样本或共享数据，讨论算法时使用匿名案例；不把个人聊天讨论写入源码文档。
'''


def export(root=ROOT, destination=None):
    root = Path(root).resolve()
    destination = Path(destination or root/'outputs/team/source')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('source_destination_must_be_empty')
    destination.mkdir(parents=True, exist_ok=True)
    tracked = subprocess.check_output(['git','ls-files','-z'],cwd=root).decode('utf-8').split('\0')
    new = subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=root).decode('utf-8').split('\0')
    files = {}
    for name in sorted(set(tracked+new)):
        path = root/name
        if name and path.is_file() and selected(name):
            if path.is_symlink():
                raise ValueError('source_link:'+name)
            files[name] = path.read_bytes()
    files['AGENTS.md'] = TEAM_AGENTS.encode('utf-8')
    files['config/workspace.json'] = b'{"role":"collaborator"}\n'
    files['STATUS.md'] = ('# 团队工作副本\n\n当前源码基线：海斗分5.1、单场表现v0.5。\n'
        '本目录不是正式发布机；本地数据版本见 work/build/team-data.json，正式站见原 WorkBuddy 网址。\n'
        '日常维护读 docs/TEAM-GUIDE.md，发布规则读 docs/TEAM-PUBLISHING.md。\n').encode('utf-8')
    files['docs/history/CHANGELOG.md'] = ('# 团队变更记录\n\n'
        '- 2026-10-27 | 基准版本 | 导入当前已发布5.1源码；不携带旧Git历史及本机讨论记录。\n').encode('utf-8')
    inventory = {}
    for name, content in files.items():
        path = destination/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
        inventory[name] = hashlib.sha256(content).hexdigest()
    report = {'files':len(files),'sha256':inventory,'history_included':False,
              'runtime_data_included':False,'personal_discussion_included':False}
    (destination.parent/'source-inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    archive = destination.parent/'battlebook-source.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
        for name in sorted(files):
            output.write(destination/name,name)
    return {'ok':True,'directory':str(destination),'archive':str(archive),'files':len(files)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args(argv)
    print(json.dumps(export(destination=args.out),ensure_ascii=False))


if __name__=='__main__':
    main()

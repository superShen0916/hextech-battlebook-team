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
        'PUBLIC-SITE.md', 'WORKFLOW.md', 'WEEKLY-EXPERIENCE.md', 'ANALYTICS.md', 'AUTOMATION.md'}
COLLECT = {'sync_new_matches.py', 'list_teammates_pilot.py', 'collect_gopher_pilot.py',
           'collect_account_pilot.py', 'fix_all_attribution.py', 'check_all_attribution.py',
           'register_cached_player.py', 'owner_roster.py'}
ROOT_FILES = {'README.md', 'CONTRIBUTING.md', 'LICENSE', '.gitignore', '.coderabbit.yaml', 'Team.cmd', 'Run-Python.cmd',
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


TEAM_AGENTS = '''# AI开发约定

## 开始工作

阅读 README.md、docs/TEAM-GUIDE.md、docs/ARCHITECTURE.md 以及所改模块规范。修改前检查Git状态，只处理任务范围，不回滚他人改动。提交前说明行为变化和实际验证结果。

## 运行与验证

使用项目根的统一入口：Workflow.cmd plan --files <文件>，修改后prepare；正式发布前ready，托管原WorkBuddy应用后online。Python回归使用Run-Python.cmd -m unittest discover -s tests -q。依赖、Node版本和浏览器检查由现有工具链定义，不另建平行入口。

## 数据边界

唯一前端为work/players-preview-20261022，唯一运行库为data/mayhem.sqlite，路径由app/project_paths.py定义。完整开发数据从原仓库公开Release取得，不把数据库、身份配置、评分生成物、令牌或发布凭据提交Git。开发副本不得覆盖发布机数据或应用绑定。

完整快照与网页摘要分开，禁止摘要覆盖完整输入。不采集逐帧时间轴。采集、构建与同步取得现有锁，不并发直跑底层脚本、不手删锁文件。采集失败不能冒充整链成功。

## 评分与功能

唯一海斗分入口为haido/rating_lp.py，单场表现来源为app/awards.py，完整规则见haido/README.md。所有玩家使用统一规则，不按账号、昵称或目标排名特判。冻结基准与标尺为持久状态，不当缓存删除；修改公式或迁移基准先获得维护者明确授权。

保留完整个人历史、雷达及同类对比、装备与海克斯Top3、评语、队友、荣誉、搜索、十人战报、回顾、分享和成就。性能优化不得静默减少内容或用最近少量对局代替全历史。产品约束见docs/FEATURE-PARITY.md。

## 部署与隐私

正式站继续使用原WorkBuddy应用；本地构建或GitHub Release不代表上线。不创建替代正式站，不推GitHub Pages。发布流程见docs/TEAM-PUBLISHING.md。

打点在开发环境默认关闭，配置只存本机。访客记录、真实设备编号、恢复包和本机配置不入库、不随战绩Release分发；分析访问情况的功能应保留。

## 文档与许可

文档只描述稳定行为、接口、架构、操作与约束，不写聊天摘要、个人评价、本机路径流水、验收记录或任务交接。运行证据放本机输出目录，变更讨论通过Issues和PR完成。同步更新受影响文档与链接。

自有代码与文档采用MIT许可证；第三方游戏素材和数据保留原许可，见THIRD-PARTY-NOTICES.md。
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

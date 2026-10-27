# 在自己的电脑上维护战报馆

仓库：`superShen0916/hextech-battlebook-team`，公开。克隆、改代码、提 PR 都不需要邀请；完整战绩数据在 Releases 里，`.\Team.cmd download` 会自动下载最新的数据包，所以任何人都能跑出和线上一致的完整档案。它以当前已发布5.1版本为新基准；旧聊天、评分试算、个人评价和原Git历史不带入。

## 第一次运行（Windows / PowerShell）

安装 Git、Python 3.10+、Node **22.23.3**（含npm）、GitHub CLI `gh`，以及Chrome或Edge。普通开发无需LOL客户端、WorkBuddy或发布账号。

```powershell
gh auth login
git clone https://github.com/superShen0916/hextech-battlebook-team.git
Set-Location hextech-battlebook-team
.\Team.cmd setup
.\Team.cmd download
.\Workflow.cmd doctor
.\Workflow.cmd prepare --files work/players-preview-20261022/src/App.tsx
.\Start-Dashboard.cmd
```

在浏览器打开 `http://127.0.0.1:5180/`。预览服务需要保留命令窗口，Ctrl+C停止。首次完整构建需要几分钟；后续构建按内容复用。页面应能查看全部共享档案、历史、雷达、十人战报、回顾和分享。

`setup` 在前端和浏览器工具目录分别执行锁定版本的 `npm ci --ignore-scripts`，不需要创建Junction。如果官方npm网络不畅，可执行 `Team.cmd setup --registry=https://registry.npmmirror.com`。Node可通过PATH寻找，但版本仍严格核对；特殊路径复制 `examples/runtime.local.json` 到 `config/runtime.local.json` 后填写，或设置环境变量 `BATTLEBOOK_NODE`。不要把自己的绝对路径提交。

其他系统可通过 `python scripts/team.py ...` 调用同一入口；采集仍依赖Windows游戏客户端。本轮完整验证环境是Windows，不宣称已验证macOS/Linux。

## 完整数据下载和更新

数据从公开Releases获取，不进入Git提交。网页下载附件无需登录或邀请；使用Team.cmd下载时先完成 `gh auth login`。公开仓库的Fork也从原仓库下载同一份数据。

```powershell
git pull --ff-only
.\Team.cmd download --replace
```

`download` 固定本次选中的Release标签，下载 `battlebook-data.zip` 和 `.sha256`，校验压缩包、每个文件的SHA256、SQLite完整性及身份绑定后才安装。首次安装无需 `--replace`；更新现有数据必须加该参数，并在 `outputs/team-import/previous-data.zip` 保留被覆盖文件的回滚包。运行前关闭本地预览、采集和数据库工具，确保没有数据库连接占用。

指定数据版本用 `Team.cmd download --tag data-YYYYMMDDTHHMMSSZ`。手动下载后执行 `Team.cmd install --archive 压缩包路径`。下载中断或校验失败不会修改现有数据；安装替换失败会尝试回滚。正式发布机因应用绑定标记而拒绝这些安装命令。

数据包包含完整数据库、匹配的身份/名单/排除配置、冻结基准与标尺、完整快照、公开页面全部数据和静态资源。维护者已授权公开游戏身份和完整战绩，任何人均可下载；不把访问者信息和凭据混入数据包。包中不包含WorkBuddy发布凭据、客户端登录令牌、访问者统计数据库或旧备份。`work/build/team-data.json` 记录本地安装版本。

## 日常改动和检查

```powershell
git switch -c feature/your-change
.\Workflow.cmd plan --files work/players-preview-20261022/src/Lobby.tsx
# 修改代码
.\Workflow.cmd prepare --files work/players-preview-20261022/src/Lobby.tsx
```

只改页面时prepare核对数据、TypeScript、7项前端检查、1440/390/320浏览器和本机产物；改Python/构建/评分时会加跑Python回归。首次没有缓存会完整计算。`prepare`只准备你自己的本机发布目录，不会更新正式网站。

提交源码分支和PR，说明修改内容、验证命令、截图或行为结果。数据包无需随PR重新上传。共享库可能滞后于正式站，这是可重复测试的固定样本；正式发布前由发布机用最新数据库完整验收。每次更换评分规则对应的源码版本后，应重新下载匹配数据包。

GitHub自动检查会从原仓库的公开Release安装完整数据，运行同一pipeline prepare；没有Release或无读取权限时明确失败，不把空页面算成功。它不持有WorkBuddy发布能力。

## 评分规则与资料边界

所有玩家使用 `app/awards.py` 与 `haido/rating_lp.py` 同一套规则；身份只用于关联记录和读取冻结历史基准，不能作为加减分条件。修改规则前先审阅，结果对全体适用。不要手改分数JSON、删除基准或为了某人的目标排名写例外。

评分说明在 `haido/README.md`，模块职责在 `docs/ARCHITECTURE.md`。源码包不含本地历史讨论，不代表旧工作区从来没有这些记录。正式发布步骤见 `TEAM-PUBLISHING.md`。

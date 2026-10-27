# 海克斯战报馆

朋友共同维护的海克斯大乱斗战绩站：玩家大厅、完整个人档案、六维雷达、十人战报、海斗分、搭档荣誉、当晚和多人回顾、分享图、成就与版本情报。

- **本仓库**：[superShen0916/hextech-battlebook-team](https://github.com/superShen0916/hextech-battlebook-team)。公开仓库，任何人不经邀请即可克隆、阅读、改代码、提 Issue 或 PR。
- **战绩数据**：完整运行库与逐局战绩不随代码入库，放在 [Releases](https://github.com/superShen0916/hextech-battlebook-team/releases) 的数据包里，`.\Team.cmd download` 会自动取最新包。想本地跑出完整页面，就按下面的步骤来。
- **正式网站**：[WorkBuddy 海克斯战报馆](https://hextech-battlebook.app.workbuddy.host/?sharecode=7ZFAIH5YHV)。GitHub负责协作和数据下载，网页继续在原WorkBuddy应用托管。
- **新成员先读**：[本地运行与完整数据下载](docs/TEAM-GUIDE.md)、[团队维护及发布流程](docs/TEAM-PUBLISHING.md)、[贡献约定](CONTRIBUTING.md)。

## 本地启动（Windows / PowerShell）

安装Git、Python 3.10+、Node 22.23.3（含npm）、GitHub CLI以及Chrome/Edge，然后：

```powershell
gh auth login
git clone https://github.com/superShen0916/hextech-battlebook-team.git
Set-Location hextech-battlebook-team
.\Team.cmd setup
.\Team.cmd download
.\Workflow.cmd prepare --files work/players-preview-20261022/src/App.tsx
.\Start-Dashboard.cmd
```

浏览器打开 `http://127.0.0.1:5180/`。完整数据包包含所有共享战绩、匹配配置、冻结评分状态、完整快照与页面资源，不是几条演示数据。开发不需要LOL客户端或WorkBuddy；只有采集和正式托管需要发布机。

更新开发数据：先更新main源码，再运行 `Team.cmd download --replace`。更新前关闭数据库连接；命令先校验完整性并备份被覆盖文件。网络镜像、Node特殊路径、指定Release及手动安装见TEAM-GUIDE。

## 维护流程

修改前 `Workflow.cmd plan --files <文件>`，完成后 `prepare`，通过分支和PR合并。正式发布由发布机执行 `ready → WorkBuddy原应用托管 → online`；本地构建和GitHub Release均不代表网站上线。机器人入口后续单独接入。

Python回归：`Run-Python.cmd -m unittest discover -s tests -q`。prepare统一运行适用的Python回归、TypeScript、7项前端检查、数据/评分/隐私门禁及1440/390/320浏览器检查，详见[WORKFLOW](docs/WORKFLOW.md)。不另写平行的评分、构建或发布实现。

## 目录与规则

| 目录 | 职责 |
| --- | --- |
| app/ | 领域统计、存储、单场表现与公开投影 |
| haido/rating_lp.py | 唯一海斗分入口，规则见[5.1规范](haido/README.md) |
| scripts/ | 构建、校验、同步、团队数据分发与源码导出 |
| work/players-preview-20261022/ | 唯一React/TypeScript/Vite前端，保留历史路径避免现站绑定失效 |
| work/gopher-pilot-20261021/scripts/ | 当前采集入口及依赖 |
| data/ | 唯一数据库、身份配置、排除规则和冻结状态；从Release数据包取得，不提交Git |
| examples/ | 不带真实身份的配置格式 |
| tests/、tools/browser/ | 回归与浏览器验收 |
| outputs/、backups/ | 本机产物与恢复点，不上传源码仓库 |

所有玩家使用统一规则；个人基准来自历史公式计算并冻结，不得按账号或目标排名加减分。周分、基准和逐局说明共用唯一评分来源。不得删除基准重建，不采集逐帧时间轴，不减少完整个人内容。

仓库公开可读并接受协作，尚未指定整个项目的开源许可证；第三方素材和依赖说明见[THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES.md)。团队源仓库不带旧Git提交、个人讨论或旧试算。

发布机当前状态见STATUS.md，其他工作副本的数据版本见work/build/team-data.json。技术导航见[docs/README](docs/README.md)。

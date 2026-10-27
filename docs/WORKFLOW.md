# 构建与验收工作流

在项目根运行 `Workflow.cmd`；也可用 `python scripts/workflow.py` 调用同一入口。开发副本用于本地验收，正式部署仅由发布机执行。

## 开发步骤

1. 阅读README、AGENTS及所改模块规范，检查Git状态，明确修改范围。
2. 运行 `plan --files <文件>` 查看检查范围。
3. 修改后运行 `prepare --files <文件>`，通过后提交PR并说明行为及验证结果。
4. 发布维护者接收已审阅源码，执行 `ready`，托管原WorkBuddy应用后执行 `online`。

```powershell
.\Workflow.cmd plan --files work/players-preview-20261022/src/Lobby.tsx
.\Workflow.cmd prepare --files work/players-preview-20261022/src/Lobby.tsx
```

## 命令

| 命令 | 职责 |
| --- | --- |
| `plan` | 只读分析文件分类和检查项 |
| `doctor` | 检查固定Node、浏览器依赖及Chrome/Edge |
| `check` | 校验仍匹配输入的现有产物，不构建或同步 |
| `prepare` | 执行检查、按内容增量构建、浏览器验收及完整同步 |
| `ready` | 复核已验收源码、数据、自然周与全部产物，不重新构建 |
| `online` | 核验原站入口、资源、代表数据和浏览器交互，不执行托管 |

## 检查范围

| 变更 | 检查 |
| --- | --- |
| 文档 | 工作副本或发布机状态一致性 |
| 前端或数据 | 数据/评分/隐私门禁、TypeScript、七项前端规则检查、1440/390/320浏览器 |
| Python、构建或其他运行逻辑 | 完整Python回归及上述检查 |

`--files` 不会跳过全项目输入和产物指纹。`--scope pipeline` 可扩大检查范围，不得用较小scope隐藏运行代码变化。测试运行入口为 `Run-Python.cmd -m unittest discover -s tests -q`；依赖安装用 `Team.cmd setup`。

## 增量构建与产物

唯一构建器为 `scripts/build_release.py`。常规prepare使用 `--data-only`，数据、前端和依赖按内容指纹分别复用；前端变化会更新前端，数据变化会重算所需数据。`--full` 用于有理由的完整重建或对照，不另设第二套构建实现。

完整快照、十人明细、评分注入、回顾/周报、成就、分片和原门禁必须保留。候选通过检查后才替换dist；浏览器失败不执行发布目录同步。固定candidate和dist-previous是构建槽位，不是可随意删除的旧备份。

`build_id` 标识数据快照，`artifact_sha256` 标识整份发布目录。发布验证使用完整文件哈希，不能只比较build_id、大小或mtime。源码、数据、自然周、依赖或产物变化会使ready拒绝过期回执。

## 工作区状态

源码副本通过`config/workspace.json`登记为`collaborator`；`Team.cmd download`只下载并安装已校验的数据。文档prepare核对安装数据和冻结基准，不需要发布机状态卡。原发布机继续保留本机STATUS.md与docs/history/CHANGELOG.md，检查器按其中事实核对运行库、产物与恢复点；接收团队源码时保留这两份本机资料，不从源码仓库恢复或覆盖它们。它们被Git忽略，不随公开源码或战绩包分发。开发副本不能通过修改工作区角色代替正式托管验收。

## 回执与失败恢复

本地日志和JSON回执写入 `outputs/workflow/<run_id>/` 与 `work/build/`，不提交Git或抄入参考文档。只有成功prepare生成可发布凭证；构建、同步与实际托管分别记录，不能把本机成功当作上线。

流程共用sync、release与workflow锁。锁冲突等待或退出，不手删锁文件。失败后保留现场，修复原因再通过同一入口验收；不得伪造回执、跳过门禁或绕过平台拒绝。

正式部署及恢复见[发布指南](TEAM-PUBLISHING.md)和[维护指南](MAINTENANCE.md)。手机视口检查只验证布局，真实手机网络可访问性另行核验。

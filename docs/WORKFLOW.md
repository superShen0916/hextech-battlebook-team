# 固定维护与验收入口

Codex 和 WorkBuddy 在项目根运行同一份 `Workflow.cmd`，跨平台助手也可执行 `Run-Python.cmd scripts/workflow.py`，参数完全相同。下列命令均为 **PowerShell**；不依赖某个助手的专有工具或后台进程寿命。

## 新对话按这个顺序

1. 读 STATUS 状态表、CHANGELOG **顶部最近3条**、`git status`，明确本次文件范围。
2. `Workflow.cmd plan --files <本次文件...>` 查看分类。无 `--files` 时保守检查全部已跟踪改动和未忽略的新文件；不会回滚、暂存或提交别人的改动。
3. 修改源码后，执行 `Workflow.cmd prepare --files <本次文件...>`。它运行需要的测试、增量构建、浏览器验收，再同步原发布目录。
4. 发布前执行同一范围的 `Workflow.cmd ready --files <本次文件...>`。成功才允许托管，发布**同一份目录**，不再重新构建。
5. 用当前助手实际可用的 WorkBuddy 原应用发布能力托管，再执行 `Workflow.cmd online --files <本次文件...>`。
6. 按真实结果覆盖 STATUS 受影响行、CHANGELOG 顶部加一条；收工跑 `Run-Python.cmd scripts/check_state.py`，涉及发布再加 `--online`。

```powershell
# 小改动示例（不要把示例文件名照抄为每轮固定范围）
.\Workflow.cmd plan --files work/players-preview-20261022/src/Lobby.tsx
.\Workflow.cmd prepare --files work/players-preview-20261022/src/Lobby.tsx
.\Workflow.cmd ready --files work/players-preview-20261022/src/Lobby.tsx
# 此处托管原应用；没有对应工具就如实停在“已同步未托管”
.\Workflow.cmd online --files work/players-preview-20261022/src/Lobby.tsx
```

`--files` 列本次已知改动文件，不会屏蔽全项目数据/源码指纹和正式数据门禁。新增 Python、未知运行文件、采集/评分/构建代码归为 pipeline，不能用 `--scope frontend` 隐藏它们。`--scope pipeline` 可主动扩大检查。仅文档 `check` 不构建、不启动浏览器，也不废弃上一份有效运行产物回执。

普通文案、数量和局部样式修改，完成后统一验收一次，不每改一行就手动开预览或遍历全站。涉及视觉设计时查看本轮生成的代表截图；只有后续修改、失败或未解决疑点才重跑相关检查。新增交互先补固定案例，不再临时搭一套浏览器环境。

## 命令与检查范围

| 命令 | 行为 |
| --- | --- |
| `plan` | 只读输出文件分组、选择的模式和检查项 |
| `doctor` | 核实固定 Node、锁定的 Playwright 和本机 Chrome/Edge；不打开可见窗口 |
| `check` | 检查**已构建且仍匹配源码/数据的** dist；不构建、不同步，不生成可发布凭证。源码变了就提示 prepare |
| `prepare` | 按需跑 Python 回归 → 唯一构建入口 → 浏览器 → 同步及完整哈希核对 → 可发布凭证 |
| `ready` | 复核上次 prepare 的源码、数据、当前自然周及 dist/发布目录哈希；不重跑测试、不重新构建 |
| `online` | 先通过 ready 同等核对，再逐文件验证线上入口/JS/CSS/代表完整数据，运行同一浏览器验收；不执行托管 |

| 分类 | 检查 |
| --- | --- |
| docs | 状态一致性检查 |
| frontend | 数据/评分/隐私门禁、TypeScript、原7项前端检查、固定浏览器验收 |
| data | 同上，数据变化触发增量生成 |
| pipeline | 完整 Python 回归，加上述全部检查 |

正常 prepare 始终使用 `build_release.py --data-only`：这是内容指纹驱动的智能构建模式，**前端源码有改动也能用**；数据未变就复用，前端变动则只重打包壳；数据或规则变了自动重算必要数据。首次缓存不匹配会生成数据。不要因“改了页面”就改用默认全量构建。`--full` 仅用于有理由的排障/对照。下层 `Update-Public-Site.cmd`、nightly 和采集入口暂保留原接口，新对话人工修改验收优先使用本入口；它不主动采集。

构建器与本入口共用 `scripts/release_checks.py` 的7项前端清单；前端 `npm test` 仍是历史3项子集，不能拿它代替正式验收。

实现边界见 [ARCHITECTURE](ARCHITECTURE.md)。数据输入和验收输入分开：维护脚本变动会重新验收，数据未变时复用数据；输入定义更新后的第一次prepare会刷新缓存。同步共用一个实现，复用本轮已验证的源清单，并完整核对目标内容，不再紧接着重复扫描目标。

## 固定浏览器覆盖

源码在 `tests/browser/smoke.mjs`，依赖在 `tools/browser/package.json` 和锁文件，禁止再将唯一验收代码放在 `work/build` 临时目录。

- 1440 / 390 / 320：周榜、总榜、全玩家数量、最近最多10条及入口、实际十人战报、个人原7分区、完整样本数、真实评分分项、页面与规则弹窗无横向溢出。
- 从当前产物选择实际玩家和实际夜晚；核对当晚场数、PNG实际生成、分享链接参数、两人同队交集场数、版本情报入口。
- 捕获页面运行错误及站内 JSON/JS/CSS 失败。外站请求全部拦截，避免写线上访问统计和自动播放音乐。
- 使用临时静态服务、系统分配端口和 Playwright 临时浏览器会话；完成或失败后关闭自己启动的浏览器及服务，不操作用户日常 Chrome。
- 不以此宣称验证了手机真实网络、相册保存、听感，或所有特殊分支。新增交互时把代表行为补进此脚本；复杂回顾日期/2—5人/荣誉边界由已有规则检查覆盖，必要时增加对应案例。

依赖恢复（PowerShell，浏览器依赖与前端 node_modules Junction 分离）：

```powershell
# 项目根；使用固定 Node 所在目录的 npm，不依赖助手 PATH
$battleNode = (Get-Content config/runtime.json -Raw | ConvertFrom-Json).node_executable
$battleNpm = Join-Path (Split-Path $battleNode) 'node_modules/npm/bin/npm-cli.js'
Push-Location tools/browser
try { & $battleNode $battleNpm ci --ignore-scripts --registry=https://registry.npmmirror.com }
finally { Pop-Location }
.\Workflow.cmd doctor
```

默认寻找已安装的 Chrome，再尝试 Edge。特殊安装位置可设 `$env:BATTLEBOOK_BROWSER_EXECUTABLE='浏览器绝对路径'`，不得给 `--user-data-dir` 编造相对目录。

## 回执、失败和发布

`work/build/workflow-latest.json` 指向最近尝试；每轮日志、计时、截图及 JSON 在 `outputs/workflow/<run_id>/`。`work/build/workflow-receipt.json` 是运行产物验收回执，不是数据库备份。只有成功的 prepare 才含 `ok=true, ready=true`；新检查/准备失败、超时后不能拿旧成功冒充本轮。check 成功仍没有发布资格。

源码、数据库内容、配置、自然周、测试代码或测试依赖变化，或 dist/发布目录任一文件变化，都会让 ready 拒绝旧回执。文档回填不会废弃已验收产物。托管前 ready 可重复执行，避免重做测试。online 核验实际入口资源和完整代表数据，不能只靠数据 build_id 判断新前端上线。online 不写“已发布”标记，也不代替托管平台成功回执；两者都成功后才回填状态。

`workflow-receipt.json` **只由本入口写入**，表示人工测试及浏览器验收；夜间入口调用同一个构建/同步内核，不伪造人工验收凭证。需要人工接管夜间产物时，运行prepare完成验收（未变化数据会复用），再ready。实际发布身份统一使用整份目录的`artifact_sha256`，不能只比较数据`build_id`；真实托管和线上核验后，沿用`nightly.py --mark-published`记录两种身份。

准备过程中也会核对测试开始前的源码指纹，并用同一只读 SQLite 连接的 `data_version` 监视并发提交；避免每个浏览器步骤反复扫描整库。正式回执仍基于数据库内容指纹。步骤超时或中断会清理该步骤自己启动的进程树，不清理其它会话进程。

prepare 的浏览器检查失败时不执行同步，现有发布目录保留。构建阶段失败仍遵守下层构建器的恢复规则。若最终检查失败可能已有新 dist，修复后再 prepare；不能将其当成已验收发布物。锁冲突等待，不手删锁、不移动目录绕过删除限制，也不修改平台保护环境变量（`CODEBUDDY_SAFE_DELETE_ENABLED` 之类）。

固定槽位按差异替换文件，删除数量取决于实际失效文件，不能由“前端变了”或“全量模式”推断会整树删除。分片文件名带内容哈希、不含build_id。平台删除/进程限制以当前平台实际错误为准；拒绝时保留现场并停止，不修改保护开关或改名绕过，不沿用历史某一环境的固定数量和时间上限。

固定目标：`wbapp_l4kVV2RXXtLHGRDJ1XMUhL`，原绝对发布目录 `outputs/public-site-20261022b`，原域名和 sharecode 保持不变。当前助手没有原应用发布能力时，明确记录“已同步未托管”，交给具备该能力的 WorkBuddy；不另建 Sites 站点，不伪造托管结果。

# 数据与采集

## 数据模型

唯一运行库为 `data/mayhem.sqlite`，路径由 `app/project_paths.py` 定义。采集、完整个人档案、十人战报、评分、回顾和成就共用该库。SQLite的WAL/SHM文件属于同一数据库，不手动删除。网站读取白名单JSON，不直接访问SQLite；不采集逐帧时间轴。

| 配置 | 职责 |
| --- | --- |
| `data/public-profiles.json` | 稳定公开ID与精确游戏身份映射、展示名单 |
| `data/collection.json` | 客户端身份、主要采集视角及默认视图 |
| `data/collection-exclusions.json` | 停止单独采集的账号；保留已收录对局 |
| `data/stat-exclusions.json` | 明确排除的统计记录 |
| `data/haido-baseline-v4.json` | 持久冻结历史基准 |
| `data/haido-weekly-calibration-v04.json` | 当前表现版本对应的冻结标尺 |

配置由完整数据Release提供，不提交到Git。源码中的配置示例只描述格式。基准、标尺和身份配置属于持久数据，不能按缓存删除或自动重建。

## 身份与采集范围

采集客户端、采集对象和展示名单分别按稳定ID选择。注册不切换活跃账号，采集及导出不依赖全局 `active_account`。不得按昵称猜测PUUID或跨账号绑定。

账号缺少昵称不能据此认定为测试数据。可通过 `register_cached_player.py --puuid <puuid>` 从已收录对局恢复身份；多局身份不一致或缺失时停止。采集范围读取 `app/collection_scope.py`，不在脚本中复制名单。

## 标准入口

| 入口 | 用途 |
| --- | --- |
| `Sync-History.cmd` | 客户端登录后增量采集，按match_key去重并补关联 |
| `Update-Battlebook.cmd` | 顺序采集和构建，任一步失败即停止 |
| `Workflow.cmd prepare --files <文件>` | 基于现有库执行完整验收与构建 |
| `Team.cmd download` | 在开发副本安装匹配数据包 |
| `Team.cmd pack` / `publish` | 在发布机制作、分发一致快照 |

采集取得sync锁，构建取得release锁；不得并发直跑底层脚本或手删锁。库、路径或身份不匹配时失败，不创建替代空库或静默回退。停采不会删除历史对局。

## 取数方式

对局明细有两个等价入口：单场 `/v3/product/lol/matchId/{id}/infoType/summary`，分页 `/v1/products/lol/player/{puuid}/SUMMARY?startIndex&count&tag`。分页响应里每项为 `{"metadata","json"}`，`json` 与单场接口同构，因此两者走同一套 `normalize` 校验。

采集器先用分页、失败或未覆盖再逐场补：队列通常落在第 0 页，N 场新对局就是 1 次请求而不是 N 次。页序等于列表序（新到旧，仍是约 1000 条的窗口），所以窗口外的 ID 必须退回逐场，不要继续翻页。规则在 `app/batch_fetch.py`，两种入口的路径与解析在 `app/core.py`（`summary_page_path`/`parse_summary_page`）。

分页并发时上游可能整体 503（`Connection retries limit exceeded`），这不是路由不存在：降级为逐场并随后重试即可，不要据此认定接口不可用。单页 `count` 默认 50（约 5.4 MB），上限 100（约 10.8 MB），响应读取上限 16 MB。

## 构建与恢复

构建链为完整快照、十人明细、评分、注入、回顾/周报、成就、分片、数据门禁及前端。`work/build/snapshot.full.json` 是完整输入，`public/api/snapshot.json` 是网页摘要，二者不可互相替代。所有玩家保留完整已收录历史。

恢复前停止写入，校验ZIP成员哈希、SQLite完整性和外键，同时恢复匹配的身份配置、基准与标尺。正常恢复目标仍是唯一运行库。网站回滚通过原发布目录和原应用执行，详见[维护指南](MAINTENANCE.md)。

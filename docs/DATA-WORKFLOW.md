# 数据库与长期维护流程

2026-10-24按用户要求完成单库收敛。当前发布结果见根STATUS，发布执行看根WORKBUDDY-HANDOFF.txt。

## 唯一数据库

运行库只有 `data/mayhem.sqlite`。采集、玩家档案、基础导出、十人战报、海斗分、回顾、成就、补缺及常用诊断都从这里读取或写入。路径集中在 `app/project_paths.py`；不在聊天目录再创建副本。

原试点库与原910局兼容库均已退出运行依赖，迁移原件已在当前恢复包验证后按用户要求删除，历史目录仅留校验记录。迁移后保留8209局、82090参战记录、43账号、13840账号对局关联，全部27个展示玩家指向同一库。按用户随后要求，逐分钟时间轴/帧/事件及其原始载荷已从运行库移除，其旧迁移备份也已退役删除；不影响正常对局日期、开局时间、时长和跨夜回顾。备份不是第二套现役库。

`.sqlite-wal`和`.sqlite-shm`是同一SQLite的配套文件，不是另外两份库，不手动删除。运行库可能随采集增长，文中的数字只是迁移核验值。

## 配置与身份

- `app/project_paths.py`：数据库、前端、采集脚本位置、构建和发布目录的统一定义。位置均从项目根推导，不依赖当前工作目录或某位助手的聊天路径。
- `data/public-profiles.json`：稳定公开id与本机精确身份映射；每行database为mayhem.sqlite。
- `data/collection.json`：client_profile指定预期登录客户端，primary_profile指定主要采集视角，default_profile指定基础视图。配置的id来自上述名单，不在采集代码里写死朋友名字或PUUID。
- `data/haido-baseline-v4.json`：原历史基准分及其旧标尺，文件保持冻结，不是缓存。
- `data/haido-weekly-calibration-v04.json`：v0.4表现权重配套的独立冻结周分标尺，2026-10-26由用户明确授权校准；不改每人原基准。也必须备份，正式构建缺失或权重失配时停止。恢复现版评分时还需恢复`backups/rating-4.8-weekly-calibration.zip`中的此文件，不能只恢复旧database.zip就声称现版评分状态完整。
- 新环境的配置格式见 `examples/`；真实本机配置留在data，不把个人数据当开源示例。

采集客户端、采集对象和展示玩家分别通过明确的稳定id选取；新增登记不切换全局活跃账号，目标采集器以显式account_key读取，导出基础视图也显式绑定身份，不靠active_account碰运气。

**`accounts` 里 `game_name`/`tag_line` 为空的行不等于测试残留。** 判据在 `participants.payload`：该 puuid 在已存对局里带有多个一致（多局相同）的 game_name+tag_line，就是真实玩家。空名行的来源是 `work/gopher-pilot-20261021/scripts/fetch_deep_matches.py` 入库时按 `INSERT INTO accounts VALUES(key,'HN1',puuid,'','') ON CONFLICT DO NOTHING` 留下的占位行，之后永不回填（`DO NOTHING` 挡住后续 upsert）。恢复用 `work/gopher-pilot-20261021/scripts/register_cached_player.py --puuid <puuid>`：身份只从 payload 取，多局不一致拒绝、缺名拒绝猜，不切换 `active_account`，重复执行幂等。只有 payload 里也取不到名字的才按测试残留处理。

2026-10-26 20:38 曾有 7 个真实玩家（糖醋排骨糖醋鱼290局、重案组之星周星星220、天高有佛以月点灯117、藤讯猎麻人46、Lucifer28、一口奶泡26、Blue丨中单杀神24）因空名被当成 10-23 测试残留删除，43→35；同日晚按上述判据恢复，账号 42 且全部有昵称，删除前整行导出在 `backups/test-residue-20261026/removed-rows.json`。

**采集范围可以小于展示名单，两份名单各管一件事。** `data/public-profiles.json` 决定页面上有谁；`data/collection-exclusions.json` 决定还去拉谁的战绩。2026-10-27 按用户要求排除 6 个不上站账号（月見琥珀 432 局、糖醋排骨糖醋鱼 303、东少D昊天i 330、重案组之星周星星 220、天高有佛以月点灯 117、Zzz1 95），`list_teammates_pilot.py --registered-only` 刷列表和 `sync_new_matches.py` 建队列都不再包含他们，日常采集 43→37，正好与公开名单一致。已入库对局、account_matches 归属和 discovered 行一律保留不动；这 6 人若出现在新对局里，仍会经由其他玩家的视角和 `fix_all_attribution.py` 进库，只是没人再单独走他们的视角。把条目移出该 JSON 即恢复采集。读取逻辑唯一实现在 `app/collection_scope.py`，不要在采集脚本里另写一份名单或硬编码昵称。

## 唯一日常链

| 步骤 | 入口 | 结果 |
| --- | --- | --- |
| 拉战绩 | `Sync-History.cmd`，需要LOL客户端登录 | 增量写入唯一库，按match_key去重、复用已保存响应并补关联 |
| 计算与构建 | `Update-Public-Site.cmd` | 完整快照→十人表现→海斗分4.0→回顾/成就→分片→全部门禁→前端 |
| 同步发布文件 | 上一步内的--sync | 完整目录同步至outputs/public-site-20261022b，并逐文件校验SHA256 |
| 托管上线 | WorkBuddy发布原应用wbapp_l4kVV2RXXtLHGRDJ1XMUhL | 保留原域名/sharecode；发布回执和线上回读后才算上线 |

`Update-Battlebook.cmd`串联采集和构建。采集非零即停止，不把部分完成冒充成功。若明确要用已保存数据发布，可独立构建，并说明仍有的采集缺口。

没有新战绩时无需采集；可直接用已有库构建。项目没有新增定时采集/定时部署服务。浏览器版本检查只刷新已发布结果，不会启动本机采集。已发现的旧public_site.py --watch进程已停止，旧上传配置已随迁移转入备份，不恢复旧GPT上传链。

## 防错与验证

- 标准采集和构建开始前只读核对配置、身份及唯一库；旧试点路径重现数据库、配置指向另一库、库缺失或身份缺失都会停止。缺库不静默回退。Store拒绝再从已退役路径创建空库。
- 标准同步持有sync.lock，构建必须拿到release.lock；重复运行直接拒绝，崩溃后由操作系统释放，不靠手删锁文件解锁。
- 采集中较早的停止事件不再被最后的普通汇总覆盖；账号失败、未完成、归属修复和名册失败均反映在退出码。限流/认证停止后不继续下一个账号。
- 同步检查核对所有文件SHA256，同大小同时间但内容不同也会失败；相同build_id不代表前端版本相同。
- 静态站只读取白名单JSON，不直接连接数据库；正式网站复制的回顾链接使用正式域名。周一切周后需重新构建发布，才对外显示新周分。

保护覆盖标准入口；任意外部程序不遵守项目约定仍可能直接改库，不能保证“任何对话都绝不会弄错”。其他对话应先读项目索引、AGENTS和STATUS，使用正式入口，不直跑历史实验或并发底层采集。

## 迁移、恢复与开源

`scripts/consolidate_database.py`默认只读预览，--apply才迁移；现已完成，重复执行返回already_single_database，不再重新合并。旧merge_databases.py只是兼容入口。迁移使用SQLite backup构造候选、按主键保留新库并补旧库缺失行、合并时间轴和日志，校验完整性/外键/全部身份后再切换。原迁移哈希保留在历史manifest中，相关旧原件已删除；当前可用恢复包为restore-point/database.zip。

运行库已清理64场旧时间轴、1245帧、59635事件与64份原始时间轴载荷，并VACUUM回收282.10MiB；现在这些表为空。普通补缺默认只拉摘要，正式项目拒绝时间轴采集，避免旧流程再次填回。空表及旧诊断函数只保留格式/测试兼容，不纳入网站或日常链。

恢复必须在停止写入并持有流程锁后进行。不要把两库备份各自恢复成两套现役库；旧迁移原件及前置源码ZIP已退役，正常恢复使用当前database.zip内的库、配置与源码快照，不按旧路径重建两套库。当前代码的正常数据恢复目标永远是data/mayhem.sqlite。

194项Python测试通过，含临时库迁移、幂等、旧数据/设置/身份/基准保留、失败退出、锁冲突与内容冲突；没有用真实网络采集测试。完整单库生产构建253.481秒通过，全部27玩家完整对局/英雄/报告/评分逐项一致，最终版本82595f7b68cf43b58f3e991d7c35568a；详见STATUS。

未来开源前应按OPEN-SOURCE-PREP.md建立不含真实数据库/身份配置/凭据的干净发布版本；本次没有推送公开仓库。

## 备份保留目标与当前限制

当前恢复包为backups/restore-point/database.zip，包含唯一主库及必要配置/冻结基准/源码快照；已验证SQLite完整性、外键、ZIP CRC与解压流SHA256。网站回滚包仍为backups/maintenance-20261024-v4/release-lpv11-before.zip。长期只保留这两类各一个有效点，不为每次无变化构建另建整库副本。

16项旧备份已在用户再次明确授权后完成删除，释放4804181510字节（4.80GB/4.47GiB）；清单与结果在restore-point/records。此前自动审批拒绝是历史尝试，当前结果为complete。前次853.68MiB旧生成物是另一份尚未执行清单，不能混写为本次清理结果。

本轮剩余旧构建/暂存已重新核实六处76472文件/996620497字节，详细保留项、清单和结果见根STATUS及backups/restore-point/records/build-cleanup-*.json。用户再次明确要求后，复核并重试仍被执行策略在启动前拒绝（blocked by policy），实际删除0，六处全部保留；本机日志未找到具体规则，此前“自动审批”归因未获证实；用户授权已明确，不重复索要确认或换方式绕过。清理状态不能与已完成的16项旧备份混写。

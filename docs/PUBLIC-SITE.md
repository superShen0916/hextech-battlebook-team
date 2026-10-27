# 当前站点与发布

唯一日常更新地址：<https://hextech-battlebook.app.workbuddy.host/?sharecode=7ZFAIH5YHV>。WorkBuddy应用`wbapp_l4kVV2RXXtLHGRDJ1XMUhL`，发布目录`outputs/public-site-20261022b`。

GPT Sites曾部署历史版本，该版本保留、不更新；旧备用v6应用也不作为当前目标。不能将两个平台的发布状态混为一谈。

## 工作流

人工修改的统一入口见 [WORKFLOW](WORKFLOW.md)：`Workflow.cmd prepare --files <本次文件...>` 完成增量构建、浏览器验收和同步；`ready` 复核同一产物；原应用真实托管后用 `online` 验证入口/资源/代表数据哈希及交互。`check_state.py` 允许明确记录的“已同步未托管”状态，不要求待发布版本等于线上旧版本。

唯一前端`work/players-preview-20261022` → `scripts/build_release.py --data-only --sync` → 校验通过并同步原目录 → **在WorkBuddy对原应用发布**。构建和目录同步与托管分开执行；原应用发布能力可用时对该应用发布。每次都读取当次manifest、真实发布回执及线上版本，不能将本机构建结果视作线上状态。当前状态见根STATUS，接续见根WORKBUDDY-HANDOFF.txt。

快照、完整分片、明细、回顾、成就由已有库生成，访客不能操作本机采集。浏览器每分钟检查小型manifest，版本变化后再加载摘要；这不等于采集或自动部署。夜间automation与执行状态见STATUS；脚本同步目录后仍由WorkBuddy托管发布并验收。

标准构建还生成带 build_id 与统计截止时刻的 api/weekly.json，供大厅前三领奖台、完整涨分榜与可切换周报使用。回顾梗卡和全站皮肤/BGM口径见 [WEEKLY-EXPERIENCE](WEEKLY-EXPERIENCE.md)；音乐是主动开启的第三方官方播放器，不属于首屏必需资源。

## 旧链已停止使用

Public-Site.cmd已指向WorkBuddy；Update-Public-Site.cmd默认使用保留全部校验的数据增量更新（完整重建另见Rebuild-Public-Site.cmd）。旧`app/public_site.py`保留公开投影与兼容测试；2026-10-24单库迁移时已停止旧watch进程，旧上传配置转入迁移备份。不运行watch，不恢复旧GPT自动上传。旧长超时上传脚本已移除。

开发入口、完整数据链、校验、备份恢复和维护记录见[MAINTENANCE](MAINTENANCE.md)、根[STATUS](../STATUS.md)。手机视口检查只代表布局，线上访问要记录是否使用代理；Cloudflare/托管平台拦截与应用错误分开判断。

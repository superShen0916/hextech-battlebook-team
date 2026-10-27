# 网站部署

正式网站：[海克斯战报馆](https://hextech-battlebook.app.workbuddy.host/?sharecode=7ZFAIH5YHV)。发布机使用原WorkBuddy应用和 `outputs/public-site-20261022b`，项目绑定目录及域名保持稳定。

唯一前端 `work/players-preview-20261022` 由 `scripts/build_release.py` 构建。`Workflow.cmd prepare` 执行验收并同步发布目录，`ready` 复核同一产物，WorkBuddy实际托管后由 `online` 验证线上入口、资源、数据哈希及交互。构建成功、目录同步和托管上线是三个不同阶段。

网站只读取公开JSON和静态资源。完整个人档案、十人明细及版本情报按需加载；小型manifest用于检查数据版本，不负责采集、构建或部署。周报和回顾由同一构建链生成，不能只更新摘要。

正式发布流程见[TEAM-PUBLISHING](TEAM-PUBLISHING.md)，构建与验收见[WORKFLOW](WORKFLOW.md)。开发者使用本地预览，不自行替换正式应用或发布到GitHub Pages。

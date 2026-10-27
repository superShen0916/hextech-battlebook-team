# 发布机维护手册

团队安装、本地运行和下载数据见TEAM-GUIDE；PR、发布接续和夜间上传见TEAM-PUBLISHING。本文只补充原发布机的恢复与日常维护。

## 当前入口

- 项目根与WorkBuddy应用绑定目录保持原位置，唯一库data/mayhem.sqlite。
- Sync-History.cmd：客户端登录时增量采集37个跟踪账号；名单和人数从当前配置读取，不在代码写死。
- Update-Public-Site.cmd：同一完整链的增量构建和发布目录同步；Rebuild-Public-Site.cmd强制全量。
- 修改验收统一Workflow.cmd plan/prepare/ready/online，不另编平行验收脚本。
- Team.cmd pack/publish：完整团队数据包和GitHub Release分发。发布机拒绝download/install覆盖自身数据。

## 数据和缓存

数据库、名单/身份、排除规则、冻结基准及标尺是持久数据，不是缓存。work/build/snapshot.full.json为完整输入；public/api/snapshot.json只是摘要，不能反向替代。旧逐帧数据已停采，不恢复到日常库。

work/build/cache为可重建计算缓存，丢失只会使构建变慢。现役dist、固定candidate、dist-previous三个槽位是正式构建机制，不能当旧历史清掉。数据、前端、验收指纹职责在ARCHITECTURE.md，正式同步核对完整文件清单和SHA256。

## 恢复点与清理

当前主库/配置/源码包：backups/restore-point/database.zip；网站回滚：同目录website.zip；清单manifest.json记录SHA256、SQLite完整性、外键和实际解压恢复测试。

旧Git提交、个人讨论和历史文档只留一份legacy-audit.zip，不随团队仓库或数据Release分发。评分5.1审阅迁移的特定恢复证据rating-5.1-before.zip单独保留。不要删除冻结基准和周标尺。

scripts/team_cleanup.py先生成精确计划，fresh backup通过后才允许apply。删除前逐项确认绝对路径、无链接、内容哈希没变；删除拒绝立即停止并记录，不改保护开关或换工具绕过。实际清单及字节数见backups/restore-point/records/team-cleanup.json。

恢复主库时停止所有写入，先解压到临时目录、核对成员SHA256、运行PRAGMA integrity_check和foreign_key_check，再在维护窗口替换data/mayhem.sqlite及匹配配置。不要覆盖打开中的WAL数据库。website.zip只能通过固定发布目录和原应用恢复上线，不能将文件解压到未知目录后新建站点。

## 状态与验证

发布机状态只维护STATUS卡片，CHANGELOG只写客观技术行为及验证证据，不保留个人聊天和分数偏好。结束前Run-Python.cmd scripts/check_state.py，涉及正式发布加--online。

团队副本使用config/workspace.json标记collaborator，check_state核对已安装数据与冻结基准，不伪造本机恢复包或网站发布状态。

本机与线上是两个状态。无托管工具时如实写“已构建/已同步未托管”，保留原站；不得使用Sites插件另建一个正式网站。当前应用与网址见STATUS和TEAM-PUBLISHING。

# 团队维护与正式发布

代码放GitHub公开仓库，完整开发数据以Release数据包分发，正式网页继续由原WorkBuddy应用托管。**GitHub合并、Release上传、本机构建成功，都不等于网站已发布。**不启用GitHub Pages，不迁移原域名或另建应用。

## 成员提交修改

各自在自己的电脑修改并运行 `Workflow.cmd prepare --files <本次文件>`，通过PR合并到main。发布者审阅代码、评分变化和验证结果。成员不需要取得WorkBuddy发布凭据。

## 发布机接收已合并代码

正式发布机使用绑定的项目目录和 `outputs/public-site-20261022b`，唯一运行库为 `data/mayhem.sqlite`。发布机工作区按明确的main提交审阅并接收源码，只更新已审阅文件，保留本机配置、数据库、基准和应用绑定。不要用reset或数据包覆盖发布机状态。

不得用同事的旧数据包覆盖发布机数据库，不能把源码仓库的示例配置覆盖真实配置。发布机不自动拉取开发分支或未经审阅的修改。

## 现有正式流程（发布机 / PowerShell）

```powershell
.\Workflow.cmd plan --files <本次文件>
.\Workflow.cmd prepare --files <本次文件>
.\Workflow.cmd ready --files <本次文件>
# 在WorkBuddy发布原应用 wbapp_l4kVV2RXXtLHGRDJ1XMUhL
.\Workflow.cmd online --files <本次文件>
.\Run-Python.cmd scripts/nightly.py --mark-published
.\Run-Python.cmd scripts/check_state.py --online
```

ready必须对应同一份已验收源码、数据和完整产物；托管后online核对原站资源及真实交互，之后才记已发布。失败保留原站，报告失败阶段，不能凭数据build_id判断完整网站已经更新。当前链接：https://hextech-battlebook.app.workbuddy.host/?sharecode=7ZFAIH5YHV 。

## 更新团队数据包

发布机在数据库与构建一致且无人采集/构建时执行：

```powershell
.\Team.cmd pack
.\Team.cmd publish
```

pack通过SQLite backup取得一致快照，同时持有现有sync/release锁；校验SQLite完整性与外键、逐文件哈希、压缩包后生成 `outputs/team/battlebook-data.zip` 和校验文件。publish检查仓库身份，仅授权原项目仓库公开分发真实游戏数据，其他目标仍必须私有；创建新的带日期Release、上传完整数据包，不把大库写进Git。每个Release对应main的一个提交，并记录数据build_id和数据库局数。

每晚自动上传由发布机私有 `config/team.local.json` 控制，格式见examples。`upload_after_nightly=true` 时，仅客户端在线、采集与构建均成功才尝试上传；无新构建身份且上次已上传时跳过。上传失败留下失败报告，下次可手动publish重试；不把它误报成网站托管失败。电脑关机、离线或客户端未登录时不会产生新战绩包。原定时任务继续使用当前入口，不新增第二个夜间调度器。

`Team.cmd publish` 需要该电脑已安装并登录gh且对仓库有写入权限，凭据留在本机。数据Release不会让WorkBuddy网站自动更新，托管仍由现有发布能力执行。

## 计划中的发布自动化接口

发布机器人尚未接入，当前由发布维护者按上述流程人工执行。后续实现的机器人应只接受授权成员的发布请求，选择已合并main提交，串行执行接收源码→prepare→ready→原应用托管→online→回执；与夜间链共用现有锁。回复代码提交、数据时间、版本、网址和失败阶段。自动化不能绕过代码审阅、流程锁、验收或原应用托管。

## 备份与清理

数据库及冻结状态保留一个最近验证的本地恢复点，网站保留一个可用回滚ZIP；运行日志、恢复资料和本机配置不上传代码仓库或战绩Release。GitHub Release是团队分发渠道，不替代本地恢复备份。

保留最新两个数据Release作为更新和回退；删除旧远端数据前核对新包上传完整、实际下载校验成功。自动上传不自动删远端Release，保留策略由发布维护者执行。

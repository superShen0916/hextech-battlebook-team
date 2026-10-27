# AI开发约定

## 开始工作

阅读 README.md、docs/TEAM-GUIDE.md、docs/ARCHITECTURE.md 以及所改模块规范。修改前检查Git状态，只处理任务范围，不回滚他人改动。提交前说明行为变化和实际验证结果。

## 运行与验证

使用项目根的统一入口：Workflow.cmd plan --files <文件>，修改后prepare；正式发布前ready，托管原WorkBuddy应用后online。Python回归使用Run-Python.cmd -m unittest discover -s tests -q。依赖、Node版本和浏览器检查由现有工具链定义，不另建平行入口。

## 数据边界

唯一前端为work/players-preview-20261022，唯一运行库为data/mayhem.sqlite，路径由app/project_paths.py定义。完整开发数据从原仓库公开Release取得，不把数据库、身份配置、评分生成物、令牌或发布凭据提交Git。开发副本不得覆盖发布机数据或应用绑定。

完整快照与网页摘要分开，禁止摘要覆盖完整输入。不采集逐帧时间轴。采集、构建与同步取得现有锁，不并发直跑底层脚本、不手删锁文件。采集失败不能冒充整链成功。

## 评分与功能

唯一海斗分入口为haido/rating_lp.py，单场表现来源为app/awards.py，完整规则见haido/README.md。所有玩家使用统一规则，不按账号、昵称或目标排名特判。冻结基准与标尺为持久状态，不当缓存删除；修改公式或迁移基准先获得维护者明确授权。

保留完整个人历史、雷达及同类对比、装备与海克斯Top3、评语、队友、荣誉、搜索、十人战报、回顾、分享和成就。性能优化不得静默减少内容或用最近少量对局代替全历史。产品约束见docs/FEATURE-PARITY.md。

## 部署与隐私

正式站继续使用原WorkBuddy应用；本地构建或GitHub Release不代表上线。不创建替代正式站，不推GitHub Pages。发布流程见docs/TEAM-PUBLISHING.md。

打点在开发环境默认关闭，配置只存本机。访客记录、真实设备编号、恢复包和本机配置不入库、不随战绩Release分发；分析访问情况的功能应保留。

## 文档与许可

文档只描述稳定行为、接口、架构、操作与约束，不写聊天摘要、个人评价、本机路径流水、验收记录或任务交接。运行证据放本机输出目录，变更讨论通过Issues和PR完成。同步更新受影响文档与链接。

自有代码与文档采用MIT许可证；第三方游戏素材和数据保留原许可，见THIRD-PARTY-NOTICES.md。

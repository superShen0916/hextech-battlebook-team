# 团队维护约定

先读 README.md、docs/TEAM-GUIDE.md、docs/TEAM-PUBLISHING.md 和 haido/README.md。
源码只有一份，唯一运行库为 data/mayhem.sqlite。真实游戏数据从公开 Release 下载，不提交数据库、身份配置、评分生成物、令牌或发布凭据。
修改使用 Workflow.cmd plan --files <文件>，完成后 prepare；prepare 仅在本机测试构建，不代表网站上线。
正式站由原 WorkBuddy 应用发布；普通成员不要创建替代站或发布 GitHub Pages。发布者必须 ready → 原应用托管 → online。
评分规则对所有玩家一致；不得按账号、昵称或目标排名单独加减分。冻结基准不是缓存，不得删除重建；算法与基准迁移需先经维护者审阅。
保留全部历史、荣誉、雷达、十人战报、回顾和分享功能。禁止时间轴/逐帧采集。
协作检出可以放任意目录；原发布机器项目和发布目录的绝对路径不得改变。
新修改通过分支和 PR 合并。测试使用合成样本或共享数据，讨论算法时使用匿名案例；不把个人聊天讨论写入源码文档。

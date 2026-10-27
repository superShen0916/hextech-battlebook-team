# 一起维护海克斯战报馆

这是朋友间共同维护的项目，仓库公开：克隆、读代码、提 Issue 和 PR 都不需要邀请，完整战绩数据从 Releases 下载。项目自有代码与文档采用 [MIT License](LICENSE)；第三方资产的许可见 `THIRD-PARTY-NOTICES.md`。首次运行见 `docs/TEAM-GUIDE.md`，正式发布见 `docs/TEAM-PUBLISHING.md`。

1. 分支修改，PR合并；只提交源码、测试和维护文档，运行数据通过Release分发。
2. PR写清具体问题、改变的行为和验证结果。页面变化附代表截图；复杂规则补有意义的边界案例。
3. 修改前运行 `Workflow.cmd plan --files <文件>`，完成后运行prepare。pipeline改动加跑Python回归，原数据门禁、TS和7项前端检查不得省略。
4. 评分规则修改必须先经维护者审阅，对所有玩家统一生效；不按账号写分数例外，不凭目标排名修改基准。
5. 保留完整历史、十人战报、全部个人内容、荣誉、雷达、回顾与分享，不为性能静默减少内容。
6. 正式采集和发布仍在发布机执行；不要并发采集、另建站点或把团队测试数据推到原站。

仓库管理员在 GitHub → Settings → Collaborators 邀请朋友的GitHub账号。其他成员无需共享管理员密码、登录令牌或WorkBuddy账号。

PR需要通过仓库质量检查、完整CI和依赖审查；AI建议由维护者确认。依赖更新由Dependabot提交PR，不自动合并。自动化和主分支规范见[自动化规范](docs/AUTOMATION.md)。

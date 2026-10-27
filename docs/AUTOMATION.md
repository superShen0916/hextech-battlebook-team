# 自动检查与代码审阅

自动化负责给出可复验的结果，维护者负责代码审阅和正式发布。任何自动检查都不直接部署WorkBuddy网站、覆盖发布机数据库或迁移冻结基准。

## 持续集成

`CI`工作流在main推送、PR和手动触发时运行：

| 检查 | 内容 |
| --- | --- |
| Repository quality | 文档链接、JSON、源码文件边界、常见凭据格式和Action固定SHA |
| full-check | Windows干净环境安装、公开完整战绩下载、Python回归、TypeScript、七项前端检查、1440/390/320浏览器、完整SHA256同步 |

权限默认为只读。同一PR的新推送取消过期检查；npm缓存按锁文件区分，实际安装仍使用锁定依赖。验证日志作为短期Actions附件保存，不写入参考文档。

本地检查公开检出目录：

```powershell
.\Run-Python.cmd scripts/check_repository.py
.\Workflow.cmd prepare --files <文件>
```

发布机的独立工作区保留运行状态和恢复资料；仓库质量检查针对公开源码检出运行。

## 安全与依赖

CodeQL由GitHub默认配置管理，按语言分析代码，并随PR、默认分支更新及平台计划运行。密钥扫描与推送保护在仓库设置中启用。Dependency review检查PR新增依赖中的高危及严重漏洞。

Dependabot每周检查前端npm、浏览器工具npm和GitHub Actions依赖。兼容的更新分组提交PR，不自动合并。第三方Action使用完整提交SHA并注明版本，由Dependabot维护更新。

## AI评审

CodeRabbit对公开仓库提供免费PR评审。维护者先在GitHub安装CodeRabbit App并仅授权此仓库，安装后自动审阅非草稿PR及后续推送；具体规则见 `.coderabbit.yaml`。无需Copilot付费订阅或在仓库保存模型API密钥。服务的当前免费范围和速率限制以[官方说明](https://www.coderabbit.ai/oss)为准。

安装应用是仓库管理员操作；仅有配置文件不代表服务已经启用。AI关注评分统一性、冻结状态、完整数据、锁与发布门禁、凭据和打点边界。建议不等于测试结论或合并许可；维护者确认问题并解决讨论。不得自动开启付费订阅、超额计费或部署。

`.github/copilot-instructions.md`保留为可选Copilot审阅规范；没有相应订阅时不启用原生Copilot自动请求规则。

## 主分支与贡献

通过分支和PR提交修改，使用Issue与PR模板描述问题、行为和验证。主分支保护要求仓库质量检查及完整测试通过，并解决代码讨论；维护者保留处理紧急情况的权限。CODEOWNERS将项目代码审阅请求交给维护者。

Fork继承源码工作流，但不继承原仓库设置。完整开发数据统一从原公开Release下载；Fork无需接触正式发布凭据。依赖扫描、AI服务和分支规则由各仓库管理员按自身权限配置。

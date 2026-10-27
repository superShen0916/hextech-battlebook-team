# 海克斯战报馆

[![CI](https://github.com/superShen0916/hextech-battlebook-team/actions/workflows/checks.yml/badge.svg)](https://github.com/superShen0916/hextech-battlebook-team/actions/workflows/checks.yml) [![MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

面向《英雄联盟》海克斯大乱斗的战绩分析与对局回顾工具。通过个人档案、英雄数据、十人战报和多人回顾，查看每场对局的表现，追踪长期变化，也留住一起开黑的高光时刻。

[在线体验](https://hextech-battlebook.app.workbuddy.host/?sharecode=7ZFAIH5YHV) · [快速开始](#快速开始) · [开发文档](docs/README.md) · [贡献指南](CONTRIBUTING.md)

## 主要功能

- **个人档案**：完整对局历史、胜率与英雄表现，结合六维雷达、同类对比、装备和海克斯偏好，呈现不同玩家的打法特点。
- **十人战报**：查看双方阵容、装备、海克斯、关键数据及单场表现，回看一局里每个人的发挥。
- **海斗分与周报**：结合胜负、单场表现和多杀奖励，展示长期积分、每周变化与周榜。计算口径见[评分规则](haido/README.md)。
- **队友与多人回顾**：统计同队对局、搭档表现和共同荣誉，按当晚或多人交集整理开黑回顾。
- **成就与分享**：汇集个人成就、荣誉和高光，生成战报与回顾分享图。
- **版本与检索**：查看版本情报，按英雄、日期、队友等条件筛选战绩，支持桌面和手机浏览。

所有统计基于已收录的海克斯大乱斗对局。

## 快速开始

支持的完整开发环境为 Windows。准备 Git、Python 3.10+、Node **22.23.3**（含 npm）、GitHub CLI，以及 Chrome 或 Edge。

在 PowerShell 中运行：

```powershell
gh auth login
git clone https://github.com/superShen0916/hextech-battlebook-team.git
Set-Location hextech-battlebook-team
.\Team.cmd setup
.\Team.cmd download
.\Workflow.cmd prepare --files work/players-preview-20261022/src/App.tsx
.\Start-Dashboard.cmd
```

打开 `http://127.0.0.1:5180/`。首次运行会下载开发数据并完成构建，需要几分钟；后续构建按内容复用。日常开发无需启动游戏客户端或安装 WorkBuddy。

依赖镜像、手动安装数据包及环境配置见[本地开发指南](docs/TEAM-GUIDE.md)。

## 开发数据

源码与战绩数据分开维护。`Team.cmd download` 从 [Releases](https://github.com/superShen0916/hextech-battlebook-team/releases) 获取匹配的数据包，包含运行数据库、名单配置、冻结评分状态、完整快照与页面资源，用于本地运行和验证功能。

更新源码后，可在关闭本地服务和数据库连接的情况下运行：

```powershell
.\Team.cmd download --replace
```

下载与安装会校验数据完整性，并备份被替换的文件。数据版本记录在 `work/build/team-data.json`，详细步骤见[数据下载与更新](docs/TEAM-GUIDE.md#完整数据下载和更新)。

## 参与开发

前端使用 React、TypeScript 和 Vite，统计、采集与构建使用 Python，运行数据存储于 SQLite。

| 路径 | 内容 |
| --- | --- |
| `work/players-preview-20261022/` | 前端页面与交互 |
| `app/` | 统计、存储、个人表现与对局接口 |
| `haido/` | 海斗分计算与评分规范 |
| `scripts/` | 数据处理、构建、校验与同步 |
| `tests/`、`tools/browser/` | 自动化测试与浏览器验收 |

修改前查看检查范围，完成后运行对应验收：

```powershell
.\Workflow.cmd plan --files <修改的文件>
.\Workflow.cmd prepare --files <修改的文件>
```

通过分支和 PR 提交修改。开发约定见[贡献指南](CONTRIBUTING.md)，AI 编程助手先读 [AGENTS.md](AGENTS.md)。架构、自动化检查和正式部署分别见[架构说明](docs/ARCHITECTURE.md)、[自动化规范](docs/AUTOMATION.md)和[发布指南](docs/TEAM-PUBLISHING.md)。

## 许可证

项目自有代码与文档采用 [MIT License](LICENSE)。游戏素材、第三方数据和依赖遵循各自许可，见[第三方说明](THIRD-PARTY-NOTICES.md)。

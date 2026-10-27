> 维护说明（2026-10-23）：本文保留早期阶段的设计/证据，人数、场次、评分版本、“仅预览/未上线”及旧部署命令属于当时状态。当前入口与维护规则以根 README、STATUS、AGENTS 和 docs/MAINTENANCE.md 为准。

# 十人赛后回看（本地预览 v5）

入口仍是高光、成就代表局、双人回忆及历史列表的原战报弹窗。先保留当前玩家原赛后记录，后接完整两队阵容。每位玩家有姓名、英雄、KDA、伤害/占比/承伤与局末海克斯；装备、队友治疗/护盾和金币可展开，海克斯点开原字典，已建档朋友可进个人页。当前1066个不同对局、3388个玩家视角全部匹配。这是赛后数据，不是录像；没有时间线、技能释放轨迹或海克斯实战触发数据。

源码在work/players-preview-20261022：prepare-match-details.py、src/MatchRoster.tsx、src/match-roster.css。脚本读取既有data/raw与试点raw；试点仅缺少松散JSON的固定已收录ID，从SQLite source_payloads以mode=ro+query_only读取已有摘要，不触发采集、不更新数据库、不刷新snapshot。公开独立编号采用既有SHA256前20位，旧mN用时间/时长/英雄/KDA/胜负签名唯一匹配；多候选或缺失会拒绝关联。玩家档案关联仅在本机原身份匹配唯一时生成，绝不凭同名猜人。

输出public/matches/index.json（按档案及旧/新公开对局ID映射到文件与参赛槽位）和m-*.json白名单明细。没有原始账号ID、puuid、区服、游戏编号、完整Riot标签、认证、客户端配置。页面首次点战报才加载索引与那一场JSON，不将所有十人数据塞入首屏快照。前端再次检查日期、时长、英雄/KDA/胜负与10人5+5，避免错局或错视角。加载失败可重试，确无关联显示待补并保留个人部分。

复验（PowerShell，先加载D:\AI-Workspace\dev-env.ps1）：
python prepare-match-details.py
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build
node verify-match-details.mjs
node verify-navigation.mjs
node verify-achievements.mjs
node verify-structure.mjs

固定统计快照未变；WorkBuddy采集完成后的新增局不会自动显示，需要后续明确接入/重新导出。当前仅本地预览，未上线。导航的current共享与32px落点见src/useSectionNavigation.ts；网页截图本轮已恢复并保存outputs。

## v6 MVP/ACE补齐

prepare-match-details.py调用既有app/awards.py纯内存函数，读取既有原始摘要，按固定快照stats_eligible决定是否评奖。不改app/awards.py/生产库/统计快照。每人performance只含version、score、award、team_rank、tied；比赛performance含version、available、reason。前端显示本局名单、各人徽章、并列和展开评分，未知/排除局明确不评。1049可评、16无效局+1零分母不评，3388视角逐条与原snapshot奖项/评分核对通过；11项原评分测试通过。仍工具自评v0.2，非游戏官方MVP。

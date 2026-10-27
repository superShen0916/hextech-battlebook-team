# 访问统计

访问统计与游戏战绩、评分和个人档案分开。实现位于唯一前端的 `lib/analytics.ts`，用于分析页面访问、功能点击和停留情况；统计失败不影响页面功能。

## 本机配置

源码默认关闭打点。需要启用的部署将 `.env.example` 复制为 `.env.local` 并填写：

```dotenv
VITE_ANALYTICS_ENDPOINT=
VITE_ANALYTICS_KEY=
```

配置文件不提交Git；开发者不使用正式站配置发送测试事件。endpoint与publishable key属于前端写入配置，不是账号登录或云库读取凭据。正式站的私有本机配置由发布者维护。

## 事件与访问记录

事件覆盖页面访问、玩家/英雄筛选、十人战报、分享、成就、回顾、评分规则、皮肤、BGM和版本情报等交互。会话汇总包含停留时间及滚动深度。具体事件类型以 `VisitEvent` 定义为准。

浏览器在localStorage生成随机visitor_id，用于同一浏览器的访问去重；存储读取或写入失败时回退为固定值unknown，按vid分组的报表会合并这些事件。它不是实名，但能关联访问行为。云库记录事件、时间、分析对象、来源页面和设备信息。前端仅写入，访客不能读取统计表。

原始访问记录、统计报告和本人设备编号不进入源码仓库或战绩Release。记录保存在部署方自己的云数据库；只有获得读取授权的维护者才能查询。

## 生成报告

在具备WorkBuddy云服务读取授权的发布环境，可运行 `scripts/visits_pull.py` 取数并生成报告。其他环境通过有权访问的云数据库导出相同格式后使用报表脚本；不在源码中保存授权头或令牌。

```powershell
.\Run-Python.cmd scripts/visits_pull.py
.\Run-Python.cmd scripts/visits_report.py --rows work/analytics/visits-YYYY-MM-DD.json --out work/analytics/report.md
.\Run-Python.cmd scripts/visits_report_html.py --rows work/analytics/visits-YYYY-MM-DD.json --out work/analytics/report.html
```

报表默认剔除无头浏览器自测。本人设备名单写入被Git忽略的 `data/analytics-self.json`，格式见 `examples/analytics-self.example.json`；生成HTML或取数时可通过 `--self` 临时指定本人设备。命令和文档示例只使用虚构编号。

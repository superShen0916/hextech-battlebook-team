> 维护说明（2026-10-23）：本文保留早期阶段的设计/证据，人数、场次、评分版本、“仅预览/未上线”及旧部署命令属于当时状态。当前入口与维护规则以根 README、STATUS、AGENTS 和 docs/MAINTENANCE.md 为准。

# 海斗分展示与静态站接入（2026-10-21）

本次已把此前查询的10个账号接入本地看板和原Sites网站源码，另18个账号保留“待查询”。显示名称为“预估海斗分（第三方）”，来源Hexdata，不称官方隐藏分。个人、队友分析展示账号分数、本区约前百分比、查询时间及网站实际显示的计入截止时间；常玩队友榜增加分数列与排序。筛选英雄不改变账号分数，未知不是0。

## 当前文件

- 本地导入数据：`data/hexdata-ratings.json`，被Git忽略，仅保存在本机；键是源玩家稳定身份，不按名字拼接公开结果。
- 原始查询归档：`outputs/海斗分查询_2026-10-21/`，成功10个，待查18个。结果截至2026-10-21，不能称实时查询。
- 数据读取和公开白名单：`app/hexdata.py`；本地接线：`app/main.py`、`app/companions.py`；公开导出：`app/public_site.py`。
- 本地界面：`app/dashboard.html`。
- 本次Sites独立检出：`work/hexdata-display/site/`。为了保留Vody在根`site/`中的未提交静态化改动，本次没有覆盖根`site/app/page.tsx`、`site/next.config.ts`、`site/public/share/index.html`或`site/public/snapshot.json`。
- Sites界面变更补丁：`work/hexdata-display/sites-ui.patch`，仅含`app/page.tsx`和`app/globals.css`；供静态站人工对照或检查后应用，不要把整个Worker项目覆盖到静态站。

## 静态站复用

`scripts/export_public_snapshot.py`仍调用共用的`public_site.load_public_snapshot()`，现在会自动读取本机海斗分文件。Vody在自己的任务中执行原静态导出流程，再把新的字段渲染出来即可。此次未替Vody重新导出或部署静态站。

公开快照的`projection_version`升为3，新增的`rating`位于：

1. `personal.rating`：主号账号分数。
2. `companions[].rating`：该队友账号分数。
3. `companions[].teammates[].rating`：以该队友为中心的搭档榜对应玩家分数。

英雄分组`by_champion`不放账号分数。页面应从当前`subject.rating`读取，不能从英雄过滤后的`focused.rating`读取，也不能通过昵称在浏览器内二次匹配分数。

```json
{
  "status": "estimated",
  "score": 1415,
  "top_percent": 47,
  "queried_at": "2026-10-21T12:23:00+08:00",
  "matches_through": "2026-10-18T16:57:00+08:00",
  "source": "Hexdata",
  "source_url": "https://hexdata.com.cn/matchmaking-position"
}
```

`top_percent`已经是百分数47，直接显示“本区约前47%”，不要再乘100。时间以Asia/Shanghai显示。`matches_through: null`表示网站没显示截止时间，不自行补成查询日期。

状态：`estimated`显示数值；`pending`显示“待查询”；`not_queried`显示“未查询”（含旧快照缺字段时）；`unavailable`显示“暂不可用”。非estimated的数字和时间均为null。按分数升降序排序时，后三种状态都放末尾。

公开字段经过白名单投影，不包含源玩家ID、账号标签、邮箱、验证码、登录Cookie或令牌；静态站只用公开快照，不发布本机海斗分文件和原始查询归档。

## 更新已查分数

下次额度恢复后继续查询，补入原始结果归档，再执行（PowerShell）：

```powershell
.\Run-Python.cmd scripts\import_hexdata_ratings.py --results "outputs\海斗分查询_2026-10-21\海斗分查询.json" --pending "outputs\海斗分查询_2026-10-21\待查询账号.json"
```

导入只读SQLite以确认身份；完整游戏ID必须唯一匹配，找不到或有歧义则失败，不按同名猜测。旧待查名单不会覆盖已查分数。新导入的本机文件更新后，本地API下次读取即可生效；新版Sites监听器会观察该文件变化并更新公开数据，静态站仍需走Vody的导出/构建/发布流程。

## 验证

- Python全套143项通过（含6项新增海斗分验证）；Sites接口9项、TypeScript和生产构建通过。
- 本地正式8766显示本人1415、LliMaozi2265；独立Sites预览切换LliMaozi/卢锡安仍2265，待查账号没有伪造分数。
- 浏览器实测320和390宽无页面横向溢出；队友榜排序升降序正确，待查均末尾。手机视口验证不等于手机真实网络访问通过。
- 生产发布结果与后续操作记录见STATUS.md最新“海斗分展示”小节。


### 2026-10-21 第二批查询数据更新

此前10有分/18待查的查询快照已更新：共查20人，16个有分、4个网站显示暂无评分、8个尚未查询。data/hexdata-ratings.json及本地8766已核验。暂无评分为unavailable，不是0分；原始查询时间保留在私人查询归档的unavailable_players和第二批10人查询.json。此轮仅保存和验证本地数据，没有执行静态站构建/发布或验收公开上传。后续导入有分账号仍可沿用既有命令，待查名单仅含剩余8人；不要把4个暂无评分重新放入pending覆盖状态。详见STATUS.md最新节。


### 2026-10-22 第三批查询完成

原待查8人已全部查询，新增7有分、1暂无评分；累计28个目标为23有分、5暂无评分、0待查。原始时间和计入截止时间见outputs/海斗分查询_2026-10-21/第三批8人查询_2026-10-22.json。data/hexdata-ratings.json和私人汇总已更新，未改网站功能；本地8766真实API对全部8人的状态、分数、百分比及有分账号两项时间核验通过。未验收本轮公开上传，线上状态不作为已完成成果。详见STATUS.md最新节。

### 2026-10-22 第三批后的覆盖与本轮 UI 补充

- 28 个目标全部查询完毕：23 个有分、5 个暂无评分、0 待查，不会再出现旧文档里的「待查询」计数。
- 本轮公开快照实际下发：主号 1415；16 位常玩队友中 13 个有分、3 个暂无评分；队友视角 teammates 71 个有分、1 个暂无评分。
- 常玩队友榜此前只有分数列没有分数排序，本轮已经补上（未查到恒定排在末尾）。

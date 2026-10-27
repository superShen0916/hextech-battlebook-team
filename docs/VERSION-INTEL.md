> 维护说明（2026-10-23）：本文保留早期阶段的设计/证据，人数、场次、评分版本、“仅预览/未上线”及旧部署命令属于当时状态。当前入口与维护规则以根 README、STATUS、AGENTS 和 docs/MAINTENANCE.md 为准。

# 版本情报（2026-10-23，本地预览）

入口：http://127.0.0.1:5180/intel.html 。唯一前端仍是 `work/players-preview-20261022`，新页面是同一Vite构建的第二个入口。大厅和个人页已加入链接；遵守用户“暂不上线”。

## 数据与口径

- 来源：[AramHex](https://github.com/czgreat/aramhex-data)，固定 `data-v7`，CC BY-NC 4.0。署名、非商业；页面保留来源与改编说明。
- 16.21常规：1,085,596有效局，173英雄，223个正式服海克斯；快照2026-10-22 17:33:16+08:00，窗口04:06至17:30（左闭右开），7区已采样记录，不是全服全集。
- 9个仅有PBE参考的海克斯按源meta.provisional_augments标注，整体榜排除，英雄搭配主动开启才显示；不跨服算基准差值。
- 16.20常规单独接入：50,570,166有效局，173英雄，210海克斯。拒绝16.21-pbe过渡目录，不混活动规则。
- 英雄胜率与搭配胜率按wins/games重算。全局海克斯按正式服英雄配对计数求和后相除，不平均百分数。源为局末持有、每人六槽位去重，不是三选一选择事件。差值不证明因果。
- 默认Wilson 95%置信下界排序；来源low_sample保留，支持样本门槛、实际胜率与场数排序。

## 更新

PowerShell（原项目根目录）：

```powershell
.\Run-Python.cmd scripts\sync_version_intel.py
.\Run-Python.cmd scripts\sync_version_intel.py --offline
```

缓存 `work/version-intel-cache`；输出 `work/players-preview-20261022/public/api/version-intel`。脚本校验公开manifest的8个文件SHA256/大小、版本路径、英雄人次/胜场人次、配对边界，再写投影；没有SQLite、SGP或个人snapshot写入。无后台更新任务。运行导入后需重新构建前端；不要声称网页自动更新。

每版本概览约数十KB，每英雄配对拆文件按需加载；16.21概览61,035字节、亚索13,588字节。当前两版349个投影文件共约4.8MB。44,888配对记录中PBE有来源标签。页面切版本/英雄时中止旧请求并校验patch、hero_id与snapshot_at，避免串版本展示。

## 装备来源调研

[Hexdata英雄详情](https://hexdata.com.cn/hero/157-yasuo)、[装备榜](https://hexdata.com.cn/items)公开展示用户所需装备胜率/样本，但研究时标16.20 / 2026-10-12。其方法页允许个人署名引用、整批转载另需许可；meta和单英雄数据端点实测403 data_not_public，已停止此类访问，未绕过。本页仅保留原站链接，不搬其完整数据集。

[aramgg公开API文档](https://data.dtodo.cn/api/v1/zh-CN/docs/cf-data-api.md)与config实测200；业务需Key。文档说明每日200 credits、60次/分钟，原始英雄详情1 credit、展开详情2。后台GitHub授权可能触发Star；本轮未登录或授权、未生成Key。主站26.21标题与API config.gamePatch=16.20存在时间差；装备路径HOWLING_ABYSS_ARAM还需真实授权响应验证是否标准海克斯、同补丁、何种分母及出装顺序。不把普通ARAM/旧版出装冒充4.0。

arammayhem.com开放下载有CC BY 4.0但不含胜率，不能替代。截图识别/玩家个人统计融合仍未实现，不将此次数据接入描述成快速推荐已经完成。

## 验证与范围

- tests/test_version_intel.py：4项边界测试，含PBE不污染、计数加权、分母/版本不符、虚构比例拒绝。
- verify-version-intel.mjs：44,888项配对与全局汇总逐项一致，PBE隔离、快照一致、极小样本排序通过。
- TypeScript、Vite双入口生产构建、verify-structure（原7区/控件保留）通过。
- 真实IAB：换补丁、点英雄、搜索、PBE开关、装备状态、返回17人大厅；320/390无整体横向溢出，截图保存本次对话outputs。仿真不等于实机网络验收。
- 本轮不改WorkBuddy采集、个人SQLite或个人统计快照，不发布线上。预览服务按需前台启动server.mjs；交付含前台启动器，关闭窗口即停。

完整调研结论：`C:/Users/PC/Documents/Codex/2026-10-23/x-x20/outputs/版本统计_调研结论.txt`。

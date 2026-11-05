# 版本情报

版本情报是同一Vite项目的第二入口 `intel.html`，由大厅和个人页进入。它使用独立的公开版本数据，不写入个人SQLite、战绩快照或评分状态。

## 按来源浏览

顶部以独立来源标签分为「AramHex」和「腾讯官方数据」，分别标注社区采样与腾讯接口、可用指标及当前选中状态。下级分类只显示该来源实际支持的内容：AramHex为英雄胜率、海克斯胜率与英雄搭配；腾讯为海克斯分档与装备情报。腾讯海克斯不展示胜率或样本场数，出装胜率单独标注。两种来源的分类选择在本页切换时分别保留，腾讯入口不依赖AramHex数据请求。

链接通过 `source=aramhex|tencent` 和 `tab=heroes|augments|pairs|items` 保存当前来源与分类，可直接打开或刷新。旧 `?tab=items` 链接自动进入腾讯装备；不支持的来源/分类组合回到该来源默认分类。AramHex入口按补丁查看，腾讯入口按来源统计日期查看。

## 数据口径

数据来源为[AramHex](https://github.com/czgreat/aramhex-data)，保留CC BY-NC 4.0许可、署名及改编说明。版本、采样区间、有效局数和来源范围以每份数据的元信息为准，不把已采样记录描述为全服全集。

英雄及搭配胜率按wins/games计算。全局海克斯按正式服配对计数汇总后相除，不平均百分数；局末持有统计不等同于三选一选择事件。差异不证明因果。

PBE参考数据单独标记，默认不进入正式服全局榜，主动开启后才展示相关搭配，不跨服计算基准差值。默认按Wilson 95%置信下界排序，保留来源低样本标记，支持样本门槛、胜率和场数排序。

## 更新与加载

在项目根运行（PowerShell）：

```powershell
.\Run-Python.cmd scripts/sync_version_intel.py
.\Run-Python.cmd scripts/sync_version_intel.py --offline
.\Run-Python.cmd scripts/sync_version_intel.py --equipment-only
.\Run-Python.cmd scripts/sync_version_intel.py --equipment-only --offline
.\Run-Python.cmd scripts/sync_version_intel.py --all
```

缓存位于 `work/version-intel-cache`，投影输出至唯一前端的 `public/api/version-intel`。两种来源的导入都取得现有release锁。AramHex导入验证文件哈希、大小、版本路径、计数和配对边界，之后通过标准构建发布。

`--all` 依次刷新两个来源，单个失败不影响另一个，输出分别带 `aramhex` 与 `equipment` 结果；夜间链路用的就是这一个入口。两个来源都是公开数据，与游戏客户端登录无关，所以夜间任务在客户端未登录时仍会刷新它们，只有内容真的变了才额外构建一份（报告里标 `intel_only_build`）。AramHex 走 GitHub raw，本机 Python 的 TLS 连接对该主机会间歇中断（实测约 1/8 成功），因此下载优先用系统 curl，urllib 仅作回退，取回内容仍要过大小与 SHA256 校验。

每版本概览与每英雄明细分片加载。切换版本或英雄时中止旧请求，并核对patch、hero_id与snapshot_at，避免混用不同版本。

英雄搭配以卡片展示真实持有胜率、胜场、样本数及相对英雄基准的百分点差；支持白银、黄金和棱彩筛选。差值不代表因果；原样本门槛、排序、分页及测试服独立标记保留。卡片图标只引用已存在的本地资源。

## 腾讯海克斯出装

装备情报读取独立的 `public/api/version-intel/tencent-equipment.json` 快照。来源是腾讯的 `https://mlol.qt.qq.com/go/battle_info/odp_proxy/fuwen_hero_rank?championid=<英雄ID>`，接口定位参考 [winer](https://github.com/sunerpy/winer/blob/main/crates/core/src/builds.rs) 的海克斯大乱斗实现；本项目独立解析数据，不引入其运行时或其他LCU连接库。

`scripts/tencent_equipment.py` 负责请求与解析，由原有 `sync_version_intel.py --equipment-only` 调用。按现有英雄目录获取全部英雄，最多3个并发；只查询公共英雄编号，不访问客户端或上传玩家身份。腾讯响应外层字段名不固定，核心/单件装备百分数按万分数转换，鞋子/出门装/完整出装比例原样保留。日期逐英雄保留，不猜测补丁、统计窗口、地区或样本场数；缺失的这些字段保持null，不提供置信区间、样本门槛或跨来源合并排序。组合内装备的排列不表示购买顺序。

完整响应集通过校验后才原子替换单份公开快照；网络错误、日期或比例异常不覆盖上一份有效数据。缓存与离线重建复用原有缓存目录，写入取得现有release锁。前端按来源日期单独呈现，支持英雄查询、单件/核心/鞋子/出门/完整出装切换及使用率/胜率排序；没有本地图标时显示装备名称，不发出失效图片请求。

现有夜间链进入构建分支时尝试刷新出装，再走同一构建器：通常在客户端在线且采集成功后执行，也包括维护者显式使用 `--skip-collect` 的情况；刷新失败记录 `equipment_refresh_failed`，保留旧快照并继续个人战绩构建。常规未登录仍整链跳过，不新增计划任务。超过3天的统计在页面标明距今天数，获取时间与统计日期分别展示。接口未公开更新承诺，不能以最近一次数据日期承诺每日更新。

## 腾讯海克斯分档与使用率

同一接口的 `augment_json_irank` 包含综合列表（`255`）及白银、黄金、棱彩分类列表，记录格式为 `序号|英雄ID|海克斯ID|分类|使用率|S/A/B/C`。它没有胜场、场数或海克斯胜率；原样保存分档与使用率，不把百分数解释为胜率。综合分档与同稀有度分档可能不同，分别保留；筛选稀有度时使用对应分类的分档及序号。稀有度按本来源的分类读取，不用本地字典覆盖。

`--equipment-only` 使用同一批响应同时生成独立的 `tencent-augments.json`，不增加额外网络请求。校验英雄身份、ID、分档、比例及综合/分类列表覆盖关系，两个投影均通过后才写出；每份JSON原子替换。名称、图标和效果说明复用本地字典，效果说明标注字典版本，动态数值以游戏内为准。

英雄搭配由顶部「AramHex」的英雄搭配分类进入；腾讯分档由「腾讯官方数据」的海克斯分档分类进入，两者的日期、筛选、指标及来源分别呈现。腾讯分档标准、统计窗口、地区、段位与样本范围未公开，不与AramHex的胜率或置信区间混算；AramHex默认统计仍为全体已采集样本。

## 来源边界

需要授权或没有公开下载接口的数据集不绕过限制。外部链接不等于已经接入；腾讯出装只展示来源提供的统计参考，不描述为已验证的同补丁、全服或特定活动规则推荐。相关校验由 `tests/test_version_intel.py`、`tests/test_tencent_equipment.py` 和 `verify-version-intel.mjs` 覆盖。

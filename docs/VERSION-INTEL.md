# 版本情报

版本情报是同一Vite项目的第二入口 `intel.html`，由大厅和个人页进入。它使用独立的公开版本数据，不写入个人SQLite、战绩快照或评分状态。

## 数据口径

数据来源为[AramHex](https://github.com/czgreat/aramhex-data)，保留CC BY-NC 4.0许可、署名及改编说明。版本、采样区间、有效局数和来源范围以每份数据的元信息为准，不把已采样记录描述为全服全集。

英雄及搭配胜率按wins/games计算。全局海克斯按正式服配对计数汇总后相除，不平均百分数；局末持有统计不等同于三选一选择事件。差异不证明因果。

PBE参考数据单独标记，默认不进入正式服全局榜，主动开启后才展示相关搭配，不跨服计算基准差值。默认按Wilson 95%置信下界排序，保留来源低样本标记，支持样本门槛、胜率和场数排序。

## 更新与加载

在项目根运行（PowerShell）：

```powershell
.\Run-Python.cmd scripts/sync_version_intel.py
.\Run-Python.cmd scripts/sync_version_intel.py --offline
```

缓存位于 `work/version-intel-cache`，投影输出至唯一前端的 `public/api/version-intel`。导入验证文件哈希、大小、版本路径、计数和配对边界，之后通过标准构建发布。

每版本概览与每英雄明细分片加载。切换版本或英雄时中止旧请求，并核对patch、hero_id与snapshot_at，避免混用不同版本。

## 来源边界

需要授权或没有公开下载接口的数据集不绕过限制。外部链接不等于已经接入；缺少同补丁、同模式和统计分母的数据，不展示为本站装备推荐。相关校验由 `tests/test_version_intel.py` 和 `verify-version-intel.mjs` 覆盖。

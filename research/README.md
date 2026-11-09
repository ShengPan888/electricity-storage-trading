# 研究结果与冻结模型复现

`results.json`是首页和离线页面的统一数值来源。两份`*_aggregate.csv`为真实实验汇总的原样副本；`provenance.json`记录来源运行、SHA256和上游commit。它们不含逐点原始标签、模型权重或合成实验成绩。

## 可运行范围

```bash
python -m pip install -r requirements-research.txt
python run.py reproduce-phase2 --data-dir /path/to/to_sais_new --output outputs/new_phase2_run
```

支持原始解压目录或含`to_sais_new.zip`的目录；ZIP仅提取需要的CSV。该命令复现冻结Phase 2的固定19列、LightGBM/CatBoost规格、训练末14天早停和5/8/11月时间验证，**不重新搜索或重新选择模型**。

输出目录必须不存在；命令不修改原始CSV，不覆盖旧模型或提交文件。输出包括配置、输入文件哈希、软件版本、组件模型、早停记录、每折预测、逐日动作和收益及合并指标。所有新模型仅保存在指定输出目录。

原研究环境在[original_environment.json](original_environment.json)。轻量Demo依赖与原AutoDL环境并不完全相同；版本、平台与浮点实现可能导致不同轮数或数值，不能承诺任意环境逐位相同。请先核对环境、行数、训练边界与来源，再解释偏差。本次公开入口的实际核验记录见[VALIDATION.md](../docs/VALIDATION.md)。

## 数据目录

```text
to_sais_new/
  train/mengxi_boundary_anon_filtered.csv
  train/mengxi_node_price_selected.csv
  test/test_in_feature_ori.csv
```

复现主验证只读取训练边界和标签，不读取测试标签；官方测试本身无标签。气象不进入冻结模型。原始标签中不完整日期的有效点保留给点模型，交易收益只计算完整96点日期。

## 指标对照

冻结研究：8832点、92日，R²=0.4209828261663392，MAE=0.450309459834742，RMSE=0.6556941823728597，日均收益=7021.769959102262，Oracle=10984.231926868759。

原研究总体指标在后续统一评价时从逐点/逐日结果重算，不能把原报告“各折均值”混作合并指标。

Phase 3B、GitHub增量和完整Stayfoool复现的本地实验文件、Trial数据库与权重未整体发布。这里公开其方法、来源哈希和汇总，不宣称这些候选已打包成一条命令可完全复现。

## 第三方与数据许可

本仓库未复制Stayfoool源码；本次GitHub更新发布的是对其方法和已完成本地复现的说明。上游为MIT，固定提交见provenance。官方数据的获取与使用服从比赛要求，本仓库MIT不授予再分发权。

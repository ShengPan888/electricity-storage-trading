# 蒙西电力现货价格预测与储能交易研究

**第四届世界科学智能大赛 · 电力市场交易赛道｜次日96点实时电价 → 储能计划 → 真实价格结算**

[![Tests](https://github.com/ShengPan888/electricity-storage-trading/actions/workflows/tests.yml/badge.svg)](https://github.com/ShengPan888/electricity-storage-trading/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

本项目研究：只知道比赛提供的次日预测边界时，如何提前选择连续两小时充电、两小时放电时窗，提高储能实际套利收益。

已完成数据审计、官方基线、供需特征消融、LightGBM/CatBoost融合、异常检测、Optuna精度/收益优化及同赛道Stayfoool方案完整复现。**当前保留Phase 2融合模型：有候选降低了价格误差，但没有通过收益替换门槛。**

更新2026-11-09。真实实验数字均为**内部开发估计**，非官方隐藏测试成绩。12月已被查看，只作诊断；价格和收益使用赛题处理尺度，不换算人民币或未经确认的物理单位。

## 项目导航

| 想了解什么 | 入口 |
|---|---|
| 从数据到交易的完整思路 | [技术路线与8张流程图](docs/architecture.md) |
| 现在的精度和收益 | [统一评价结果](docs/RESULTS.md) · [精确JSON](research/results.json) |
| 为什么调参后仍保留原模型 | [实验演进与选择](docs/experiment_history.md) |
| 模型到底输入哪些特征 | [19特征模型卡](docs/model_card.md) |
| 如何避免未来信息泄漏 | [数据与信息边界](docs/data_contract.md) |
| 与蒙西实际交易相差什么 | [政策对照](docs/policy_alignment.md) |
| 没有比赛数据怎样运行 | 下方合成Demo与离线研究概览 |

## 1. 完整技术路线

![项目技术路线](docs/assets/project_workflow.svg)

```mermaid
flowchart LR
    A[官方数据与规则] --> B[时间、缺失与信息审计]
    B --> C[官方预测与候选特征]
    C --> D[特征组消融与模型训练]
    D --> E[时间外推与训练侧早停]
    E --> F[次日96点预测]
    F --> G[3321种策略与不交易]
    G --> H[锁定充放电动作]
    H --> I[真实价格结算与Oracle]
    I --> J[跨月收益与误差、Bootstrap]
    J --> K{是否通过替换门槛}
    K -->|通过| L[独立候选与审核]
    K -->|未通过| M[保留Phase 2]
```

预测对象是**次日实时电价**，充放电计划提前制定。历史真实价格在训练时作标签，回测时作结算依据；当前不把真实前15分钟价格作为输入。

## 2. 最新统一结果

共同验证集合：2025年5月、8月、11月，8832个有效点、92个完整日。R²在合并逐点预测上计算；日收益只在96点完整日期计算。所有方案使用相同储能规则与原始真实价格结算。

| 方案 | R² ↑ | MAE ↓ | RMSE ↓ | 日均收益 ↑ | 捕获率 ↑ |
|---|---:|---:|---:|---:|---:|
| **Phase 2冻结：LightGBM＋CatBoost等权融合** | **0.420983** | **0.450309** | **0.655694** | **7021.77** | **63.93%** |
| Phase 3B：Optuna精度导向融合 | 0.441167 | 0.438821 | 0.644164 | 6862.65 | 62.48% |
| 同赛道Stayfoool完整复现，无策略先验 | 0.453506 | 0.406726 | 0.637013 | 6800.53 | 61.91% |
| 高低价事件修正候选 | 0.450439 | 0.432548 | 0.638798 | 6879.66 | 62.63% |

共同Oracle日均收益10984.23，表示事后已知真实价格时的同约束最优合法收益，不能直接交易。

![价格误差与真实收益](docs/assets/accuracy_profit.svg)

**为什么不选R²最高的模型？** 收益由所选两个连续8点窗口的真实价差决定，全天误差下降仍可能选错窗口。完整Stayfoool方案预测更准，但日均收益比冻结模型低约3.15%，没有通过替换门槛。

尖峰仍是短板：训练期P95定义下，主验证有112个高价事件点，上表各方案召回率均为0；没有预测阳性时Precision未定义。[完整结果与限制](docs/RESULTS.md)

## 3. 模型输入与结构

当前模型使用**19列＝7官方预测＋11时间特征＋1候选比例**：

- 官方预测：系统负荷、风光总加、联络线、风电、光伏、水电、非市场化机组。
- 时间：hour、minute、dayofweek、month、slot_id，以及slot/weekday/month各自sin、cos。
- `renewable_ratio_candidate`：风光总加预测/负荷预测，分母近零返回缺失。

```mermaid
flowchart TD
    A[7预测、11时间、1候选比例] --> B[固定19列白名单]
    B --> C[LightGBM L2]
    B --> D[训练侧插补与CatBoost]
    C --> E[50%价格权重]
    D --> F[50%价格权重]
    E --> G[96点融合电价]
    F --> G
    G --> H[合法储能计划]
```

供需差值是待检验候选，未知单位、缩放和联络线方向下，不能认定为官方物理竞价空间。相关性不解释为因果。冻结模型没有未来实际边界、历史价滞后或气象输入。[模型卡](docs/model_card.md)

## 4. 实验演进

```mermaid
flowchart LR
    A[Phase 1 数据审计] --> B[Phase 2 特征与融合]
    B --> C[Phase 2B/2C 分组消融与调参]
    C --> D[Phase 3A 异常与鲁棒预测]
    D --> E[Phase 3B 信息审计与360次Optuna]
    E --> F[GitHub三组增量]
    F --> G[Stayfoool完整复现]
    G --> H[保留Phase 2]
```

Stayfoool上游固定为[10864ce](https://github.com/Stayfoool/electricity-ai4s-2026/tree/10864ce6f88941cad54bac83161800bb503ed1f2)。原作者协议24项公开指标匹配，之后用共同日期、训练侧早停、三种子和统一结算比较。复现成功不等于取得官方排行榜成绩。[演进记录](docs/experiment_history.md)

## 5. 储能优化

每个日期96点，初始SOC=0、容量8000。连续8点充电，动作−1000；之后连续8点放电，动作＋1000；其他为0。每日最多一个完整循环，也可不交易。

- 充电起点 `0≤tc≤80`；放电起点 `tc+8≤td≤88`。
- 合法组合 `81+80+…+1=3321`，另加不交易。
- 最优预测收益不为正时不交易；真实收益严格按 `Profit=sum(P×E)`。
- 不额外乘0.25，不擅自加入效率、费用或衰减。

[优化器](src/storage_trading/core.py)检查SOC、连续性、先充后放、边界和单循环。真实设备效率、可用容量、调节速率、禁限时段、调度校核及完整结算**尚未实现**。[政策边界](docs/policy_alignment.md)

## 6. 运行Demo与复现

### A. 无数据：合成策略Demo

Python≥3.10，无第三方依赖：

```bash
git clone https://github.com/ShengPan888/electricity-storage-trading.git
cd electricity-storage-trading
python run.py demo
python run.py test
```

打开 `outputs/demo/report.html` 查看价格、动作和SOC。合成曲线只演示规则，不是训练结果或比赛成绩。

### B. 无数据：最新研究概览

```bash
python run.py research-report --output outputs/research
```

打开 `outputs/research/index.html` 离线浏览真实汇总、路线图和候选对照。该命令读取公开汇总，**不重训模型、不捏造结果**。

### C. 持有官方数据：复现冻结Phase 2规格

```bash
python -m pip install -r requirements-research.txt
python run.py reproduce-phase2 --data-dir /path/to/to_sais_new --output outputs/phase2_new_run
```

输入目录含`train/mengxi_boundary_anon_filtered.csv`及`train/mengxi_node_price_selected.csv`，也支持本地官方ZIP。[配置](configs/phase2_frozen.json)固定19列、参数、内层14天早停及5/8/11月验证。保存版本、输入哈希、模型、预测、动作和收益；拒绝覆盖已有运行。[详细说明](research/README.md)

旧`real-demo`仍提供11特征单LightGBM教学版与逐日交互页面，**不是上述最新融合模型**：

```bash
python -m pip install -r requirements-model.txt
python run.py real-demo --data-dir /path/to/to_sais_new --output outputs/legacy_real_demo
```

已有预测可用`backtest --predictions ...`作真实价格结算，或`submit --predictions ...`只读预测生成动作，见[数据契约](docs/data_contract.md)。

## 7. 仓库结构

```text
configs/phase2_frozen.json       冻结参数与时间划分
src/storage_trading/
  core.py                       3321组合、SOC与结算
  research.py                   最新19特征融合复现
  research_report.py            公开研究结果离线页面
  pipeline.py                   早期11特征教学流水线
  cli.py                        Demo、回测与策略导出
research/                       汇总结果、来源哈希和原环境
scripts/render_research_assets.py 图示生成与公开记录检查
docs/architecture.md            项目全逻辑与8张路线图
docs/RESULTS.md                 最新指标与统计限制
docs/model_card.md              特征、训练、推理契约
docs/policy_alignment.md        政策与实盘差距
docs/history/2026-10-28/         旧文档存档
tests/                          储能规则与信息边界核验
```

## 8. 下一步与公开边界

- [x] 官方基线、特征组消融、模型/策略对照与真实标签结算。
- [x] 信息边界审计、规范调参、完整同赛道复现。
- [x] 冻结模型保留，未通过门槛的尝试可追溯。
- [ ] 取得真正未参与选择的新时间区间，检验跨季节与跨年份表现。
- [ ] 在可证明的发布时间下研究NWP及历史状态增量。
- [ ] 改善高价事件与8点窗口排序，研究收益导向预测。
- [ ] 接入设备参数、禁限时段、调度反馈和适用结算。

原始比赛数据、真实逐点标签/预测、模型权重和完整本地实验目录不公开。MIT覆盖本仓库代码，不授予官方数据再分发权。本项目是竞赛研究与回测Demo，不是已认证实盘系统。

# 蒙西电力现货储能交易实验

[![Tests](https://github.com/ShengPan888/electricity-storage-trading/actions/workflows/tests.yml/badge.svg)](https://github.com/ShengPan888/electricity-storage-trading/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

目标：用可复现的代码，把“供需数据 → 次日电价预测 → 储能充放电计划 → 真实电价结算 → 单日复盘”完整做出来。

当前已接入官方本地数据，完成 LightGBM 训练、2025 年 10—11 月开发回测、12 月留出评估和 2026 年 1—2 月测试策略生成。包含单日价格、充放电、SOC 与收益的交互式本地页面。尚未进行官方榜单评测，也未核实官方容器运行结果。

本仓库公开代码、配置、合成样例和汇总研究结果。官方原始数据、训练模型、真实逐点预测及本地真实数据页面不随仓库发布。没有官方数据也可以先运行下面的合成演示。

```shell
git clone https://github.com/ShengPan888/electricity-storage-trading.git
cd electricity-storage-trading
python run.py demo
```

打开生成的 `outputs/demo/report.html`。公开样例的来源与运行方式见 [examples/README.md](examples/README.md)。

## 运行真实数据 demo

在项目目录运行：

```powershell
python -m pip install -r requirements-model.txt
python run.py real-demo --data-dir D:\saitidata --output outputs\real_demo
```

打开 `outputs/real_demo/index.html` 即可交互查看；不依赖互联网。也可以在本机启动预览：

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory outputs\real_demo
```

然后访问 `http://127.0.0.1:8765/`。双击根目录的 `打开真实数据演示.bat` 也会打开本地页面。

输入支持官方压缩包所在目录，或者已解压的 `to_sais_new` 数据根目录。只需要读取三个 CSV；程序不会展开整个气象目录，也不会改动原始压缩包。若只有压缩包，三个 CSV 解压到输入目录下的 `extracted/`。

### 当前实验结果（2026-10-28）

收益使用赛题处理后的数值单位，不代表人民币。日期为完整自然日，包含不交易日；无测试真值，因此不报告测试收益。

| 方法 | 10—11 月开发期日均收益（61天） | 12月留出日均收益（31天） |
|---|---:|---:|
| 官方特征 LightGBM（时间验证适配） | 7270.47 | 5972.90 |
| 加入供需与日内形状特征 | 6905.12 | 未进入最终评估 |
| 训练期价格形状确定的固定时窗 | 6147.49 | 5727.81 |
| 不交易 | 0.00 | 0.00 |

候选方法只按10—11月真实日均收益选择，然后冻结并评估12月。供需特征候选的开发期 MAE 更低（0.5033 vs 0.5189），但交易收益更低，因此保留官方特征基线。12月仍有2个亏损日，最差日收益为 -11244.30；不声称稳定无亏损。

测试输出 `outputs/real_demo/submission/output.csv` 共5664行、59个完整日期，已核对官方示例的列名/时间戳并逐日检查储能约束。它是当前模型的待评测策略，不能据此推断比赛成绩。

更多内容见 [数据与验证说明](docs/data_contract.md) 和 [实验结果](docs/RESULTS.md)。

## 不需要官方数据的合成演示

需要 Python 3.10 或以上。合成演示只用 Python 标准库，无需安装第三方包。在本目录运行：

```powershell
python run.py test
python run.py demo
```

规则测试使用标准库；真实数据管线的附加测试需要 `requirements-model.txt`，未安装时会明确跳过。当前安装环境中15项测试通过。

打开 `outputs/demo/report.html`，可以看到：

- 预测与真实价格曲线（此处两者均为人为构造的示例）。
- 充放电动作：负数充电，正数放电。
- 每时段操作后的 SOC，初始为 0。
- 预测收益、实际结算收益和事后最优收益。

`outputs/demo/output.csv` 采用官方列名 `times,实时价格,power`。这只是合成演示文件，不应提交比赛；真实测试输出在 `outputs/real_demo/submission/output.csv`。

## 已实现的规则

- 每个北京时间自然日 96 个 15 分钟时段。
- 初始 SOC=0，容量 8000。
- 充电每时段 -1000，放电 +1000。
- 充放电各连续 8 点，先充后放，不重叠，每天最多一个完整循环。
- 充电起点 0–80；放电起点不早于充电起点+8，且不晚于88。
- 精确比较 3321 个合法组合和不交易，预测收益不大于零时不交易。
- 按赛题 `sum(价格 × power)` 结算，不额外乘 0.25，不自行增加效率损耗、费用或衰减。

## 后续模型的接口

预测模型应输出一个中间 CSV：

```csv
times,pred_price,true_price
2026-01-01 00:00:00,100,105
```

上面只展示字段，真实文件每天必须有完整的 96 行。`true_price` 仅在离线评估时提供。`times` 为无时区后缀的北京时间，必须按时间严格递增。

```powershell
python run.py backtest --predictions path/to/validation_predictions.csv --output outputs/validation
python run.py submit --predictions path/to/test_predictions.csv --output outputs/submission
```

`submit` 只读取预测价格，不读取真实价格。它生成调度结果，不会训练模型。

评估会生成：

| 文件 | 内容 |
|---|---|
| `output.csv` | 时间、预测电价、充放电动作 |
| `slot_details.csv` | 每时段预测、真值、动作、SOC |
| `daily.csv` | 每天充放电开始时间、收益与事后收益差距 |
| `summary.json` | 日均收益、亏损日比例、最差日等 |
| `report.html` | 可直接打开的曲线和日收益表 |

事后最优收益使用真实价格计算，只用于诊断，不是可以提前获得的策略。使用同一预测、替换真实价格，不得改变充放电动作；测试覆盖这一点。

## 官方 baseline 的适配说明

官方 `lgb_baseline.py` 的策略生成函数为空；提供的 `inference.py` 依赖一个未随这四份资料给出的 `strategy` 模块。我们独立实现调度与校验。

保留官方七项预测边界、hour/minute/dayofweek/month 和主要 LightGBM 参数。不同之处：排除5个标签不完整日期；每轮在评估月之前的一个月选择迭代数，再用此前全部数据重训；采用完整日期和真实交易收益评估。不是原脚本最后20%划分的逐字复现。

未使用未来实际边界或历史价格滞后，避免连续测试期缺少新价格标签的问题。原始预测发布截止时刻未在文件中明确，使用与官方 baseline 相同的输入可用性假设。NC气象尚未纳入首版。

后续工作：更充分的滚动月份评估、分时段模型、气象时间审计，以及 `/saisdata/34/` → `/saisresult/output.csv` 的官方容器适配。本轮12月结果已被查看，后续反复修改不能继续称其为未见数据。

比赛原始数据、模型和输出默认不纳入 Git。气象、历史真值仅按比赛允许的数据来源和可用时刻使用。

## 目录

```text
src/storage_trading/core.py   储能规则、精确调度、结算
src/storage_trading/cli.py    CSV 接口、演示、复盘报告
src/storage_trading/pipeline.py 官方数据审计、时间切分、训练与推理
src/storage_trading/dashboard.html 本地交互页面模板
tests/test_core.py           规则与评估隔离验证
data/raw/                   官方原始数据（不提交 Git）
examples/                   可公开的合成价格样例
docs/RESULTS.md              汇总实验结果与失败分析
docs/learning_path.md        每阶段需要真正理解的问题
outputs/                    本地输出（不提交 Git）
```

## 参考

- 任务定义：用户提供的赛题说明和本地官方 `lgb_baseline.py`、`inference.py`、`output_demo.csv`。
- 同赛题公开工程：[Stayfoool/electricity-ai4s-2026](https://github.com/Stayfoool/electricity-ai4s-2026)。用于研究方案对照；当前调度与结算代码独立实现，没有声称复现其分数。
- 角色式交易原型：[ElectricityTradingAgents](https://github.com/yuhaozhang420/ElectricityTradingAgents)。后续若接入 Agent，要比较有无 Agent 的真实验证收益；不预设其有效。

## 许可证

本项目代码、文档和合成样例采用 [MIT License](LICENSE)。比赛原始数据不属于本仓库发布内容，取得与使用方式以主办方规定为准。

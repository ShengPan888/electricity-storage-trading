"""Render the checked-in guides/demo from curated public JSON definitions."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from storage_trading.research_report import render_report


def load(name):
    return json.loads((ROOT / "research" / name).read_text(encoding="utf-8"))


def feature_table():
    data = load("feature_dictionary.json")
    lines = ["|顺序|模型实际列名|来源 / 公式|作用与含义边界|可用性、单位与检查|", "|---|---|---|---|---|"]
    for r in data["features"]:
        lines.append(f'|{r["order"]}|`{r["name"]}`|{r["formula"]}|{r["meaning"]}|{r["availability"]}；{r["unit"]}；{r["guard"]}|')
    return "\n".join(lines)


def build():
    features = load("feature_dictionary.json")
    rules = load("market_rules.json")
    rows = feature_table()
    excluded = "\n".join(f'|{r["name"]}|{r["use"]}|{r["reason"]}|' for r in features["excluded"])
    body = f'''# 输入特征、标签与信息时点：完整字典

更新2026-11-09。由`research/feature_dictionary.json`生成，列顺序与冻结模型代码测试核对。

## 一眼看清原始输入、训练标签和输出

- 原始CSV输入：`times`＋7项官方预测，共8个原始字段；`times`派生时间，不作为第20列数值特征。
- 模型X：7官方预测＋11时间/周期编码＋1候选比例，共19列；两个模型分别预测，再按50%＋50%融合。
- 训练y：历史节点实时价`A`。验证真实价在动作锁定后结算，不进入当期X。
- 输出：`times,实时价格,power`，预测实时价不是市场报价曲线。
- 范围：当前Phase 2冻结融合、Phase 3B首轮19列；Stayfoool完整结构是17列，不能混称。

## 逐项19列

{rows}

## 哪些没用，哪些只用于训练或事后评价

|字段|当前用途|信息边界|
|---|---|---|
{excluded}

## 从一行原始输入理解变换

教学示例（不是比赛数据）：北京时间2025-08-01 13:15；负荷4、风光1.2、联络线−0.1、风电0.8、光伏0.4、水电0.2、非市场化0.4。得到hour=13、minute=15、dayofweek=4、month=8、slot_id=53，比例=0.3；其余6个周期值按上表计算。

该例不调用预测模型，不代表物理单位、预测价格或真实市场结论。可下载[完整演示HTML](demo/index.html)展开19个示例值。

## 为什么还要核实可得时点

7列由赛题规定提供，因此在竞赛契约下可用；原CSV没有issue_time、修订版本或label_available_at，不能证明实盘申报截止前可获得同一版本。目标时间先后切分也不能自动证明训练标签当时已发布，需按真实决策截止另设gap/embargo。

没有把未知单位解释为MW或元/MWh；候选比例不被认定为已核实的物理新能源占比。相关性和特征重要性不解释为因果。

[模型卡](model_card.md) · [数据契约](data_contract.md) · [行业规则与实现差距](market_rule_guide.md)
'''
    (ROOT / "docs/feature_dictionary.md").write_text(body, encoding="utf-8")
    sources = []
    for r in rules["sources"]:
        sources.append(f'### {r["id"]}｜[{r["title"]}]({r["url"]})\n\n- 状态：{r["status"]}。\n- 范围：{r["scope"]}。\n- 定位：{r["locator"]}。\n- 限制：{r["note"]}。\n')
    matrix = []
    source_urls = {r["id"]: r["url"] for r in rules["sources"]}
    for r in rules["matrix"]:
        refs = "、".join(f'[{k}]({source_urls[k]})' for k in r["sources"])
        matrix.append(f'|{r["id"]} {r["topic"]}|{r["principle"]} {refs}|{r["implementation"]}|{r["status"]}|{r["missing"]}|')
    flow = "\n".join(f'{i+1}. **{r["step"]}**：{r["purpose"]}。当前：{r["status"]}。' for i, r in enumerate(rules["workflow"]))
    formulas = "\n".join(f'### {r["name"]}\n\n`{r["formula"]}`\n\n仍缺：{r["missing"]}。\n' for r in rules["draft_formulas"])
    content = f'''# 电力交易行业规则：文件层级、业务流程与代码差距

核查日期2026-11-09。这里的“规范”是已核查文件的业务要求与软件映射，不是给本项目出具现行合规认证。

## 先明确三种边界

1. **国家框架与蒙西细则**：国家注册、校核、调度、计量、披露框架不替代具体地方参数。项目是蒙西，不混用蒙东规则。
2. **正式文件与征求意见稿**：M1是正式印发通知；M2是2026中长期安排；D1只是2026征求意见稿，不能直接作为生效阈值。
3. **历史研究与真实交易**：2025回测要按当时适用规则理解；2026文件不倒推2025合规。公告施行日期已核，不表示已经穷尽所有后续修改。

## 已核查官方来源

{chr(10).join(sources)}

## 真实业务流程中，本项目做了哪些

{flow}

模型预测不是市场出清；预测价格不是量价申报；单站合法策略不是系统安全校核；提交曲线不保证原样执行；价差收益不等于含所有合约和费用的电站净收益。

## 逐项规则—实现—缺失信息对照

|环节|业务要求与来源|当前实现|状态|缺失输入 / 下一步|
|---|---|---|---|---|
{chr(10).join(matrix)}

## 禁充禁放：只列草案公式，不制造合规判断

D1草案的供需比≤1.03禁充、新能源富裕程度<0禁放等仅用于差距对照；本轮未取得其整体正式生效依据，当前优化器没有增加这些约束。

{formulas}

项目的net_load_candidate、renewable_ratio_candidate都不是这两个定义。缺失火电边界、备用和单位/符号时，不能把未知量填0，也不能显示“满足官方禁限条件”。详细页码见[征求稿专项对照](policy_alignment.md)。

## 真实设备版本必须另建

竞赛保留96点、容量8000、动作±1000、连续8点及`Profit=sum(P×E)`，不增加0.25。真实设备版在确认MW/MWh量纲后，才按时间步长、效率、SOC、可用容量、功率和斜率建模，再读取适用禁限时段、校核和调度反馈。

完整结算需要适用计量点、实际充放电量、合约以及明确适用的费用；不能自行把不明费用加进比赛评分，也不能把比赛套利收益写为实盘净利润。

## 应请从业者核实的证据

- 实际参与主体和申报模式、有效规则清单及实施日。
- 决策截止、预测版本、历史价格标签发布时间。
- 联络线方向、匿名缩放、节点与计量点对应关系。
- 核定设备参数、禁限规则、调度调整与执行记录。
- 对应合约和费用的完整结算单及新时期验证标准。

来源内容仅用于方法与规则说明，不作为模型外部训练数据；这次更新不改变19列、模型权重或储能收益公式。
'''
    (ROOT / "docs/market_rule_guide.md").write_text(content, encoding="utf-8")
    demo = ROOT / "docs/demo"
    demo.mkdir(exist_ok=True)
    (demo / "index.html").write_text(render_report(), encoding="utf-8")
    (demo / "README.md").write_text('''# 可下载的完整演示页面

`index.html`包含完整19特征、交易流程、规则来源、实现差距与最新结果。无需比赛数据和本地服务，下载后双击即可离线使用；外部链接只用于查看官方政策原文。

GitHub文件页展示源码，不会自动运行HTML。请点击文件页的“Download raw file”下载，或克隆仓库后直接打开本文件。当前没有启用GitHub Pages，不把这个文件链接描述成已部署的在线平台。

重建：在仓库根目录运行`python scripts/build_guide_documents.py`，或用`python run.py research-report --output outputs/new_guide`生成独立目录。后者拒绝覆盖已有结果。
''', encoding="utf-8")
    print("Rendered feature dictionary, market-rule guide and downloadable demo")


if __name__ == "__main__":
    build()

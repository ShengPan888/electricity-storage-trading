"""Offline, standard-library view of real published aggregate research results."""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build_report(output: Path) -> Path:
    if output.exists():
        raise FileExistsError("Choose a new directory to preserve previous reports")
    data = json.loads((ROOT / "research/results.json").read_text(encoding="utf-8"))
    workflow = (ROOT / "docs/assets/project_workflow.svg").read_text(encoding="utf-8")
    figure = (ROOT / "docs/assets/accuracy_profit.svg").read_text(encoding="utf-8")
    figure = figure[figure.index("<svg"):]
    rows = []
    for r in data["models"]:
        cls = ' class="selected"' if r["selected"] else ""
        rows.append(f'<tr{cls}><td>{html.escape(r["label"])}</td><td>{r["r2"]:.6f}</td>'
                    f'<td>{r["mae"]:.6f}</td><td>{r["rmse"]:.6f}</td>'
                    f'<td>{r["mean_daily_profit"]:.2f}</td><td>{r["capture"]:.2%}</td></tr>')
    options = "".join(f'<option value="{html.escape(r["id"])}">{html.escape(r["label"])}</option>' for r in data["models"])
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>蒙西储能交易研究 · 最新结果</title><style>
body{margin:0;background:#f3f7fb;color:#19364a;font:16px system-ui,"Microsoft YaHei",sans-serif;line-height:1.75}header{background:#153c55;color:white;padding:34px max(24px,calc((100vw - 1150px)/2))}h1{margin:0;font-size:30px}main{max-width:1150px;margin:auto;padding:24px}section{background:white;border:1px solid #dce6ee;border-radius:14px;padding:24px;margin-bottom:22px}h2{margin:0 0 14px;font-size:22px}svg{width:100%;height:auto}.notice{background:#e8f3ed;border-left:4px solid #146b55;padding:16px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:12px;border-bottom:1px solid #e1e8ee;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}.selected{background:#e8f3ed;font-weight:bold}select{padding:10px;max-width:100%;font:inherit}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:20px 0}.card{padding:18px;background:#f3f7fb;border-radius:10px}.value{font-size:25px;font-weight:700}.muted{color:#5f7585}a{color:#226c99}@media(max-width:650px){.cards{grid-template-columns:1fr}main{padding:14px}section{padding:17px}h1{font-size:24px}}</style>
<header><h1>蒙西电价预测与储能交易研究</h1><p>次日96点预测 → 合法计划 → 原始真实价格结算｜更新2026-11-09</p></header><main>
<section><p class="notice"><strong>当前保留Phase 2冻结融合。</strong> 新候选提高精度，但未通过收益与稳定性替换门槛。以下为真实历史实验汇总，不是合成训练结果或官方隐藏测试成绩。</p>
<p>同一2025年5/8/11月，8832点、92完整日。12月已见，仅作诊断；价格和收益使用竞赛处理尺度，不代表人民币。</p></section>
<section><h2>完整技术路线</h2>WORKFLOW</section>
<section><h2>候选结果比较</h2><label for="model">选择方案：</label><select id="model">OPTIONS</select>
<div class="cards"><div class="card">R²<div class="value" id="r2"></div></div><div class="card">日均收益<div class="value" id="profit"></div></div><div class="card">收益捕获率<div class="value" id="capture"></div></div></div><p id="difference"></p>
<div class="scroll"><table><thead><tr><th>方案</th><th>R²</th><th>MAE</th><th>RMSE</th><th>日均收益</th><th>捕获率</th></tr></thead><tbody>ROWS</tbody></table></div></section>
<section><h2>为什么没有选最高R²</h2>FIGURE<p>套利取决于两个连续8点窗口的真实价差；全天误差下降仍可能选错充电低谷。Oracle使用真实价格求解，仅作为事后上限。</p></section>
<section><h2>当前模型与策略</h2><p>19列：7官方预测＋11时间编码＋1候选比例。LightGBM与CatBoost价格各50%，再用同一个优化器决策。历史价滞后、未来实际边界与NWP不进入冻结模型。</p><p>96点，连续8点充电后连续8点放电，容量8000，初始和日末SOC为0，最多一个循环。3321种合法组合加不交易，Profit=sum(P×E)，不增加0.25。</p></section>
<section><h2>不足与下一步</h2><p>主验证112个训练P95高价事件点，各候选召回率为0；仍有亏损日。验证历史已被反复研究，不能包装成盲测。后续需要新日期、尖峰/窗口改善和可证明的发布时间。</p><p>真实设备效率、调节速率、容量变化、禁限时段、调度校核与完整合约费用结算尚未实现；政策材料为征求意见稿对照，不能宣称现行合规认证。</p></section>
<p class="muted">本页读取仓库research/results.json，不重训模型，不含原始比赛数据、逐点标签或权重。细节见GitHub仓库README与docs。</p></main>
<script>const data=PAYLOAD;const base=data.models.find(x=>x.selected);function update(){const r=data.models.find(x=>x.id===document.getElementById('model').value);document.getElementById('r2').textContent=r.r2.toFixed(6);document.getElementById('profit').textContent=r.mean_daily_profit.toFixed(2);document.getElementById('capture').textContent=(r.capture*100).toFixed(2)+'%';const delta=(r.mean_daily_profit/base.mean_daily_profit-1)*100;document.getElementById('difference').textContent=r.selected?'当前冻结模型；其余方案未通过替换门槛。':'相对Phase 2日均收益变化：'+(delta>=0?'+':'')+delta.toFixed(2)+'%；不能仅凭R²提高就替换。';}document.getElementById('model').addEventListener('change',update);update();</script></html>'''
    for key, value in [("WORKFLOW", workflow), ("OPTIONS", options), ("ROWS", "".join(rows)),
                       ("FIGURE", figure), ("PAYLOAD", payload)]:
        page = page.replace(key, value)
    output.mkdir(parents=True, exist_ok=False)
    path = output / "index.html"
    path.write_text(page, encoding="utf-8")
    return path.resolve()

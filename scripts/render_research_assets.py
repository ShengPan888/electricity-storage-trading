"""Regenerate standalone figures from public aggregates; no competition inputs.

Workflow SVG uses the standard library. The accuracy/profit figure uses the
optional plotting dependency matplotlib; it is not needed to run the demo.
"""

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets"


def workflow():
    boxes = [
        (35, 100, "01  数据与信息审计", ["7项预测白名单", "时间对齐、缺失与发布边界"]),
        (425, 100, "02  机理特征与模型", ["关联组消融，冻结19列", "LightGBM + CatBoost等权"]),
        (815, 100, "03  严格时间验证", ["训练侧早停后完整重拟合", "5 / 8 / 11月，共92日"]),
        (815, 345, "04  充放电决策", ["96点 → 连续8点窗口", "3321种合法组合 + 不交易"]),
        (425, 345, "05  原始真实价格结算", ["Profit = sum(P × E)", "Oracle、捕获率、Regret"]),
        (35, 345, "06  复盘与模型选择", ["跨月、多种子、区块Bootstrap", "收益门槛未通过：保留Phase 2"])]
    s = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="590" viewBox="0 0 1200 590" role="img" aria-labelledby="title desc">',
         '<title id="title">蒙西电价预测与储能交易研究技术路线</title>',
         '<desc id="desc">数据审计，19特征融合模型，时间验证，合法调度，真实结算，按收益稳定性选择模型。</desc>',
         '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#718b9b"/></marker></defs>',
         '<rect width="1200" height="590" rx="20" fill="#f3f7fb"/>',
         '<g font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif">',
         '<text x="35" y="43" font-size="25" font-weight="700" fill="#17364d">从信息边界到交易收益：完整研究闭环</text>',
         '<text x="35" y="72" font-size="15" fill="#567184">次日96点批量预测 · 原始标签 · 同约束结算 · 内部开发估计</text>']
    for x1, y1, x2, y2 in [(380, 177, 420, 177), (770, 177, 810, 177),
                            (987, 260, 987, 338), (815, 422, 778, 422), (425, 422, 388, 422)]:
        s.append(f'<path d="M{x1},{y1} L{x2},{y2}" stroke="#718b9b" stroke-width="2.5" marker-end="url(#arrow)" fill="none"/>')
    for i, (x, y, title, lines) in enumerate(boxes):
        color = "#146b55" if i == 5 else "#245c85"
        s.append(f'<rect x="{x}" y="{y}" width="345" height="160" rx="12" fill="white" stroke="#cfdee8"/>')
        s.append(f'<rect x="{x}" y="{y}" width="6" height="160" rx="3" fill="{color}"/>')
        s.append(f'<text x="{x+24}" y="{y+39}" font-size="21" font-weight="700" fill="{color}">{escape(title)}</text>')
        for j, line in enumerate(lines):
            s.append(f'<text x="{x+24}" y="{y+81+j*33}" font-size="16" fill="#29485b">{escape(line)}</text>')
    s.append('<text x="35" y="548" font-size="16" fill="#567184">研究已完成不等于实盘就绪：设备参数、禁限时段、调度校核及完整结算仍待接入。</text></g></svg>')
    (OUT / "project_workflow.svg").write_text("\n".join(s), encoding="utf-8")


def chart():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    chinese = next((n for n in ["Microsoft YaHei", "Noto Sans CJK SC", "SimHei"] if n in fonts), None)
    plt.rcParams.update({"font.family": chinese or "DejaVu Sans", "axes.unicode_minus": False,
                         "svg.fonttype": "path", "svg.hashsalt": "mengxi-research-20261109", "font.size": 11})
    data = json.loads((ROOT / "research/results.json").read_text(encoding="utf-8"))
    ids = ["phase2_frozen", "latest_price", "stayfoool_no_prior", "C_event"]
    rows = [{r["id"]: r for r in data["models"]}[i] for i in ids]
    labels = ["Phase 2 冻结", "Phase 3B 精度", "Stayfoool 无先验", "事件修正候选"] if chinese else ["Phase 2 frozen", "Phase 3B price", "Stayfoool no prior", "Event correction"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), layout="constrained")
    colors = ["#146b55", "#497fad", "#8a70a8", "#ce9651"]
    for ax, field, title, lim in [(axes[0], "rmse", "RMSE（越低越好）" if chinese else "RMSE (lower is better)", (0, .75)),
                                   (axes[1], "mean_daily_profit", "日均收益（越高越好）" if chinese else "Mean daily profit (higher is better)", (0, 8200))]:
        values = [r[field] for r in rows]
        ax.barh(range(4), values, color=colors, height=.58)
        ax.set_yticks(range(4), labels)
        ax.invert_yaxis()
        ax.set_xlim(*lim)
        ax.set_title(title, loc="left", fontweight="bold", pad=18)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.grid(axis="x", alpha=.15)
        ax.set_axisbelow(True)
        for j, v in enumerate(values):
            ax.text(v + lim[1] * .015, j, f"{v:.4f}" if field == "rmse" else f"{v:.2f}", va="center", fontsize=10)
    title = "预测误差下降，没有自动转化为交易收益提高" if chinese else "Lower prediction error did not automatically improve trading profit"
    foot = "同一2025年5/8/11月 · 8832点 / 92日 · 竞赛处理尺度 · 内部开发估计，非官方成绩" if chinese else "Same May/Aug/Nov 2025 | 8,832 points / 92 days | Competition scale | Internal development estimates"
    fig.suptitle(title, fontsize=16, fontweight="bold")
    fig.supxlabel(foot, fontsize=10, color="#52677b")
    fig.savefig(OUT / "accuracy_profit.svg", metadata={"Date": "2026-11-09"})
    svg_path = OUT / "accuracy_profit.svg"
    svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    preview = ROOT / "outputs/figure_preview.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(preview, dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    workflow()
    chart()
    print("Generated workflow and accuracy/profit SVGs from public records")

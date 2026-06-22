"""定板策略健康检查。

读取端午 research 结果，把可以吸收到正式流程的结论整理成一页报告。
本脚本不修改线上策略、不写业务数据库，只输出 Markdown/JSON。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("reports") / "research" / "official_strategy_health_check.md"
SHORT_LIVE = "profile_v4_adaptive_quality_v9_sector_quality_guard + baseline exit + Top3"
LONGTERM_LIVE = "longterm_quality_lifecycle_v18_market_sync"


def build_official_strategy_health_check(root: str | Path = ".") -> dict[str, Any]:
    root = Path(root)
    research_dir = root / "reports" / "research"
    layer = _load_json(research_dir / "dragon_boat_layer_quality.json")
    candidates = _load_json(research_dir / "dragon_boat_candidate_simulation.json")
    factor = _load_json(research_dir / "dragon_boat_factor_stability.json")

    short = _short_decision(layer.get("short", {}), candidates.get("short", {}), factor.get("short", {}))
    longterm = _longterm_decision(layer.get("longterm", {}), candidates.get("longterm", {}), factor.get("longterm", {}))

    return {
        "live_defaults_changed": False,
        "short_live": SHORT_LIVE,
        "longterm_live": LONGTERM_LIVE,
        "short": short,
        "longterm": longterm,
        "copyable_to_current_version": [
            "保留短线 v9 Top3 定板，不复制 Top1 或轻重排候选。",
            "把分层质量诊断作为短线健康监控，而不是直接改权重。",
            "长线吸收“质量地板 + Top10观察池 + 生命周期经营”作为下一轮验证方向。",
            "任何成熟候选先进入 research 验证，不直接替换 main.py 默认策略。",
        ],
        "required_reports": [
            "reports/research/dragon_boat_layer_quality.json",
            "reports/research/dragon_boat_candidate_simulation.json",
            "reports/research/dragon_boat_factor_stability.json",
        ],
    }


def write_official_strategy_health_check_report(
    root: str | Path = ".",
    output: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    output = Path(output)
    result = build_official_strategy_health_check(root=root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_format_markdown(result), encoding="utf-8")
    output.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _short_decision(layer: dict[str, Any], candidates: dict[str, Any], factor: dict[str, Any]) -> dict[str, Any]:
    layers = layer.get("layers", {})
    candidate_map = candidates.get("candidates", {})
    top3 = layers.get("top3", {})
    quality_floor = candidate_map.get("short_v9_quality_floor_top3", {})

    return {
        "action": "keep_live_baseline",
        "reason": "Top3 分层仍有质量优势，但候选改动没有跨区间稳定胜出。",
        "top3_layer": {
            "classification": top3.get("classification"),
            "avg_edge_vs_all": top3.get("avg_edge_vs_all"),
        },
        "candidate_observation": {
            "name": "short_v9_quality_floor_top3",
            "classification": quality_floor.get("classification"),
            "edge_vs_baseline": quality_floor.get("overall", {}).get("edge_vs_baseline"),
            "decision": "继续观察，不进入上线验证",
        },
        "factor_note": _factor_note(factor),
    }


def _longterm_decision(layer: dict[str, Any], candidates: dict[str, Any], factor: dict[str, Any]) -> dict[str, Any]:
    layers = layer.get("layers", {})
    candidate_map = candidates.get("candidates", {})
    top3 = layers.get("top3", {})
    top10 = layers.get("top10", {})
    quality_floor = candidate_map.get("long_v18_quality_floor_top10", {})
    classification = quality_floor.get("classification")
    action = "validate_research_candidate" if classification == "promising_for_validation" else "continue_research"

    return {
        "action": action,
        "candidate": "long_v18_quality_floor_top10",
        "reason": "v18 池子有价值，但 Top3 排序精度不足，更适合质量地板后的 Top10 生命周期观察池。",
        "top3_layer": {
            "classification": top3.get("classification"),
            "avg_edge_vs_all": top3.get("avg_edge_vs_all"),
        },
        "top10_layer": {
            "classification": top10.get("classification"),
            "avg_edge_vs_all": top10.get("avg_edge_vs_all"),
        },
        "candidate_observation": {
            "classification": classification,
            "edge_vs_baseline": quality_floor.get("overall", {}).get("edge_vs_baseline"),
            "decision": "建议进入下一轮验证，不直接上线",
        },
        "factor_note": _factor_note(factor),
    }


def _factor_note(factor: dict[str, Any]) -> str:
    if not factor:
        return "未读取到因子稳定性报告。"
    stable_positive = factor.get("stable_positive", [])
    unstable = factor.get("unstable", [])
    if stable_positive:
        names = [item.get("factor", "") for item in stable_positive[:3]]
        return "稳定正向因子较少，当前可参考：" + "、".join(filter(None, names))
    if unstable:
        names = [item.get("factor", "") for item in unstable[:3]]
        return "多数因子阶段不稳定，避免直接按单因子加权；典型不稳定项：" + "、".join(filter(None, names))
    return "未发现足够稳定的单因子，继续使用组合验证。"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _format_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 定板策略健康检查",
        "",
        "## 结论",
        f"- 上线默认策略未改变：`live_defaults_changed = {result['live_defaults_changed']}`。",
        f"- 短线正式版：`{result['short_live']}`。",
        f"- 长线当前版：`{result['longterm_live']}`。",
        "",
        "## 可吸收到现有定板流程的内容",
    ]
    for item in result["copyable_to_current_version"]:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 短线 v9",
            f"- 动作：`{result['short']['action']}`。",
            f"- 原因：{result['short']['reason']}",
            f"- Top3 分层：`{result['short']['top3_layer'].get('classification')}`，相对全样本 `{_fmt_num(result['short']['top3_layer'].get('avg_edge_vs_all'))}`。",
            f"- 候选观察：`{result['short']['candidate_observation']['name']}`，结论：{result['short']['candidate_observation']['decision']}。",
            f"- 因子备注：{result['short']['factor_note']}",
            "",
            "## 长线 v18",
            f"- 动作：`{result['longterm']['action']}`。",
            f"- 候选：`{result['longterm']['candidate']}`。",
            f"- 原因：{result['longterm']['reason']}",
            f"- Top3 分层：`{result['longterm']['top3_layer'].get('classification')}`，相对全样本 `{_fmt_num(result['longterm']['top3_layer'].get('avg_edge_vs_all'))}`。",
            f"- Top10 分层：`{result['longterm']['top10_layer'].get('classification')}`，相对全样本 `{_fmt_num(result['longterm']['top10_layer'].get('avg_edge_vs_all'))}`。",
            f"- 候选观察：`long_v18_quality_floor_top10`，结论：{result['longterm']['candidate_observation']['decision']}。",
            f"- 因子备注：{result['longterm']['factor_note']}",
            "",
            "## 复跑顺序",
            "```powershell",
            "python research\\strategy_layer_quality.py --output reports\\research\\dragon_boat_layer_quality.md",
            "python research\\strategy_factor_stability.py --output reports\\research\\dragon_boat_factor_stability.md",
            "python research\\strategy_candidate_simulator.py --output reports\\research\\dragon_boat_candidate_simulation.md",
            "python research\\official_strategy_health_check.py --output reports\\research\\official_strategy_health_check.md",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt_num(value: Any) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):+.4f}"
    except (TypeError, ValueError):
        return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成定板策略健康检查报告。")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Markdown 输出路径")
    args = parser.parse_args()

    result = write_official_strategy_health_check_report(root=args.root, output=args.output)
    print(f"Report written: {args.output}")
    print(f"short_action={result['short']['action']} longterm_action={result['longterm']['action']}")


if __name__ == "__main__":
    main()

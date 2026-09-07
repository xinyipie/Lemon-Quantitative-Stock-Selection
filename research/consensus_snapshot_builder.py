"""Build reusable consensus candidate snapshots from saved IC candidate pools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy_profiles import apply_style_gate, factor_profile_score


DEFAULT_INPUT_MAP = Path("reports") / "stage1_metric_ic_map_v19_v25_v27.csv"
DEFAULT_OUTPUT = Path("reports") / "consensus_snapshot_v19_v25_v27.csv"

PROFILE_CONFIGS = {
    "v19_top1_hold3": ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
    "v25_top1_hold3": ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
    "v27_top1_hold3": ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
}

KEEP_COLUMNS = [
    "period",
    "select_date",
    "buy_date",
    "ts_code",
    "code",
    "name",
    "industry",
    "score",
    "original_score",
    "select_close",
    "buy_open",
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_wyckoff",
    "factor_accel",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
    "market_style",
    "macro_mode",
    "market_state",
    "operation_mode",
    "regime",
    "market_index_change",
    "sector_ma10_ratio",
    "sector_ma10_above",
    "sector_ma10_total",
    "limit_up_count",
    "limit_down_count",
    "limit_up_down_ratio",
    "ret_3d",
    "ret_5d",
    "mfe_pct",
    "mae_pct",
]


def build_consensus_snapshot(input_map: str | Path = DEFAULT_INPUT_MAP) -> pd.DataFrame:
    """Replay virtual gates from mapped IC files and aggregate per-date consensus votes."""
    input_map = Path(input_map)
    mapping = pd.read_csv(input_map, encoding="utf-8-sig")
    frames = []
    for _, map_row in mapping.iterrows():
        strategy = str(map_row.get("strategy") or "")
        if strategy not in PROFILE_CONFIGS:
            continue
        label, factor_profile, style_gate = PROFILE_CONFIGS[strategy]
        ic_path = _resolve_path(input_map.parent, map_row.get("ic_file"))
        if not ic_path.exists():
            continue
        ic_df = _read_csv(ic_path)
        if ic_df.empty:
            continue
        scored = _replay_profile_candidates(ic_df, factor_profile=factor_profile, style_gate=style_gate)
        if scored.empty:
            continue
        scored = scored.copy()
        scored["period"] = str(map_row.get("period") or "")
        scored["virtual_profile"] = label
        scored["virtual_strategy"] = strategy
        scored["virtual_score"] = pd.to_numeric(
            scored.get("experiment_score", scored.get("score")),
            errors="coerce",
        ).fillna(0.0)
        scored = scored.sort_values(
            ["select_date", "virtual_score", "ts_code"],
            ascending=[True, False, True],
        )
        scored["virtual_rank"] = scored.groupby("select_date").cumcount() + 1
        frames.append(scored)

    if not frames:
        return _empty_snapshot()

    combined = pd.concat(frames, ignore_index=True)
    combined = _normalize_key_columns(combined)
    rows = []
    for (_, select_date, ts_code), group in combined.groupby(["period", "select_date", "ts_code"], sort=False):
        base = group.sort_values(["virtual_rank", "virtual_score"], ascending=[True, False]).iloc[0].copy()
        votes = int(group["virtual_profile"].nunique())
        rank_mean = float(pd.to_numeric(group["virtual_rank"], errors="coerce").mean())
        score_mean = float(pd.to_numeric(group["virtual_score"], errors="coerce").mean())
        for col in KEEP_COLUMNS:
            if col not in base.index:
                base[col] = None
        base["consensus_votes"] = votes
        base["consensus_avg_rank"] = round(rank_mean, 4)
        base["consensus_avg_score"] = round(score_mean, 4)
        base["consensus_profiles"] = ",".join(sorted(group["virtual_profile"].astype(str).unique()))
        base["consensus_score"] = round(votes * 100.0 + score_mean - rank_mean * 0.01, 4)
        rows.append(base)

    snapshot = pd.DataFrame(rows)
    columns = [col for col in KEEP_COLUMNS if col in snapshot.columns] + [
        "virtual_profile",
        "virtual_strategy",
        "virtual_rank",
        "virtual_score",
        "consensus_votes",
        "consensus_avg_rank",
        "consensus_avg_score",
        "consensus_profiles",
        "consensus_score",
    ]
    columns = [col for col in columns if col in snapshot.columns]
    return snapshot[columns].sort_values(
        ["period", "select_date", "consensus_votes", "consensus_avg_rank", "consensus_avg_score", "ts_code"],
        ascending=[True, True, False, True, False, True],
    ).reset_index(drop=True)


def write_consensus_snapshot(
    input_map: str | Path = DEFAULT_INPUT_MAP,
    output: str | Path = DEFAULT_OUTPUT,
) -> dict:
    """Write snapshot CSV and a compact JSON summary for later rule searches."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_consensus_snapshot(input_map)
    snapshot.to_csv(output, index=False, encoding="utf-8-sig")
    summary = _summary(snapshot, input_map=input_map, output=output)
    output.with_suffix(".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _replay_profile_candidates(df: pd.DataFrame, factor_profile: str, style_gate: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    score_col = "score" if "score" in out.columns else out.columns[0]
    if "original_score" not in out.columns:
        out["original_score"] = out[score_col]
    out["experiment_score"] = out.apply(
        lambda row: factor_profile_score(row, factor_profile, score_col),
        axis=1,
    )
    out = apply_style_gate(out, style_gate)
    if not out.empty:
        out["score"] = out["experiment_score"]
    out["factor_profile"] = factor_profile
    out["style_gate"] = style_gate
    return out.sort_values("experiment_score", ascending=False).reset_index(drop=True)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _resolve_path(base_dir: Path, value) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path
    candidate = Path.cwd() / path
    if candidate.exists():
        return candidate
    return base_dir / path


def _normalize_key_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "ts_code" not in out.columns and "code" in out.columns:
        out["ts_code"] = out["code"].astype(str)
    if "code" not in out.columns and "ts_code" in out.columns:
        out["code"] = out["ts_code"].astype(str).str[:6]
    out["select_date"] = out["select_date"].astype(str)
    out["ts_code"] = out["ts_code"].astype(str)
    return out


def _empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        columns=KEEP_COLUMNS
        + [
            "virtual_profile",
            "virtual_strategy",
            "virtual_rank",
            "virtual_score",
            "consensus_votes",
            "consensus_avg_rank",
            "consensus_avg_score",
            "consensus_profiles",
            "consensus_score",
        ]
    )


def _summary(snapshot: pd.DataFrame, input_map: str | Path, output: Path) -> dict:
    vote_counts = {}
    if "consensus_votes" in snapshot.columns and not snapshot.empty:
        vote_counts = {
            str(int(vote)): int(count)
            for vote, count in snapshot["consensus_votes"].value_counts().sort_index().items()
        }
    return {
        "input_map": str(input_map),
        "output": str(output),
        "rows": int(len(snapshot)),
        "dates": int(snapshot["select_date"].nunique()) if "select_date" in snapshot.columns else 0,
        "periods": sorted(snapshot["period"].dropna().astype(str).unique().tolist()) if "period" in snapshot.columns else [],
        "vote_counts": vote_counts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build reusable v19/v25/v27 consensus candidate snapshot.")
    parser.add_argument("--input-map", type=Path, default=DEFAULT_INPUT_MAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = write_consensus_snapshot(args.input_map, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

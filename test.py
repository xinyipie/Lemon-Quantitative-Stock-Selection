"""
test.py — standardized backtest driver

Default:
  python test.py
  Runs a fast one-week smoke test for baseline + current experiment.

Common modes:
  python test.py --full      # full periods, core scenarios only
  python test.py --matrix    # full periods, all scenarios
  python test.py --scenario profile_v4_weak_only --full
  python test.py --start 20250101 --end 20250131 --scenario score_desc,profile_v4
"""
import argparse
import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime

# ── Test presets ──
QUICK_PERIODS = [
    {"label": "quick_1w", "start": "20250102", "end": "20250110"},
]
FULL_PERIODS = [
    {"label": "2026Q1",  "start": "20260101", "end": "20260420"},
    {"label": "2025全年", "start": "20250101", "end": "20251231"},
]
ALL_SCENARIOS = [
    {"label": "score_desc", "score_order": "desc", "factor_profile": "original", "style_gate": "none"},
    {"label": "score_asc",  "score_order": "asc",  "factor_profile": "original", "style_gate": "none"},
    {"label": "diagnostic_v1", "score_order": "desc", "factor_profile": "diagnostic_v1", "style_gate": "none"},
    {"label": "profile_v2", "score_order": "desc", "factor_profile": "profile_v2", "style_gate": "none"},
    {"label": "profile_v3", "score_order": "desc", "factor_profile": "profile_v3", "style_gate": "none"},
    {"label": "profile_v4", "score_order": "desc", "factor_profile": "profile_v4", "style_gate": "none"},
    {"label": "profile_v5", "score_order": "desc", "factor_profile": "profile_v5", "style_gate": "none"},
    {"label": "profile_v4_no_momentum", "score_order": "desc", "factor_profile": "profile_v4", "style_gate": "no_momentum"},
    {"label": "profile_v4_no_active_sideways", "score_order": "desc", "factor_profile": "profile_v4", "style_gate": "no_active_sideways"},
    {"label": "profile_v4_weak_only", "score_order": "desc", "factor_profile": "profile_v4", "style_gate": "weak_only"},
    {"label": "profile_v4_weak_or_cautious_sideways", "score_order": "desc", "factor_profile": "profile_v4", "style_gate": "weak_or_cautious_sideways"},
    {"label": "profile_v4_adaptive_quality", "score_order": "desc", "factor_profile": "profile_v4", "style_gate": "adaptive_quality"},
    {"label": "profile_v4_adaptive_quality_v2", "score_order": "desc", "factor_profile": "profile_v4", "style_gate": "adaptive_quality_v2"},
    {"label": "profile_v4_adaptive_quality_v5", "score_order": "desc", "factor_profile": "profile_v4", "style_gate": "adaptive_quality_v5"},
]
CORE_SCENARIO_LABELS = ["score_desc", "profile_v4_adaptive_quality"]
EXIT_PROFILES = [
    {"label": "baseline", "args": {}},
    {
        "label": "exit_v1_tight_lock",
        "args": {
            "fallback_stop": -6.0,
            "fallback_profit": 12.0,
            "trailing_stop": 4.5,
            "trailing_activate": 5.0,
        },
    },
    {
        "label": "exit_v1_mid_lock",
        "args": {
            "fallback_stop": -6.0,
            "fallback_profit": 15.0,
            "trailing_stop": 5.0,
            "trailing_activate": 6.0,
        },
    },
    {
        "label": "exit_v1_profit_guard",
        "args": {
            "fallback_stop": -6.0,
            "fallback_profit": 18.0,
            "trailing_stop": 4.0,
            "trailing_activate": 8.0,
        },
    },
    {
        "label": "exit_v2_conditional_lock",
        "args": {
            "conditional_lock": True,
            "conditional_lock_activation": 6.0,
            "conditional_lock_trailing": 4.8,
        },
    },
]
RESULTS_DIR = Path("backtest_results")
FACTOR_COLUMNS = [
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_counter_trend",
    "factor_wyckoff",
    "factor_accel",
    "score_base",
]

def parse_args():
    parser = argparse.ArgumentParser(
        description="Run short-strategy backtest scenarios and write test_result.json."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full standard periods, but only core scenarios by default.",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Run full standard periods and all scenarios, equivalent to the old 8-run test.",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Comma-separated scenario labels, e.g. score_desc,profile_v4_weak_only. Use 'all' for all scenarios.",
    )
    parser.add_argument("--start", help="Custom start date, YYYYMMDD.")
    parser.add_argument("--end", help="Custom end date, YYYYMMDD.")
    parser.add_argument("--label", default="custom", help="Label for custom --start/--end period.")
    parser.add_argument("--hold", default="8", help="Hold days passed to backtest_v2.py.")
    parser.add_argument("--topn", default="3", help="TopN passed to backtest_v2.py.")
    parser.add_argument(
        "--exit-profile",
        default="baseline",
        help="Comma-separated exit profile labels, e.g. baseline,exit_v1_tight_lock. Use 'all' for all exit profiles.",
    )
    return parser.parse_args()

def select_periods(args):
    if args.start or args.end:
        if not args.start or not args.end:
            raise SystemExit("--start and --end must be provided together.")
        return [{"label": args.label, "start": args.start, "end": args.end}]
    if args.full or args.matrix:
        return FULL_PERIODS
    return QUICK_PERIODS

def select_scenarios(args):
    scenario_map = {item["label"]: item for item in ALL_SCENARIOS}
    if args.scenario:
        labels = [part.strip() for part in args.scenario.split(",") if part.strip()]
        if labels == ["all"]:
            return ALL_SCENARIOS
        unknown = [label for label in labels if label not in scenario_map]
        if unknown:
            raise SystemExit(f"Unknown scenario(s): {', '.join(unknown)}")
        return [scenario_map[label] for label in labels]
    if args.matrix:
        return ALL_SCENARIOS
    return [scenario_map[label] for label in CORE_SCENARIO_LABELS]

def select_exit_profiles(args):
    profile_map = {item["label"]: item for item in EXIT_PROFILES}
    labels = [part.strip() for part in args.exit_profile.split(",") if part.strip()]
    if labels == ["all"]:
        return EXIT_PROFILES
    unknown = [label for label in labels if label not in profile_map]
    if unknown:
        raise SystemExit(f"Unknown exit profile(s): {', '.join(unknown)}")
    return [profile_map[label] for label in labels]

def find_newest(pattern, exclude):
    candidates = set(RESULTS_DIR.glob(pattern)) - exclude
    return sorted(candidates)[-1] if candidates else None

def build_exit_args(exit_profile):
    args = exit_profile.get("args") or {}
    cli_map = {
        "fallback_stop": "--fallback-stop",
        "fallback_profit": "--fallback-profit",
        "trailing_stop": "--trailing-stop",
        "trailing_activate": "--trailing-activate",
        "conditional_lock_activation": "--conditional-lock-activation",
        "conditional_lock_trailing": "--conditional-lock-trailing",
    }
    cmd = []
    if args.get("conditional_lock"):
        cmd.append("--conditional-lock")
    for key, flag in cli_map.items():
        if key in args:
            cmd.extend([flag, str(args[key])])
    return cmd

def calc_ic(ic_csv_path, n):
    try:
        import pandas as pd
        from scipy.stats import spearmanr
        df = pd.read_csv(ic_csv_path, encoding="utf-8-sig")
        col = f"ret_{n}d"
        if "score" not in df.columns or col not in df.columns:
            return None
        valid = df[["score", col]].dropna()
        if len(valid) < 10:
            return None
        ic_val, pval = spearmanr(valid["score"], valid[col])
        n3 = max(1, len(valid) // 3)
        top_ret = valid.nlargest(n3, "score")[col].mean()
        bot_ret = valid.nsmallest(n3, "score")[col].mean()
        return {
            "ic":      round(float(ic_val), 4),
            "pval":    round(float(pval), 3),
            "avg_ret": round(float(valid[col].mean()), 2),
            "top_ret": round(float(top_ret), 2),
            "bot_ret": round(float(bot_ret), 2),
            "hl_diff": round(float(top_ret - bot_ret), 2),
            "n":       int(len(valid)),
        }
    except Exception as e:
        return {"error": str(e)}

def calc_factor_ic(ic_csv_path, n=10):
    try:
        import pandas as pd
        from scipy.stats import spearmanr
        df = pd.read_csv(ic_csv_path, encoding="utf-8-sig")
        ret_col = f"ret_{n}d"
        if ret_col not in df.columns:
            return None
        result = {}
        for factor in FACTOR_COLUMNS:
            if factor not in df.columns:
                continue
            valid = df[[factor, ret_col]].dropna()
            if len(valid) < 10 or valid[factor].nunique() < 2:
                continue
            ic_val, pval = spearmanr(valid[factor], valid[ret_col])
            n3 = max(1, len(valid) // 3)
            top_ret = valid.nlargest(n3, factor)[ret_col].mean()
            bot_ret = valid.nsmallest(n3, factor)[ret_col].mean()
            result[factor] = {
                "ic": round(float(ic_val), 4),
                "pval": round(float(pval), 3),
                "top_ret": round(float(top_ret), 2),
                "bot_ret": round(float(bot_ret), 2),
                "hl_diff": round(float(top_ret - bot_ret), 2),
                "n": int(len(valid)),
            }
        return result
    except Exception as e:
        return {"error": str(e)}

def calc_factor_target_ic(ic_csv_path, target_col):
    try:
        import pandas as pd
        from scipy.stats import spearmanr
        df = pd.read_csv(ic_csv_path, encoding="utf-8-sig")
        if target_col not in df.columns:
            return None
        result = {}
        for factor in FACTOR_COLUMNS:
            if factor not in df.columns:
                continue
            valid = df[[factor, target_col]].dropna()
            if len(valid) < 10 or valid[factor].nunique() < 2:
                continue
            ic_val, pval = spearmanr(valid[factor], valid[target_col])
            n3 = max(1, len(valid) // 3)
            top_val = valid.nlargest(n3, factor)[target_col].mean()
            bot_val = valid.nsmallest(n3, factor)[target_col].mean()
            result[factor] = {
                "ic": round(float(ic_val), 4),
                "pval": round(float(pval), 3),
                "top": round(float(top_val), 2),
                "bot": round(float(bot_val), 2),
                "hl_diff": round(float(top_val - bot_val), 2),
                "n": int(len(valid)),
            }
        return result
    except Exception as e:
        return {"error": str(e)}

def calc_trade_diagnostics(trades_csv_path):
    try:
        import pandas as pd
        df = pd.read_csv(trades_csv_path, encoding="utf-8-sig")
        if df.empty or "profit_pct" not in df.columns:
            return None

        for col in ["profit_pct", "mfe_pct", "mae_pct"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "mfe_pct" not in df.columns:
            df["mfe_pct"] = None
        if "mae_pct" not in df.columns:
            df["mae_pct"] = None

        df["giveback_pct"] = df["mfe_pct"] - df["profit_pct"]
        high_mfe = df[df["mfe_pct"] >= 5]
        high_mfe_losers = high_mfe[high_mfe["profit_pct"] <= 0]
        big_giveback = df[(df["mfe_pct"] >= 8) & (df["giveback_pct"] >= 6)]
        defensive_exit_reasons = {
            "stop_loss",
            "trailing_stop",
            "time_stop_dynamic",
            "time_stop_short",
            "weak_close_exit",
        }
        if "exit_reason" in df.columns:
            stopped_after_5pct_mfe = df[
                df["exit_reason"].isin(defensive_exit_reasons) & (df["mfe_pct"] >= 5)
            ]
        else:
            stopped_after_5pct_mfe = df.iloc[0:0]

        def safe_avg(series):
            valid = series.dropna()
            return round(float(valid.mean()), 2) if len(valid) else None

        def safe_rate(count, total):
            return round(count / total * 100, 2) if total else None

        by_exit_reason = {}
        if "exit_reason" in df.columns:
            for reason, group in df.groupby("exit_reason", dropna=False):
                wins = int((group["profit_pct"] > 0).sum())
                by_exit_reason[str(reason)] = {
                    "trades": int(len(group)),
                    "win_rate": safe_rate(wins, len(group)),
                    "avg_profit_pct": safe_avg(group["profit_pct"]),
                    "avg_mfe_pct": safe_avg(group["mfe_pct"]),
                    "avg_mae_pct": safe_avg(group["mae_pct"]),
                    "avg_giveback_pct": safe_avg(group["giveback_pct"]),
                }

        by_market_style = {}
        if "market_style" in df.columns:
            for style, group in df.groupby("market_style", dropna=False):
                wins = int((group["profit_pct"] > 0).sum())
                by_market_style[str(style)] = {
                    "trades": int(len(group)),
                    "win_rate": safe_rate(wins, len(group)),
                    "avg_profit_pct": safe_avg(group["profit_pct"]),
                    "avg_mfe_pct": safe_avg(group["mfe_pct"]),
                    "avg_mae_pct": safe_avg(group["mae_pct"]),
                }

        return {
            "trades": int(len(df)),
            "avg_giveback_pct": safe_avg(df["giveback_pct"]),
            "high_mfe_trades": int(len(high_mfe)),
            "high_mfe_losers": int(len(high_mfe_losers)),
            "high_mfe_loser_rate": safe_rate(len(high_mfe_losers), len(high_mfe)),
            "big_giveback_trades": int(len(big_giveback)),
            "stopped_after_5pct_mfe": int(len(stopped_after_5pct_mfe)),
            "by_exit_reason": by_exit_reason,
            "by_market_style": by_market_style,
        }
    except Exception as e:
        return {"error": str(e)}

def main():
    args = parse_args()
    periods = select_periods(args)
    scenarios = select_scenarios(args)
    exit_profiles = select_exit_profiles(args)
    base_cmd = [
        sys.executable, "backtest_v2.py",
        "--mode", "short",
        "--offline",
        "--no-timing",
        "--hold", str(args.hold),
        "--topn", str(args.topn),
    ]
    run_mode = "matrix" if args.matrix else ("full" if args.full else "quick")

    print("\n" + "="*60)
    print(f"  test.py mode={run_mode}  scenarios={[s['label'] for s in scenarios]}  "
          f"exit_profiles={[e['label'] for e in exit_profiles]}  periods={[p['label'] for p in periods]}")
    print("="*60)

    results = []

    for scenario in scenarios:
        scenario_label = scenario["label"]
        score_order = scenario["score_order"]
        factor_profile = scenario["factor_profile"]
        style_gate = scenario.get("style_gate", "none")
        for exit_profile in exit_profiles:
            for p in periods:
                run_one_backtest(
                    base_cmd,
                    scenario_label,
                    score_order,
                    factor_profile,
                    style_gate,
                    exit_profile,
                    p,
                    results,
                )

    write_result(args, run_mode, scenarios, exit_profiles, periods, results)
    print_summary(results)

def run_one_backtest(base_cmd, scenario_label, score_order, factor_profile, style_gate, exit_profile, p, results):
    label, start, end = p["label"], p["start"], p["end"]
    exit_label = exit_profile["label"]
    print(f"\n{'='*60}")
    print(f"  [{scenario_label} | {exit_label} | {label}]  {start} → {end}")
    print(f"{'='*60}\n", flush=True)

    before_metrics = set(RESULTS_DIR.glob("metrics_*.json"))
    before_ic = set(RESULTS_DIR.glob("ic_short_*.csv"))
    before_trades = set(RESULTS_DIR.glob("trades_*.csv"))

    cmd = base_cmd + [
        "--score-order", score_order,
        "--factor-profile", factor_profile,
        "--style-gate", style_gate,
        "--start", start,
        "--end", end,
    ] + build_exit_args(exit_profile)
    subprocess.run(cmd, check=True)

    metrics_file = find_newest("metrics_*.json", before_metrics)
    ic_file = find_newest("ic_short_*.csv", before_ic)
    trades_file = find_newest("trades_*.csv", before_trades)

    entry = {
        "scenario": scenario_label,
        "score_order": score_order,
        "factor_profile": factor_profile,
        "style_gate": style_gate,
        "exit_profile": exit_label,
        "exit_params": exit_profile.get("args") or {},
        "label": label,
        "period": f"{start}->{end}",
    }

    if metrics_file:
        with open(metrics_file, encoding="utf-8") as f:
            m = json.load(f)
        entry["metrics"] = {
            "total_trades": m.get("total_trades"),
            "win_rate": m.get("win_rate"),
            "total_return_pct": m.get("total_return_pct"),
            "alpha_pct": m.get("alpha_pct"),
            "sharpe_ratio": m.get("sharpe_ratio"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "avg_win_pct": m.get("avg_win_pct"),
            "avg_loss_pct": m.get("avg_loss_pct"),
            "profit_loss_ratio": m.get("profit_loss_ratio"),
            "avg_mfe_pct": m.get("avg_mfe_pct"),
            "median_mfe_pct": m.get("median_mfe_pct"),
            "avg_mae_pct": m.get("avg_mae_pct"),
            "median_mae_pct": m.get("median_mae_pct"),
            "avg_window_end_pct": m.get("avg_window_end_pct"),
            "hit_3pct_rate": m.get("hit_3pct_rate"),
            "hit_5pct_rate": m.get("hit_5pct_rate"),
            "hit_10pct_rate": m.get("hit_10pct_rate"),
            "ambiguous_hit_days": m.get("ambiguous_hit_days"),
        }
        entry["metrics_file"] = metrics_file.name
    else:
        entry["metrics"] = None
        print("  WARNING: 未找到 metrics JSON")

    if ic_file:
        entry["ic"] = {
            "5d": calc_ic(ic_file, 5),
            "10d": calc_ic(ic_file, 10),
            "20d": calc_ic(ic_file, 20),
        }
        entry["factor_ic_10d"] = calc_factor_ic(ic_file, 10)
        entry["factor_signal_ic"] = {
            "mfe_pct": calc_factor_target_ic(ic_file, "mfe_pct"),
            "mae_pct": calc_factor_target_ic(ic_file, "mae_pct"),
            "window_end_pct": calc_factor_target_ic(ic_file, "window_end_pct"),
        }
        entry["ic_file"] = ic_file.name
    else:
        entry["ic"] = None
        print("  WARNING: 未找到 IC CSV")

    if trades_file:
        entry["trades_file"] = trades_file.name
        entry["trade_diagnostics"] = calc_trade_diagnostics(trades_file)
    else:
        entry["trade_diagnostics"] = None
        print("  WARNING: no trades CSV found")

    results.append(entry)

def write_result(args, run_mode, scenarios, exit_profiles, periods, results):
    out_path = Path("test_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": run_mode,
            "params": f"--no-timing --hold {args.hold} --topn {args.topn} --exit-profile {args.exit_profile}",
            "scenarios": scenarios,
            "exit_profiles": exit_profiles,
            "periods": periods,
            "results": results,
        }, f, ensure_ascii=False, indent=2)

def print_summary(results):
    print("\n" + "="*60)
    print("  汇总对比")
    print("="*60)
    for r in results:
        m = r.get("metrics") or {}
        ic5 = (r.get("ic") or {}).get("5d") or {}
        diag = r.get("trade_diagnostics") or {}
        print(f"\n  [{r['scenario']} | {r.get('exit_profile', 'baseline')} | {r['label']}]")
        if diag:
            print(f"    ExitDiag: highMFE={diag.get('high_mfe_trades')}  "
                  f"highMFE_losers={diag.get('high_mfe_losers')}  "
                  f"big_giveback={diag.get('big_giveback_trades')}  "
                  f"stopped_after_5pct_mfe={diag.get('stopped_after_5pct_mfe')}  "
                  f"avg_giveback={diag.get('avg_giveback_pct')}%")
        print(f"    笔数={m.get('total_trades')}  胜率={m.get('win_rate')}%  "
              f"总收益={m.get('total_return_pct')}%  α={m.get('alpha_pct')}%  "
              f"夏普={m.get('sharpe_ratio')}")
        print(f"    MFE均值={m.get('avg_mfe_pct')}%  MAE均值={m.get('avg_mae_pct')}%  "
              f"窗口期末={m.get('avg_window_end_pct')}%  "
              f"触及3/5/10={m.get('hit_3pct_rate')}%/{m.get('hit_5pct_rate')}%/{m.get('hit_10pct_rate')}%")
        print(f"    IC(5d)={ic5.get('ic')}  p={ic5.get('pval')}  "
              f"高低差={ic5.get('hl_diff')}%  n={ic5.get('n')}")

    print("\nOK: 详细结果已写入 test_result.json\n")

if __name__ == "__main__":
    main()

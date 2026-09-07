"""研究流程共用的时间切分与证据资格约束。"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


def _parse_research_dates(values: pd.Series) -> pd.Series:
    """统一解析字符串、整数YYYYMMDD和时间戳日期。"""
    strings = values.astype("string").str.strip()
    compact = strings.str.replace("-", "", regex=False).str.replace("/", "", regex=False)
    yyyymmdd = compact.str.extract(r"^(\d{8})", expand=False)
    parsed = pd.to_datetime(yyyymmdd, format="%Y%m%d", errors="coerce")
    fallback = pd.to_datetime(strings.where(yyyymmdd.isna()), errors="coerce")
    return parsed.fillna(fallback)


def _parse_research_date(value: str | int | pd.Timestamp) -> pd.Timestamp:
    parsed = _parse_research_dates(pd.Series([value])).iloc[0]
    if pd.isna(parsed):
        raise ValueError(f"无效日期: {value}")
    return pd.Timestamp(parsed)


def purge_overlapping_label_tail(
    frame: pd.DataFrame,
    horizon: int,
    date_column: str = "trade_date",
    *,
    prediction_start_date: str | int | pd.Timestamp | None = None,
    label_exit_date_column: str | None = None,
    require_label_exit_date: bool = True,
) -> pd.DataFrame:
    """按标签退出日或保守日历间隔清除跨预测边界的训练标签。"""
    if horizon < 0:
        raise ValueError("horizon不能为负数")
    if date_column not in frame.columns:
        raise ValueError(f"训练样本缺少日期列: {date_column}")
    work = frame.copy()
    signal_dates = _parse_research_dates(work[date_column])
    if signal_dates.isna().any():
        raise ValueError(f"训练样本{date_column}包含无法解析的日期")
    if prediction_start_date is None:
        latest = signal_dates.max()
        if pd.isna(latest):
            raise ValueError("无法从训练样本推导下一预测年度")
        prediction_start = pd.Timestamp(year=int(latest.year) + 1, month=1, day=1)
    else:
        prediction_start = _parse_research_date(prediction_start_date)

    exit_column = label_exit_date_column or f"label_exit_date_{int(horizon)}d"
    if exit_column in work.columns:
        exit_dates = _parse_research_dates(work[exit_column])
        if require_label_exit_date and exit_dates.isna().any():
            raise ValueError(f"严格走步验证的{exit_column}包含缺失退出日")
        calendar_embargo_days = max(14, int(horizon) * 4)
        fallback_cutoff = prediction_start - pd.Timedelta(days=calendar_embargo_days)
        safe = exit_dates.lt(prediction_start)
        safe |= exit_dates.isna() & signal_dates.lt(fallback_cutoff)
        purge_basis = exit_column
        label_boundary_verified = bool(exit_dates.notna().all())
    else:
        if require_label_exit_date:
            raise ValueError(
                f"严格走步验证需要{exit_column}；旧clean store必须重建，"
                "日历间隔不能证明长期停牌样本没有跨界"
            )
        calendar_embargo_days = max(14, int(horizon) * 4)
        fallback_cutoff = prediction_start - pd.Timedelta(days=calendar_embargo_days)
        safe = signal_dates.lt(fallback_cutoff)
        purge_basis = "conservative_calendar_embargo"
        label_boundary_verified = False

    removed = work.loc[~safe, date_column].astype(str).drop_duplicates().tolist()
    work = work.loc[safe].copy()
    work.attrs["purged_label_dates"] = removed
    work.attrs["label_horizon"] = int(horizon)
    work.attrs["purge_boundary"] = prediction_start.strftime("%Y%m%d")
    work.attrs["purge_basis"] = purge_basis
    work.attrs["calendar_embargo_days"] = calendar_embargo_days
    work.attrs["label_boundary_verified"] = label_boundary_verified
    return work


def lock_observable_topn(
    frame: pd.DataFrame,
    date_column: str,
    score_column: str,
    topn: int,
    code_column: str = "ts_code",
) -> pd.DataFrame:
    """只用信号时可见分数和稳定代码键锁定每日候选。"""
    required = {date_column, score_column, code_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"候选缺少字段: {sorted(missing)}")
    return (
        frame.sort_values(
            [date_column, score_column, code_column],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby(date_column, group_keys=False)
        .head(int(topn))
        .copy()
    )


def evidence_qualification(
    research_id: str,
    blockers: Iterable[str] = (),
    *,
    evidence_tier: str = "exploratory",
) -> dict[str, object]:
    """生成机器可读证据资格；存在阻断项时永不标记 ready。"""
    normalized = sorted({str(item).strip() for item in blockers if str(item).strip()})
    return {
        "research_id": str(research_id),
        "evidence_tier": str(evidence_tier),
        "strict_oos_eligible": not normalized,
        "deployment_ready": False,
        "evidence_blockers": normalized,
    }

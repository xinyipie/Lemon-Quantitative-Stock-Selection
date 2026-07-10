import backtest_v2
import config
from unittest.mock import patch


def test_official_short_profile_matches_live_config():
    assert config.get_official_short_profile() == {
        "factor_profile": config.SHORT_LIVE_FACTOR_PROFILE,
        "style_gate": config.SHORT_LIVE_STYLE_GATE,
        "consensus_profile": config.SHORT_LIVE_CONSENSUS_PROFILE,
    }


def test_official_longterm_profile_matches_live_config():
    assert config.get_official_longterm_profile() == config.LONGTERM_LIVE_PROFILE


def test_backtest_cli_defaults_to_official_profiles():
    args = backtest_v2._build_arg_parser().parse_args([])
    short_profile = config.get_official_short_profile()

    assert args.factor_profile == short_profile["factor_profile"]
    assert args.style_gate == short_profile["style_gate"]
    assert args.consensus_profile == short_profile["consensus_profile"]
    assert args.longterm_profile == config.get_official_longterm_profile()


def test_backtest_cli_preserves_explicit_research_profiles():
    args = backtest_v2._build_arg_parser().parse_args(
        [
            "--factor-profile",
            "original",
            "--style-gate",
            "none",
            "--consensus-profile",
            "none",
            "--longterm-profile",
            "zscore_v4_1",
        ]
    )

    assert args.factor_profile == "original"
    assert args.style_gate == "none"
    assert args.consensus_profile == "none"
    assert args.longterm_profile == "zscore_v4_1"


def test_programmatic_longterm_backtest_defaults_to_official_profile():
    with (
        patch("backtest_v2.get_trade_dates", return_value=[]),
        patch("backtest_v2.get_index_daily", return_value=None),
    ):
        backtest = backtest_v2.BacktestLongterm(
            pro=object(),
            start_date="20250101",
            end_date="20250131",
        )

    assert backtest.longterm_profile == config.get_official_longterm_profile()

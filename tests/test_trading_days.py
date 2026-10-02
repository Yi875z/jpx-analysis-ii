"""短縮週（祝日で営業日が5日未満）の扱い（agents/report_agent.py）。

2026-09-25 週は 9/21〜23 が連休で 9/24〜25 の2営業日しかない。5営業日の週と金額を並べると
「急減」「Zスコアが小さい＝平常」と誤読されるため、営業日数を機械計算してプロンプトに渡す。
通常週ではプロンプトを変えない（過去週の再生成結果を変えない）ことも守る。
"""

from datetime import date

from agents.report_agent import _build_trading_days_facts, _week_first_day, tse_trading_days


def test_silver_week_2026_is_two_days():
    assert tse_trading_days(date(2026, 9, 25)) == [date(2026, 9, 24), date(2026, 9, 25)]
    assert _week_first_day(date(2026, 9, 25)) == date(2026, 9, 24)
    facts = _build_trading_days_facts(date(2026, 9, 25))
    assert "2日" in facts and "09/24・09/25" in facts


def test_normal_week_adds_nothing():
    assert len(tse_trading_days(date(2026, 9, 18))) == 5
    assert _week_first_day(date(2026, 9, 18)) == date(2026, 9, 14)
    assert _build_trading_days_facts(date(2026, 9, 18)) == ""


def test_new_year_closure_counts_as_holiday():
    """12/31 と 1/1〜1/3 は祝日でなくても東証は休場。2027-01-08 週（1/4〜1/8）は5日、
    2026-01-02 週（12/29〜1/2）は 12/29・12/30 の2日。"""
    assert tse_trading_days(date(2026, 1, 2)) == [date(2025, 12, 29), date(2025, 12, 30)]
    assert len(tse_trading_days(date(2027, 1, 8))) == 5

"""
tests/test_report_rules.py
2026-08-06 の外部査読で指摘された P0 項目の回帰テスト。

対象は「AI呼び出しを伴わない純粋関数」に限定する（API課金・非決定性を持ち込まない）。
実行: python -m pytest tests/ -q
"""

from datetime import date, datetime

import pytest

from agents import report_lint
from agents.report_agent import (
    JST,
    _build_calendar_facts,
    _build_nt_bias_facts,
    _build_scheduled_flow_note,
    _build_spot_futures_detail,
    _build_time_axis_facts,
    classify_nt_bias,
    classify_period,
    nt_amounts_by_investor,
)


# ─────────────────────────────────────────────────────────────
# NT方向判定（FIX-001 / P0）
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "nikkei, topix, expected, must_include, must_not_include",
    [
        # 日経買い・TOPIX売り → NTロング方向
        (1000, -800, "NT_LONG_CANDIDATE", "NTロング方向", "NTショート"),
        # 日経売り・TOPIX買い → NTショート方向
        (-1000, 800, "NT_SHORT_CANDIDATE", "NTショート方向", "NTロング"),
        # 両方買い・TOPIX優位（査読で「NTロング」と誤記された実データ相当）
        (1170, 3864, "BOTH_BUY", "TOPIX優位", "NT"),
        # 両方買い・日経優位
        (3000, 1000, "BOTH_BUY", "日経225優位", "NT"),
        # 両方売り・TOPIX側優位
        (-500, -1500, "BOTH_SELL", "TOPIX側の売りが優位", "NT"),
        # 片側ゼロ
        (1000, 0, "ONE_SIDE_ZERO_OR_NEUTRAL", "中立", "NTロング"),
    ],
)
def test_classify_nt_bias(nikkei, topix, expected, must_include, must_not_include):
    result = classify_nt_bias(nikkei, topix)
    assert result["classification"] == expected
    assert must_include in result["label"]
    assert must_not_include not in result["label"]


def test_nt_bias_never_claims_spread_confirmed():
    """どの分類でも「純粋なスプレッド取引」を確定させない。"""
    for n, t in [(1000, -800), (-1000, 800), (1170, 3864), (-500, -1500), (0, 0)]:
        note = classify_nt_bias(n, t)["note"]
        assert ("確認不能" in note) or ("スプレッド取引ではない" in note) or ("使わない" in note)


def test_nt_facts_block_uses_amount_not_lots():
    rows = [
        {"futures_type": "nikkei225_large", "investor_type": "foreign", "net_amount_oku": 1169.6},
        {"futures_type": "nikkei225_mini",  "investor_type": "foreign", "net_amount_oku": 562.1},
        {"futures_type": "topix_large",     "investor_type": "foreign", "net_amount_oku": 3863.8},
        {"futures_type": "topix_mini",      "investor_type": "foreign", "net_amount_oku": -423.2},
    ]
    amounts = nt_amounts_by_investor(rows)
    assert amounts["foreign"]["nikkei"] == pytest.approx(1731.7)
    assert amounts["foreign"]["topix"] == pytest.approx(3440.6)

    # 分類行（投資家名を含む行）が「両指数とも買い越し・TOPIX優位」であること。
    # ブロック冒頭の説明文には用語の使用条件として NTロング/NTショート が出てくるため、
    # 判定行だけを取り出して照合する。
    block = _build_nt_bias_facts(rows)
    verdict = next(ln for ln in block.splitlines() if "海外投資家" in ln)
    assert "両指数とも買い越し" in verdict
    assert "TOPIX優位" in verdict
    assert "NTロング" not in verdict and "NTショート" not in verdict


# ─────────────────────────────────────────────────────────────
# 異種原資産の枚数合算・比較（FIX-002 / P0）
# ─────────────────────────────────────────────────────────────
def test_spot_futures_detail_has_no_cross_product_lot_total():
    """AIに渡すデータに商品をまたぐ「先物合計 ○○枚」を含めない。"""
    context = {"investors": [{"key": "foreign", "label": "海外投資家",
                              "spot_net": -4921.6, "combined_net": 250.8}]}
    rows = [
        {"futures_type": "nikkei225_large", "investor_type": "foreign",
         "net_lots": 1961, "net_amount_oku": 1169.6},
        {"futures_type": "topix_large", "investor_type": "foreign",
         "net_lots": 9747, "net_amount_oku": 3863.8},
    ]
    block = _build_spot_futures_detail(context, rows)
    assert "先物合計（金額のみ）" in block
    # 「先物合計」行に枚数が現れないこと
    total_line = next(ln for ln in block.splitlines() if "先物合計" in ln)
    assert "枚" not in total_line


# ─────────────────────────────────────────────────────────────
# 時間軸（FIX-003 / P0）
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "as_of, expected",
    [
        (date(2026, 8, 1), "FUTURE"),
        (date(2026, 8, 6), "IN_PROGRESS"),
        (date(2026, 8, 10), "PAST"),
    ],
)
def test_classify_period(as_of, expected):
    assert classify_period(as_of, date(2026, 8, 3), date(2026, 8, 7)) == expected


def test_time_axis_facts_in_progress_splits_elapsed_days():
    """査読事例（対象週7/27〜7/31・作成2026-08-06 20:36 JST）を固定ケース化。"""
    block = _build_time_axis_facts(
        date(2026, 7, 31), datetime(2026, 8, 6, 20, 36, tzinfo=JST))
    assert "IN_PROGRESS" in block
    assert "進行中の週（08/03〜08/07）の残存監視項目" in block
    assert "経過済み: 08/03〜08/06" in block
    assert "未経過: 08/07" in block
    assert "「来週」とは書かない" in block


def test_time_axis_facts_future_allows_next_week_heading():
    block = _build_time_axis_facts(
        date(2026, 7, 31), datetime(2026, 7, 31, 18, 0, tzinfo=JST))
    assert "FUTURE" in block
    assert "次週（08/03〜08/07）の注目点" in block
    assert "経過済み" not in block


def test_time_axis_before_close_keeps_today_unfinished():
    """大引け前（15:30以前）の作成なら当日は未経過扱い。"""
    block = _build_time_axis_facts(
        date(2026, 7, 31), datetime(2026, 8, 5, 9, 0, tzinfo=JST))
    assert "経過済み: 08/03〜08/04" in block
    assert "未経過: 08/05〜08/07" in block


# ─────────────────────────────────────────────────────────────
# カレンダー事実・Scheduled Flow（FIX-008 / P1）
# ─────────────────────────────────────────────────────────────
def test_calendar_facts_detects_month_end():
    block = _build_calendar_facts(date(2026, 7, 31))
    assert "07月31日" in block
    assert "四半期末（3/6/9/12月末）: 非該当" in block
    assert "確認不能" in block


def test_calendar_facts_detects_quarter_end():
    assert "四半期末（3/6/9/12月末）: 該当" in _build_calendar_facts(date(2026, 6, 30))


def test_scheduled_flow_note_emits_unconfirmed_when_no_event():
    """7月上旬のETFイベント週以外は「カレンダー未入力＝確認不能」を明示する。"""
    note = _build_scheduled_flow_note(date(2026, 7, 31))
    assert "イベントカレンダー未入力" in note
    assert "確認不能" in note


def test_scheduled_flow_note_keeps_etf_event_block():
    note = _build_scheduled_flow_note(date(2026, 7, 10))
    assert "分配金捻出売り" in note


# ─────────────────────────────────────────────────────────────
# 公開前チェック（report_lint）
# ─────────────────────────────────────────────────────────────
def _rules(findings):
    return {f["rule"] for f in findings}


def test_lint_detects_nt_direction_reversal():
    md = "海外投資家はTOPIXを相対的に強く買い越すNTロング型フローを構築した。"
    findings = report_lint.lint_weekly_report(
        md, nt_classifications={"foreign": "BOTH_BUY"}, next_week_state="FUTURE")
    assert "nt-direction" in _rules(findings)
    assert any(f["severity"] == report_lint.SEVERITY_P0 for f in findings)


def test_lint_allows_nt_long_when_machine_agrees():
    md = "日経225買い・TOPIX売りであり、NTロング方向の組み合わせである。"
    findings = report_lint.lint_weekly_report(
        md, nt_classifications={"foreign": "NT_LONG_CANDIDATE"}, next_week_state="FUTURE")
    assert "nt-direction" not in _rules(findings)


def test_lint_detects_next_week_label_on_elapsed_period():
    md = "## 来週（08/03〜08/07）の注目点"
    findings = report_lint.lint_weekly_report(md, next_week_state="IN_PROGRESS")
    assert "time-axis" in _rules(findings)


def test_lint_allows_next_week_label_when_future():
    md = "## 来週（08/03〜08/07）の注目点"
    findings = report_lint.lint_weekly_report(md, next_week_state="FUTURE")
    assert "time-axis" not in _rules(findings)


def test_lint_detects_cross_product_lot_total():
    md = "- 先物合計: -20,543枚 / -5,676.3億円"
    assert "cross-product-lots" in _rules(report_lint.lint_weekly_report(md))


def test_lint_detects_dealer_mm_conflation_and_purpose_claims():
    md = ("### 自己（MM）のガンマ・ポジション\n"
          "海外投資家はプットを買い越しており、下方ヘッジ姿勢が鮮明である。")
    rules = _rules(report_lint.lint_weekly_report(md))
    assert "dealer-is-not-mm" in rules
    assert "option-purpose" in rules


def test_lint_uniqueness_scope():
    bad = "投資信託が唯一のTwin-Buy主体だった。"
    ok = "表示対象6主体の中で唯一、投資信託が現物・先物とも買い越した。"
    assert "uniqueness-scope" in _rules(report_lint.lint_weekly_report(bad))
    assert "uniqueness-scope" not in _rules(report_lint.lint_weekly_report(ok))


@pytest.mark.parametrize(
    "line",
    [
        # 2026-08-07 再生成レポートの実文。規律に従った免責文を違反として拾わないこと
        "- **両指数とも買い越し（金額ベースでTOPIX優位）**。これは**スプレッド取引ではなく、"
        "NTロング／NTショートの語は適用しない**。",
        "両指数とも買い越しのためスプレッド取引ではなく、NTロング/NTショートの語は使わない。",
        "- なお、**ネット集計から相対取引の相手方は特定できない**ため、"
        "「誰が誰の反対側に立った」とは断定しない。",
        "- 相対取引の相手方（カウンターパーティ）は投資部門別ネット集計から**特定不能**。",
        "- ただし、既存ロングのヘッジ／新規の弱気ポジション／スプレッドの一部のいずれであるかは、"
        "**限月・行使価格・建玉増減が無いため確認不能**。「ヘッジを行った」と目的で断定しない。",
    ],
)
def test_lint_ignores_disclaimer_lines(line):
    """レポートが規律どおり書いた免責文でP0が誤検出されないこと。"""
    findings = report_lint.lint_weekly_report(
        line, nt_classifications={"foreign": "BOTH_BUY"}, next_week_state="IN_PROGRESS")
    assert findings == []


def test_lint_clean_report_has_no_findings():
    md = (
        "海外投資家は日経225先物、TOPIX先物をともに買い越した。\n"
        "買い越し金額はTOPIX側が大きく、TOPIX優位の買い越しだった。\n"
        "先物合計（金額）: +5,172.3億円。\n"
        "自己部門を用いたProxy GEX判定では-GEX方向のバイアスが示唆される。\n"
        "表示対象6主体の中で唯一、投資信託が現物・先物とも買い越した。\n"
        "## 進行中の週（08/03〜08/07）の残存監視項目\n"
    )
    findings = report_lint.lint_weekly_report(
        md, nt_classifications={"foreign": "BOTH_BUY"}, next_week_state="IN_PROGRESS")
    assert findings == []

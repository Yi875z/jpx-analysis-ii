"""
agents/report_lint.py
生成された週次レポートを機械判定の事実と突き合わせる公開前チェック（リリースゲート）。

2026-08-06 の外部査読で、system プロンプトの規律だけでは防ぎきれなかった
「NT方向の反転」「経過済みの週を来週と表記」「商品をまたぐ合計枚数」等が
本番レポートに出た。プロンプトに加えて出力側でも検出できるようにする。

判定は決定的（正規表現＋機械判定済みの分類との突き合わせ）に限定し、
曖昧な文意判定は行わない。検出しても生成は止めず WARNING を出す
（自動ワークフローを落とさない。人間が再生成を判断する）。
"""

import re

# P0: 結論・方向が反転する誤り。検出されたら再生成を検討する
# P1: 表現規律違反。表現修正が望ましい
SEVERITY_P0 = "P0"
SEVERITY_P1 = "P1"


# レポートは規律に従って「〜とは断定しない」「NTロングの語は使わない」「確認不能」等の
# 免責文を本文に書く。これを違反として拾うと毎回P0が誤検出され、警告が形骸化する。
# 否定・留保の手がかりを含む行は違反とみなさない（再現率より適合率を優先する。
# 深い検証は外部査読で行う前提）。
_NEGATION_CUES = re.compile(
    r"ではな|しない|しません|せず|できな|不能|不可|わない|かない|らない|禁止|留保|べきでな"
)


def _hit(pattern: str, text: str) -> list[str]:
    """パターンに一致した行を返す（否定・留保の文脈は除外する）。"""
    rx = re.compile(pattern)
    return [ln.strip() for ln in text.splitlines()
            if rx.search(ln) and not _NEGATION_CUES.search(ln)]


def lint_weekly_report(report_md: str,
                       nt_classifications: dict[str, str] | None = None,
                       next_week_state: str | None = None) -> list[dict]:
    """週次レポート本文を検査し、検出した違反のリストを返す。

    Parameters
    ----------
    report_md : str
        生成されたレポート本文（Markdown）
    nt_classifications : dict[str, str] | None
        投資家キー -> classify_nt_bias() の classification。
        NTロング/NTショートの語が機械判定と食い違わないか照合する。
    next_week_state : str | None
        classify_period() が返した対象週の翌週の状態（PAST / IN_PROGRESS / FUTURE）。
    """
    findings: list[dict] = []

    def add(severity: str, rule: str, message: str, lines: list[str]) -> None:
        if lines:
            findings.append({
                "severity": severity,
                "rule": rule,
                "message": message,
                "lines": lines[:3],
            })

    # ── P0: NT方向の反転 ───────────────────────────────────────
    # 機械判定でNTロング候補（日経買い・TOPIX売り）の主体が一人もいないのに
    # 本文が「NTロング」と書いていれば、TOPIX優位を逆方向に読んでいる可能性が高い。
    if nt_classifications is not None:
        classes = set(nt_classifications.values())
        if "NT_LONG_CANDIDATE" not in classes:
            add(SEVERITY_P0, "nt-direction",
                "機械判定にNTロング候補（日経225買い越し・TOPIX売り越し）が無いのに「NTロング」と表記",
                _hit(r"NTロング", report_md))
        if "NT_SHORT_CANDIDATE" not in classes:
            add(SEVERITY_P0, "nt-direction",
                "機械判定にNTショート候補（日経225売り越し・TOPIX買い越し）が無いのに「NTショート」と表記",
                _hit(r"NTショート", report_md))

    # ── P0: 時制の不整合 ──────────────────────────────────────
    if next_week_state in ("PAST", "IN_PROGRESS"):
        add(SEVERITY_P0, "time-axis",
            f"対象週の翌週は作成時点で {next_week_state} なのに「来週」と表記",
            _hit(r"来週", report_md))

    # ── P0: 商品をまたぐ合計枚数 ──────────────────────────────
    add(SEVERITY_P0, "cross-product-lots",
        "商品をまたぐ「先物合計」を枚数で記載（乗数・原資産が異なるため経済量として無効）",
        _hit(r"先物合計[^|\n]{0,20}[-+\d,]+\s*枚", report_md))

    # ── P0: ラージ換算枚数による日経 vs TOPIX の規模比較 ──────
    add(SEVERITY_P0, "cross-product-compare",
        "ラージ換算枚数で日経225とTOPIXの規模を倍率比較（原資産をまたぐ比較は金額のみ）",
        _hit(r"ラージ換算[^\n]{0,40}(?:倍|上回|下回)", report_md))

    # ── P1: 自己部門とMMの同一視 ──────────────────────────────
    add(SEVERITY_P1, "dealer-is-not-mm",
        "自己部門をMMと同一視する表記（自己部門は在庫・顧客反対売買を含む）",
        _hit(r"自己\s*[（(]\s*MM\s*[）)]", report_md))

    # ── P1: オプション取引目的の断定 ──────────────────────────
    add(SEVERITY_P1, "option-purpose",
        "オプションの取引目的を断定（限月・行使価格・建玉増減が無いため確認不能）",
        _hit(r"(?:ヘッジ姿勢|ヘッジを行っ|保険を掛け|リスクオフ志向|ベア・コンビネーション|ブル・コンビネーション)",
             report_md))

    # ── P1: 相手方の断定 ──────────────────────────────────────
    add(SEVERITY_P1, "counterparty",
        "ネット集計から特定できない相対取引の相手方を断定",
        _hit(r"カウンターパーティ|の反対側|受け皿", report_md))

    # ── P1: 唯一性の範囲未明示 ────────────────────────────────
    add(SEVERITY_P1, "uniqueness-scope",
        "対象範囲を示さない「唯一」表現（本データは6主体のみ）",
        [ln for ln in _hit(r"唯一", report_md) if "表示対象" not in ln])

    # ── P1: 確定的なGEX断定 ───────────────────────────────────
    add(SEVERITY_P1, "gex-proxy",
        "Proxy判定でしかないGEX環境を断定（「-GEX環境である」等）",
        _hit(r"[-＋+−]?GEX環境(?:である|だ|に入っ)|ネガティブガンマ環境である", report_md))

    return findings


def format_findings(findings: list[dict]) -> list[str]:
    """ログ出力用に1行ずつ整形する。"""
    out = []
    for f in findings:
        sample = f" 例: {f['lines'][0][:60]}" if f["lines"] else ""
        out.append(f"[{f['severity']}] {f['rule']}: {f['message']}{sample}")
    return out

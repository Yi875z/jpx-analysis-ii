# Advisor Tool 統合アップグレード指示書
## JPX投資主体別売買動向システム向け

**対象システム:** JPX投資家別売買動向分析システム（Supabase + Python + n8n）  
**指示日:** 2026年4月13日  
**目的:** Anthropic Advisor Tool（Beta）をシステムに統合し、コスト効率を維持しながらレポート解釈品質を大幅向上させる

---

## 1. 背景と目的の理解

このシステムの処理フローには、性質が根本的に異なる2種類の作業が混在している。

**機械的作業（全体の約95%）:** CSVの取得・パース、Supabaseへのデータ挿入、集計クエリの実行、Markdownテンプレートへの数値埋め込み。これらはSonnet/Haiku（高速・低コスト）で処理すべき仕事。

**解釈・判断作業（全体の約5%）:** 「今週の外国人売り越しは構造的リスクオフなのかSQ週のポジション整理なのか」「信託銀行の買いはGPIFリバランスなのか」といった、マクロ文脈・季節性・オプション建玉・円相場を統合した判断。これはOpus（高知性）が担うべき仕事。

**Advisor Toolとは:**  
AnthropicのBeta機能（`advisor-tool-2026-03-01`）で、Executor（Sonnet/Haiku）がタスク実行中に判断困難な局面に遭遇した際、Advisor（Opus）に戦略的助言を求められる仕組み。全処理は単一の `/v1/messages` リクエスト内で完結する。APIリクエストに以下を追加するだけで動作する。

```http
Header: anthropic-beta: advisor-tool-2026-03-01
Tool: {"type": "advisor_20260301", "name": "advisor", "model": "claude-opus-4-6"}
```

---

## 2. 現状コードベースの調査タスク

以下のファイルとディレクトリを調査し、現在の実装状況を把握すること。

```
調査対象:
- parse_futures_csv_v2.py（先物CSVパーサー）
- Supabaseクライアントの初期化コード
- n8nワークフローのHTTP Requestノード設定（エクスポートJSONがあれば）
- レポート生成ロジック（Markdown出力部分）
- requirements.txt または pyproject.toml
```

調査で確認すべき点は次の通り。現在のAnthropicライブラリのバージョン、APIキーの管理方法（環境変数名）、レポート生成でAnthropicを呼び出している箇所があるか、n8nとPythonの連携方式（webhookかHTTP Requestか）。

---

## 3. 実装タスク（優先順位順）

### タスク1：Pythonラッパーモジュールの作成（最優先）

`advisor_client.py` という新規モジュールを作成すること。このモジュールはAdvisor Toolを有効化したAnthropicクライアントのラッパーで、システム全体から再利用できる形にする。

```python
# advisor_client.py
# Advisor Tool（Beta）を有効化したAnthropicクライアントラッパー
# JPX投資主体別売買動向システム専用

import anthropic
import os
from typing import Optional

EXECUTOR_MODEL = "claude-sonnet-4-6"       # 実行モデル（高速・低コスト）
ADVISOR_MODEL  = "claude-opus-4-6"          # 助言モデル（高知性）
BETA_HEADER    = "advisor-tool-2026-03-01"  # Betaヘッダー

ADVISOR_TOOL_DEFINITION = {
    "type": "advisor_20260301",
    "name": "advisor",
    "model": ADVISOR_MODEL,
}

def create_advisor_client() -> anthropic.Anthropic:
    """Advisor Tool対応のAnthropicクライアントを生成する"""
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        default_headers={"anthropic-beta": BETA_HEADER},
    )

def call_with_advisor(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
    advisor_enabled: bool = True,
) -> str:
    """
    Advisor Tool付きでAnthropicを呼び出す。
    
    advisor_enabled=Falseにすると通常のSonnet単体呼び出しになり、
    コストとアドバイザー呼び出しをA/Bテストできる。
    """
    client = create_advisor_client()
    tools = [ADVISOR_TOOL_DEFINITION] if advisor_enabled else []

    response = client.messages.create(
        model=EXECUTOR_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        tools=tools,
    )

    # レスポンスからテキストブロックだけ抽出して返す
    text_blocks = [
        block.text for block in response.content
        if hasattr(block, "text")
    ]
    return "\n".join(text_blocks)
```

### タスク2：レポート生成への組み込み

既存のレポート生成コードを特定し、以下の2箇所にAdvisorの呼び出しポイントを追加すること。

**呼び出しポイントA（データ読み込み直後・解釈開始前）:**  
Supabaseから週次データを取得してテーブルに整形した直後に、Opusへ解釈の方向性を問う。この呼び出しは「解釈の地図」を得るためのもので、その後のレポート本文生成でSonnetはこの地図に従って書く。

```python
# レポート生成関数内の、データ取得完了直後に追加する

def generate_weekly_report(weekly_data: dict) -> str:
    
    # --- ① データ整形（既存コード）---
    summary_table = format_summary_table(weekly_data)
    
    # --- ② Advisor呼び出しポイントA：解釈の地図を取得 ---
    # ここでOpusに解釈の方向性を問い、Sonnetはその指針でレポートを書く
    interpretation_guide = call_with_advisor(
        system_prompt=REPORT_SYSTEM_PROMPT,
        user_message=build_interpretation_query(summary_table),
        advisor_enabled=True,
    )
    
    # --- ③ レポート本文生成（Sonnetがinterpretation_guideを参照）---
    draft = call_with_advisor(
        system_prompt=REPORT_SYSTEM_PROMPT,
        user_message=build_draft_query(summary_table, interpretation_guide),
        advisor_enabled=False,  # ドラフト生成はSonnet単体で十分
    )
    
    # --- ④ Advisor呼び出しポイントB：最終査読 ---
    # ドラフト完成後にOpusが重大な見落としや解釈の誤りを検出する
    final_report = call_with_advisor(
        system_prompt=REPORT_SYSTEM_PROMPT,
        user_message=build_review_query(draft, weekly_data),
        advisor_enabled=True,
    )
    
    return final_report
```

**解釈クエリの構築関数（新規追加）:**

```python
def build_interpretation_query(summary_table: str) -> str:
    """Advisor呼び出しポイントA用のクエリを構築する"""
    return f"""
以下の今週のJPX投資主体別売買動向データを確認してください。

{summary_table}

このデータの解釈に入る前に、以下を判断してください：
1. 外国人の動向は「構造的リスクオフ」「SQ週ポジション整理」「テクニカルリバランス」のどれに近いか
2. 信託銀行の動きはGPIFリバランスの可能性があるか
3. 個人の動向は逆張り買いとして解釈すべき水準か
4. 今週特に注目すべき投資主体の組み合わせはどれか

分析の方向性を示す「解釈の地図」を200字以内で返してください。
"""

def build_review_query(draft: str, weekly_data: dict) -> str:
    """Advisor呼び出しポイントB用の査読クエリを構築する"""
    return f"""
以下のドラフトレポートを投資判断の観点から査読してください。

【ドラフト】
{draft}

【元データサマリー】
外国人現物: {weekly_data.get('foreign_spot')}億円
外国人先物: {weekly_data.get('foreign_futures')}枚
信託銀行現物: {weekly_data.get('trust_spot')}億円
個人現物: {weekly_data.get('individual_spot')}億円

確認ポイント：
- 外国人動向の持続性について重大な見落としがないか
- 個人の逆張りタイミング判断に誤りがないか
- マクロ文脈（VIX・円相場）との整合性が取れているか

修正が必要な場合は修正済みの最終レポートを出力し、問題がなければドラフトをそのまま返してください。
"""
```

### タスク3：CLAUDE.md へのAdvisor使用ルール追記

プロジェクトルートの `CLAUDE.md`（なければ新規作成）に以下を追記すること。これによりClaude Code自身がCursor内で作業する際に、適切なタイミングでAdvisorを呼ぶようになる。

```markdown
## Advisor Tool の使用ルール（JPXシステム用）

Claude Codeとしてこのリポジトリで作業する際、以下の局面では必ず `/advisor` を実行すること。

**必須タイミング（実質的な作業の前）:**
- 新規テーブルスキーマ設計時（Supabaseのカラム追加・変更を含む）
- parse_futures_csv_v2.py のプロダクトコードマッピングやunit変換ロジックを変更する前
- レポート生成ロジックの解釈アルゴリズムを変更する前
- n8nワークフローの分岐ロジックや新ノード追加を設計する前

**不要なタイミング（通常のSonnetで進める）:**
- 既存パーサーの軽微なバグ修正（タイポ・変数名修正など）
- Markdownテンプレートの文言調整
- SELECT文のみのSupabaseクエリ調整
- ログ出力の追加

**Advisorへの質問フォーマット:**
実質的な作業開始前に、変更の意図・対象ファイル・懸念点を簡潔に伝えてから /advisor を呼ぶこと。
```

### タスク4：n8nワークフロー用HTTPリクエスト設定の出力

n8nからAdvisor Tool付きAPIを呼べるよう、HTTP Requestノードの設定JSONを生成すること。以下のテンプレートを参考に、実際のワークフロー構造に合わせて調整する。

```json
{
  "name": "JPX Report - Advisor API Call",
  "type": "n8n-nodes-base.httpRequest",
  "parameters": {
    "method": "POST",
    "url": "https://api.anthropic.com/v1/messages",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        { "name": "x-api-key",       "value": "={{ $env.ANTHROPIC_API_KEY }}" },
        { "name": "anthropic-version","value": "2023-06-01" },
        { "name": "content-type",    "value": "application/json" },
        { "name": "anthropic-beta",  "value": "advisor-tool-2026-03-01" }
      ]
    },
    "sendBody": true,
    "contentType": "json",
    "body": {
      "model": "claude-sonnet-4-6",
      "max_tokens": 4096,
      "tools": [
        {
          "type": "advisor_20260301",
          "name": "advisor",
          "model": "claude-opus-4-6"
        }
      ],
      "system": "={{ $json.system_prompt }}",
      "messages": [
        {
          "role": "user",
          "content": "={{ $json.user_message }}"
        }
      ]
    }
  }
}
```

---

## 4. 確認・検証タスク

実装完了後に以下を確認すること。

**動作確認（必須）:**

```bash
# Advisor Tool有効でのテスト呼び出し
python -c "
from advisor_client import call_with_advisor
result = call_with_advisor(
    system_prompt='あなたはJPX投資主体別データの分析エキスパートです。',
    user_message='外国人が現物で3000億円売り越した場合、最初に確認すべき文脈は何ですか？',
    advisor_enabled=True,
)
print(result)
"
```

**コスト確認:**  
Advisorはトークン消費量をレスポンスの `usage` フィールドに含む。`iterations` フィールドを確認し、1レポート生成あたりAdvisorが何回呼ばれたかを記録すること。週次運用での月間コスト試算も行うこと。

**A/Bテスト（推奨）:**  
既存のサンプルデータを使い、`advisor_enabled=True` と `advisor_enabled=False` で同じレポートを生成し、解釈の深さを比較すること。

---

## 5. 実装上の注意点

**Betaの制限事項について:**  
現時点でAdvisor Toolはクラウド上のAnthropicAPIでのみ動作する。VertexAI経由では未対応の可能性があるため、直接APIを使うこと。

**マルチターン会話での注意:**  
会話履歴に `advisor_tool_result` ブロックが含まれる場合、次のリクエストにもそのブロックを含めること。省略すると400エラーになる。

**コスト上限の設定:**  
Advisorはデフォルトでは呼び出し回数に上限がない。1会話あたりの上限をクライアントサイドでカウントし、上限到達後は `tools` 配列からAdvisorを除外すること（推奨上限：レポート1本あたり3回）。

---

## 6. 完了報告のフォーマット

実装完了後、以下の形式で報告すること。

```
## 実装完了報告

### 作成・変更したファイル
- advisor_client.py（新規）
- [レポート生成ファイル名]（変更）
- CLAUDE.md（追記）
- n8n設定JSON（新規）

### Advisor呼び出しポイントの設置箇所
- [具体的な関数名・行番号]

### テスト結果
- 動作確認：OK / エラー詳細
- A/Bテスト：解釈品質の比較コメント

### 懸念点・要確認事項
- [あれば記載]
```

---

*この指示書はAnthropicのAdvisor Tool公式ドキュメント（advisor-tool-2026-03-01 Beta）に基づいて作成。*

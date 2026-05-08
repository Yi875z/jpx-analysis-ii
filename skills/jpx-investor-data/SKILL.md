---
name: jpx-investor-data
description: >
  JPX（日本取引所グループ）の投資家別売買動向データを取得・集計・分析し、
  週次・月次レポートをMarkdown／Excel／PDFで生成するスキル。
  現物（東証プライム）と先物（日経225・TOPIX）の両方を対象に、
  海外投資家・個人・投信信託銀行・事業法人・自己（証券会社）の
  買い越し・売り越しサマリー、先週比・前月比変化分析、セグメント別ハイライトを出力する。
  GEX環境判定・マクロ文脈・季節性アノマリーを加味した「解釈付き」需給レポートを生成できる。
  ユーザーが「JPX投資家別」「売買動向」「外国人の買い越し」「投資主体別」
  「需給分析」「先物現物の投資家動向」「週次需給レポート」「両輪買い」
  「信託銀行の動向」「GPIFのリバランス」などと言った場合は必ずこのスキルを使うこと。
  CSVアップロードでもJPXサイト自動取得でも両方に対応する。
---

# JPX投資家別売買動向スキル（アップグレード版）

## 概要

JPXが毎週木曜公表する「投資部門別売買状況」を取得・解析し、
現物と先物を分離した投資家別需給レポートを自動生成する。

本スキルは**2層構造**で設計されている：
1. **データ処理層**: CSVの取得・パース・集計（scripts/）
2. **解釈・判断層**: 知識ファイルを参照した「意味のあるコメント」の生成（references/）

---

## データソース

### 自動取得モード（JPXサイト）

```
現物（東証プライム）:
https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html

先物（日経225・TOPIX先物）:
https://www.jpx.co.jp/markets/statistics-derivatives/sector/index.html
```

`main.py` が自動的に上記URLからXLS/CSVをダウンロードして処理する。
```bash
python main.py
```

### 手動アップロードモード
```bash
python main.py --spot stock_val_1_YYMMWW.xls --futures Tousi_DV_W_YYYYMM_N_MMDD_MMDD.csv --date YYYY-MM-DD
```

---

## 対象投資家区分

| 内部名 | JPX表記（例） | 解釈の性質 |
|--------|--------------|-----------|
| foreign | 海外投資家（外国人） | トレンドセッター（最重要） |
| individual | 個人投資家 | 逆張り傾向（養分になりやすい） |
| trust_bank | 信託銀行 | GPIF主体、機械的リバランス逆張り |
| inv_trust | 投資信託 | アクティブ・パッシブ混在 |
| corporate | 事業法人 | 自社株買い、下落時サポート |
| dealer | 自己（証券会社） | デルタヘッジ由来の機械的フロー |

カラム名の詳細マッピング → `references/column_map.md`

---

## 分析ロジック

### 1. 買い越し・売り越し計算
```
net_buy = 買い付け額 - 売り付け額
正値 → 買い越し（▲表示）
負値 → 売り越し（▼表示）
```

### 2. 比較分析
- **先週比**: 当週net_buy - 前週net_buy
- **前月比**: 当月累計 - 前月累計（月次レポート時）
- **4週移動平均**: トレンド把握用（オプション）

### 3. 現物・先物の分離集計
現物と先物を必ず別テーブルで集計し、最後に合算サマリーも出す。

---

## 解釈コメントの生成ルール

レポートのセグメント別ハイライトを書く際は、必ず以下のファイルを参照すること。

### `references/jpx_micro_flows.md`（最重要）
- 各投資家区分の行動原理の解釈
- 「両輪買い（Twin Engine）」判定（現物買い＋先物買い＝最強強気シグナル）
- 「裁定買い」と「本物の買い」の区別（現物買い＋先物売り＝見かけほど強くない）
- 信託銀行＝GPIF逆張りロジック
- J-NET取引の解釈（ロールオーバー判定）
- CVDフラット化＝フロー枯渇のサイン

### `references/options_gex_master.md`
- 現在のGEX環境（+GEX / -GEX）を判定し、レポートに一行記載する
- 先物データから建玉集中ストライク（マグネット/Pinning）を特定
- GEX環境に応じた戦略示唆を最後のセクションに追記
- 日経VIの水準（25超=IV高い/18未満=IV低い）とレポートの推奨戦略を連動させる

### `references/global_macro_dynamics.md`
- IMM円ショートの状況とのクロスチェック（「円ショート極値なら円高リスクあり」等）
- 日銀・FRBのイベント有無（今週・来週）を確認し文脈として記載
- 季節性アノマリーが該当する場合は必ず言及
  - 月末 → リバランス売り圧力の有無
  - SQ週 → 魔の水曜日・Pinning効果
  - 8月 → 夏枯れ・お盆ショック警戒
  - 3月末 → 配当落ち・ドレッシング買い
  - 4月 → 海外勢新年度買いのアノマリー

### `references/quant_tech_psychology.md`（任意）
- VWAPとの乖離、出来高の裏付けについて補足コメントを追加
- Zスコア的な観点で「現在の買い越し額は過去と比較して統計的に高いか/低いか」に言及
- ユーザーの言動に「FOMO」「リベンジトレード」「確証バイアス」の兆候があれば警告を追記

---

## セグメント別ハイライトの書き方

`jpx_micro_flows.md` の解釈ルールに基づき、以下の優先順で記述：

### 🔵 海外投資家（常に最優先）
- 現物・先物のネットを確認
- 「両輪買い（現物買い＋先物買い）」→ 最強の強気シグナルとして明記
- 「裁定買い（現物買い＋先物売り）」→「見かけほど強くない」と明記
- 2週以上連続の方向性 → トレンド継続性に言及

### 🟡 個人投資家（逆張りチェック）
- 海外勢と逆の方向か確認
- 「逆張り傾向」「信用買い残の状況」に言及

### 🟢 投信・信託銀行（GPIF逆張り）
- 急落局面での買いを「GPIFリバランス発動の可能性」と解釈
- 急騰局面での売りを「健全な調整売り、ただし上値の重し」と解釈

### 🟠 事業法人・自己（特異動向のみ）
- 異常値（過去平均の2倍以上）が出た時のみ言及
- 事業法人の大口買いは「自社株買い強化」として解釈

---

## 出力フォーマット

### A. Markdownレポート（必須）

`references/report_template.md` のフォーマットを使用。
ファイル名: `jpx_investor_YYYYMMDD.md`

構成:
```
# JPX投資家別売買動向 YYYY年MM月DD日週
## エグゼクティブサマリー（3〜5行）
## マクロ・市場環境（GEX環境・季節性・マクロ文脈） ← アップグレードで新規追加
## 現物：投資家別買い越し・売り越し
## 先物：投資家別買い越し・売り越し
## 合算：現物＋先物ネット
## 注目セグメント動向（解釈付きハイライト）
## 先週比・前月比変化
## 戦略示唆（GEX環境に応じた推奨アプローチ） ← アップグレードで新規追加
```

### B. Excelファイル
`scripts/build_excel.py` で生成（`main.py` から自動呼び出し）。
ファイル: `outputs/excel/jpx_investor_YYYY.xlsx`
シート: 現物 / 先物 / 合算 / 月次サマリー（月次時のみ）

### C. Google Drive出力（オプション）
「Driveに保存して」と言われた場合のみ。Google Drive MCPを使用。

---

## 週次・月次レポートの違い

| 項目 | 週次 | 月次 |
|------|------|------|
| 比較基準 | 前週比 | 前月比 |
| 期間集計 | 当週のみ | 月累計 |
| アノマリー言及 | 今週の特異日 | 月全体の季節性 |
| ハイライト行数 | 3〜5行 | 5〜8行 |

---

## 実行フロー

```
python main.py  （木曜日：全自動）
  ↓
1. データ取得
   ├── 自動モード → scripts/fetch_jpx.py（JPXサイトからXLS/CSVをDL）
   └── 手動モード → --spot / --futures / --date 引数で指定

2. データパース
   ├── 現物XLS → scripts/parse_spot_xls.py（行インデックスベース）
   └── 先物CSV → scripts/parse_futures_csv.py（列インデックスベース・ヘッダーなし）

3. Supabaseへ保存
   └── db/supabase_client.py（weekly_spot / weekly_futures / weekly_combined upsert）

4. Z-スコア・統計分析
   └── scripts/analyze_jpx.py（26週移動平均・Z-スコア・合算計算）

5. AIレポート生成（Claude API）
   └── agents/report_agent.py
       ├── references/jpx_micro_flows.md    ← 投資家行動原理の解釈（必須）
       ├── references/options_gex_master.md ← GEX環境判定・Pinning（必須）
       ├── references/global_macro_dynamics.md ← マクロ文脈・季節性（必須）
       └── references/quant_tech_psychology.md ← Z-スコア補足（任意）

6. 出力
   ├── outputs/reports/jpx_investor_YYYYMMDD.md
   └── outputs/excel/jpx_investor_YYYY.xlsx（build_excel.py）

月次集計: python main.py --monthly YYYY-MM
```

---

## エラーハンドリング

- JPXサイト構造変更でCSVが取得できない場合 → ユーザーに手動DLを依頼し、手動モードで続行
- カラム名が異なる場合 → `references/column_map.md` の別名マッピングを試みる
- データ欠損（特定週のデータなし）→ 欠損を明示したうえで利用可能なデータで集計
- 先物単位（枚 vs 億円）不一致 → `references/unit_conversion.md` を参照

---

## 参照ファイル一覧

| ファイル | 用途 | 参照タイミング |
|---------|------|--------------|
| `references/jpx_micro_flows.md` | 投資家行動原理・CVD解釈 | セグメントハイライト生成時（必須） |
| `references/options_gex_master.md` | GEX環境判定・オプション戦略 | 戦略示唆セクション生成時（必須） |
| `references/global_macro_dynamics.md` | マクロ文脈・季節性アノマリー | マクロ環境セクション生成時（必須） |
| `references/quant_tech_psychology.md` | テクニカル・統計補足 | Zスコア言及・心理コメント時（任意） |
| `references/column_map.md` | JPX CSVカラム名マッピング | データパース時（必須） |
| `references/report_template.md` | Markdownレポートひな型 | MD生成時（必須） |
| `references/unit_conversion.md` | 先物単位換算 | 合算集計時（必須） |

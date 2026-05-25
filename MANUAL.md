# JPX需給分析システム 操作マニュアル

**最終更新: 2026-05-25**

> 🌐 **公開URL（要認証）**: https://jpx-investor-flow.streamlit.app
> 本機を起動していなくても、スマホ・別PCから外出先でも閲覧可能。

---

## 1. システム全体像

JPX（日本取引所グループ）が毎週木曜に公表する「投資部門別売買状況」を自動で取得・分析し、AIレポートとExcelグラフを生成するシステムです。

```
JPXサイト（毎週木曜）
  ↓ 自動ダウンロード（fetch_jpx.py）
  ↓ JPXページから対象期間を自動解決して week_date を補正
現物XLS + 先物・オプションCSV
  ↓ パース・Supabase保存
weekly_spot / weekly_futures / weekly_options テーブル
  ↓ Zスコア・統計分析（analyze_jpx.py）
Claude API（AIレポート生成・プロンプトキャッシュ有効）
  ↓
週次MDレポート + Excel更新
  ↓ Gmail通知
y.ioku1973@gmail.com

Streamlitダッシュボード（localhost:8503 / LAN・Tailscale経由でも閲覧可）
  ↑ Supabaseから直接読み込み（常時参照可）
```

### 対象投資家区分

| 内部名 | 表示名 | 見るポイント |
|--------|--------|-------------|
| foreign | 海外投資家 | 最重要。トレンドの方向性を決める |
| individual | 個人投資家 | 逆張り傾向。海外と逆方向なら典型パターン |
| trust_bank | 信託銀行 | GPIFリバランス。急落時の買いは年金底値拾い |
| inv_trust | 投資信託 | アクティブ・パッシブ混在 |
| corporate | 事業法人 | 自社株買い。下落局面のサポート |
| dealer | 自己（証券会社） | デルタヘッジ。機械的フロー |

---

## 2. ダッシュボード操作

### 起動方法（推奨：ワンタッチ）

プロジェクト直下の **`dashboard.bat`** をダブルクリック。
- 既に起動中なら → ブラウザだけ自動で開く
- 未起動なら → Streamlit を `0.0.0.0:8503` で起動 → ブラウザで開く

PowerShellから起動する場合：
```powershell
cd C:\CarSol\jpx-analysis
streamlit run dashboard/app.py --server.port 8503 --server.headless true --server.address 0.0.0.0
```

### アクセスURL

| 環境 | URL |
|---|---|
| 本機 | `http://localhost:8503` |
| 同じWi-Fi内の別PC・スマホ | `http://192.168.11.12:8503`（Wi-FiのIPは可変） |
| Tailscale経由（外出先含む・本機ON必要） | `http://is-2025-lenovo:8503`（MagicDNS有効時）<br>または `http://100.90.57.39:8503` |
| **Streamlit Cloud（本機OFFでも閲覧可・要認証）** | **https://jpx-investor-flow.streamlit.app** |

> Tailscale を利用する場合はスマホ・別PCにも Tailscale アプリをインストールして本機と同じアカウントでログインする。MagicDNSをONにしておくと短いデバイス名でアクセス可能。
>
> Streamlit Cloud は本機を起動していなくてもクラウド側で常時稼働。Username `yioku` + bcrypt生成時のパスワードでログイン。データ取得・AIレポート生成は本機側で行い、結果は Supabase 経由で Cloud へ反映される。

### 共通操作（全ページ共通）

**サイドバー**に以下の設定が存在する（ページごとに一部異なる）。

- **表示期間**: 4週・13週・26週・52週から選択。グラフの表示範囲が変わる。
- **投資家フィルター**: 表示する投資家をチェックボックスで選択。デフォルトは外国人・信託銀行・個人の3者。
- **ダーク/ライト切り替えボタン**: テーマを切り替える。切り替えはセッション中のみ有効（再起動でライトモードに戻る）。
- **キャッシュ更新ボタン**: データキャッシュを強制クリアしてSupabaseから再取得する。新しいデータが反映されない場合に使う。

**各ページ共通: AI解釈expander**
各ナビゲーション（1_現物フロー / 2_先物フロー / 3_合算分析 / 4_Zスコア / 5_月次集計 / 7_オプション）のタイトル直下に「📋 ○○ — 最新週AI解釈」expander が表示される。クリックすると最新週のAIレポートから該当セクションだけ抜粋表示される。グラフを見ながら解釈を確認できる。

---

### トップ画面（`app.py`）

`http://localhost:8501` を開いた最初の画面。

**KPIカード（3枚）**
外国人・信託銀行・個人の直近週の現物NET（億円）と前週比を表示する。値がプラスなら緑、マイナスなら赤で表示される。左端のボーダー色でも方向が一目でわかる。

**ツインエンジン判定**
外国人が現物・先物の両方で買い越しの場合に「🟢 ON」と表示される。現物・先物どちらかが売り越しであれば「⚪ OFF」となる。ツインエンジンONは上昇エネルギーが強い局面を示す。

**4週間NET推移グラフ**
直近4週の現物・先物合算NETを投資家別に折れ線で表示する。短期トレンドの確認に使う。

---

### ページ1: 現物フロー

**概要**: `weekly_spot` テーブルの週次データを可視化する。

**グラフ1 — 投資家別NET推移（折れ線）**
選択した投資家の現物NET（億円）を週次折れ線で比較表示する。複数投資家の方向の一致・乖離を俯瞰するのに使う。

**グラフ2 — 買い越し/売り越し棒グラフ（投資家別タブ）**
1投資家ずつタブで切り替えて棒グラフを表示する。プラスが青緑（買い越し）、マイナスが赤（売り越し）。週ごとの強弱の変化を視覚的に確認できる。

**サイドバー固有設定**
- 表示期間: 4/13/26/52週
- 投資家フィルター
- 市場: 合計 / 東証プライム / 東証スタンダード（切り替え）

---

### ページ2: 先物フロー

**概要**: `weekly_futures` テーブルの週次データ。日経225先物とTOPIX先物をタブで切り替えて表示する。

**タブ: 日経225先物 / TOPIX先物**
それぞれのタブで2つのグラフを表示する。

**グラフ1 — NET推移（枚）**
建て玉のネット枚数（ロット）推移。先物の量的な変化を見る際に使う。

**グラフ2 — NET推移（億円換算）**
枚数を時価換算した億円ベースの棒グラフ。現物データと金額ベースで比較しやすくなる。同一投資家の棒を色分けして表示（投資家ごとに固有色）。

**サイドバー固有設定**
- 表示期間: 4/13/26/52週
- 投資家フィルター

---

### ページ3: 合算分析

**概要**: `weekly_combined` テーブルを使い、現物と先物を組み合わせた分析を行う。

**グラフ1 — 外国人：現物 vs 先物 方向一致/乖離チャート（2軸）**
現物NET（棒グラフ・左軸）と先物NET（折れ線・右軸）を同一グラフに重ねる。両者が同方向なら需給が揃っている、逆方向なら乖離が発生している状態。

**グラフ2 — ツインエンジン発動履歴ヒートマップ**
過去N週の各投資家について、現物・先物の買い/売りの組み合わせをヒートマップで表示する。「両輪買い」「両輪売り」「乖離」の状態が一覧できる。

**グラフ3 — 外国人 現物+先物合算 累積フロー**
外国人の合算NETの週次棒グラフと累積折れ線を重ねたチャート。資金フローの方向性の持続性を確認するのに使う。

**サイドバー固有設定**
- 表示期間: 13/26/52週（投資家フィルターなし・外国人固定表示）

---

### ページ4: Zスコア

**概要**: 現物・先物それぞれについてローリングZスコアを動的計算して表示する。統計的な過熱・売られすぎ水準の把握に使う。

**サイドバー固有設定**
- 表示期間: 13/26/52週
- データ種別: 現物（`weekly_spot` の net_amount）/ 先物（`weekly_futures` の net_amount_oku、日経225＋TOPIX合算）
- 投資家フィルター

**セクション1 — Zスコアヒートマップ（26週基準）**
選択投資家 × 週 のヒートマップ。±2.0を超えると統計的に異常な水準と判断する。

| 色 | Zスコア | 意味 |
|----|---------|------|
| 濃赤 | +2.0以上 | 統計的に強い買い越し（過熱） |
| 淡赤 | +1.0以上 | やや買い越し優勢 |
| グレー | ±1.0以内 | 通常範囲 |
| 淡青 | -1.0以下 | やや売り越し優勢 |
| 濃青 | -2.0以下 | 統計的に強い売り越し |

**セクション2 — 26週 vs 52週 Zスコア比較**
投資家ごとにタブを切り替え、26週基準（実線）と52週基準（オレンジ点線）のZスコアを重ねて表示する。26週が先行し、52週が追従する動きが典型パターン。

**セクション3 — 4週移動平均トレンド**
各投資家のNET値の4週移動平均を折れ線表示。短期的な方向転換の確認に使う。

---

### ページ6: AIレポート

**概要**: 過去のAI需給分析レポート（週次・月次）を一覧から選んで全文閲覧する。Supabase `reports` テーブル＋`outputs/reports/` のファイルから自動抽出。

**サイドバー**
- 種別: 週次 / 月次
- ※ ファイル一覧は自動で取得済み

**操作**
1. プルダウンで対象週を選択（最新が先頭）
2. 全文Markdownで表示
3. 「📥 ダウンロード」ボタンでMDファイル取得

---

### ページ7: オプション

**概要**: 投資部門別の日経225オプション（標準＋ミニ）のコール／プット net売買枚数を可視化する。GEX推定値も自動算出。

**KPIカード（4枚）**
- **海外 PCR（プット/コール比）**: 1.5以上で赤（ヘッジ姿勢強）、0.7以下で緑（強気バイアス）
- **海外プット net 枚数**: 下方ヘッジ規模
- **海外コール net 枚数**: 上方期待の規模
- **MM ガンマ推定**: 自己（dealer）のコール/プット net から自動判定 → `-GEX（ボラ拡大）` / `+GEX（Pinning）` / `中立`

**グラフ**
1. 最新週: 投資家別 コール/プット 売買差引バーチャート（標準＋ミニ合算、グループ棒）
2. 海外投資家 PCR 推移（PCR=1.0 / 1.5 ガイドライン付き）
3. 海外投資家 4オプション net 時系列（日経225 × コール/プット の4本）

**expander**: 直近週の詳細データ（全投資家×全 option_type）

---

### ページ5: 月次集計

**概要**: 週次データを月単位に集計して中期的なフローを把握する。

**グラフ1 — 月次フロー棒グラフ（現物NET）**
月別・投資家別の現物NETを棒グラフで表示する。季節性の確認や、複数ヶ月にわたる買い越し/売り越しトレンドの把握に使う。

**グラフ2 — 月次フロー棒グラフ（現物+先物 合算NET）**
現物と先物を合算した月次NETを棒グラフで表示する。外国人の総需給を評価する際に最も重要な指標。

**グラフ3 — 投資家別月次NETヒートマップ（現物）**
横軸に投資家、縦軸に年月をとったヒートマップ。赤が売り越し、緑が買い越し。複数投資家の月次傾向を一覧できる。

**テーブル — 直近12ヶ月推移テーブル（現物NET）**
投資家を行、年月を列として数値を色分け表示する。+5,000億円超は太字緑、-5,000億円超は太字赤で強調される。

**サイドバー固有設定**
- 表示月数: 6/12/24ヶ月
- 投資家フィルター

---

## 3. 毎週の自動実行（通常運用）

**木曜日20時にPCの電源が入っていれば、何もしなくて自動で動きます。**

自動実行の流れ：
1. n8n（Docker）がスケジュール起動
2. Supabaseの起動確認（無料版のスリープ解除）
3. `main.py` を実行（データ取得→DB保存→AIレポート生成→Excel更新）
4. 完了メールを `y.ioku1973@gmail.com` に送信
5. ダッシュボードは次回アクセス時に自動反映（「キャッシュ更新」ボタン推奨）

### 自動実行が動かない場合のチェックリスト

```
□ Docker Desktop が起動しているか（タスクトレイのクジラアイコン）
□ n8nコンテナが動いているか → http://localhost:5678 が開けるか
□ api_server.py が起動しているか → タスクバーにPowerShellウィンドウがあるか
□ Supabase が停止していないか → https://supabase.com/dashboard
□ Anthropic APIクレジット残高 → https://console.anthropic.com/settings/billing
```

---

## 4. 手動実行

### A. 通常の週次実行（推奨：ワンタッチ）

プロジェクト直下の **`fetch_report.bat`** をダブルクリック。

実行する処理：
1. JPXサイトから最新データ取得（現物XLS + 先物・オプションCSV）
2. **JPXページの対象期間を自動解決して `week_date` を補正**（公開遅延・GW飛ばしに対応）
3. Supabase各テーブル（weekly_spot / weekly_futures / weekly_options など）に upsert
4. Claude APIでAIレポート生成（約2〜3分・プロンプトキャッシュ有効）
5. `outputs/reports/` にMD・Excel保存

PowerShellから起動する場合：

```powershell
cd C:\CarSol\jpx-analysis
python main.py
```

### B. 特定週のファイルを手動指定して実行

JPXサイトからファイルを手動ダウンロードした場合：

```powershell
python main.py --spot stock_val_1_260401.xls --futures Tousi_DV_W_202604_1_0330_0403.csv --date 2026-04-03
```

### C. データはそのままでレポートだけ再生成

AIレポートの内容が気に入らない場合や、プロンプトを改善した後に使います。データの再取得・DB保存は行いません。

```powershell
# 直近週のレポートを再生成（日付省略で直近金曜を自動検出）
python main.py --report-only

# 特定週を指定して再生成
python main.py --report-only --date 2026-05-01
```

**VIX・日経VIを補足したい場合のみ（任意）**
通常は不要です。AIがデータから推論します。より精確な数値を反映させたいときだけ追加してください。

```powershell
python main.py --report-only --date 2026-05-01 --vix 18.5 --nikkei-vi 22.0 --usdjpy 143.50
```

上記の数値はTradingViewやYahooファイナンスで確認した値を入力します。省略した項目はAIが自律的に推論します（エラーにはなりません）。

### D. 月次サマリーの集計 + AIレポート生成

```powershell
python main.py --monthly 2026-04
```

`--monthly` を実行すると以下が一括で行われます。

1. 当月の週次データをDB集計して `monthly_summary` テーブルに保存
2. 直近13ヶ月分を取得してClaude APIで月次AIレポート生成
3. `outputs/reports/jpx_monthly_202604.md` に保存
4. Supabaseの `reports` テーブルに記録（week_date=月末日）

月次レポートは週次レポートと異なり、中期トレンド（連続買越し月数・前年同月比・1〜3ヶ月先の見通し）に特化した分析内容です。毎月末の週次実行後に手動で実行してください。

### E. Excelファイルの再生成

```powershell
python scripts/build_excel.py
```

年ごとに `jpx_investor_2025.xlsx`・`jpx_investor_2026.xlsx` を生成します。

---

## 5. 過去データのバックフィル

2025年4月以降のデータは取得済みです。さらに古いデータや特定期間を再取得したい場合：

```powershell
# 2025年1月以降を取得（例）
python scripts/backfill_jpx.py --from 2025-01-01

# 何件処理されるか事前確認（ドライラン）
python scripts/backfill_jpx.py --from 2025-01-01 --dry-run
```

1週あたり約2分（Claude APIのレポート生成込み）かかります。

---

## 6. 出力ファイルの見方

### 週次AIレポート（Markdown）

場所：`outputs/reports/jpx_investor_YYYYMMDD_YYYYMMDD.md`（週初日_週末日）

タイトル：`# JPX投資家別売買動向 YYYY年MM月DD日〜MM月DD日`（期間表記）

構成：
- **エグゼクティブサマリー** ← 毎週メールで送られてくる部分
- マクロ・市場環境
- 現物：投資家別買い越し・売り越し
- 先物：商品種別×投資家 内訳テーブル（日経225ラージ/ミニ・TOPIXラージ/ミニ）
- 合算：現物＋先物ネット（現物Zスコア・先物Zスコアの両方を記載）
- 注目セグメント動向（外国人・信託銀行（GPIF）の詳細解釈付き）
- **オプションフロー分析**（日経225標準＋ミニ。海外プット買い、PCR、MMガンマ推定、-GEX/+GEX判定など）
- 先週比・Zスコア分析
- 戦略示唆

### 月次AIレポート（Markdown）

場所：`outputs/reports/jpx_monthly_YYYYMM.md`

`python main.py --monthly YYYY-MM` を実行すると生成されます。

構成：
- **エグゼクティブサマリー**（中期トレンドの変化・継続を要約）
- 月次需給テーブル（現物/先物/合算の12ヶ月推移表）
- 投資家別中期トレンド分析（連続買越し月数・累積金額・前年同月比）
- 季節性・アノマリー分析
- 中期見通しと戦略示唆（1〜3ヶ月先）

### Excelファイル

場所：`outputs/excel/jpx_investor_YYYY.xlsx`

| シート名 | 内容 |
|---------|------|
| 現物_週次 | 週ごとの買い越し・売り越し額（億円）。J〜O列にZスコアヒートマップ付き |
| チャート_外国人 | 海外投資家ネット棒グラフ（青/赤）＋4週移動平均線（オレンジ） |
| チャート_全投資家 | 6投資家の週次ネット比較ラインチャート |
| チャート_Zスコア | 上段：海外投資家の現物Zスコア推移 / 下段：先物Zスコア推移（52週・26週バンド付き） |
| 月次サマリー | 月別合算ネット（現物＋先物）。新しい月が上に表示 |

#### Zスコアの見方（現物_週次シート J〜O列）

| 色 | Zスコア範囲 | 意味 |
|---|------------|-----|
| 濃青 | +2.0以上 | 統計的に異常な買い越し |
| 淡青 | +1.0以上 | やや強めの買い越し |
| グレー | -1.0〜+1.0 | 通常範囲 |
| 淡赤 | -1.0以下 | やや強めの売り越し |
| 濃赤 | -2.0以下 | 統計的に異常な売り越し |

**注意：** 最初の3週はZスコアの計算に必要なデータが不足するため空白になります。4週目から算出開始、52週分揃ってから統計的に最も信頼できる値になります。

---

## 7. n8nの操作

### ワークフロー確認・手動実行

1. `http://localhost:5678` を開く
2. 「JPX_Weekly_Analysis」ワークフローを開く
3. 「Execute workflow」で手動実行
4. 「Active」トグルがONになっているか確認（木曜自動実行に必要）

### n8n再起動が必要な場合（Docker操作）

PowerShellで1行ずつ実行（`&&` はWindows PowerShellで使えない）：

```powershell
cd C:\CarSol\jpx-analysis\config
docker stop n8n
docker rm n8n
docker compose up -d
```

---

## 8. Supabaseが停止した場合

無料プランは7日間アクセスなしで自動停止します。

1. `https://supabase.com/dashboard` を開く
2. プロジェクト `syyojlcrnachuvrbvttw` を選択
3. 「Restore project」をクリック（復旧に1〜2分）
4. 復旧後に手動で `python main.py` を実行

---

## 9. 主要ファイル構成

```
C:\CarSol\jpx-analysis\
├── main.py                    ← メインエントリーポイント
├── api_server.py              ← n8n→Windows橋渡しサーバー（常時起動）
├── dashboard.bat              ← ダッシュボード起動（ワンタッチ・LAN/Tailscale対応）
├── fetch_report.bat           ← 週次レポート取得・生成（ワンタッチ）
├── start_api_server.bat       ← スタートアップ登録済み
├── config/
│   ├── .env                   ← APIキー（変更時のみ編集）
│   ├── docker-compose.yml     ← n8n Docker設定
│   └── n8n_workflow.json      ← n8nワークフロー定義
├── dashboard/
│   ├── app.py                 ← トップ画面（KPI・ツインエンジン・4週トレンド）
│   ├── components/
│   │   ├── data_loader.py     ← Supabase接続・1000行ページネーション対応
│   │   ├── charts.py          ← 投資家カラー定義（COLORS / INV_BAR_COLORS）
│   │   ├── metrics.py         ← KPI計算ヘルパー
│   │   └── theme.py           ← ダーク/ライト切り替えCSS
│   └── pages/
│       ├── 1_現物フロー.py    ← NET推移折れ線・棒グラフ
│       ├── 2_先物フロー.py    ← 日経225/TOPIX先物タブ切り替え
│       ├── 3_合算分析.py      ← 現物vs先物2軸・ツインエンジン履歴
│       ├── 4_Zスコア.py       ← ヒートマップ・26週vs52週比較（現物/先物切替）
│       ├── 5_月次集計.py      ← 月次棒グラフ・ヒートマップ・推移テーブル
│       ├── 6_AIレポート.py    ← 過去レポート全文閲覧（週次/月次切替）
│       └── 7_オプション.py    ← オプションフロー・PCR・GEX推定
├── scripts/
│   ├── fetch_jpx.py                  ← JPX自動DL（week_date自動補正）
│   ├── jpx_week_resolver.py          ← JPXページから対象期間を解決
│   ├── parse_spot_xls.py             ← 現物XLSパーサー
│   ├── parse_futures_csv.py          ← 先物CSVパーサー
│   ├── parse_options_csv.py          ← オプションCSVパーサー（コード303/304/332/333）
│   ├── analyze_jpx.py                ← Zスコア・統計計算
│   ├── build_excel.py                ← Excelチャート生成
│   ├── backfill_jpx.py               ← 過去データ一括取得
│   ├── backfill_options.py           ← オプションデータバックフィル
│   ├── audit_week_dates.py           ← week_date 整合性チェック・修正
│   ├── fix_mislabeled_reports.py     ← 誤ラベルレポート修正
│   ├── normalize_report_format.py    ← レポート名・タイトル正規化
│   ├── fetch_missing_week.py         ← 欠落週の追加取得
│   └── extract_report_summary.py     ← メール用サマリー抽出
├── agents/
│   └── report_agent.py        ← Claude APIレポート生成（プロンプトキャッシュ・モデル切替対応）
├── db/
│   ├── supabase_client.py     ← Supabase全CRUD（オプション含む）
│   └── schema_options.sql     ← weekly_options テーブル定義
├── outputs/
│   ├── reports/               ← 週次MD（jpx_investor_YYYYMMDD_YYYYMMDD.md）
│   │                             月次MD（jpx_monthly_YYYYMM.md）
│   └── excel/                 ← 年間累積Excel
└── skills/jpx-investor-data/references/
    ├── jpx_micro_flows.md     ← 投資家行動原理の解釈知識
    ├── options_gex_master.md  ← GEX環境判定
    ├── global_macro_dynamics.md ← マクロ文脈・関税リスク（2026年4月版）
    └── quant_tech_psychology.md ← Zスコア・アルゴ行動
```

---

## 10. よくあるトラブルと対処

| 症状 | 原因 | 対処 |
|------|------|------|
| メールが来ない | Docker/n8nが停止 | Docker起動確認→n8n Active確認 |
| メールは来たがエラー | main.pyが失敗 | ログ確認 `logs/jpx_YYYYMMDD.log` |
| Anthropic APIエラー | クレジット不足 | console.anthropic.com でチャージ |
| Supabase接続エラー | プロジェクト停止 | ダッシュボードで手動復旧 |
| JPXサイト404 | URL変更 | `scripts/fetch_jpx.py` のURL確認 |
| Excelが開けない | ファイルが壊れている | `python scripts/build_excel.py` で再生成 |
| ダッシュボードのデータが古い | キャッシュが残っている | サイドバーの「キャッシュ更新」ボタンをクリック |
| ダッシュボードが真っ白 | Streamlit起動失敗 | `streamlit run dashboard/app.py` を再実行 |
| 先物ZスコアがExcelに出ない | all_futures_historyが空 | Supabase復旧後に `python scripts/build_excel.py` を再実行 |

---

## 11. AIレポートの品質について

AIは対象週の日付を認識した上でGEX判定・季節性解析・マクロ推論を行います。特定の地政学イベントや政策の固有名詞（例: 「○○ショック」「○○戦争」）は断定的に使わず、「外部ショック」「地政学的不確実性」等の一般表現で記述します。

### プロンプト設計の重要ポイント

- **符号規約の明示**: AIに渡すデータテーブルは `+/-` の符号付き数値（正=買い越し / 負=売り越し）。日本式の `▲/▼` は使わない（会計上「▲＝マイナス」の用法と混同するリスクを排除）
- **両輪買い/売りの判定**: 現物と先物の符号が一致した場合のみ「Twin-Buy / Twin-Sell」と表現。逆方向の場合は「方向性乖離／ヘッジ的」と表現
- **オプションフロー解釈**: 海外プット買いコール売り → ベア、海外プット売りコール買い → ブル、自己コール/プット net → GEX判定など、明確な解釈ルールを system プロンプトに記載
- **プロンプトキャッシュ**: リファレンス4ファイル（約1.5万トークン）に `cache_control: ephemeral` を付与。5分TTL以内の再実行（バックフィル等）でコスト90%・レイテンシ半減
- **モデル切替**: `.env` の `CLAUDE_MODEL` で指定可能（未設定時は `claude-sonnet-4-6`）

### 再生成方法

レポートの解釈に明らかな誤りがある場合は `python main.py --report-only --date YYYY-MM-DD` で再生成してください。

---

## 12. 既知の制限・注意事項

`weekly_stats` テーブルのZスコアはバックフィル時に誤った計算値が保存されている。ただしExcel・ダッシュボード・レポートはすべてこのテーブルを使わず `spot_history` / `futures_history` から直接ローリング計算するため実害なし。

過去のMDレポート内Zスコアはバックフィル生成のため誤った値が記載されている可能性あり。2026-04-03以降の最新週は正確。

Zスコアは最初の3週は空白になる仕様。計算に4週以上必要で、52週分揃ってから統計的に最も信頼できる値になる。

ダッシュボードのテーマ切り替え（ダーク/ライト）はセッション中のみ有効で、再起動するとライトモード（`config.toml` の `base="light"`）に戻る。

オプションデータは2026-04-13週以降のみDBに投入済み（JPX最新公開ページから取得可能な範囲）。過去オプションのバックフィルは未対応。

---

## 13. リモートアクセス（LAN・Tailscale）

### 設定済みの内容

- Streamlit を `--server.address 0.0.0.0` で起動 → LAN/Tailscale経由のアクセス可能
- Tailscale: MagicDNS有効、本機デバイス名 `is-2025-lenovo`、IP `100.90.57.39`、テールネット `tail0b9276.ts.net`

### アクセスURL早見表

| 状況 | URL |
|---|---|
| 本機 | `http://localhost:8503` |
| 同じWi-Fi内のスマホ・別PC | `http://192.168.11.12:8503` |
| Tailscale経由（外出先含む） | `http://is-2025-lenovo:8503` |

### 他デバイスにTailscaleを追加する手順

1. iOS/AndroidアプリまたはWindows/Macアプリで Tailscale をインストール
2. 本機と同じアカウントでサインイン
3. 「Connected」状態にしてブラウザで上記Tailscale URLにアクセス

---

## 14. 自動アラート機能

`fetch_report.bat` または `python main.py` 実行時、レポート生成後に自動で異常検知が走ります。

### 検知ルール

| ルール | 閾値（.envで上書き可） |
|---|---|
| 海外現物 Zスコア(52w) 絶対値 | `ALERT_ZSCORE_THRESHOLD=2.0` |
| 海外先物 Zスコア(52w) 絶対値 | `ALERT_ZSCORE_THRESHOLD=2.0` |
| 海外 PCR（プット/コール）高水準 | `ALERT_PCR_HIGH=1.8` |
| 海外 PCR 低水準 | `ALERT_PCR_LOW=0.6` |
| 海外 mini プット大量買い越し | `ALERT_MINI_PUT_LARGE=20000` |
| ツインエンジン点灯/解除（前週比較） | — |
| MM ガンマ環境（+GEX ↔ -GEX）切替 | — |

### 結果の出力先

- `outputs/alerts/latest.json` ← 最新評価結果
- `outputs/alerts/YYYY-MM-DD.json` ← 日付別アーカイブ
- ダッシュボードのトップ画面に「⚠️ アクティブアラート」帯で表示
- Gmail送信（`.env` に `SMTP_USER` + `SMTP_APP_PASSWORD` 設定時のみ）

### 単独実行

```powershell
python scripts/check_alerts.py                  # 最新週で評価
python scripts/check_alerts.py --date 2026-05-15
python scripts/check_alerts.py --no-mail        # メール送信スキップ
```

### Gmail送信を有効化したい場合

`.env` に以下を追加：

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=y.ioku1973@gmail.com
SMTP_APP_PASSWORD=xxxxxxxxxxxxxxxx  # Gmail アプリパスワード（2段階認証必須）
```

アプリパスワードは https://myaccount.google.com/apppasswords で発行。

---

## 15. Streamlit Cloud デプロイ（将来計画）

本機を起動しなくても外出先でダッシュボードが見られる状態を作る将来計画。**まだ未デプロイ**。

詳細手順は [DEPLOY.md](DEPLOY.md) を参照してください。要点：

1. GitHubプライベートリポジトリ作成 → push
2. https://share.streamlit.io でデプロイ（無料）
3. Secrets に Supabase キー、`[auth]` セクション（streamlit-authenticator）を設定
4. パスワード保護必須（Cloud は公開URL）
5. **データ取得は本機側のまま**（Cloud は閲覧専用）

実装側は既に対応済み：
- `requirements.txt` に streamlit / plotly / streamlit-authenticator 追加
- `dashboard/components/data_loader.py` が st.secrets → 環境変数の順で接続情報取得
- `dashboard/app.py` 冒頭に「st.secretsに `[auth]` があれば認証発動」ロジック
- `.streamlit/secrets.toml.example` テンプレート同梱

---

## 16. 自動化スクリプト一覧

ワンタッチで実行できるBATファイル：

| ファイル | 用途 |
|---|---|
| `dashboard.bat` | ダッシュボード起動＋ブラウザ自動オープン（重複起動防止付き） |
| `fetch_report.bat` | JPX最新データ取得＋AIレポート生成（n8n非依存の手動実行） |

データメンテナンス用スクリプト（必要時のみ実行）：

| スクリプト | 用途 |
|---|---|
| `python scripts/audit_week_dates.py [--fix]` | DB全テーブルの week_date 整合性チェック |
| `python scripts/fix_mislabeled_reports.py [--apply]` | 誤ラベルレポートのリネーム＋タイトル修正 |
| `python scripts/normalize_report_format.py [--apply]` | 過去レポート名を新フォーマット（YYYYMMDD_YYYYMMDD）に正規化 |
| `python scripts/backfill_options.py` | JPX公開中の全週分のオプションデータ（日経225/mini/TOPIX/JPX400 × call/put）をDB投入 |
| `python scripts/fetch_missing_week.py --week-end YYYY-MM-DD` | 欠落週の追加取得（XLS+CSV→DB→レポート） |
| `python scripts/check_alerts.py [--date YYYY-MM-DD]` | 異常検知（PCR・Zスコア・GEX切替）+ JSON書き出し + Gmail送信 |

---

*このマニュアルはClaude Codeが自動生成しました。*

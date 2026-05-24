# Streamlit Cloud デプロイ手順書

本機を起動しなくても、Streamlit Cloud（無料・公開URL）でダッシュボードを公開する手順。

> ⚠️ Streamlit Cloud は **デフォルトで公開URL** になります。必ずパスワード保護（streamlit-authenticator）を有効化してください。

---

## 全体像

```
ローカル本機（現状）              Streamlit Cloud
─────────────────                 ───────────────────
fetch_report.bat                  ダッシュボード閲覧専用
（取得・AIレポート生成）           ↑ Supabase から読むだけ
       ↓
   Supabase ─────────────────────→ Supabase（同じ）
       ↑
   ダッシュボード（本機）
```

データ取得・AIレポート生成は **本機側に残す**（n8n自動化、Claude APIコスト管理のため）。Cloud 側は **閲覧専用** にして、Supabaseを共通バックエンドにする。

---

## ステップ1: GitHubプライベートリポジトリ作成

1. https://github.com/new で **プライベート** リポジトリ作成
   - 名前例: `jpx-analysis`
   - Privateを選択
2. ローカルから push
   ```powershell
   cd C:\CarSol\jpx-analysis
   git remote add origin https://github.com/<username>/jpx-analysis.git
   git push -u origin main
   ```
3. `.gitignore` で除外済みのファイル確認:
   - `config/.env` ← APIキー入り、絶対にコミットしない
   - `.streamlit/secrets.toml` ← クラウド側で別管理
   - `outputs/` ← レポートMD・Excel（容量大）
   - `logs/`

---

## ステップ2: パスワード保護の準備

ローカルで bcrypt ハッシュを生成：

```python
# generate_hash.py（一時スクリプト・実行後削除可）
import streamlit_authenticator as stauth
hashed = stauth.Hasher(['ここに設定したいパスワード']).generate()
print(hashed[0])
```

```powershell
pip install streamlit-authenticator
python generate_hash.py
# 出力例: $2b$12$abc.....xyz
```

このハッシュを **secrets.toml** に貼る（次ステップ）。

---

## ステップ3: Streamlit Cloud アカウント作成・デプロイ

1. https://share.streamlit.io にアクセス → GitHubでサインイン
2. **「New app」** → 以下を入力
   - **Repository**: `<username>/jpx-analysis`
   - **Branch**: `main`
   - **Main file path**: `dashboard/app.py`
   - **App URL**: 任意のサブドメイン（例: `jpx-yioku.streamlit.app`）
3. **「Advanced settings」** → **Secrets** に以下を貼り付け

```toml
SUPABASE_URL = "https://syyojlcrnachuvrbvttw.supabase.co"
SUPABASE_SERVICE_KEY = "eyJ..."  # 実際のキーを貼る

# AIレポート再生成を Cloud 上で行わないなら不要
# ANTHROPIC_API_KEY = "sk-ant-..."

[auth]
username = "yioku"
password_hash = "$2b$12$..."  # ステップ2で生成したハッシュ
cookie_name = "jpx_dashboard_auth"
cookie_key = "ランダム32文字以上の文字列"
cookie_expiry_days = 30
```

4. **「Deploy」** をクリック → 3〜5分でビルド完了

---

## ステップ4: 認証ロジックを app.py に組み込み

> 📝 デプロイ完了したらこの編集を行います。本機ではパスワードを毎回入力するのが煩雑なので、認証は **st.secrets が存在する時のみ有効化** にすると LAN/Tailscale 環境では不要のままです。

[dashboard/app.py](dashboard/app.py) の先頭に挿入する想定コード：

```python
# Streamlit Cloud 上のみ認証を要求
import streamlit as st
if "auth" in (st.secrets if hasattr(st, "secrets") else {}):
    import streamlit_authenticator as stauth
    cfg = st.secrets["auth"]
    authenticator = stauth.Authenticate(
        credentials={"usernames": {cfg["username"]: {
            "name": cfg["username"],
            "password": cfg["password_hash"],
        }}},
        cookie_name=cfg["cookie_name"],
        key=cfg["cookie_key"],
        cookie_expiry_days=cfg["cookie_expiry_days"],
    )
    name, auth_status, _ = authenticator.login("main")
    if not auth_status:
        st.stop()
```

これにより、`st.secrets["auth"]` が存在する Cloud 環境では認証画面が出て、ローカル（`.env`実行）では従来通りそのまま動作します。

---

## ステップ5: Supabase の RLS 確認

Streamlit Cloud は service_role key を使う場合、誰でも全テーブルにアクセス可能になるリスクがあります。**閲覧専用** であることを徹底するために：

### 推奨案 A: 専用の anon role + RLS 設定（本格運用向け）
1. Supabase Dashboard → Auth → Policies で各 `weekly_*` テーブルに SELECT のみ許可
2. Cloud には service_role の代わりに `anon` key を設定
3. Streamlit Cloud から書き込み不可になる

### 推奨案 B: そのまま service_role を使う（簡易・短期向け）
- 認証で公開を阻止しているため、漏洩リスクは限定的
- ダッシュボード機能では書き込みしないので運用上は問題なし

**まずは B で運用開始 → 必要に応じて A に移行** が現実的。

---

## ステップ6: 動作確認

1. `https://<your-app>.streamlit.app/` にアクセス
2. ログイン画面が出る → 設定したユーザー名・パスワードでログイン
3. ダッシュボードが表示されることを確認
4. データが最新であること（本機で `fetch_report.bat` を回した後の状態が反映される）

---

## 制限事項・注意

- **Streamlit Cloud Free 枠**: 1GB RAM、CPU 1コア、月 1,000時間の起動時間。個人利用なら十分。
- **スリープ**: 7日間アクセスなしで自動スリープ。次回アクセス時に再起動（数秒）。
- **データ書き込み禁止**: Cloud 側ではデータ取得（main.py）を実行しない。Cloud は閲覧専用。
- **outputs/ ファイルは Cloud で見えない**: GitHub にコミットしていないため。**reports は Supabase の reports.content_md を使えば閲覧可能**。
- **Secret更新**: Streamlit Cloud → App settings → Secrets で編集 → 自動再起動。

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| ビルド失敗 | requirements.txt の依存解決失敗 | バージョン緩和、`pip install` でローカル動作確認 |
| Supabase接続エラー | Secret の `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` 誤り | App settings で再確認 |
| ログイン後に画面が真っ白 | secrets の `[auth]` 形式エラー | toml の構文を再確認、cookie_key を32文字以上に |
| データが古い | Cloud のキャッシュ | サイドバーの「キャッシュ更新」または App再起動 |

---

*このドキュメントは Phase ③ で生成されました。実際のデプロイは GitHub リポ作成後に着手してください。*

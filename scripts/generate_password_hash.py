"""
scripts/generate_password_hash.py
================================
Streamlit Cloud デプロイ用に bcrypt パスワードハッシュを生成する
（一時スクリプト・実行後に削除しても良い）

使い方:
  python scripts/generate_password_hash.py

実行すると対話的にパスワード入力を求められ、ハッシュが出力される。
そのハッシュを Streamlit Cloud の Secrets の [auth] password_hash に貼る。

注意:
  - パスワードは画面に表示されない（getpass）
  - ハッシュは公開しても安全な値（bcrypt は一方向）
"""

import getpass
import secrets
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    print("=" * 60)
    print("  Streamlit Cloud パスワードハッシュ生成")
    print("=" * 60)

    # bcrypt を直接使う（streamlit_authenticator が内部でも bcrypt を使用）
    try:
        import bcrypt
    except ImportError:
        print("\n[エラー] bcrypt がインストールされていません")
        print("以下を実行してから再度試してください:")
        print("  pip install bcrypt")
        sys.exit(1)

    pw1 = getpass.getpass("パスワードを入力: ")
    pw2 = getpass.getpass("確認のためもう一度入力: ")
    if pw1 != pw2:
        print("\n[エラー] パスワードが一致しません")
        sys.exit(1)
    if len(pw1) < 8:
        print("\n[警告] パスワードが短い (8文字以上推奨)")

    hashed = bcrypt.hashpw(pw1.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cookie_key = secrets.token_urlsafe(48)

    print()
    print("=" * 60)
    print("  Streamlit Cloud Secrets に貼り付ける値")
    print("=" * 60)
    print()
    print(f"password_hash = \"{hashed}\"")
    print(f"cookie_key    = \"{cookie_key}\"")
    print()
    print("（cookie_key はランダム生成済み・このまま使ってOK）")
    print("（password_hash は再生成するたびに変わるが、どれも有効）")
    print()


if __name__ == "__main__":
    main()

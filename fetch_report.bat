@echo off
chcp 65001 >nul
title JPX 週次レポート生成
cd /d "%~dp0"

echo ============================================================
echo  JPX 週次レポート生成
echo ============================================================
echo  処理内容:
echo    1. JPX サイトから最新データを取得 ^(現物 XLS + 先物 CSV^)
echo    2. JPX ページの対象期間を解決して week_date を補正
echo    3. Supabase の各テーブルに upsert
echo    4. Claude API で AI レポート生成 ^(約 2 〜 3 分^)
echo    5. outputs\reports に Markdown / Excel を保存
echo ============================================================
echo.
echo [INFO] 開始時刻: %DATE% %TIME%
echo.

python main.py
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
if "%RC%"=="0" (
    echo  [完了] レポート生成が成功しました
    echo         outputs\reports\ を確認してください
    echo         ダッシュボードからも閲覧可能です ^(dashboard.bat^)
) else (
    echo  [エラー] レポート生成に失敗しました ^(exit code: %RC%^)
    echo          logs\ フォルダのログを確認してください
)
echo ============================================================
echo.
echo  何かキーを押すと閉じます...
pause >nul
exit /b %RC%

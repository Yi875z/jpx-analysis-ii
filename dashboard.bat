@echo off
chcp 65001 >nul
title JPX 投資家別売買動向ダッシュボード
cd /d "%~dp0"

REM ───── 既に 8503 でリスニング中ならブラウザだけ開く ─────
netstat -ano | findstr ":8503 " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo [INFO] ダッシュボードは既に起動中です ^(port 8503^)
    echo [INFO] ブラウザで http://localhost:8503 を開きます...
    start "" "http://localhost:8503"
    timeout /t 2 /nobreak >nul
    exit /b 0
)

echo ============================================================
echo  JPX 投資家別売買動向ダッシュボード 起動
echo ============================================================
echo  URL : http://localhost:8503
echo ============================================================
echo.

REM ───── Streamlit を別ウィンドウ（最小化）で起動 ─────
REM   --server.address 0.0.0.0 : LAN内・Tailscale経由の他デバイスからもアクセス可能
start "JPX Dashboard (port 8503)" /min cmd /c "streamlit run dashboard\app.py --server.port 8503 --server.headless true --server.address 0.0.0.0"

REM ───── 起動完了を待ってブラウザを開く ─────
echo [INFO] 起動中... (約5秒)
timeout /t 5 /nobreak >nul

REM ───── 8503がLISTENING状態になっているか確認 ─────
set "READY=0"
for /L %%i in (1,1,10) do (
    netstat -ano | findstr ":8503 " | findstr "LISTENING" >nul
    if not errorlevel 1 (
        set "READY=1"
        goto :open
    )
    timeout /t 1 /nobreak >nul
)

:open
if "%READY%"=="1" (
    start "" "http://localhost:8503"
    echo [完了] ブラウザを開きました
) else (
    echo [警告] ダッシュボードが10秒以内に起動しませんでした
    echo        手動で http://localhost:8503 を確認してください
)

timeout /t 3 /nobreak >nul
exit /b 0

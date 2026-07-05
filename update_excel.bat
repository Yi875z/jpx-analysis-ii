@echo off
title JPX Excel Update
cd /d "%~dp0"

echo ============================================================
echo  JPX Excel Update  (rebuild from Supabase DB)
echo  - no data fetch / no AI report cost, approx. 20 sec
echo  - output: outputs/excel/jpx_investor_YYYY.xlsx
echo ============================================================
echo.
python main.py --excel-only
echo.
pause

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "scripts"))
load_dotenv(_HERE / "config" / ".env")
from parse_spot_xls import parse_spot_xls
from db.supabase_client import upsert_spot, save_log

rows = parse_spot_xls('stock_val_1_260301.xls', '2026-03-06')
n = upsert_spot(rows)
save_log('2026-03-06', 'success', spot_rows=n)
print(f'Supabaseに{n}件保存完了！')

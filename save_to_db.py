import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'scripts')
import os
from dotenv import load_dotenv
load_dotenv('config/.env')
from parse_spot_xls import parse_spot_xls
from db.supabase_client import upsert_spot, save_log

rows = parse_spot_xls('stock_val_1_260301.xls', '2026-03-06')
n = upsert_spot(rows)
save_log('2026-03-06', 'success', spot_rows=n)
print(f'Supabaseに{n}件保存完了！')

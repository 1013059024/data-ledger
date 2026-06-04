"""
麒麟版配置 — SQLite 数据库
"""
import os

# 数据库文件：存放在 DATA_DIR/data/ 下
DATA_DIR = os.environ.get("DATA_LEDGER_DATA") or os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "data", "data_ledger.db")

FLASK_SECRET = "data-ledger-kylin-2026"

"""
PyInstaller entry point for road-ledger Flask server

When compiled with --onefile, PyInstaller extracts bundled files to
sys._MEIPASS temporary directory. This script:
  1. Detects frozen (exe) vs dev (script) mode
  2. Sets DATA_LEDGER_BASE = _MEIPASS (templates/static live here)
  3. Sets DATA_LEDGER_DATA = current working directory (configs/backups here)
  4. Patches Flask paths and imports the real app
  5. Starts the server
"""
import os
import sys

# ── Detect environment ──────────────────────────────
if getattr(sys, 'frozen', False):
    # Running as compiled EXE — extracted to temp dir
    BASE = sys._MEIPASS
    DATA_DIR = os.getcwd()
else:
    # Running as plain Python script (debug)
    BASE = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = BASE

# Make sure data dir is writable
os.makedirs(DATA_DIR, exist_ok=True)

# Signal the real app where to look for things
os.environ['DATA_LEDGER_BASE'] = BASE
os.environ['DATA_LEDGER_DATA'] = DATA_DIR

# ── Import the real Flask app ──────────────────────
#   (add BASE to path so app.py finds its sibling modules)
sys.path.insert(0, BASE)

# ── Ensure data directory exists ────────────────────
#   SQLite database will be created automatically on first connection
os.makedirs(os.path.join(DATA_DIR, "data"), exist_ok=True)

import app as data_ledger_app
import routes_column  # 列操作路由（侧边导入，注册到 app）

# Override Flask's template/static folders to point at the extracted bundle
data_ledger_app.app.root_path = BASE
data_ledger_app.app.template_folder = os.path.join(BASE, 'templates')
data_ledger_app.app.static_folder = os.path.join(BASE, 'static')
data_ledger_app.app.static_url_path = '/static'

# ── 端口释放 ──────────────────────────────────────
PORT = 5000
def _free_port(port):
    """尝试多种方式释放端口"""
    import subprocess
    cmds = [
        ["fuser", "-k", f"{port}/tcp"],
        ["lsof", "-ti", f":{port}"],
    ]
    for cmd in cmds:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if cmd[0] == "fuser":
                if result.returncode == 0:
                    print(f"  OK 释放端口 {port}（fuser）")
                    return
            else:
                pids = result.stdout.strip().split()
                if pids:
                    subprocess.run(["kill", "-9"] + pids, capture_output=True, timeout=5)
                    print(f"  OK 释放端口 {port}（kill {pids}）")
                    return
        except Exception:
            pass
    # 备选：通过 /proc/net/tcp 查找
    try:
        with open("/proc/net/tcp") as f:
            for line in f:
                cols = line.strip().split()
                if len(cols) < 10: continue
                local = cols[1]
                if local.endswith(f":{port:04X}"):
                    pid_hex = cols[9]
                    if pid_hex != "0":
                        pid = int(pid_hex, 16)
                        subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=5)
                        print(f"  OK 释放端口 {port}（/proc/net/tcp pid={pid}）")
                        return
    except Exception:
        pass
    print(f"  ! 无法自动释放端口 {port}，请在麒麟终端执行：")
    print(f"    sudo ss -tlnp | grep {port}")
    print(f"    找到 PID 后用 kill -9 <PID> 杀掉")

_free_port(PORT)

# ── Run ──────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 50)
    print("数据台账系统 — 服务器")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Base:   {BASE}")
    print(f"  Data:   {DATA_DIR}")
    print(f"  端口:   {PORT}")
    print("=" * 50)
    data_ledger_app.app.run(host='0.0.0.0', port=PORT, debug=False)

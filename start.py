"""
road-ledger — One-click launcher
Starts MySQL (if not running) -> ensures database -> starts Flask
Usage:  python start.py
"""
import os
import sys
import time
import subprocess
import socket
import signal

# ── Paths ──────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(PROJECT_DIR, "server")
DATA_DIR = os.path.join(PROJECT_DIR, "mysql-data")
MYSQLD = r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe"
MYSQL = r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe"
DB_NAME = "data_ledger"
PORT = 3306
FLASK_PORT = 5000

# ── Process tracking ──────────────────────────────────
_mysql_proc = None
_flask_proc = None


def e(msg: str):
    """Safe echo — strips non-ASCII for Windows GBK consoles"""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe, flush=True)


def cleanup(signum=None, frame=None):
    e("")
    e(">> Shutting down...")
    for proc, name in [(_flask_proc, "Flask"), (_mysql_proc, "MySQL")]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
                e(f"   OK {name} stopped")
            except subprocess.TimeoutExpired:
                proc.kill()
                e(f"   OK {name} force stopped")
    e("Done")
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def port_open(port, host="127.0.0.1"):
    """Check if a port is open"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        return s.connect_ex((host, port)) == 0


def start_mysql():
    """Start MySQL server"""
    e(">> Checking MySQL status...")
    if port_open(PORT):
        e(f"   OK MySQL already running on port {PORT}")
        return True

    if not os.path.exists(MYSQLD):
        e(f"   FAIL MySQL binary not found: {MYSQLD}")
        return False

    # Check if data directory is initialized
    if not os.path.exists(os.path.join(DATA_DIR, "mysql")):
        e("   !! Data dir not initialized. Running --initialize-insecure ...")
        ret = subprocess.run(
            [MYSQLD, "--initialize-insecure", f"--datadir={DATA_DIR}", "--console"],
            capture_output=True, text=True, timeout=60
        )
        if ret.returncode != 0:
            e(f"   FAIL Init error: {ret.stderr or ret.stdout}")
            return False
        e("   OK Data dir initialized")

    e("   Starting MySQL...")
    global _mysql_proc
    _mysql_proc = subprocess.Popen(
        [MYSQLD, f"--datadir={DATA_DIR}", "--port=3306", "--console", "--skip-symbolic-links"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Wait for MySQL to be ready
    for i in range(20):
        if port_open(PORT):
            e(f"   OK MySQL ready (PID {_mysql_proc.pid})")
            return True
        if _mysql_proc.poll() is not None:
            e("   FAIL MySQL process exited prematurely")
            return False
        time.sleep(0.5)

    e("   FAIL MySQL startup timeout")
    _mysql_proc.kill()
    return False


def ensure_database():
    """Ensure data_ledger database exists"""
    e(">> Checking database...")
    ret = subprocess.run(
        [MYSQL, "-u", "root", "-e",
         f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
         "--batch"],
        capture_output=True, text=True, timeout=10
    )
    if ret.returncode == 0:
        e(f"   OK Database `{DB_NAME}` ready")
        return True
    else:
        e(f"   FAIL Database error: {ret.stderr}")
        return False


def start_flask():
    """Start Flask application"""
    e(">> Starting Flask...")
    global _flask_proc
    _flask_proc = subprocess.Popen(
        [sys.executable, "-u", "app.py"],
        cwd=SERVER_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )

    # Wait for Flask to be ready
    for i in range(15):
        if port_open(FLASK_PORT):
            e("   OK Flask ready")
            return True
        if _flask_proc.poll() is not None:
            output = _flask_proc.stdout.read()
            e(f"   FAIL Flask error:\n{output}")
            return False
        time.sleep(0.5)

    e("   FAIL Flask startup timeout")
    return False


def main():
    e("=" * 50)
    e("   Road Ledger - One-Click Launcher")
    e("=" * 50)
    e("")

    if not start_mysql():
        cleanup()

    if not ensure_database():
        cleanup()

    if not start_flask():
        cleanup()

    e("")
    e("=" * 50)
    e("   ALL SYSTEMS READY!")
    e(f"   http://127.0.0.1:{FLASK_PORT}")
    e("=" * 50)
    e("   Press Ctrl+C to stop all services")
    e("")

    try:
        # Stream Flask logs in real-time
        while True:
            line = _flask_proc.stdout.readline()
            if not line:
                if _flask_proc.poll() is not None:
                    break
                continue
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        cleanup()
    finally:
        cleanup()


if __name__ == "__main__":
    # Set PYTHONUNBUFFERED for this process
    os.environ["PYTHONUNBUFFERED"] = "1"
    main()

"""
Build portable road-ledger package

Creates a self-contained portable directory:
  data-ledger-portable/
    data-ledger-server.exe   <- PyInstaller-compiled Flask server
    mysql/bin/mysqld.exe     <- Portable MySQL
    mysql/share/             <- MySQL i18n
    mysql/lib/plugin/        <- MySQL plugins
    data/                    <- MySQL data
    my.cnf                   <- MySQL config
    start.py                 <- Portable launcher

Usage: python build_standalone.py
"""
import os, sys, shutil, stat, subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(PROJECT_DIR, "server")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "data-ledger-portable")
EXE_SRC = os.path.join(PROJECT_DIR, "dist", "data-ledger-server.exe")
MYSQL_DIR = r"C:\Program Files\MySQL\MySQL Server 8.4"


def log(msg):
    print(f"  {msg}")

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path

def rmtree_force(path):
    if not os.path.exists(path):
        return
    def _onerror(fn, p, _):
        os.chmod(p, stat.S_IWRITE)
        fn(p)
    shutil.rmtree(path, onerror=_onerror)


def step_clean():
    log("清理旧目录...")
    rmtree_force(OUTPUT_DIR)
    return True

def step_dirs():
    log("创建目录结构...")
    for d in ["", "mysql/bin", "mysql/share", "mysql/lib/plugin", "data"]:
        ensure_dir(os.path.join(OUTPUT_DIR, d))
    return True

def step_exe():
    log("复制编译好的 server.exe ...")
    if not os.path.exists(EXE_SRC):
        log(f"  FAIL: {EXE_SRC}")
        return False
    shutil.copy2(EXE_SRC, os.path.join(OUTPUT_DIR, "data-ledger-server.exe"))
    log(f"  OK ({os.path.getsize(EXE_SRC)//1024//1024} MB)")
    return True

def step_mysql():
    log("复制 MySQL 便携版...")
    src = os.path.join(MYSQL_DIR, "bin", "mysqld.exe")
    if not os.path.exists(src):
        log(f"  FAIL: {src}")
        return False
    shutil.copy2(src, os.path.join(OUTPUT_DIR, "mysql", "bin"))
    log("  mysqld.exe OK")

    bin_dir = os.path.join(MYSQL_DIR, "bin")
    dlls = 0
    for f in os.listdir(bin_dir):
        if f.endswith(".dll"):
            shutil.copy2(os.path.join(bin_dir, f), os.path.join(OUTPUT_DIR, "mysql", "bin"))
            dlls += 1
    log(f"  {dlls} DLLs OK")

    for sub in ["charsets", "english"]:
        src = os.path.join(MYSQL_DIR, "share", sub)
        if os.path.exists(src):
            shutil.copytree(src, os.path.join(OUTPUT_DIR, "mysql", "share", sub),
                          dirs_exist_ok=True)
    log("  share/ OK")

    src = os.path.join(MYSQL_DIR, "lib", "plugin")
    if os.path.exists(src):
        for f in os.listdir(src):
            full = os.path.join(src, f)
            if os.path.isfile(full):
                shutil.copy2(full, os.path.join(OUTPUT_DIR, "mysql", "lib", "plugin"))
    log("  lib/plugin/ OK")
    return True

def step_init_data():
    data_dir = os.path.join(OUTPUT_DIR, "data")
    if os.path.exists(os.path.join(data_dir, "mysql")):
        log("数据目录已存在，跳过")
        return True
    log("初始化 MySQL 数据目录...")
    ensure_dir(data_dir)
    mysqld = os.path.join(OUTPUT_DIR, "mysql", "bin", "mysqld.exe")
    try:
        ret = subprocess.run(
            [mysqld, "--initialize-insecure", f"--datadir={data_dir}", "--console"],
            capture_output=True, text=True, timeout=60
        )
        if ret.returncode == 0 or os.path.exists(os.path.join(data_dir, "mysql")):
            log("  OK")
            return True
        else:
            log(f"  FAIL: {ret.stderr[:200]}")
            return False
    except Exception as e:
        log(f"  FAIL: {e}")
        return False

def step_mycnf():
    log("创建 my.cnf ...")
    cnf = """[mysqld]
port=3306
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
"""
    with open(os.path.join(OUTPUT_DIR, "my.cnf"), "w") as f:
        f.write(cnf)
    log("  OK")
    return True

def step_launcher():
    log("创建启动器...")
    launcher = r'''"""
Data Ledger portable launcher
Starts MySQL + Web server, one click.
"""
import os, sys, subprocess, time, socket, signal

BASE = os.path.dirname(os.path.abspath(__file__))
MYSQLD = os.path.join(BASE, "mysql", "bin", "mysqld.exe")
DATA_DIR = os.path.join(BASE, "data")
MY_CNF = os.path.join(BASE, "my.cnf")
SERVER_EXE = os.path.join(BASE, "data-ledger-server.exe")

_mysql_proc = None
_server_proc = None

def port_open(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0

def cleanup(signum=None, frame=None):
    print("\nShutting down...")
    for proc, name in [(_server_proc, "Web"), (_mysql_proc, "MySQL")]:
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except: proc.kill()
            print(f"  {name} stopped")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

print("=" * 50)
print("  Data Ledger System")
print("=" * 50)

# Start MySQL
print("[1/2] MySQL...", end=" ", flush=True)
if port_open(3306):
    print("already running")
else:
    mysql_dir = os.path.join(BASE, "mysql")
    _mysql_proc = subprocess.Popen(
        [MYSQLD, "--datadir=" + DATA_DIR, "--port=3306", "--console"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    ok = False
    for i in range(20):
        if port_open(3306):
            ok = True; break
        if _mysql_proc.poll() is not None: break
        time.sleep(0.5)
    print("OK" if ok else "FAIL")
    if not ok:
        input("Press Enter to exit...")
        sys.exit(1)

# Start Web server
print("[2/2] Web server...", end=" ", flush=True)
if port_open(5000):
    print("already running")
else:
    _server_proc = subprocess.Popen(
        [SERVER_EXE],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    ok = False
    for i in range(20):
        if port_open(5000):
            ok = True; break
        if _server_proc.poll() is not None: break
        time.sleep(0.5)
    print("OK" if ok else "FAIL")
    if not ok:
        input("Press Enter to exit...")
        sys.exit(1)

print()
print("System ready! http://127.0.0.1:5000")
print("Press Ctrl+C to stop all services")
print()

import webbrowser
webbrowser.open("http://127.0.0.1:5000")

try:
    while True:
        line = _server_proc.stdout.readline()
        if not line:
            if _server_proc.poll() is not None: break
            continue
        sys.stdout.write(line)
        sys.stdout.flush()
except KeyboardInterrupt:
    cleanup()
finally:
    cleanup()
'''
    # start.py - launcher
    with open(os.path.join(OUTPUT_DIR, "start.py"), "w", encoding="utf-8") as f:
        f.write(launcher)

    # start.bat - ascii only (per rule: no chinese in bat)
    bat = '''@echo off
python "%~dp0start.py"
pause
'''
    with open(os.path.join(OUTPUT_DIR, "start.bat"), "w") as f:
        f.write(bat)

    log("  start.py + start.bat OK")
    return True


def summary():
    total = 0
    for root, _, files in os.walk(OUTPUT_DIR):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    size_mb = total / 1024 / 1024
    print()
    print("=" * 55)
    print(f"  Portable package created!")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Size:   {size_mb:.0f} MB")
    print()
    print(f"  How to distribute:")
    print(f"  1. Zip the data-ledger-portable folder")
    print(f"  2. User unzips and double-clicks start.bat")
    print("=" * 55)


def main():
    steps = [
        ("Clean old dir", step_clean),
        ("Create dirs", step_dirs),
        ("Copy server.exe", step_exe),
        ("Copy MySQL portable", step_mysql),
        ("Init MySQL data dir", step_init_data),
        ("Create my.cnf", step_mycnf),
        ("Create launcher", step_launcher),
    ]
    for name, fn in steps:
        print(f"\n> {name}")
        try:
            if not fn():
                print(f"  FAILED at: {name}")
                sys.exit(1)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    summary()


if __name__ == "__main__":
    main()

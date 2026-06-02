"""
road-ledger single EXE builder
===============================
Creates a single-file portable EXE for 数据台账系统.

Method:
  1. Zip the entire portable folder into a single bundle
  2. Create a Python launcher stub that extracts the ZIP on first run
  3. Use PyInstaller --add-data to embed the ZIP inside the EXE
  4. At runtime the ZIP is in sys._MEIPASS, launcher reads it from there

Output: E:\reasonix-data\projects\road-ledger\dist\数据台账系统.exe
"""
import os, sys, shutil, zipfile, subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
PORTABLE_DIR = os.path.join(PROJECT_DIR, "data-ledger-portable")
STUB_SRC = os.path.join(PROJECT_DIR, "server", "_launcher_stub.py")
OUTPUT_EXE = os.path.join(DIST_DIR, "数据台账系统.exe")
ZIP_PATH = os.path.join(PROJECT_DIR, "_portable_bundle.zip")
PYINSTALLER = r"C:\Users\Administrator\AppData\Roaming\Python\Python314\Scripts\pyinstaller.exe"


def log(msg):
    print(f"  {msg}")


def create_stub():
    """Create the launcher stub that reads the ZIP from _MEIPASS"""
    stub = r'''"""
Data Ledger self-extracting launcher
Extracts embedded portable bundle to user profile and starts services.
"""
import os, sys, subprocess, time, socket, signal, zipfile, webbrowser

WORK_DIR = os.path.join(os.path.expanduser("~"), ".data-ledger")
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


def extract():
    """Extract embedded _portable_bundle.zip from _MEIPASS to WORK_DIR"""
    marker = os.path.join(WORK_DIR, ".extracted")
    if os.path.exists(marker):
        return True

    print("First run - extracting to " + WORK_DIR + " ...")

    # In PyInstaller --onefile, bundled files are in sys._MEIPASS
    base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
    zip_src = os.path.join(base, "_portable_bundle.zip")

    if not os.path.exists(zip_src):
        print("  ERROR: bundle not found at " + zip_src)
        return False

    os.makedirs(WORK_DIR, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_src, 'r') as zf:
            zf.extractall(WORK_DIR)
        with open(marker, 'w') as f:
            f.write("ok")
        print("  OK")
        return True
    except Exception as e:
        print("  Extract failed: " + str(e))
        return False


def main():
    print("=" * 50)
    print("  Data Ledger System")
    print("=" * 50)

    if not extract():
        input("Press Enter to exit...")
        sys.exit(1)

    MYSQLD = os.path.join(WORK_DIR, "mysql", "bin", "mysqld.exe")
    DATA_DIR = os.path.join(WORK_DIR, "data")
    SERVER_EXE = os.path.join(WORK_DIR, "data-ledger-server.exe")

    # Start MySQL
    print("[1/2] MySQL...", end=" ", flush=True)
    if port_open(3306):
        print("already running")
    else:
        mysql_dir = os.path.join(WORK_DIR, "mysql")
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
            cwd=WORK_DIR,
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


if __name__ == "__main__":
    main()
'''
    with open(STUB_SRC, 'w', encoding='utf-8') as f:
        f.write(stub)
    log(f"  Stub created: {STUB_SRC}")
    return STUB_SRC


def create_bundle():
    """Zip the portable directory into bundle.zip"""
    log("Zipping portable package...")
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PORTABLE_DIR):
            rel_root = os.path.relpath(root, PORTABLE_DIR)
            for f in files:
                file_path = os.path.join(root, f)
                arcname = os.path.join(rel_root, f)
                zf.write(file_path, arcname)
    size_mb = os.path.getsize(ZIP_PATH) // 1024 // 1024
    log(f"  bundle.zip: {size_mb} MB")
    return ZIP_PATH


def compile_exe():
    """Compile stub + embedded ZIP into single EXE"""
    log("Compiling with PyInstaller...")
    # Use --add-data to embed the ZIP
    ret = subprocess.run([
        PYINSTALLER, "--onefile",
        "--name", "数据台账系统",
        "--distpath", DIST_DIR,
        "--add-data", ZIP_PATH + os.pathsep + ".",
        "--hidden-import", "pymysql",
        STUB_SRC
    ], capture_output=True, text=True, timeout=600)
    if ret.returncode != 0:
        log(f"  FAIL: {ret.stderr[:1000]}")
        log(f"  stdout: {ret.stdout[:1000]}")
        return False
    # Check output
    exe_path = os.path.join(DIST_DIR, "数据台账系统.exe")
    if os.path.exists(exe_path):
        log(f"  OK ({os.path.getsize(exe_path)//1024//1024} MB)")
        return True
    log("  FAIL: output not found")
    return False


def cleanup():
    """Remove temp files"""
    for p in [ZIP_PATH, STUB_SRC]:
        try: os.remove(p)
        except: pass
    # Clean up build dir
    build_dir = os.path.join(PROJECT_DIR, "build")
    try: shutil.rmtree(build_dir)
    except: pass
    # Also remove the other launcher if present
    other = os.path.join(DIST_DIR, "data-ledger-launcher.exe")
    try: os.remove(other)
    except: pass


def main():
    print("=" * 55)
    print("  Data Ledger - Single EXE Builder")
    print("  PyInstaller + embedded bundle")
    print("=" * 55)

    if not os.path.exists(PORTABLE_DIR):
        log(f"ERROR: {PORTABLE_DIR} not found. Run build_standalone.py first.")
        sys.exit(1)

    create_stub()
    create_bundle()

    if not compile_exe():
        log("FAILED to compile")
        cleanup()
        sys.exit(1)

    cleanup()

    print()
    print("=" * 55)
    print(f"  Single EXE created!")
    print(f"  {OUTPUT_EXE}")
    print(f"  Size: {os.path.getsize(OUTPUT_EXE)//1024//1024} MB")
    print()
    print("  Distribution:")
    print("  1. Copy 数据台账系统.exe to any Windows 10+ PC")
    print("  2. Double-click to run")
    print("     (First run: extracts ~370MB to %USERPROFILE%\\.data-ledger\\)")
    print("  3. Browser opens automatically at http://127.0.0.1:5000")
    print("  4. Data persists in %USERPROFILE%\\.data-ledger\\data\\")
    print("=" * 55)


if __name__ == "__main__":
    main()

"""
农村公路台账 — 便携体验版打包工具
====================================
从当前开发环境提取必要文件并下载依赖，构建用户双击即可运行的体验版。

用法:
  python build_portable.py

输出目录: target/road-ledger-体验版/
"""
import os, sys, shutil, subprocess, json, urllib.request, zipfile, re, stat, time, io

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(PROJECT_DIR, "server")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "target", "road-ledger-体验版")
MYSQL_INSTALL = r"C:\Program Files\MySQL\MySQL Server 8.4"

# Python 版本匹配
PY_MAJOR = sys.version_info.major
PY_MINOR = sys.version_info.minor
PY_MICRO = sys.version_info.micro
PY_TAG = f"{PY_MAJOR}{PY_MINOR}"
PY_VER = f"{PY_MAJOR}.{PY_MINOR}.{PY_MICRO}"

# 嵌入版 Python 下载链接
EMBED_URL = (
    f"https://www.python.org/ftp/python/{PY_VER}/"
    f"python-{PY_VER}-embed-amd64.zip"
)
GETPIP_URL = "https://bootstrap.pypa.io/get-pip.py"


# ── 工具函数 ──────────────────────────────────────────

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

def download(url, dest):
    """下载文件，显示进度"""
    log(f"下载 {os.path.basename(url)} ...")
    urllib.request.urlretrieve(url, dest)
    size_kb = os.path.getsize(dest) / 1024
    log(f"  完成 ({size_kb:.0f} KB)")

def run(cmd, timeout=120, **kw):
    """执行命令并返回 (ok, stdout)"""
    try:
        # text=False + 手动解码：避免 subprocess 的 reader 线程因非 UTF-8 输出崩溃
        ret = subprocess.run(cmd, capture_output=True, text=False, timeout=timeout, **kw)
        out = (ret.stdout or b"").decode("utf-8", errors="replace") + (ret.stderr or b"").decode("utf-8", errors="replace")
        return ret.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "超时"
    except Exception as e:
        return False, str(e)


# ── 打包步骤 ──────────────────────────────────────────

def step_clean():
    log("清理旧目录...")
    rmtree_force(OUTPUT_DIR)
    return True

def step_dirs():
    log("创建目录结构...")
    for d in ["app", "mysql/bin", "mysql/share", "mysql/lib/plugin", "data", "python"]:
        ensure_dir(os.path.join(OUTPUT_DIR, d))
    return True

def step_mysql():
    log("打包 MySQL 便携版...")
    # mysqld.exe
    src = os.path.join(MYSQL_INSTALL, "bin", "mysqld.exe")
    if not os.path.exists(src):
        log(f"  ❌ 未找到 {src}")
        return False
    shutil.copy2(src, os.path.join(OUTPUT_DIR, "mysql", "bin"))
    log("  mysqld.exe ✓")

    # DLLs
    dlls = 0
    bin_dir = os.path.join(MYSQL_INSTALL, "bin")
    for f in os.listdir(bin_dir):
        if f.endswith(".dll"):
            shutil.copy2(os.path.join(bin_dir, f),
                         os.path.join(OUTPUT_DIR, "mysql", "bin"))
            dlls += 1
    log(f"  {dlls} DLLs ✓")

    # share/ (charsets + 英文错误信息)
    for sub in ["charsets", "english"]:
        src = os.path.join(MYSQL_INSTALL, "share", sub)
        if os.path.exists(src):
            shutil.copytree(src, os.path.join(OUTPUT_DIR, "mysql", "share", sub),
                          dirs_exist_ok=True)
    log("  share/ ✓")

    # lib/plugin/
    src = os.path.join(MYSQL_INSTALL, "lib", "plugin")
    if os.path.exists(src):
        for f in os.listdir(src):
            full = os.path.join(src, f)
            if os.path.isfile(full):
                shutil.copy2(full, os.path.join(OUTPUT_DIR, "mysql", "lib", "plugin"))
    log("  lib/plugin/ ✓")
    return True

def step_mysql_data():
    data_dir = os.path.join(OUTPUT_DIR, "data")
    if os.path.exists(os.path.join(data_dir, "mysql")):
        log("数据目录已存在，跳过初始化")
        return True
    log("初始化 MySQL 数据目录...")
    ensure_dir(data_dir)
    mysqld = os.path.join(OUTPUT_DIR, "mysql", "bin", "mysqld.exe")
    ok, out = run([mysqld, "--initialize-insecure",
                   f"--datadir={data_dir}", "--console"], timeout=60)
    if ok:
        log("  完成 ✓")
    else:
        log(f"  ⚠ 输出: {out[-200:]}")
        # 可能已初始化过
        if os.path.exists(os.path.join(data_dir, "mysql")):
            log("  数据目录已存在 ✓")
            return True
        log(f"  ❌ 初始化失败")
        return False
    return True

def step_python_embed():
    """下载并解压 Python 嵌入版"""
    py_dir = os.path.join(OUTPUT_DIR, "python")
    zip_path = os.path.join(PROJECT_DIR, "_python_embed.zip")

    if not os.path.exists(zip_path):
        try:
            download(EMBED_URL, zip_path)
        except Exception as e:
            log(f"  ❌ 下载失败: {e}")
            log("  请手动下载后重试:")
            log(f"    {EMBED_URL}")
            log(f"  放入 {zip_path}")
            return False
    else:
        log("使用缓存的 Python 嵌入版...")

    log("解压 Python 嵌入版...")
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(py_dir)
    log("  解压完成 ✓")
    return True

def step_install_pip():
    """安装 pip 到嵌入版 Python"""
    py_dir = os.path.join(OUTPUT_DIR, "python")
    python_exe = os.path.join(py_dir, "python.exe")
    
    if not os.path.exists(python_exe):
        log("  ❌ 找不到 python.exe")
        return False

    # 下载 get-pip.py
    getpip_path = os.path.join(PROJECT_DIR, "_get-pip.py")
    if not os.path.exists(getpip_path):
        try:
            download(GETPIP_URL, getpip_path)
        except Exception as e:
            log(f"  ❌ 下载 get-pip.py 失败: {e}")
            return False

    # 修改 python._pth 添加应用和依赖路径
    pth_file = os.path.join(py_dir, f"python{PY_TAG}._pth")
    if os.path.exists(pth_file):
        with open(pth_file, 'r') as f:
            content = f.read()
        if "#import site" in content:
            content = content.replace("#import site", "import site")
        # 添加 site-packages 和应用路径
        lines = content.strip().splitlines()
        new_lines = []
        added = {"Lib\\site-packages": False, "..\\app": False}
        for l in lines:
            new_lines.append(l)
            if l.strip() == ".":
                new_lines.append("Lib\\site-packages")
                new_lines.append("..\\app")
        content = "\n".join(new_lines) + "\n"
        with open(pth_file, 'w') as f:
            f.write(content)
        log("  启用 site-packages 和应用路径 ✓")

    # 安装 pip
    log("安装 pip...")
    ok, out = run([python_exe, getpip_path, "--no-warn-script-location"], timeout=60)
    if ok:
        log("  pip ✓")
    else:
        log(f"  ⚠ 输出: {out[-200:]}")
    
    # 验证 pip
    ok, out = run([python_exe, "-m", "pip", "--version"], timeout=30)
    if ok:
        log(f"  {out.strip()}")
        return True
    else:
        log(f"  ❌ pip 不可用")
        return False

def step_install_deps():
    """安装 Flask 等依赖到便携 Python"""
    py_dir = os.path.join(OUTPUT_DIR, "python")
    python_exe = os.path.join(py_dir, "python.exe")

    deps = ["flask>=3.0", "pymysql>=1.1", "openpyxl>=3.1", "xlrd>=2.0"]
    log("安装 Python 依赖...")
    site_pkg = os.path.join(py_dir, "Lib", "site-packages")
    # 用 --target 强制安装到便携包的 site-packages，防止装到用户目录
    for dep in deps:
        log(f"  {dep} ...")
        ok, out = run([python_exe, "-m", "pip", "install",
                       f"--target={site_pkg}", dep,
                       "--no-warn-script-location"], timeout=120)
        if ok:
            log(f"    ✓")
        else:
            log(f"    ⚠ {out[-200:]}")
    
    log("依赖安装完成 ✓")
    return True

def step_copy_app():
    log("复制应用代码...")
    app_out = os.path.join(OUTPUT_DIR, "app")
    for item in os.listdir(SERVER_DIR):
        if item in ("__pycache__", "_backup", ".gitignore"):
            continue
        src = os.path.join(SERVER_DIR, item)
        dst = os.path.join(app_out, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    # 清理 _backup 下的旧备份（体验版不需要）
    backup_dir = os.path.join(app_out, "_backup")
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
        ensure_dir(backup_dir)
        # 创建空的 manifest
        with open(os.path.join(backup_dir, "_manifest.json"), "w") as f:
            json.dump([], f)
    log("  完成 ✓")
    return True

def step_create_launchers():
    """创建启动/关闭脚本"""
    log("创建启动脚本...")

    # ── 启动脚本 ──────────────────────────────
    bat = r"""@echo off
chcp 65001 >nul
title 农村公路台账 - 体验版
cd /d "%~dp0"
setlocal enabledelayedexpansion

set PYTHON_DIR=%~dp0python
set APP_DIR=%~dp0app
set PATH=%PYTHON_DIR%;%~dp0mysql\bin;%PATH%
set PYTHONNOUSERSITE=1
set PYTHONUTF8=1

echo ========================================
echo    农村公路台账 — 体验版
echo ========================================
echo.

::======== 1. 启动 MySQL ========
echo [1/3] MySQL ...

tasklist /fi "IMAGENAME eq mysqld.exe" 2>nul | find /i "mysqld.exe" >nul
if errorlevel 1 (
    start /b "" .\mysql\bin\mysqld.exe --basedir=.\mysql --datadir=.\data --port=3306 --console --lc-messages-dir=.\mysql\share
    set tries=0
    :wait_mysql_loop
    ping -n 2 127.0.0.1 >nul
    netstat -an 2>nul | findstr ":3306 " >nul
    if errorlevel 1 (
        set /a tries+=1
        if !tries! lss 10 goto wait_mysql_loop
    )
)
echo   OK

::======== 2. 创建数据库 ========
echo [2/3] 初始化数据库...
"%PYTHON_DIR%\python.exe" -c "import pymysql;c=pymysql.connect(host='127.0.0.1',user='root',password='',autocommit=True);c.cursor().execute('CREATE DATABASE IF NOT EXISTS road_ledger CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci');c.close()" 2>nul
echo   OK

::======== 3. 启动 Web ========
echo [3/3] 启动 Web 服务...
start "" http://127.0.0.1:5000
cd /d "%APP_DIR%"
"%PYTHON_DIR%\python.exe" -u app.py

echo.
echo 服务已停止
pause >nul

echo.
echo 服务已停止，按任意键退出...
pause >nul
"""
    with open(os.path.join(OUTPUT_DIR, "启动体验版.bat"), "w", encoding="utf-8") as f:
        f.write(bat)

    # ── 停止脚本 ──────────────────────────────
    stop = r"""@echo off
chcp 65001 >nul
title 农村公路台账 - 关闭
echo 正在关闭农村公路台账...
:: 关闭 Flask
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1 && echo   Flask 已关闭
)
:: 关闭 MySQL
taskkill /f /im mysqld.exe >nul 2>&1 && echo   MySQL 已关闭
echo.
echo 所有服务已关闭
timeout /t 2 /nobreak >nul
"""
    with open(os.path.join(OUTPUT_DIR, "停止体验版.bat"), "w", encoding="utf-8") as f:
        f.write(stop)

    # ── 使用说明 ──────────────────────────────
    readme = """农村公路台账 — 体验版
====================================

使用方法：
  1. 双击「启动体验版.bat」
  2. 等待浏览器自动打开 http://127.0.0.1:5000
  3. 开始使用（导入 Excel、建表、编辑数据）
  4. 用完双击「停止体验版.bat」关闭服务

文件说明：
  app/           ─ Web 应用（Flask 后端 + 前端页面）
  mysql/         ─ MySQL 数据库便携版
  data/          ─ 您的数据（建表后存在这里）
  python/        ─ Python 运行环境

注意事项：
  - 所有数据保存在 data/ 目录，重装前请备份
  - 备份在 app/_backup/ 目录中
  - 端口 5000 被占用时，改启动脚本中的端口
  - 关闭时请用「停止体验版.bat」，不要直接关窗口

系统要求：
  - Windows 10/11 64位
  - 无需安装任何额外软件
"""
    with open(os.path.join(OUTPUT_DIR, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(readme)

    log("  完成 ✓")
    return True


def step_optimize():
    """优化：删除不必要的文件减小体积"""
    log("优化体积...")
    
    # 删除 Python 缓存
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for d in dirs:
            if d == "__pycache__":
                path = os.path.join(root, d)
                rmtree_force(path)
                log(f"  清理: {path}")
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                os.remove(os.path.join(root, f))
    
    # 删除 MySQL 不需要的组件
    mysql_bin = os.path.join(OUTPUT_DIR, "mysql", "bin")
    keep_exe = {"mysqld.exe"}
    for f in os.listdir(mysql_bin):
        if f.endswith(".exe") and f not in keep_exe:
            os.remove(os.path.join(mysql_bin, f))
    
    log("  完成 ✓")
    return True


def summary():
    """打印打包结果"""
    print()
    print("=" * 55)
    print("  ✅ 便携体验版打包完成！")
    print(f"  输出目录: {OUTPUT_DIR}")
    print()
    
    total_size = 0
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for f in files:
            total_size += os.path.getsize(os.path.join(root, f))
    
    print(f"  总大小: {total_size/1024/1024:.1f} MB")
    print()
    print("  体验版文件清单：")
    for item in sorted(os.listdir(OUTPUT_DIR)):
        full = os.path.join(OUTPUT_DIR, item)
        if os.path.isdir(full):
            sz = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(full) for f in fn) / 1024
            tag = "<DIR>"
        else:
            sz = os.path.getsize(full) / 1024
            tag = "     "
        print(f"    {tag}  {sz:>8.0f} KB  {item}")
    print()
    print("  分发方式：将整个文件夹压缩为 .zip 即可。")
    print("  用户解压后双击「启动体验版.bat」。")
    print("=" * 55)


# ── 主流程 ────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  农村公路台账 — 便携体验版打包工具")
    print(f"  Python {PY_VER} 嵌入版下载地址:")
    print(f"  {EMBED_URL}")
    print("=" * 55)
    print()

    steps = [
        ("清理旧目录", step_clean),
        ("创建目录结构", step_dirs),
        ("复制 MySQL 便携版", step_mysql),
        ("初始化 MySQL 数据目录", step_mysql_data),
        ("下载 Python 嵌入版", step_python_embed),
        ("安装 pip", step_install_pip),
        ("安装 Python 依赖", step_install_deps),
        ("复制应用代码", step_copy_app),
        ("创建启动脚本", step_create_launchers),
        ("优化体积", step_optimize),
    ]

    for name, fn in steps:
        print(f"\n▶ {name}")
        try:
            if not fn():
                print(f"\n  ❌ 步骤失败: {name}")
                sys.exit(1)
        except KeyboardInterrupt:
            print(f"\n  ⚠ 用户中断")
            sys.exit(1)
        except Exception as e:
            print(f"\n  ❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    summary()


if __name__ == "__main__":
    main()

# 🛣️ 数据台账系统

农村公路建设项目台账管理工具 —— 支持 **Windows** 和 **麒麟 Linux (ARM64)**。

## 版本说明

| 分支 | 平台 | 数据库 | 运行方式 |
|------|------|--------|---------|
| `windows/linux` | Windows x64 | MySQL | `python start.py` 或编译单文件 exe |
| `kylin-build` | 麒麟 V10 ARM64 | SQLite | `./data-ledger` 或双击 `start-kylin.sh` |

---

## Windows 版

```bash
pip install flask pymysql openpyxl xlrd
python start.py
```

浏览器打开 http://127.0.0.1:5000

> 需要本机安装 MySQL 8.4

## 麒麟版

从 [Releases](https://github.com/1013059024/data-ledger/releases) 下载 `data-ledger-kylin-single-file`（v1.1.0-kylin），
解压得到 `data-ledger` 二进制文件：

```bash
chmod +x data-ledger
./data-ledger
```

浏览器打开 http://127.0.0.1:5000

也可双击 `start-kylin.sh` 一键启动（需和 `data-ledger` 放同一目录）。

> 麒麟版为 PyInstaller 单文件编译，内置 Python 3.9 + 全部依赖，**无需联网、无需预装任何环境**。

---

## 项目结构

```
server/               # Web 应用源码
├── app.py            # Flask 路由与业务逻辑
├── db.py             # 数据库操作层
├── config.py         # 配置
├── templates/        # 前端界面
├── static/           # 静态资源
└── pyi_entry.py      # PyInstaller 入口（含端口释放）
kylin-build/server/   # 麒麟版 SQLite 源码（同上结构）
Dockerfile            # 麒麟版 ARM64 构建
start-kylin.sh        # 麒麟桌面启动脚本
```

## 构建

- **Windows 编译**: 使用 PyInstaller 打包 `server/pyi_entry.py`
- **麒麟版构建**: GitHub Actions → `build-kylin-single` workflow，QEMU 模拟 ARM64 编译

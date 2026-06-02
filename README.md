# 🛣️ 数据台账系统系统

农村公路建设项目台账管理工具。

> 详细操作说明见 **[使用手册.md](使用手册.md)**

---

## 目录结构

```
E:\reasonix-data\projects\data-ledger\
├── server/              ← 源码
│   ├── app.py            Flask 路由与业务逻辑
│   ├── db.py             数据库操作层
│   ├── config.py         配置
│   └── templates/        前端界面
├── mysql-data/           ← MySQL 数据目录
├── _备份_源码勿删!/       ← 源码备份（火绒保护）
├── portable_packages/    ← 便携包（linux / win 两种）
├── build_portable.py     ← 便携版打包脚本
├── start.py / start.bat ← 启动脚本
├── 使用手册.md            ← 操作指南
└── 使用手册.md           ← 本文档
```

## 快速启动

```bash
pip install flask pymysql openpyxl xlrd
python start.py
```

浏览器打开 http://127.0.0.1:5000

## 便携版打包

```bash
python build_portable.py
```

输出在 `target/data-ledger-便携版/`

> 需要本机安装 MySQL 8.4 + 有网络

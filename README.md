# 🛣️ 农村公路台账系统

农村公路建设项目台账管理工具，支持多表管理、字段映射同步、汇总统计、Excel 导入导出。

## 快速启动

```bash
python start.py
```

浏览器打开 `http://127.0.0.1:5000`

## 技术栈

- 后端：Python Flask + PyMySQL
- 前端：jQuery + Bootstrap 5
- 数据库：MySQL 8.4（便携版，项目内 data 目录）

## 详细文档

详见 [`使用手册.md`](使用手册.md)。

## 目录结构

```
server/         后端 + 前端单页应用
├── app.py       Flask 路由与业务逻辑
├── db.py        数据库操作层
├── config.py    MySQL 连接配置
├── templates/index.html   全部前端界面
├── _backup/     删表自动备份
├── _sync_mappings.json   映射配置
├── _key_fields.json      关键字段配置
└── _hidden_columns.json  隐藏列配置
start.py        一键启动脚本
```

## 系统要求

- Python ≥ 3.10
- MySQL 8.4（或兼容版本）
- Windows（启动脚本基于 Windows 环境）

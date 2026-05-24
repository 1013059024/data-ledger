# 农村公路台账 — Web 管理工具

> 从 Excel/CSV 导入数据到 MySQL，通过 Web 页面浏览、编辑、同步跨表数据。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python Flask 3.0 |
| 数据库 | MySQL 8.4（`road_ledger` 库） |
| 前端 | Bootstrap 5 + jQuery |
| 连接 | PyMySQL |

## 目录结构

```
road-ledger-main/
├── README.md                  # 本文件
├── start.py                   # 一键启动脚本（Python，推荐）
├── start_debug.bat            # 一键启动脚本（批处理，带 LAN 共享）
├── close_debug.bat            # 关闭防火墙端口
├── mysql-data/                # MySQL 数据目录（自动初始化）
├── server/
│   ├── app.py                 # Flask 入口（路由 + API）
│   ├── db.py                  # MySQL 操作（查询/分页/建表/同步）
│   ├── config.py              # MySQL 连接配置
│   ├── requirements.txt       # Python 依赖
│   ├── _sync_mappings.json    # 字段映射配置
│   ├── _table_groups.json     # 表分组配置
│   ├── _uploads/              # 上传临时文件
│   ├── templates/index.html   # 前端页面
│   └── static/css/style.css   # 自定义样式
```

## 启动（推荐）

```bash
# Python 方式（跨平台，自动处理 MySQL）
python start.py

# Windows 批处理方式（含 LAN 共享）
start_debug.bat
```

访问 `http://127.0.0.1:5000`

> MySQL 8.4 须已安装（默认路径 `C:\Program Files\MySQL\MySQL Server 8.4\`），首次启动会自动初始化数据目录和数据库。root 空密码。

## 功能

### 数据导入
- 支持 .xlsx / .xls / .csv
- 多 Sheet 选择
- 双层表头合并（表头行数设为 2）
- 勾选要导入的列
- 指定关键字段，只导入该字段非空的行
- 自动识别列类型（INT / DOUBLE / DATE / VARCHAR / TEXT）

### 数据浏览
- 左侧表目录切换
- 每页 50 条分页 + 搜索
- 双击单元格编辑值
- 双击表头编辑字段名
- DOUBLE 类型保留两位小数

### 表管理
- 导入自动建表
- 重命名 / 删除表
- 重命名字段

### 跨表同步
- 通过「🔗 映射」配置字段对应关系
- 关键字段值相等的记录间自动同步
- 不同名的字段也可映射（如 县区 ↔ 区县）
- 映射保存在 `_sync_mappings.json`

## 数据库

库名：`road_ledger`  
连接：`127.0.0.1:3306` / root / 无密码

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tables` | 表列表 |
| GET | `/api/table/<name>` | 表数据（分页搜索） |
| DELETE | `/api/table/<name>` | 删除表 |
| PUT | `/api/table/<name>` | 重命名表 |
| PATCH | `/api/table/<name>` | 更新单元格 |
| PUT | `/api/table/<name>/column` | 重命名字段 |
| GET | `/api/sync/mappings` | 查询映射 |
| POST | `/api/sync/mappings` | 保存映射 |
| POST | `/api/upload/parse` | 上传解析 |
| POST | `/api/upload/select_sheet` | 切换 Sheet |
| POST | `/api/upload/set_header_rows` | 表头行数 |
| POST | `/api/upload/import` | 确认导入 |

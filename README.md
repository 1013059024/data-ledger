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
├── start.py                   # 开发环境一键启动（Python）
├── build_portable.py          # 便携体验版打包工具
├── mysql-data/                # 开发用 MySQL 数据目录（自动初始化）
├── target/                    # 打包输出目录（便携体验版）
│   └── road-ledger-体验版/    # 用户双击即可运行的完整包
├── server/                    # Flask 应用源码
│   ├── app.py                 # Flask 入口（路由 + API）
│   ├── db.py                  # MySQL 操作（查询/分页/建表/同步）
│   ├── config.py              # MySQL 连接配置
│   ├── requirements.txt       # Python 依赖
│   ├── _sync_mappings.json    # 字段映射配置
│   ├── _table_groups.json     # 表分组配置
│   ├── _key_fields.json       # 关键字段配置
│   ├── _backup/               # 自动备份目录
│   ├── templates/index.html   # 前端页面
│   └── static/css/style.css   # 自定义样式
```

## 两种使用方式

### ① 开发模式（本机调试，需要 Python + MySQL 环境）

#### 前置条件
- Python 3.14+
- MySQL 8.4（默认路径 `C:\Program Files\MySQL\MySQL Server 8.4\`）
- root 空密码

#### 启动
```bash
python start.py
```

一键自动：启动 MySQL → 确保 `road_ledger` 库存在 → 启动 Flask Web 服务。

访问 `http://127.0.0.1:5000`

#### 停止
按 `Ctrl+C` 即可关闭 MySQL + Flask。

### ② 便携体验版（用户双击即用，无需任何安装）

适用于分发给不熟悉技术的用户。**用户电脑无需安装 Python、MySQL 等任何环境。**

#### 获取体验版

**方式 A：直接打包（推荐）**
```bash
python build_portable.py
```
输出目录：`target/road-ledger-体验版/`（约 370 MB，含 MySQL + Python + 全部依赖）

将整个文件夹压缩为 `.zip` 即可分发给用户。

**方式 B：下载已打包的版本**
（待提供下载链接）

#### 用户使用方法

| 操作 | 方法 |
|---|---|
| **启动** | 双击 `启动体验版.bat` |
| **使用** | 自动打开浏览器 `http://127.0.0.1:5000` |
| **关闭** | 双击 `停止体验版.bat` 或直接关掉命令行窗口 |

体验版启动后会自动完成：启动 MySQL → 创建数据库 → 启动 Web → 打开浏览器。

#### 文件说明

| 目录/文件 | 说明 |
|---|---|
| `app/` | Web 应用（Flask 后端 + 前端页面） |
| `mysql/` | MySQL 8.4 便携版 |
| `python/` | Python 3.14 嵌入版 + Flask/pymysql/openpyxl 依赖 |
| `data/` | 用户数据（建表后存储在这里，注意备份） |
| `启动体验版.bat` | 一键启动 |
| `停止体验版.bat` | 一键关闭 |
| `使用说明.txt` | 给最终用户的操作指引 |

---

## 功能介绍

### 数据导入
- 支持 `.xlsx` / `.xls` / `.csv`
- 多 Sheet 选择
- 双层表头合并（表头行数设为 2）
- 勾选要导入的列
- 指定关键字段，只导入该字段非空的行
- 自动识别列类型（INT / DOUBLE / DATE / VARCHAR / TEXT）

### 数据浏览
- 左侧表目录切换
- 每页 50 条分页 + 搜索
- 双击单元格编辑值，自动跨表同步
- 双击表头编辑字段名
- DOUBLE 类型保留两位小数

### 表管理
- 导入自动建表 / 手动建表
- 重命名 / 删除表（删表前自动备份）
- 新增 / 重命名 / 删除字段
- 调整字段顺序
- 修改字段数据类型

### 跨表同步（🔗 映射）
- 配置表间字段对应关系
- 关键字段值相等的记录间自动同步编辑
- 不同名字段也可映射（如 `县区` ↔ `区县`）
- 重命名字段时自动更新相关映射

### 汇总表
- 多表数据合并为汇总视图
- 同义不同名字段自动合并
- 汇总表双向同步回源表

### 自动备份
- 删表前自动备份数据+结构到 `_backup/` 目录
- 建表/导入后记录 manifest
- 可通过 API 恢复备份

### 导出
- 导出为 Excel（公文格式：黑体标题 + 仿宋正文 + 全框线 + 居中）

---

## 数据库

| 项目 | 值 |
|---|---|
| 库名 | `road_ledger` |
| 连接 | `127.0.0.1:3306` |
| 用户 | `root`（无密码） |

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tables` | 表列表 |
| GET | `/api/table/<name>` | 表数据（分页搜索） |
| POST | `/api/tables` | 手动建表 |
| DELETE | `/api/table/<name>` | 删除表 |
| PUT | `/api/table/<name>` | 重命名表 |
| PATCH | `/api/table/<name>` | 更新单元格 |
| PUT | `/api/table/<name>/column` | 重命名字段 |
| POST | `/api/table/<name>/column` | 新增字段 |
| DELETE | `/api/table/<name>/column/<col>` | 删除字段 |
| PATCH | `/api/table/<name>/column/<col>/type` | 修改字段类型 |
| PUT | `/api/table/<name>/reorder-columns` | 调整字段顺序 |
| POST | `/api/table/<name>/row` | 添加行 |
| DELETE | `/api/table/<name>/row/<id>` | 删除行 |
| POST | `/api/table/<name>/row/<id>/hide` | 隐藏行 |
| GET | `/api/table/<name>/lookup` | 按字段查找（自动补全） |
| GET | `/api/table/<name>/export` | 导出 Excel |
| GET | `/api/table/<name>/key-field` | 获取关键字段 |
| PUT | `/api/table/<name>/key-field` | 设置关键字段 |
| GET | `/api/sync/mappings` | 查询映射 |
| POST | `/api/sync/mappings` | 保存映射 |
| GET | `/api/table-groups` | 查询分组 |
| POST | `/api/table-groups` | 保存分组 |
| GET | `/api/backup/list` | 备份列表 |
| POST | `/api/backup/restore` | 恢复备份 |
| POST | `/api/upload/parse` | 上传解析 Excel/CSV |
| POST | `/api/upload/select_sheet` | 切换 Sheet |
| POST | `/api/upload/set_header_rows` | 设置表头行数 |
| POST | `/api/upload/import` | 确认导入 |

## 开发说明

### 调试时常用命令

```bash
# 启动
python start.py

# 打包便携体验版
python build_portable.py

# 手动管理 MySQL
"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -e "CREATE DATABASE IF NOT EXISTS road_ledger CHARACTER SET utf8mb4"
```

### 文件说明

| 文件 | 用途 |
|---|---|
| `server/app.py` | Flask 应用入口，所有路由和 API 定义 |
| `server/db.py` | MySQL 数据库操作层（查询/建表/分页/同步） |
| `server/config.py` | MySQL 连接配置 |
| `server/templates/index.html` | 前端单页应用（Bootstrap 5 + jQuery） |
| `server/static/css/style.css` | 自定义样式 |
| `build_portable.py` | 便携体验版打包工具 |
| `start.py` | 开发环境一键启动脚本 |

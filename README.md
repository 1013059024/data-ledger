# 数据台账系统 — 麒麟版

ARM64 Linux 单文件 Web 应用（Flask + SQLite），用于表格数据浏览、编辑、导入/导出。

---

## 启动方式

```bash
bash start.sh
```

打开浏览器访问 **http://127.0.0.1:5000**

---

## 常见问题

### Excel 导入提示"失败"

旧目录的进程仍占着 5000 端口。已修改 `start.sh` 自动检测并杀掉旧进程，运行 `bash start.sh` 即可。

### 按钮前有小方框

360 浏览器 emoji 渲染问题，换 Chrome/Firefox 即可。

---

## 项目结构

```
├── start.sh          # 启动脚本（自动清理旧进程）
├── py.tar.gz         # ARM64 Python 运行环境
├── bin/              # Python 3.9 及工具链
├── server/           # Web 应用（Flask + SQLite）
│   ├── app.py        # 主程序
│   ├── db.py         # 数据库操作
│   ├── config.py     # 配置
│   ├── static/       # 静态资源
│   └── templates/    # 前端页面
├── data/             # 数据库文件
└── README.md
```

## 构建

GitHub Actions 自动构建，使用 conda-pack 打包 ARM64 Python 运行环境。

详细操作见 [使用手册.md](使用手册.md)

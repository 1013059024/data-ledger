#!/bin/bash
# 数据台账系统 — 麒麟桌面启动脚本
# 放到 data-ledger 同目录，双击即可运行（选择"在终端中运行"）

# 获取脚本所在目录
cd "$(dirname "$0")"

echo "========================================"
echo "  数据台账系统 启动中..."
echo "========================================"
echo ""

# 检查二进制是否存在
if [ ! -f "./data-ledger" ]; then
    echo "❌ 错误：未找到 data-ledger 文件"
    echo "   请将此脚本与 data-ledger 放在同一目录"
    echo ""
    echo "按 Enter 键退出..."
    read
    exit 1
fi

# 检查执行权限
if [ ! -x "./data-ledger" ]; then
    echo "设置执行权限..."
    chmod +x ./data-ledger
fi

# 释放端口（麒麟兼容方式）
echo "释放端口 5000..."
fuser -k 5000/tcp 2>/dev/null
# 或通过 /proc/net/tcp
if command -v ss &>/dev/null; then
    PID=$(ss -tlnp 2>/dev/null | grep ':5000' | grep -oP 'pid=\K\d+')
    [ -n "$PID" ] && kill -9 $PID 2>/dev/null
fi

echo ""
echo "========================================"
echo "  启动服务器..."
echo "  浏览器打开: http://127.0.0.1:5000"
echo "========================================"
echo ""

# 运行
./data-ledger

# 运行结束后暂停（双击运行时可以看到退出信息）
echo ""
echo "服务器已停止。按 Enter 键关闭窗口..."
read

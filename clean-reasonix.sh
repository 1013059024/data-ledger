#!/bin/bash
# Reasonix 麒麟系统完全清理脚本
echo "Reasonix 完全清理"
PIDS=$(ps aux | grep reasonix | grep -v grep | awk '{print $2}')
[ -n "$PIDS" ] && kill $PIDS 2>/dev/null && kill -9 $PIDS 2>/dev/null && echo "进程已停止"
for p in /usr/local/bin/reasonix /usr/bin/reasonix ~/.local/bin/reasonix ./reasonix-kylin ./reasonix; do
    [ -f "$p" ] && rm -f "$p" && echo "已删除: $p"
done
for d in ~/.reasonix ~/.config/reasonix ~/.cache/reasonix .reasonix; do
    [ -d "$d" ] && rm -rf "$d" && echo "已删除: $d"
done
command -v npm &>/dev/null && npm uninstall -g reasonix 2>/dev/null
command -v pnpm &>/dev/null && pnpm uninstall -g reasonix 2>/dev/null
rm -rf ~/.npm/_npx/*reasonix* 2>/dev/null
[ -f ~/.bashrc ] && sed -i '/reasonix/d' ~/.bashrc 2>/dev/null
[ -f ~/.zshrc ] && sed -i '/reasonix/d' ~/.zshrc 2>/dev/null
echo "清理完成"

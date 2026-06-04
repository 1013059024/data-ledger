#!/bin/bash
# Reasonix 麒麟系统安装脚本
# 1. 去 Actions 下载 reasonix-kylin-arm64 放到本目录
# 2. 把数据台账系统-麒麟版.zip 也放本目录
# 3. bash reasonix-kylin-setup.sh
# 4. 输入 API Key
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Reasonix 麒麟安装"
BIN="$DIR/reasonix-kylin"
[ ! -f "$BIN" ] && echo "❌ 没找到 reasonix-kylin" && exit 1
chmod +x "$BIN"
mkdir -p "$DIR/.reasonix"
echo -n "DeepSeek API Key: "
read KEY
cat > "$DIR/.reasonix/config.json" << EOF
{"apiKey":"$KEY","editMode":"review","projects":{"$DIR/data-ledger":{"shellAllowed":["python","pip","ls","cat","ps","netstat","kill","curl","tar","unzip","echo","which","file","fc-list"]}}}
EOF
Z="$(ls 数据台账系统-麒麟版*.zip 2>/dev/null|head -1)"
[ -f "$Z" ] && unzip -o "$Z" -d "$DIR/data-ledger" 2>/dev/null && echo "data-ledger 已解压"
echo "完成! 运行: cd data-ledger && ../reasonix-kylin code"

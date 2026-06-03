# 麒麟版数据台账系统 — 单文件可执行文件构建（已修复）
# 修复：加装 pymysql + 强制 PyInstaller 打包 hidden imports

# ── 构建阶段 ──
FROM quay.io/pypa/manylinux2014_aarch64 AS builder

WORKDIR /build
COPY server/ ./server/

# 用 conda 装 Python 3.9（预编译，带 --enable-shared）
# 修复：加装 pymysql（麒麟版运行时之前找不到此模块）
RUN curl -fsSL -o /tmp/miniforge.sh \
    https://github.com/conda-forge/miniforge/releases/download/24.11.3-0/Miniforge3-Linux-aarch64.sh \
    && bash /tmp/miniforge.sh -b -p /opt/conda \
    && rm /tmp/miniforge.sh \
    && /opt/conda/bin/conda install -y python=3.9 pip \
    && /opt/conda/bin/pip install --no-cache-dir \
        pyinstaller \
        flask>=3.0 \
        pymysql>=1.1 \
        openpyxl>=3.1 \
        xlrd>=2.0

# PyInstaller 打包为单文件
# 修复：添加 --hidden-import 确保 pymysql 等模块被强制打包
ENV LD_LIBRARY_PATH=/opt/conda/lib:$LD_LIBRARY_PATH
RUN cd server && \
    /opt/conda/bin/python3.9 -m PyInstaller --onefile \
    --name 数据台账系统 \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --hidden-import pymysql \
    --hidden-import openpyxl \
    --hidden-import xlrd \
    --hidden-import decimal \
    pyi_entry.py

# ── 输出阶段 ──
# scratch 是空镜像，只复制二进制文件
FROM scratch AS output
COPY --from=builder /build/server/dist/数据台账系统 /dist/

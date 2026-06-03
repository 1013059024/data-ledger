# 麒麟版数据台账系统 — 单文件可执行文件构建（SQLite 版）
# 无 MySQL/pymysql 依赖，麒麟系统上直接运行

# ── 构建阶段 ──
FROM quay.io/pypa/manylinux2014_aarch64 AS builder

WORKDIR /build
# 注意：编译 kylin-build/server/（SQLite 版），不是 server/（MySQL 版）
COPY kylin-build/server/ ./server/

# 用 conda 装 Python 3.9（预编译，带 --enable-shared）
# SQLite 版无需 pymysql，Python 标准库自带 sqlite3
RUN curl -fsSL -o /tmp/miniforge.sh \
    https://github.com/conda-forge/miniforge/releases/download/24.11.3-0/Miniforge3-Linux-aarch64.sh \
    && bash /tmp/miniforge.sh -b -p /opt/conda \
    && rm /tmp/miniforge.sh \
    && /opt/conda/bin/conda install -y python=3.9 pip \
    && /opt/conda/bin/pip install --no-cache-dir \
        pyinstaller \
        flask>=3.0 \
        openpyxl>=3.1 \
        xlrd>=2.0

# PyInstaller 打包为单文件（英文名，麒麟终端更方便）
ENV LD_LIBRARY_PATH=/opt/conda/lib:$LD_LIBRARY_PATH
RUN cd server && \
    /opt/conda/bin/python3.9 -m PyInstaller --onefile \
    --name data-ledger \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --hidden-import openpyxl \
    --hidden-import xlrd \
    pyi_entry.py

# ── 输出阶段 ──
FROM scratch AS output
COPY --from=builder /build/server/dist/data-ledger /dist/

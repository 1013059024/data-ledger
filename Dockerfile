# 麒麟版数据台账系统 — 单文件可执行文件构建
FROM quay.io/pypa/manylinux2014_aarch64

WORKDIR /build
COPY server/ ./server/

# 装 conda（比编译 Python 源码快 10 倍）
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

# PyInstaller 打包
ENV LD_LIBRARY_PATH=/opt/conda/lib:$LD_LIBRARY_PATH
RUN cd server && \
    /opt/conda/bin/python3.9 -m PyInstaller --onefile \
    --name 数据台账系统 \
    --add-data "templates:templates" \
    --add-data "static:static" \
    pyi_entry.py

RUN mkdir -p /build/dist && \
    cp /build/server/dist/数据台账系统 /build/dist/

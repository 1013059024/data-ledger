# 麒麟版数据台账系统 — 单文件可执行文件构建
#
# 构建方式（GitHub Actions 自动执行）：
#   docker buildx build --platform linux/arm64 --output type=local,dest=./output -f Dockerfile .
#
# 产物：dist/数据台账系统（aarch64 ELF 单文件）

FROM quay.io/pypa/manylinux2014_aarch64

WORKDIR /build

# 复制服务端代码
COPY kylin-build/server/ ./server/

# 安装 Python 依赖
RUN /opt/python/cp39-cp39/bin/pip install --no-cache-dir \
    pyinstaller \
    flask>=3.0 \
    openpyxl>=3.1 \
    xlrd>=2.0

# PyInstaller 打包为单文件
RUN cd server && \
    /opt/python/cp39-cp39/bin/pyinstaller --onefile \
    --name 数据台账系统 \
    --add-data "templates:templates" \
    --add-data "static:static" \
    pyi_entry.py

# 产物在 /build/server/dist/数据台账系统
RUN mkdir -p /build/dist && \
    cp /build/server/dist/数据台账系统 /build/dist/

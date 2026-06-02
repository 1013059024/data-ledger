# 麒麟版数据台账系统 — 单文件可执行文件构建
#
# 构建方式：
#   docker buildx build --platform linux/arm64 --output type=local,dest=./output -f Dockerfile .

FROM quay.io/pypa/manylinux2014_aarch64

WORKDIR /build

# 从源码编译 Python 3.9（manylinux 自带的 Python 没有 --enable-shared）
COPY server/ ./server/

RUN yum install -y wget make gcc openssl-devel bzip2-devel libffi-devel zlib-devel \
    sqlite-devel readline-devel tk-devel ncurses-devel gdbm-devel xz-devel \
    && wget -q https://www.python.org/ftp/python/3.9.21/Python-3.9.21.tgz \
    && tar xzf Python-3.9.21.tgz \
    && cd Python-3.9.21 \
    && ./configure --enable-shared --enable-optimizations --prefix=/usr/local \
    && make -j$(nproc) \
    && make altinstall \
    && cd /build \
    && rm -rf Python-3.9.21* \
    && /usr/local/bin/python3.9 -m pip install --no-cache-dir \
        pyinstaller \
        flask>=3.0 \
        openpyxl>=3.1 \
        xlrd>=2.0

# PyInstaller 打包为单文件
ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
RUN cd server && \
    /usr/local/bin/python3.9 -m PyInstaller --onefile \
    --name 数据台账系统 \
    --add-data "templates:templates" \
    --add-data "static:static" \
    pyi_entry.py

# 产物
RUN mkdir -p /build/dist && \
    cp /build/server/dist/数据台账系统 /build/dist/

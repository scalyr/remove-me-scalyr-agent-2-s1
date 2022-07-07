#!/usr/bin/env bash

set -e

OPENSSH_VERSION="1_1_1k"
PYTHON_VERSION="3.8.10"

build_dir=$(mktemp -d)
cd "${build_dir}"

curl -L "https://github.com/openssl/openssl/archive/refs/tags/OpenSSL_${OPENSSH_VERSION}.tar.gz" > openssl.tar.gz
tar -xvf "openssl.tar.gz"
pushd "openssl-OpenSSL_${OPENSSH_VERSION}"
./Configure linux-x86_64 shared --prefix="/usr/local"
make "-j$(nproc)"
make DESTDIR="$STEP_OUTPUT_PATH" install

cp -a "$STEP_OUTPUT_PATH/." /
echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf
echo "/usr/local/lib" >> /etc/ld.so.conf.d/local.conf
ldconfig

popd

curl -L "https://github.com/python/cpython/archive/refs/tags/v${PYTHON_VERSION}.tar.gz" > python.tar.gz
tar -xvf "python.tar.gz"
pushd "cpython-${PYTHON_VERSION}"
./configure --with-openssl=/usr/local --enable-shared --prefix=/usr/local
make "-j$(nproc)"
make DESTDIR="$STEP_OUTPUT_PATH" install

cp -a "$STEP_OUTPUT_PATH/." /

popd

ldconfig
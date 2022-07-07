#!/bin/bash

set -e

##BUILD_OPENSSL_STEP_OUTPUT=$1
#BUILD_PYTHON_STEP_OUTPUT=$1
#
##cp -a "$BUILD_OPENSSL_STEP_OUTPUT/openssl/." /
#cp -a "$BUILD_PYTHON_STEP_OUTPUT/." /
#echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf
#echo "/usr/local/lib" >> /etc/ld.so.conf.d/local.conf
#
##cp -a "$BUILD_PYTHON_STEP_OUTPUT/python/." /
#
#ldconfig

# Install Rust.
UPDATE_PATH_CMD='export PATH="$HOME/.cargo/bin:${PATH}"'
ADD_CURL_ALIAS_CMD='alias curl="curl --tlsv1.2"'

eval "$UPDATE_PATH_CMD"
eval "$ADD_CURL_ALIAS_CMD"

echo "$UPDATE_PATH_CMD" >> ~/.bashrc
echo "$ADD_CURL_ALIAS_CMD" >> ~/.bashrc

#curl -sSf https://sh.rustup.rs | sh -s -- -y
#rustup toolchain install nightly
#rustup default nightly

# Install python dependencies of the agent.
REQUIREMENTS_DIR="$SOURCE_ROOT/agent_build/requirement-files"

pip_cache_path=$(pip3 cache dir)

restore_from_cache pip_cache "$pip_cache_path"

python3 -m pip install --upgrade pip
CC="gcc -std=c99 -D PATH_MAX=4096 -D_POSIX_C_SOURCE=200808L" python3 \
  -m pip install \
  -r "$REQUIREMENTS_DIR/frozen-binaries-requirements.txt"

python3 -m pip install  -r "$REQUIREMENTS_DIR/main-requirements.txt"

save_to_cache pip_cache "$pip_cache_path"

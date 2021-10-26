SOURCE_ROOT=$(dirname "$(dirname "$(dirname "$0")")")

CACHE_DIR="${1}"

use_cache=false
save_cache=false

if [ -n "$CACHE_DIR" ]; then
  if [ ! -d "$CACHE_DIR" ]; then
    mkdir -p "${CACHE_DIR}"
    save_cache=true
  fi
  use_cache=true
fi

if $use_cache ; then
  cp -a "$CACHE_DIR/pip" ~/.cache/pip
fi

python3 -m pip install -r "${SOURCE_ROOT}/dev-requirements.txt"

if $save_cache ; then
  cp -a ~/.cache/pip "$CACHE_DIR/pip"
fi
#!/bin/sh
# CodeKing one-line installer — no registry account required.
#
#   curl -fsSL https://raw.githubusercontent.com/ByteTitan-star/CodingKing/main/install.sh | sh
#
# Env knobs:
#   CODEKING_SOURCE   install from a local path or git URL (default: this repo)
#   CODEKING_PYTHON   pin the interpreter used to create the venv
set -eu

REPO="${CODEKING_SOURCE:-git+https://github.com/ByteTitan-star/CodingKing.git}"
VENV_DIR="$HOME/.codeking/venv"
BIN_DIR="$HOME/.local/bin"

msg() { printf 'codeking: %s\n' "$1"; }

# ── locate a Python >= 3.12 (or delegate to uv) ───────────────────────
find_python() {
  if [ -n "${CODEKING_PYTHON:-}" ]; then
    echo "$CODEKING_PYTHON"
    return 0
  fi
  for candidate in python3.12 python3.13 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      ver=$("$candidate" -c 'import sys; print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)
      if [ "$ver" -ge 312 ]; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  echo ""
}

case "$REPO" in
  git+*) command -v git >/dev/null 2>&1 || { msg "需要 git（安装来源为 git 仓库）"; exit 1; } ;;
esac

if [ ! -x "$VENV_DIR/bin/python" ]; then
  PY=$(find_python)
  if [ -n "$PY" ]; then
    msg "创建运行环境 $VENV_DIR"
    "$PY" -m venv "$VENV_DIR"
  elif command -v uv >/dev/null 2>&1; then
    msg "使用 uv 创建运行环境 $VENV_DIR"
    uv venv "$VENV_DIR" --python 3.12
  else
    msg "需要 Python 3.12+（或 uv）。安装后重跑本脚本，或用 CODEKING_PYTHON 指定解释器。"
    exit 1
  fi
fi

msg "安装 coderking（来源：${REPO}）"
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade "$REPO"

# ── expose the commands ───────────────────────────────────────────────
mkdir -p "$BIN_DIR"
for name in codeking coderking; do
  ln -sf "$VENV_DIR/bin/$name" "$BIN_DIR/$name"
done

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    msg "把下面这行加入 ~/.zshrc（或 ~/.bashrc）后重开终端："
    printf '  export PATH="%s:$PATH"\n' "$BIN_DIR"
    ;;
esac

msg "安装完成 — 运行 \`codeking\` 开始。"

#!/bin/bash
# SessionStart 钩子：让每个全新的云端会话（Claude Code on the web）开箱即用。
# 装两样东西——① 后端 Python 依赖；② LibreOffice calc/writer 应用模块。
# 幂等、非交互；只在云端跑（本地 Mac 有自己的环境，也没 apt）。
set -euo pipefail

# 仅限 Claude Code on the web 的远程容器；本地会话直接退出。
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

echo "[session-start] 安装后端 Python 依赖…"
# ⚠ 系统自带的 Debian 版 PyJWT 卸不掉（RECORD 缺失），必须带 --ignore-installed PyJWT。
pip install --ignore-installed PyJWT \
  -r shared/py/requirements.txt \
  -r apps/api/requirements.txt

echo "[session-start] 安装 LibreOffice calc/writer…"
# 基础镜像只带 libreoffice-core + libreoffice-common，能起却加载不了任何文档
# （报 "source file could not be loaded"），报价渲染验证 render_check 的 xlsx→pdf 转不了。
# calc/writer 缺一不可。best-effort：装不上不阻塞会话——render 步骤无可用 soffice 时会自动降级为 warning。
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  # apt 索引可能过期（指向的具体版本 .deb 会 404），先 update 再装。
  apt-get update -qq || true
  if ! apt-get install -y libreoffice-calc libreoffice-writer; then
    echo "[session-start] ⚠ libreoffice-calc/writer 安装失败，报价渲染验证将降级为 warning（不阻塞）"
  fi
fi

echo "[session-start] 完成。"

#!/bin/bash
# 快速開啟碰撞播放器（雙擊即可）。
#
# 站根必須同時含 player/ 與 scenes/，scene-loader.js 的 ../scenes/ 才解得到——
# 所以這裡要回到 repo 根，不是腳本所在的 tools/。
# （2026-08-20 目錄重整：threejs/ → player/，本腳本從根目錄移進 tools/。）
set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
PORT=8950
SCENE="${1:-test1}"          # 可傳場景代號：tools/open-player.command tainan_yongkang

URL="http://127.0.0.1:${PORT}/player/index.html?scene=${SCENE}"

# server 沒開就開（背景），已開就沿用
if ! curl -s -o /dev/null "http://127.0.0.1:${PORT}/" 2>/dev/null; then
  echo "啟動本地 server (port ${PORT})…"
  (python3 -m http.server "${PORT}" >/dev/null 2>&1 &)
  sleep 1
fi

echo "開啟：${URL}"
open "${URL}"

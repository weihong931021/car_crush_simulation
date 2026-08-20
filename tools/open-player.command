#!/bin/bash
# 快速開啟碰撞播放器（雙擊即可）。
#   - threejs-v1/ = 凍結的「最高品質基準版」（2026-08-03 存檔）
#   - threejs/    = 現行開發版（重新設計中）
# 站根同時含 threejs*/ 與 scenes/，相對路徑 ../scenes/ 才解得到。
set -e
cd "$(dirname "$0")"
PORT=8950
SCENE="${1:-test1}"          # 可傳場景代號：./open-player.command tainan_yongkang
VER="${2:-v1}"               # v1 = 基準版；live = 開發版

if [ "$VER" = "live" ]; then DIR="threejs"; else DIR="threejs-v1"; fi
URL="http://127.0.0.1:${PORT}/${DIR}/index.html?scene=${SCENE}"

# server 沒開就開（背景），已開就沿用
if ! curl -s -o /dev/null "http://127.0.0.1:${PORT}/" 2>/dev/null; then
  echo "啟動本地 server (port ${PORT})…"
  (python3 -m http.server "${PORT}" >/dev/null 2>&1 &)
  sleep 1
fi

echo "開啟：${URL}"
open "${URL}"

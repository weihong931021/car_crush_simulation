#!/usr/bin/env python3
"""workbench 共用工具。"""
import re

# 地點代號只允許英數與 - _：它會變成 output/<code> 目錄名（capture/enhance 都用）。
# 放行 `/` 或 `..` 會讓輸出寫到 output 之外，放行引號/換行也可能污染下游取用。
# 與 player/scene-loader.js 的場景代號規則（/^[\w-]+$/）維持同一條界線。
CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_code(code):
    """檢查地點代號；合法則原樣回傳，不合法 raise ValueError。

    可直接當 argparse 的 type= 使用（argparse 會把 ValueError 轉成乾淨的 CLI 錯誤），
    同時也在各 library 函式開頭再擋一次，讓程式化呼叫者一樣受保護。
    """
    if not isinstance(code, str) or not CODE_RE.match(code):
        raise ValueError(
            f"地點代號不合法：{code!r}（只允許英數、-、_，不可含路徑分隔或引號）"
        )
    return code

#!/usr/bin/env python3
"""產生對外簡報用的三張 16:9 SVG（各自獨立）＋合一預覽頁 index.html。改字改座標後重跑：python3 docs/diagrams/make_diagrams.py"""
from pathlib import Path

W, H = 1600, 900
FONT = '"PingFang TC","Noto Sans TC","Microsoft JhengHei","Helvetica Neue",Arial,sans-serif'
INK, MUTED, LINE = "#14212B", "#63707C", "#A3AEBA"
HUMAN, HUMAN_BG = "#C46A12", "#FBEBD3"
AUTO, AUTO_BG = "#1E63D6", "#DDE8FA"
OUT, OUT_BG = "#178A4C", "#D8F1E2"
BG = "#FFFFFF"

DEFS = f"""<defs>
  <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/>
  </marker>
  <marker id="ar-dark" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="{INK}"/>
  </marker>
</defs>"""


def person(cx, cy, color, s=1.0):
    """人形圖示（頭＋肩）。cx,cy 是頭中心。"""
    r = 9 * s
    R = 17 * s
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>'
            f'<path d="M{cx-R},{cy+30*s} a{R},{R} 0 0 1 {2*R},0 z" fill="{color}"/>')


def bolt(cx, cy, color, s=1.0):
    """閃電（自動）。"""
    pts = [(-6, -16), (4, -16), (-1, -3), (7, -3), (-6, 16), (-2, 2), (-9, 2)]
    d = " ".join(f"{cx+x*s},{cy+y*s}" for x, y in pts)
    return f'<polygon points="{d}" fill="{color}"/>'


def play(cx, cy, color, s=1.0):
    return f'<polygon points="{cx-9*s},{cy-12*s} {cx+13*s},{cy} {cx-9*s},{cy+12*s}" fill="{color}"/>'


def box(x, y, w, h, fill, stroke, title, desc, icon=None, title_size=30, desc_size=19, dash=""):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    s = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="2.5"{dash_attr}/>')
    cx = x + w / 2
    ty = y + h / 2 - (10 if desc else -10)
    if icon:
        s += icon
    s += f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="{title_size}" font-weight="700" fill="{INK}">{title}</text>'
    if desc:
        s += f'<text x="{cx}" y="{ty+32}" text-anchor="middle" font-size="{desc_size}" fill="{MUTED}">{desc}</text>'
    return s


def arrow(x1, y1, x2, y2, label=None, color=LINE, width=3, marker="ar", label_dy=-10, poly=None):
    if poly:
        pts = " ".join(f"{px},{py}" for px, py in poly)
        s = f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" marker-end="url(#{marker})"/>'
        lx, ly = poly[len(poly) // 2]
    else:
        s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" marker-end="url(#{marker})"/>'
        lx, ly = (x1 + x2) / 2, (y1 + y2) / 2
    if label:
        s += f'<text x="{lx}" y="{ly+label_dy}" text-anchor="middle" font-size="18" fill="{MUTED}">{label}</text>'
    return s


def browser(x, y, w, h, title_bar=True):
    """瀏覽器視窗外框。"""
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="#F7F9FB" stroke="{OUT}" stroke-width="3.5"/>'
    s += f'<rect x="{x}" y="{y}" width="{w}" height="34" rx="16" fill="{OUT_BG}"/>'
    s += f'<rect x="{x}" y="{y+18}" width="{w}" height="16" fill="{OUT_BG}"/>'
    for i, c in enumerate(["#E5484D", "#F5A524", "#30A46C"]):
        s += f'<circle cx="{x+22+i*20}" cy="{y+17}" r="6" fill="{c}"/>'
    return s


def scene_mockup(x, y, w, h):
    """3D 重演縮圖：十字路口、兩台車、軌跡、碰撞點、速度滑桿。"""
    s = ""
    # 路面
    rw = w * 0.30
    s += f'<rect x="{x+w/2-rw/2}" y="{y}" width="{rw}" height="{h}" fill="#3B4048"/>'
    s += f'<rect x="{x}" y="{y+h/2-rw/2}" width="{w}" height="{rw}" fill="#3B4048"/>'
    # 斑馬線
    for i in range(5):
        s += f'<rect x="{x+w/2-rw/2+8+i*14}" y="{y+h/2-rw/2-26}" width="8" height="18" fill="#E8EAED"/>'
        s += f'<rect x="{x+w/2-rw/2+8+i*14}" y="{y+h/2+rw/2+8}" width="8" height="18" fill="#E8EAED"/>'
    # 軌跡（實線車、虛線機車）
    s += f'<line x1="{x+w/2-8}" y1="{y+h}" x2="{x+w/2-8}" y2="{y+h/2+10}" stroke="#F2C14E" stroke-width="5"/>'
    s += f'<line x1="{x}" y1="{y+h/2+12}" x2="{x+w/2-30}" y2="{y+h/2+12}" stroke="#F58A3C" stroke-width="5" stroke-dasharray="10 8"/>'
    # 車（白車）與機車（綠）
    s += f'<rect x="{x+w/2-22}" y="{y+h/2-6}" width="28" height="52" rx="8" fill="#F1F3F5" stroke="#8B93A1" stroke-width="2"/>'
    s += f'<rect x="{x+w/2-52}" y="{y+h/2+4}" width="26" height="14" rx="6" fill="#2E8B57"/>'
    # 碰撞點
    cx, cy = x + w / 2 - 28, y + h / 2 + 8
    s += f'<circle cx="{cx}" cy="{cy}" r="16" fill="none" stroke="#E5484D" stroke-width="4"/>'
    return s


def slider(x, y, w, label_l, label_r, val=0.5):
    s = f'<line x1="{x}" y1="{y}" x2="{x+w}" y2="{y}" stroke="{LINE}" stroke-width="5" stroke-linecap="round"/>'
    s += f'<circle cx="{x+w*val}" cy="{y}" r="9" fill="{AUTO}"/>'
    s += f'<text x="{x-8}" y="{y+6}" text-anchor="end" font-size="16" fill="{MUTED}">{label_l}</text>'
    s += f'<text x="{x+w+8}" y="{y+6}" font-size="16" fill="{MUTED}">{label_r}</text>'
    return s


def legend(x, y):
    items = [(HUMAN_BG, HUMAN, "需要人動手", "person"), (AUTO_BG, AUTO, "系統自動", "bolt"), (OUT_BG, OUT, "產出", "play")]
    s = ""
    for i, (bg, fg, t, ic) in enumerate(items):
        xx = x + i * 190
        s += f'<rect x="{xx}" y="{y-14}" width="34" height="26" rx="8" fill="{bg}" stroke="{fg}" stroke-width="2"/>'
        if ic == "person":
            s += person(xx + 17, y - 6, fg, 0.55)
        elif ic == "bolt":
            s += bolt(xx + 17, y - 1, fg, 0.65)
        else:
            s += play(xx + 17, y - 1, fg, 0.7)
        s += f'<text x="{xx+44}" y="{y+5}" font-size="18" fill="{MUTED}">{t}</text>'
    return s


def slide(title, subtitle, body, aria):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{aria}" font-family='{FONT}'>
{DEFS}
<rect width="{W}" height="{H}" fill="{BG}"/>
<text x="80" y="92" font-size="44" font-weight="800" fill="{INK}">{title}</text>
<text x="80" y="134" font-size="22" fill="{MUTED}">{subtitle}</text>
{body}
</svg>"""


# ───────────────────────── 圖 A：系統架構 ─────────────────────────
def figure_a():
    b = ""
    # 版面：左側輸入 chip → 上軌（地面）／下軌（動態）→ 場景合成（Y 匯流）→ 3D 重演（放大）
    top_y, bot_y = 220, 470
    bw, bh = 220, 110
    x_in, x1, x2, x3, x_merge = 80, 300, 590, 880, 1180
    # 軌道標題
    b += f'<text x="{x1}" y="{top_y-24}" font-size="18" fill="{MUTED}" letter-spacing="2">地面資料</text>'
    b += f'<text x="{x1}" y="{bot_y-24}" font-size="18" fill="{MUTED}" letter-spacing="2">動態資料</text>'
    # 輸入 chips（人工提供）
    for yy, t in ((top_y, "經緯度"), (bot_y, "監視影片")):
        b += f'<rect x="{x_in}" y="{yy+20}" width="180" height="70" rx="14" fill="{HUMAN_BG}" stroke="{HUMAN}" stroke-width="2.5"/>'
        b += person(x_in + 26, yy + 44, HUMAN, 0.6)
        b += f'<text x="{x_in+52}" y="{yy+64}" font-size="24" font-weight="700" fill="{INK}">{t}</text>'
        b += arrow(x_in + 180, yy + 55, x1 - 4, yy + 55)
    # 上軌
    b += box(x1, top_y, bw, bh, AUTO_BG, AUTO, "現場底圖", "地點 → 衛星圖底圖", icon=bolt(x1 + 26, top_y + 26, AUTO, 0.7))
    # 下軌
    b += box(x1, bot_y, bw, bh, AUTO_BG, AUTO, "影像素材", "事故當下的車輛畫面", icon=bolt(x1 + 26, bot_y + 26, AUTO, 0.7))
    b += box(x2, bot_y, bw, bh, HUMAN_BG, HUMAN, "空間對位", "影像位置 ↔ 現場位置", icon=person(x2 + 26, bot_y + 24, HUMAN, 0.7))
    b += box(x3, bot_y, bw, bh, AUTO_BG, AUTO, "車輛軌跡", "還原每台車的移動", icon=bolt(x3 + 26, bot_y + 26, AUTO, 0.7))
    # 軌道內箭頭
    b += arrow(x1 + bw, bot_y + bh / 2, x2 - 4, bot_y + bh / 2, "取畫面")
    b += arrow(x2 + bw, bot_y + bh / 2, x3 - 4, bot_y + bh / 2, "定位")
    # 現場底圖 → 空間對位（細箭頭：對位置）
    b += arrow(0, 0, 0, 0, "對位置", width=2, poly=[(x1 + bw / 2, top_y + bh), (x1 + bw / 2, top_y + bh + 60), (x2 + bw / 2, top_y + bh + 60), (x2 + bw / 2, bot_y - 4)], label_dy=-10)
    # 場景合成（Y 匯流）
    my = (top_y + bot_y) / 2
    b += box(x_merge, my, bw, bh, AUTO_BG, AUTO, "場景合成", "底圖 + 軌跡 合而為一", icon=bolt(x_merge + 26, my + 26, AUTO, 0.7))
    b += arrow(0, 0, 0, 0, "鋪現場", poly=[(x1 + bw, top_y + bh / 2), (x_merge - 60, top_y + bh / 2), (x_merge - 4, my + 30)], label_dy=-12)
    b += arrow(0, 0, 0, 0, "放車流", poly=[(x3 + bw, bot_y + bh / 2), (x_merge - 60, bot_y + bh / 2), (x_merge - 4, my + bh - 30)], label_dy=26)
    # 3D 重演（焦點，右下放大瀏覽器視窗）
    ox, oy, ow, oh = 1140, 620, 380, 220
    # 場景合成 → 3D 重演
    b += arrow(x_merge + bw / 2, my + bh, x_merge + bw / 2, oy - 6, "生成", color=INK, width=3.5, marker="ar-dark", label_dy=-8)
    b += browser(ox, oy, ow, oh)
    b += scene_mockup(ox + 20, oy + 50, 170, 150)
    b += f'<text x="{ox+210}" y="{oy+88}" font-size="30" font-weight="800" fill="{OUT}">3D 重演</text>'
    b += f'<text x="{ox+210}" y="{oy+120}" font-size="17" fill="{MUTED}">瀏覽器直接看</text>'
    b += f'<text x="{ox+210}" y="{oy+144}" font-size="17" fill="{MUTED}">調車速，看會不會撞</text>'
    b += slider(ox + 226, oy + 184, 110, "慢", "快", 0.5)
    b += legend(80, 862)
    return slide("兩種資料，合成一個 3D 現場",
                 "地點給底圖、影片給軌跡；經空間對位後在同一個 3D 場景匯流，產出可互動的事故重演",
                 b, "系統架構：地點與監視影片兩條資料，經空間對位與車輛軌跡還原，在場景合成匯流，產出瀏覽器 3D 重演")


# ───────────────────────── 圖 B：使用流程 ─────────────────────────
def figure_b():
    b = ""
    # 每行「誰：做什麼」≤9 字（200px 寬的框、17px 字），超過就拆行
    steps = [
        ("提供素材", "human", [("你", "給影片、填地點"), ("系統", "抓現場底圖")]),
        ("對準現場", "human", [("你", "點兩畫面同一處"), ("系統", "建立位置對應")]),
        ("還原軌跡", "auto", [("系統", "辨識車輛"), ("", "還原每台車移動")]),
        ("指定事故", "human", [("你", "挑兩車、標碰撞"), ("系統", "鎖定主角與時間")]),
        ("建立場景", "auto", [("系統", "合成道路、車輛"), ("", "與碰撞")]),
    ]
    sx, sy, sw, sh, gap = 80, 300, 200, 250, 24
    for i, (title, kind, lines) in enumerate(steps):
        x = sx + i * (sw + gap)
        fill, stroke = (HUMAN_BG, HUMAN) if kind == "human" else (AUTO_BG, AUTO)
        b += f'<rect x="{x}" y="{sy}" width="{sw}" height="{sh}" rx="16" fill="{fill}" stroke="{stroke}" stroke-width="2.5"/>'
        # 步驟號
        b += f'<circle cx="{x+30}" cy="{sy+32}" r="18" fill="{stroke}"/>'
        b += f'<text x="{x+30}" y="{sy+39}" text-anchor="middle" font-size="20" font-weight="800" fill="#fff">{i+1}</text>'
        # 圖示
        if kind == "human":
            b += person(x + sw - 34, sy + 26, stroke, 0.8)
        else:
            b += bolt(x + sw - 34, sy + 32, stroke, 0.9)
        b += f'<text x="{x+sw/2}" y="{sy+96}" text-anchor="middle" font-size="30" font-weight="800" fill="{INK}">{title}</text>'
        # 你做什麼 / 系統做什麼（label 用 tspan 上色；續行以全形空白縮排）
        yy = sy + 140
        for who, txt in lines:
            if who:
                col = HUMAN if who == "你" else AUTO
                lab = f'<tspan fill="{col}" font-weight="700">{who}</tspan><tspan fill="{MUTED}">：</tspan>'
            else:
                lab, txt = "", "　　" + txt
            b += f'<text x="{x+18}" y="{yy}" font-size="17" fill="{INK}">{lab}{txt}</text>'
            yy += 30
        # 箭頭
        if i < len(steps) - 1:
            b += arrow(x + sw + 3, sy + sh / 2, x + sw + gap - 3, sy + sh / 2, width=3)
    # 第 6 步：互動重演（大瀏覽器視窗）
    ox = sx + 5 * (sw + gap) + 8
    ow = W - 80 - ox
    oy, oh = sy - 40, sh + 80
    b += arrow(ox - gap - 6, sy + sh / 2, ox - 3, sy + sh / 2, width=3.5, color=INK, marker="ar-dark")
    b += browser(ox, oy, ow, oh)
    b += f'<circle cx="{ox+ow-30}" cy="{oy+60}" r="18" fill="{OUT}"/>'
    b += play(ox + ow - 30, oy + 60, "#fff", 0.8)
    b += f'<text x="{ox+22}" y="{oy+72}" font-size="30" font-weight="800" fill="{OUT}">6  互動重演</text>'
    b += scene_mockup(ox + 22, oy + 92, ow - 44, 150)
    b += slider(ox + 60, oy + 268, ow - 120, "慢", "快", 0.5)
    b += f'<text x="{ox+ow/2}" y="{oy+300}" text-anchor="middle" font-size="17" fill="{INK}">調車速・切鏡頭・看會不會撞</text>'
    b += f'<text x="{ox+ow/2}" y="{oy+322}" text-anchor="middle" font-size="16" fill="{OUT}" font-weight="700">系統即時算出安全車速</text>'
    # 底部三個人形總結
    b += f'<text x="80" y="{sy+sh+90}" font-size="22" fill="{INK}" font-weight="700">你只做三件事：</text>'
    for i, t in enumerate(["給地點與影片", "點對應位置", "挑車、標碰撞"]):
        xx = 250 + i * 250
        b += person(xx, sy + sh + 78, HUMAN, 0.75)
        b += f'<text x="{xx+22}" y="{sy+sh+90}" font-size="22" fill="{INK}">{t}</text>'
    b += f'<text x="80" y="{sy+sh+130}" font-size="20" fill="{MUTED}">其餘辨識、軌跡重建、場景生成、碰撞計算全部自動。</text>'
    b += legend(80, 862)
    return slide("三次人工，其餘自動",
                 "從一支監視器影片到可操作的 3D 事故重演，使用者只需在三個地方動手",
                 b, "使用流程六步：提供素材（人工）、對準現場（人工）、還原軌跡（自動）、指定事故（人工）、建立場景（自動）、互動重演（產出）")


# ───────────────────────── 圖 C：技術架構（RAG 教學圖語法）─────────────────────────
# 元件用圖示＋名稱、主要流程編號、核心管線框成一塊淺藍區、外部服務獨立一盒、資料源在底部；
# 藍色編號＝重建主流程、橘色編號＝底圖與校正準備；人形＝需要人動手。
FLOW = AUTO          # 主流程（藍）
PREP = HUMAN         # 準備流程（琥珀）
REGION = "#E9EFF7"   # 核心區底色（冷灰藍，像圖紙）


def icon_users(cx, cy, s=1.0):
    """兩個人（User）。"""
    out = ""
    for dx in (-13 * s, 13 * s):
        out += person(cx + dx, cy - 6 * s, INK, 1.25 * s)
    return out


def icon_browser(x, y, w, h):
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#fff" stroke="{INK}" stroke-width="2.5"/>'
    s += f'<rect x="{x}" y="{y}" width="{w}" height="16" rx="8" fill="{INK}"/><rect x="{x}" y="{y+8}" width="{w}" height="8" fill="{INK}"/>'
    for i, c in enumerate(["#E5484D", "#F5A524", "#30A46C"]):
        s += f'<circle cx="{x+12+i*11}" cy="{y+8}" r="3.2" fill="{c}"/>'
    return s


def icon_camera(cx, cy, s=1.0):
    return (f'<rect x="{cx-16*s}" y="{cy-9*s}" width="26*s" height="18*s" rx="4" fill="{INK}"/>'
            .replace("26*s", str(26 * s)).replace("18*s", str(18 * s)) +
            f'<polygon points="{cx+10*s},{cy-4*s} {cx+20*s},{cy-9*s} {cx+20*s},{cy+9*s} {cx+10*s},{cy+4*s}" fill="{INK}"/>')


def icon_pin(cx, cy, s=1.0):
    return (f'<path d="M{cx},{cy+16*s} C{cx-14*s},{cy} {cx-14*s},{cy-6*s} {cx-14*s},{cy-8*s} '
            f'a14,14 0 0 1 {28*s},0 C{cx+14*s},{cy-6*s} {cx+14*s},{cy} {cx},{cy+16*s} z" fill="{INK}"/>'
            f'<circle cx="{cx}" cy="{cy-8*s}" r="{5*s}" fill="#fff"/>')


def icon_db(cx, cy, s=1.0):
    r, h = 22 * s, 30 * s
    out = f'<ellipse cx="{cx}" cy="{cy-h/2}" rx="{r}" ry="{8*s}" fill="{INK}"/>'
    out += f'<rect x="{cx-r}" y="{cy-h/2}" width="{2*r}" height="{h}" fill="{INK}"/>'
    out += f'<ellipse cx="{cx}" cy="{cy+h/2}" rx="{r}" ry="{8*s}" fill="{INK}"/>'
    for k in (0.15, 0.55):
        out += f'<ellipse cx="{cx}" cy="{cy-h/2+h*k+8*s}" rx="{r}" ry="{8*s}" fill="none" stroke="#fff" stroke-width="{2*s}"/>'
    return out


def icon_cube(cx, cy, s=1.0):
    r = 18 * s
    top = f'{cx},{cy-r} {cx+r*0.87},{cy-r/2} {cx},{cy} {cx-r*0.87},{cy-r/2}'
    left = f'{cx-r*0.87},{cy-r/2} {cx},{cy} {cx},{cy+r} {cx-r*0.87},{cy+r/2}'
    right = f'{cx},{cy} {cx+r*0.87},{cy-r/2} {cx+r*0.87},{cy+r/2} {cx},{cy+r}'
    return (f'<polygon points="{top}" fill="#6EA1F5"/><polygon points="{left}" fill="{FLOW}"/>'
            f'<polygon points="{right}" fill="#1D4FA0"/>')


def bubble(x, y, w, lines, tail="left"):
    """虛線對話框：資料範例（像 RAG 圖裡的 Query / Relevant Docs）。"""
    h = 18 + 20 * len(lines)
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#fff" stroke="{INK}" stroke-width="1.6" stroke-dasharray="5 4"/>'
    if tail == "left":
        s += f'<polygon points="{x},{y+h/2-8} {x-12},{y+h/2} {x},{y+h/2+8}" fill="#fff" stroke="{INK}" stroke-width="1.6" stroke-dasharray="5 4"/>'
    for i, ln in enumerate(lines):
        w8 = 700 if i == 0 else 400
        s += f'<text x="{x+12}" y="{y+22+i*20}" font-size="14" font-weight="{w8}" fill="{INK}">{ln}</text>'
    return s


HALO = 'paint-order="stroke" stroke="#fff" stroke-width="7" stroke-linejoin="round"'


def badge(x, y, num, color):
    """編號徽章（圓形、白字）——像路線圖上的站號。"""
    return (f'<circle cx="{x}" cy="{y}" r="13" fill="{color}"/>'
            f'<text x="{x}" y="{y+5}" text-anchor="middle" font-size="15" font-weight="800" fill="#fff">{num}</text>')


def flow_label(x, y, label, color, num=None, anchor="start"):
    """箭頭說明：徽章＋文字，文字帶白色光暈，壓在線上也讀得清楚。"""
    approx = int(len(label) * 17 * 0.98) + (34 if num is not None else 0)
    if anchor == "end":
        x = x - approx
    s = ""
    tx = x
    if num is not None:
        s += badge(x + 13, y - 6, num, color)
        tx = x + 34
    s += f'<text x="{tx}" y="{y}" font-size="17" font-weight="700" fill="{color}" {HALO}>{label}</text>'
    return s


def num_arrow(pts, label, color, num, label_pos=None, dashed=False):
    """帶編號的箭頭：pts 折線；label_pos=(x, y, anchor) 指定說明放哪（一定放在空白處）。"""
    marker = "ar-flow" if color == FLOW else "ar-prep"
    pstr = " ".join(f"{px},{py}" for px, py in pts)
    dash = ' stroke-dasharray="8 6"' if dashed else ""
    s = f'<polyline points="{pstr}" fill="none" stroke="{color}" stroke-width="3"{dash} stroke-linejoin="round" marker-end="url(#{marker})"/>'
    if label_pos is None:
        (x1, y1), (x2, y2) = pts[0], pts[1]
        label_pos = ((x1 + x2) / 2 - 40, (y1 + y2) / 2 - 12, "start")
    lx, ly, anchor = label_pos
    s += flow_label(lx, ly, label, color, num, anchor)
    return s


def comp(x, y, w, h, title, sub=None, icon=None, fill="#fff", stroke=INK):
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2.5"/>'
    if icon:
        s += icon
    ty = y + h / 2 + (2 if not sub else -6)
    s += f'<text x="{x+w/2}" y="{ty}" text-anchor="middle" font-size="22" font-weight="800" fill="{INK}">{title}</text>'
    if sub:
        s += f'<text x="{x+w/2}" y="{ty+24}" text-anchor="middle" font-size="15" fill="{MUTED}">{sub}</text>'
    return s


def figure_c():
    b = ""
    b += f"""<defs>
  <marker id="ar-flow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{FLOW}"/></marker>
  <marker id="ar-prep" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{PREP}"/></marker>
</defs>"""
    # ── 幾何（8px 網格；每條線走水平／垂直，說明一律放空白處）
    U = (110, 520)                                  # User 中心
    F = dict(x=300, y=470, w=230, h=100)            # 網頁前端
    E = dict(x=300, y=200, w=320, h=118)            # 外部服務
    R = dict(x=610, y=350, w=830, h=380)            # 重建管線區
    K = dict(x=640, y=392, w=220, h=84)             # 空間校正
    D = dict(x=640, y=606, w=220, h=84)             # 車輛偵測
    L = dict(x=930, y=606, w=220, h=84)             # 地面定位
    T = dict(x=1200, y=606, w=220, h=84)            # 軌跡整理
    J = dict(x=1190, y=190, w=330, h=120)           # Three.js
    S = dict(cx=1000, cy=810)                       # 場景包（圓柱中心）
    I = dict(x=60, y=730, w=230, h=110)             # 輸入資料
    cx = lambda o: o["x"] + o["w"] / 2
    cy = lambda o: o["y"] + o["h"] / 2
    right = lambda o: o["x"] + o["w"]
    bottom = lambda o: o["y"] + o["h"]

    # ── 重建管線區
    b += f'<rect x="{R["x"]}" y="{R["y"]}" width="{R["w"]}" height="{R["h"]}" rx="24" fill="{REGION}"/>'
    b += f'<text x="{right(R)-24}" y="{R["y"]+36}" text-anchor="end" font-size="22" font-weight="800" fill="{INK}">TrafficLab 重建管線</text>'
    b += f'<text x="{right(R)-24}" y="{R["y"]+60}" text-anchor="end" font-size="15" fill="{MUTED}">Python・OpenCV・YOLO・PifPaf</text>'
    b += comp(K["x"], K["y"], K["w"], K["h"], "空間校正", "G-projection：H・K/D・視差", fill="#FFF6E8", stroke=PREP)
    b += comp(D["x"], D["y"], D["w"], D["h"], "車輛偵測", "YOLO 追蹤 + PifPaf 24 關鍵點")
    b += comp(L["x"], L["y"], L["w"], L["h"], "地面定位", "關鍵點 → 現場公尺座標")
    b += comp(T["x"], T["y"], T["w"], T["h"], "軌跡整理", "平滑・直線化・速度剖面")
    # 資料範例（虛線對話框）：K 右側、L／T 正上方
    b += bubble(right(K) + 26, K["y"] + 12, 250, ["對應點 ≥4 對", "影像 px ↔ 現場 m・px/m"], tail="left")
    b += bubble(880, 520, 220, ["每幀每車 (x, y) m", "spread・輪點數（品質）"], tail="none")
    b += bubble(T["x"], 520, 220, ["position_m・startT", "速度剖面（實錄）"], tail="none")
    # 區內流程
    b += num_arrow([(right(D), cy(D)), (L["x"] - 4, cy(L))], "定位", FLOW, 6, label_pos=(right(D) + 6, cy(D) - 14, "start"))
    b += num_arrow([(right(L), cy(L)), (T["x"] - 4, cy(T))], "整理", FLOW, 7, label_pos=(right(L) + 2, cy(L) - 14, "start"))
    b += num_arrow([(cx(K), bottom(K)), (cx(K), 500), (1120, 500), (1120, L["y"] - 4)],
                   "校正參數", PREP, None, label_pos=(cx(K) + 12, 494, "start"))

    # ── User
    b += icon_users(U[0], U[1] - 10, 1.0)
    b += f'<rect x="{U[0]-46}" y="{U[1]+40}" width="92" height="30" rx="6" fill="#fff" stroke="{INK}" stroke-width="2"/>'
    b += f'<text x="{U[0]}" y="{U[1]+61}" text-anchor="middle" font-size="18" font-weight="700" fill="{INK}">User</text>'
    # ── 網頁前端
    b += icon_browser(F["x"] + 20, F["y"] - 44, 60, 40)
    b += comp(F["x"], F["y"], F["w"], F["h"], "網頁前端", "底圖工作台・標註・播放器")
    b += f'<text x="{cx(F)}" y="{bottom(F)+24}" text-anchor="middle" font-size="15" fill="{MUTED}">瀏覽器，零安裝</text>'
    # User → 前端：三條平行線，說明各放線上方
    ux0, ux1 = U[0] + 62, F["x"] - 4
    for yy, lab, col, num in ((F["y"] + 18, "影片＋經緯度", FLOW, 1), (F["y"] + 52, "點對應點", PREP, 4), (F["y"] + 86, "挑車・標碰撞", FLOW, 8)):
        b += num_arrow([(ux0, yy), (ux1, yy)], lab, col, num, label_pos=(ux0 + 2, yy - 10, "start"))
    # 前端 → 校正（4）與 → 偵測（5）：走 x=580 的垂直廊道
    gx = 580
    b += num_arrow([(right(F), F["y"] + 30), (gx, F["y"] + 30), (gx, cy(K)), (K["x"] - 4, cy(K))], "對應點", PREP, 4, label_pos=(gx + 10, cy(K) - 54, "start"))
    b += num_arrow([(right(F), F["y"] + 70), (gx, F["y"] + 70), (gx, cy(D)), (D["x"] - 4, cy(D))], "影格", FLOW, 5, label_pos=(gx + 10, cy(D) - 54, "start"))
    # ── 外部服務
    b += f'<rect x="{E["x"]}" y="{E["y"]}" width="{E["w"]}" height="{E["h"]}" rx="18" fill="#F4F6F8" stroke="{LINE}" stroke-width="2"/>'
    b += f'<text x="{right(E)-14}" y="{E["y"]+20}" text-anchor="end" font-size="13" fill="{MUTED}">外部服務</text>'
    b += icon_pin(E["x"] + 36, E["y"] + 40, 0.9)
    b += f'<text x="{E["x"]+64}" y="{E["y"]+40}" font-size="19" font-weight="800" fill="{INK}">Google 衛星圖</text>'
    b += f'<text x="{E["x"]+64}" y="{E["y"]+60}" font-size="14" fill="{MUTED}">Static Maps API・zoom 21</text>'
    b += f'<circle cx="{E["x"]+36}" cy="{E["y"]+92}" r="12" fill="none" stroke="{INK}" stroke-width="3"/><circle cx="{E["x"]+36}" cy="{E["y"]+92}" r="4.5" fill="{INK}"/>'
    b += f'<text x="{E["x"]+64}" y="{E["y"]+92}" font-size="19" font-weight="800" fill="{INK}">Gemini 去車</text>'
    b += f'<text x="{E["x"]+64}" y="{E["y"]+112}" font-size="14" fill="{MUTED}">偵測車框 → inpaint → 銳化</text>'
    # 2：前端 → 外部服務（垂直，說明放線左側、瀏覽器圖示上方）
    ax2 = F["x"] + 170
    b += num_arrow([(ax2, F["y"] - 4), (ax2, bottom(E) + 4)], "經緯度 → 擷取衛星圖", PREP, 2, label_pos=(ax2 - 12, 396, "end"))
    # 3：外部服務 → 校正（右、下）
    b += num_arrow([(right(E), cy(E)), (cx(K), cy(E)), (cx(K), K["y"] - 4)], "去車銳化的底圖", PREP, 3, label_pos=(cx(K) + 12, 300, "start"))
    # ── Three.js（右上）
    b += f'<rect x="{J["x"]}" y="{J["y"]}" width="{J["w"]}" height="{J["h"]}" rx="18" fill="#fff" stroke="{FLOW}" stroke-width="3"/>'
    b += icon_cube(J["x"] + 44, J["y"] + 60, 1.1)
    b += f'<text x="{J["x"]+84}" y="{J["y"]+42}" font-size="22" font-weight="800" fill="{INK}">Three.js 3D 重演</text>'
    b += f'<text x="{J["x"]+84}" y="{J["y"]+66}" font-size="15" fill="{MUTED}">瀏覽器內前向物理模擬</text>'
    b += f'<text x="{J["x"]+84}" y="{J["y"]+88}" font-size="15" fill="{MUTED}">OBB 碰撞・衝量・調速倍率・安全車速</text>'
    # ── 場景包
    b += icon_db(S["cx"], S["cy"], 1.0)
    b += f'<rect x="{S["cx"]+34}" y="{S["cy"]-22}" width="236" height="44" rx="8" fill="#fff" stroke="{INK}" stroke-width="2"/>'
    b += f'<text x="{S["cx"]+48}" y="{S["cy"]-2}" font-size="18" font-weight="800" fill="{INK}">場景包 scenes/&lt;code&gt;/</text>'
    b += f'<text x="{S["cx"]+48}" y="{S["cy"]+16}" font-size="13" fill="{MUTED}">scene.json・ground.png・trajectory.json</text>'
    # 9：軌跡整理 → 場景包
    b += num_arrow([(cx(T), bottom(T)), (cx(T), 760), (1150, 760), (1150, S["cy"] - 26)], "build_scene 打包", FLOW, 9, label_pos=(cx(T) + 12, 752, "start"))
    # 10：場景包 → Three.js（右側繞上）
    b += num_arrow([(S["cx"] + 274, S["cy"]), (1560, S["cy"]), (1560, cy(J)), (right(J) + 4, cy(J))], "載入場景包", FLOW, 10, label_pos=(1548, S["cy"] - 14, "end"))
    # 11：Three.js → User（沿頂部回程）
    b += num_arrow([(cx(J), J["y"]), (cx(J), 168), (U[0], 168), (U[0], U[1] - 66)], "3D 重演回到瀏覽器", FLOW, 11, label_pos=(cx(J) - 12, 160, "end"))
    # ── 輸入資料
    b += f'<rect x="{I["x"]}" y="{I["y"]}" width="{I["w"]}" height="{I["h"]}" rx="10" fill="none" stroke="{LINE}" stroke-width="2" stroke-dasharray="6 5"/>'
    b += icon_camera(I["x"] + 40, I["y"] + 32, 1.0)
    b += f'<text x="{I["x"]+76}" y="{I["y"]+38}" font-size="17" font-weight="700" fill="{INK}">CCTV 影片</text>'
    b += icon_pin(I["x"] + 40, I["y"] + 84, 0.85)
    b += f'<text x="{I["x"]+76}" y="{I["y"]+90}" font-size="17" font-weight="700" fill="{INK}">事故地點</text>'
    b += f'<text x="{I["x"]+12}" y="{bottom(I)+18}" font-size="13" fill="{MUTED}">輸入資料</text>'
    b += num_arrow([(right(I), I["y"] + 55), (F["x"] + 30, I["y"] + 55), (F["x"] + 30, bottom(F) + 4)], "上傳", FLOW, None, label_pos=(F["x"] + 40, I["y"] - 60, "start"))
    # 圖例
    lx, ly = 600, 868
    b += f'<line x1="{lx}" y1="{ly}" x2="{lx+40}" y2="{ly}" stroke="{FLOW}" stroke-width="3" marker-end="url(#ar-flow)"/><text x="{lx+50}" y="{ly+6}" font-size="15" fill="{MUTED}">重建主流程 1 → 11</text>'
    b += f'<line x1="{lx+230}" y1="{ly}" x2="{lx+270}" y2="{ly}" stroke="{PREP}" stroke-width="3" marker-end="url(#ar-prep)"/><text x="{lx+280}" y="{ly+6}" font-size="15" fill="{MUTED}">底圖與校正準備 2 → 4</text>'
    b += f'<rect x="{lx+500}" y="{ly-11}" width="30" height="22" rx="6" fill="#fff" stroke="{INK}" stroke-width="1.6" stroke-dasharray="5 4"/><text x="{lx+540}" y="{ly+6}" font-size="15" fill="{MUTED}">資料範例</text>'
    return slide("系統架構：監視器影片 → 3D 事故重演",
                 "前端收素材與人工標註；重建管線把影像換成現場公尺座標與軌跡；Three.js 在瀏覽器內模擬重演",
                 b, "技術架構：使用者經網頁前端提供影片與地點，外部 Google 衛星圖與 Gemini 去車產出底圖，重建管線做校正、偵測、定位、軌跡整理，打包成場景包，由 Three.js 在瀏覽器內模擬重演並回到使用者")


def main():
    out_dir = Path(__file__).resolve().parent          # docs/diagrams/
    out_dir.mkdir(parents=True, exist_ok=True)
    a, bsvg, csvg = figure_a(), figure_b(), figure_c()
    (out_dir / "architecture-overview.svg").write_text(a, encoding="utf-8")
    (out_dir / "user-flow-overview.svg").write_text(bsvg, encoding="utf-8")
    (out_dir / "system-architecture-flow.svg").write_text(csvg, encoding="utf-8")

    def inline(svg):  # artifact 內嵌：拿掉固定 width/height 讓它隨容器縮放
        return svg.replace(f'width="{W}" height="{H}" ', "", 1)

    html = f"""<title>事故重建簡報圖</title>
<style>
body{{margin:0;background:#E6E9EE;color:#1B2430;font-family:{FONT};}}
main{{max-width:1500px;margin:0 auto;padding:36px 24px 60px}}
h1{{font-size:22px;font-weight:600;margin:0 0 6px}}
p.sub{{color:#5C6675;margin:0 0 28px;font-size:15px}}
section{{margin-bottom:44px}}
h2{{font-size:14px;letter-spacing:.14em;text-transform:uppercase;color:#5C6675;font-weight:600;margin:0 0 10px}}
figure{{margin:0;background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.08);overflow-x:auto;padding:0}}
figure svg{{display:block;width:100%;height:auto;min-width:800px}}
figcaption{{font-size:14px;color:#5C6675;padding:10px 14px 12px}}
code{{background:#DDE2E8;padding:1px 6px;border-radius:4px;font-size:.9em}}
.script{{background:#fff;border-radius:10px;padding:18px 22px;max-width:70ch;line-height:1.8;font-size:15px}}
</style>
<main>
<h1>事故重建簡報圖</h1>
<p class="sub">三張各自獨立的 16:9 簡報頁；SVG 原檔在 <code>docs/diagrams/</code>，可直接拖進 Keynote／PowerPoint／Google Slides。圖 A、B 給非技術觀眾；圖 C 是元件級技術架構（RAG 教學圖語法：圖示＋編號流程）。</p>
<section>
<h2>圖 A・系統架構</h2>
<figure>{inline(a)}<figcaption>地點給底圖、影片給軌跡，經空間對位後在場景合成匯流，產出瀏覽器 3D 重演。<code>docs/diagrams/architecture-overview.svg</code></figcaption></figure>
</section>
<section>
<h2>圖 B・使用流程</h2>
<figure>{inline(bsvg)}<figcaption>六步中三步要人動手（橘色）、兩步自動（藍色）、最後一步是產出（綠色）。<code>docs/diagrams/user-flow-overview.svg</code></figcaption></figure>
</section>
<section>
<h2>圖 C・技術架構（元件＋編號流程）</h2>
<figure>{inline(csvg)}<figcaption>藍色編號 1→11 是重建主流程，橘色 2–5 是底圖與校正準備；淺藍區是 Python 重建管線，右上外部服務，右下瀏覽器內的 Three.js 物理模擬，下方是場景包與輸入資料。<code>docs/diagrams/system-architecture-flow.svg</code></figcaption></figure>
</section>
<section>
<h2>30 秒口述稿</h2>
<div class="script">
<p><b>圖 A：</b>我們把事故地點轉成現場底圖，同時從監視影片還原車輛軌跡；兩種資料經過空間對位後，在同一個 3D 場景匯流，最後產生可操作的事故重演。</p>
<p><b>圖 B：</b>使用者只需提供地點與影片、點選對應位置、再挑出事故車輛與碰撞時刻；其餘辨識、軌跡重建與場景生成都由系統完成。最後可以調整車速、切換鏡頭，直接比較碰撞結果與安全車速。</p>
</div>
</section>
</main>
"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")   # 三張合一的預覽頁（artifact 同內容）
    print("ok", len(a), len(bsvg), len(csvg))


if __name__ == "__main__":
    main()

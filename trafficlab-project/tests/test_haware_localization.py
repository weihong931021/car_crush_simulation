"""haware 定位器的座標系手性回歸測試。

背景：模板座標系（x=車左、z=車後）映到衛星像素系（x 右、**y 下**）需要一次**反射**
（det = −1），但 `localize()` 的 Procrustes 曾經強制 det = +1（`no reflection`），
等於排除唯一正確的解。誤差不是隨機的，而是解析可預測的：

    heading 誤差 = 2 × angle(點集主軸, 車體 z 軸)

所以**縱向主導**的點集（全 24 點、車頂群）heading 看起來正確，**橫向主導**的點集
（擋風玻璃對、前燈對）恰好錯 180°，同側輪對則 heading 對、位置錯一個軌距。
決策紀錄見 docs/decisions/2026-07-27-haware-localizer-parity-bug.md。

本檔用「恆等投影」的假 g_engine 隔離 Procrustes 本身，不受 homography 與視差干擾。
"""
import math
import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trafficlab.motion.haware_localization import (  # noqa: E402
    HawareLocalizer, build_car_template, _FALLBACK_DIMS,
)

# 具鑑別力的關鍵點子集（索引見 build_car_template）
WINDSHIELD = [0, 1]          # 純橫向：手性錯時 heading 恰錯 180°
HEADLIGHTS = [2, 3]          # 純橫向
WHEELS_LEFT = [7, 8]         # 同側前後輪，純縱向：heading 對但位置錯一個軌距
WHEELS_RIGHT = [19, 18]
ROOF = [0, 1, 6, 10, 11, 16]
ALL24 = list(range(24))


class IdentityEngine:
    """把 CCTV 座標原封不動當成衛星座標的假投影引擎。

    這樣 localize() 收到的 p_sat 就等於我們擺進去的真值，任何偏差都只可能來自
    Procrustes 本身——把手性問題與 homography／視差誤差分離。
    """
    px_per_m = 1.0

    def cctv_to_sat(self, x_img, y_img, h=0.0):
        return (float(x_img), float(y_img))


class BlowUpEngine(IdentityEngine):
    """把座標放大 k 倍，模擬 homography 在遠場／近地平線的外推爆炸。"""

    def __init__(self, k):
        self.k = float(k)

    def cctv_to_sat(self, x_img, y_img, h=0.0):
        return (float(x_img) * self.k, float(y_img) * self.k)


def place_vehicle(template, center, heading_deg, subset):
    """把模板依 (center, heading) 擺進衛星平面，回傳 localize() 吃的 (24,3) 陣列。

    座標約定（與 localize() 的 heading 公式一致）：
      forward = (cos θ, sin θ)   —— heading = atan2(fwd_y, fwd_x)，衛星系 y 向下
      left    = (fwd_y, −fwd_x)  —— 車頭朝北(0,−1) 時左側為西(−1,0)
      模板 (x=左, z=後) 的位移 = x·left + z·(−forward)
    """
    th = math.radians(heading_deg)
    fwd = (math.cos(th), math.sin(th))
    left = (fwd[1], -fwd[0])
    kp = np.zeros((24, 3), dtype=float)
    for i in subset:
        x_b, _h_b, z_b = template[i]
        kp[i, 0] = center[0] + x_b * left[0] - z_b * fwd[0]
        kp[i, 1] = center[1] + x_b * left[1] - z_b * fwd[1]
        kp[i, 2] = 1.0            # confidence
    return kp


def angdiff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


class HandednessTest(unittest.TestCase):
    """模板→衛星的映射必須是反射（det = −1）；擬合要能表達它。"""

    def setUp(self):
        self.template = build_car_template(_FALLBACK_DIMS)
        self.loc = HawareLocalizer(IdentityEngine(), self.template, kp_conf=0.2)

    def test_模板到衛星的映射行列式為負(self):
        """自我檢定：body(x=左,z=後) → sat(x右,y下) 必然含一次反射。

        取車體的 left 與 rear 兩個基向量在衛星系的像，組成的矩陣行列式應為 −1。
        若哪天座標約定改了、這裡變成 +1，下面的擬合測試就失去意義，會先在這裡現形。
        """
        for heading in (0.0, 90.0, 217.0):
            th = math.radians(heading)
            fwd = np.array([math.cos(th), math.sin(th)])
            left = np.array([fwd[1], -fwd[0]])
            rear = -fwd
            M = np.column_stack([left, rear])      # body(x,z) → sat(x,y)
            self.assertAlmostEqual(np.linalg.det(M), -1.0, places=9,
                                   msg=f"heading={heading} 時映射行列式應為 −1")


class LocalizeRoundTripTest(unittest.TestCase):
    """把已知姿態的車擺進去再解回來，中心與朝向都要還原。"""

    HEADINGS = (0.0, 45.0, 90.0, 180.0, 270.0, 35.0, 217.0)
    CENTER = (120.0, 80.0)

    def setUp(self):
        self.template = build_car_template(_FALLBACK_DIMS)
        self.loc = HawareLocalizer(IdentityEngine(), self.template, kp_conf=0.2)

    def _roundtrip(self, subset, heading, center=None):
        center = center or self.CENTER
        kp = place_vehicle(self.template, center, heading, subset)
        res = self.loc.localize(kp)
        self.assertEqual(res.status, 'ok', f"subset={subset} heading={heading} 定位失敗")
        return res

    def test_全24點還原(self):
        for heading in self.HEADINGS:
            res = self._roundtrip(ALL24, heading)
            self.assertLess(angdiff(res.heading, heading), 1e-6,
                            f"全 24 點 heading={heading} 還原失敗（得到 {res.heading}）")
            self.assertLess(math.dist(res.sat_coords, self.CENTER), 1e-6)

    def test_擋風玻璃對還原(self):
        """純橫向點對——手性錯時這裡恰好錯 180°，是最具鑑別力的案例。"""
        for heading in self.HEADINGS:
            res = self._roundtrip(WINDSHIELD, heading)
            self.assertLess(angdiff(res.heading, heading), 1e-6,
                            f"擋風玻璃對 heading={heading} 應還原（得到 {res.heading}）")
            self.assertLess(math.dist(res.sat_coords, self.CENTER), 1e-6,
                            f"擋風玻璃對 heading={heading} 中心應還原")

    def test_前燈對還原(self):
        for heading in self.HEADINGS:
            res = self._roundtrip(HEADLIGHTS, heading)
            self.assertLess(angdiff(res.heading, heading), 1e-6)

    def test_同側輪對還原(self):
        """純縱向點對——手性錯時 heading 正確但中心橫移一個軌距，只有位置斷言抓得到。"""
        for subset in (WHEELS_LEFT, WHEELS_RIGHT):
            for heading in self.HEADINGS:
                res = self._roundtrip(subset, heading)
                self.assertLess(angdiff(res.heading, heading), 1e-6,
                                f"{subset} heading={heading} 還原失敗")
                self.assertLess(math.dist(res.sat_coords, self.CENTER), 1e-6,
                                f"{subset} heading={heading} 中心應還原（手性錯時會橫移一個軌距）")

    def test_車頂群還原且殘差為零(self):
        """對稱點集即使手性錯，中心與 heading 仍可能正確——但殘差不會是零。
        所以這裡同時斷言殘差，才抓得到手性問題。"""
        for heading in self.HEADINGS:
            kp = place_vehicle(self.template, self.CENTER, heading, ROOF)
            res = self.loc.localize(kp)
            self.assertEqual(res.status, 'ok')
            self.assertLess(angdiff(res.heading, heading), 1e-6)
            # 無噪的完美輸入，正確的擬合殘差必須是 0；手性錯時會殘留約 1.4 m
            pred = np.array([res.p_sat[i] for i in ROOF])
            obs = np.array([(kp[i, 0], kp[i, 1]) for i in ROOF])
            self.assertLess(float(np.abs(pred - obs).max()), 1e-6)

    def test_rank1成對點集不因數值噪音翻轉(self):
        """2 點時交叉共變異數是 rank-1，第二奇異向量任意。實作必須穩定（不可用
        `R = Vt.T @ U.T` 讓 det 由噪音決定），所以這裡掃過整圈角度確認無跳變。"""
        prev = None
        for deg in range(0, 360, 7):
            res = self._roundtrip(WINDSHIELD, float(deg))
            self.assertLess(angdiff(res.heading, float(deg)), 1e-6,
                            f"heading={deg} 時 rank-1 擬合翻轉")
            if prev is not None:
                step = angdiff(res.heading, prev)
                self.assertLess(step, 20.0, f"heading={deg} 附近出現不連續跳變（{step}°）")
            prev = res.heading


class SpreadGateTest(unittest.TestCase):
    """品質閘門：關鍵點投影後的展開度遠大於車長，就代表 homography 在外推。

    這條閘門的用途是把「靜默給出錯誤結論」換成「明確拒答」——下游（filter_and_enrich
    → build_scene）只讀 sat_coords，不看 status，所以外推幀若不標記就會一路流進場景包。
    """

    CENTER = (300.0, 200.0)

    def setUp(self):
        self.template = build_car_template(_FALLBACK_DIMS)

    def _localize(self, engine, subset=ALL24, heading=35.0, **kw):
        loc = HawareLocalizer(engine, self.template, kp_conf=0.2, **kw)
        return loc.localize(place_vehicle(self.template, self.CENTER, heading, subset))

    def test_正常車輛的展開度約等於車身對角線且通過(self):
        res = self._localize(IdentityEngine())
        self.assertEqual(res.status, 'ok')
        # 車長 3.8 m、車寬含後視鏡約 1.9 m → 對角線約 4.2 m，遠低於 8 m 門檻
        self.assertGreater(res.spread_m, 3.5)
        self.assertLess(res.spread_m, 5.5)

    def test_外推幀被標記為extrapolated(self):
        """放大 4 倍模擬遠場外推：展開度衝到約 17 m，必須被擋下。"""
        res = self._localize(BlowUpEngine(4.0))
        self.assertGreater(res.spread_m, 8.0)
        self.assertEqual(res.status, 'extrapolated',
                         "展開度超過門檻時 status 必須明確標記，不可仍是 'ok'")

    def test_被擋下時仍保留座標供診斷(self):
        """拒答不等於丟棄——sat_coords/heading 仍要在，只是 status 說不可信。"""
        res = self._localize(BlowUpEngine(4.0))
        self.assertIsNotNone(res.sat_coords)
        self.assertIsNotNone(res.heading)

    def test_閘門可關閉(self):
        res = self._localize(BlowUpEngine(4.0), max_spread_m=None)
        self.assertEqual(res.status, 'ok')
        self.assertGreater(res.spread_m, 8.0, "關閘門只影響 status，spread_m 仍要照算")

    def test_門檻可調(self):
        self.assertEqual(self._localize(IdentityEngine(), max_spread_m=1.0).status,
                         'extrapolated')
        self.assertEqual(self._localize(BlowUpEngine(4.0), max_spread_m=100.0).status, 'ok')

    def test_回報參與擬合的輪點數(self):
        """n_wheel_kp 是 heading 可信度最強的指標（實測 ≥2 個時中位誤差 2.42°、
        0–1 個時約 98°），必須輸出讓下游能據此拒答。"""
        eng = IdentityEngine()
        self.assertEqual(self._localize(eng, subset=ALL24).n_wheel_kp, 4)
        self.assertEqual(self._localize(eng, subset=WHEELS_LEFT).n_wheel_kp, 2)
        self.assertEqual(self._localize(eng, subset=WINDSHIELD).n_wheel_kp, 0)
        self.assertEqual(self._localize(eng, subset=[7, 0, 1]).n_wheel_kp, 1)

    def test_點數不足時不誤報(self):
        """只有 1 個關鍵點時定位本來就失敗，不該被展開度閘門蓋掉原本的失敗原因。"""
        loc = HawareLocalizer(IdentityEngine(), self.template, kp_conf=0.2)
        res = loc.localize(place_vehicle(self.template, self.CENTER, 0.0, [0]))
        self.assertEqual(res.status, 'failed_insufficient_kp')


if __name__ == "__main__":
    unittest.main()

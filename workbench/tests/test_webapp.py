"""底圖網頁流程（spec docs/specs/2026-08-16-web-onboarding-flow-design.md ②）的離線測試。

釘的是三件事：
1. 去車降級**要留下機器可讀狀態**（不能再與「真的沒車」同值），前端據此警示
2. 大小由使用者決定、縮小是裁中央、確認才鎖定 meta——鎖定後所有變體同一個涵蓋範圍
3. 空白圖磚（Google 該 zoom 無影像）要能偵測，供 zoom 探測用
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PIL import Image
    import numpy as np
    import cv2  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def _noise_img(w, h, seed=0):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class DecarStatusTest(unittest.TestCase):
    """降級不能靜默：enhance_file 回傳 decar_status，enhance() 寫進 meta。"""

    def test_無key時decar_status為no_key(self):
        import image_enhance
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "s.png"
            _noise_img(64, 48).save(src)
            info = image_enhance.enhance_file(src, Path(d) / "o.png", key="", upscale=1)
        self.assertEqual(info["decar_status"], "no_key")
        self.assertEqual(info["vehicles_removed"], 0)

    def test_decar關閉時狀態為skipped且不碰Gemini(self):
        """使用者不要去車：只銳化＋2x。狀態要與 no_key（想去但沒 key）區分開，前端才不會誤報紅字。"""
        import image_enhance
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "s.png"
            _noise_img(64, 48).save(src)
            # key 給一個假值：decar=False 時根本不該呼叫 Gemini，所以不會因為假 key 而失敗
            info = image_enhance.enhance_file(src, Path(d) / "o.png", key="FAKE", upscale=2, decar=False)
            out = Image.open(Path(d) / "o.png")
        self.assertEqual(info["decar_status"], "skipped")
        self.assertEqual(info["vehicles_removed"], 0)
        self.assertEqual(out.size, (128, 96))          # 銳化＋2x 照做

    def test_enhance把decar_status寫進meta(self):
        import image_enhance
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            out_dir.mkdir()
            _noise_img(64, 48).save(out_dir / "sat_raw.png")
            (out_dir / "meta.json").write_text(json.dumps({"px_per_meter": 29.0}))
            image_enhance.enhance("loc", key="", upscale=1, out_dir=out_dir)
            meta = json.loads((out_dir / "meta.json").read_text())
        self.assertEqual(meta["decar_status"], "no_key")


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class CaptureMetaTest(unittest.TestCase):
    """map_capture 不給 size 時，meta.size_m 必須是實際涵蓋公尺數而不是 null。"""

    def test_不裁切時size_m為整張涵蓋寬度(self):
        import map_capture
        img = _noise_img(1280, 1280)
        with tempfile.TemporaryDirectory() as d:
            meta = map_capture.finish_capture(img, 23.0, 120.0, "loc", 21, 2,
                                              size_m=None, out_dir=Path(d) / "loc")
        self.assertAlmostEqual(meta["size_m"], 1280 / meta["px_per_meter"], places=3)
        self.assertEqual((meta["img_w"], meta["img_h"]), (1280, 1280))

    def test_裁切時size_m原樣且圖為正方(self):
        import map_capture
        img = _noise_img(1280, 1280)
        with tempfile.TemporaryDirectory() as d:
            meta = map_capture.finish_capture(img, 23.0, 120.0, "loc", 21, 2,
                                              size_m=25.0, out_dir=Path(d) / "loc")
            saved = Image.open(Path(d) / "loc" / "sat_raw.png")
        self.assertEqual(meta["size_m"], 25.0)
        self.assertEqual(saved.size[0], saved.size[1])
        self.assertEqual(saved.size[0], round(25.0 * meta["px_per_meter"]))


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class BlankTileTest(unittest.TestCase):
    def test_均勻灰底判為空白(self):
        import webapp
        self.assertTrue(webapp.is_blank(Image.new("RGB", (100, 100), (229, 227, 223))))

    def test_有內容的圖不判為空白(self):
        import webapp
        self.assertFalse(webapp.is_blank(_noise_img(100, 100)))


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class UpsampleDetectionTest(unittest.TestCase):
    """Google 在該 zoom 沒影像時，不是回空白磚，而是把低 zoom 的圖放大充數。

    實例：23.062901,120.249615（使用者打錯的座標）zoom 21 銳利度 35、zoom 18 是 317——
    宣稱 29 px/m 實際只有 ~3.6 px/m 的資訊量。灰階 std 10.26 遠高於 is_blank 的門檻 6，
    所以舊的空白偵測完全抓不到，webapp 靜默給出一張糊底圖。
    """

    def test_放大充數的圖被判為細節不足(self):
        import webapp
        sharp = _noise_img(512, 512, 3)
        # 模擬 Google 的行為：降到 1/4 再放大回來——尺寸相同，但高頻資訊沒了
        blurred = sharp.resize((128, 128), Image.LANCZOS).resize((512, 512), Image.LANCZOS)
        self.assertGreater(webapp.detail_score(sharp), webapp.detail_score(blurred) * 3)
        self.assertTrue(webapp.looks_upsampled(blurred))

    def test_真正銳利的圖不被誤判(self):
        import webapp
        self.assertFalse(webapp.looks_upsampled(_noise_img(512, 512, 4)))

    def test_空白磚也算細節不足(self):
        import webapp
        self.assertTrue(webapp.looks_upsampled(Image.new("RGB", (256, 256), (229, 227, 223))))


class BestZoomTest(unittest.TestCase):
    """選 zoom 的規則：能裝下需求尺寸的**最高** zoom。

    這條規則原本只存在於 CLI 的人腦裡，網頁版沒有 → 使用者為了拿 38m 按了「降 zoom 重抓」，
    拿到 14.56 px/m 的糊圖，但 38m 在 zoom 21（涵蓋 43.97m）底下本來就放得下、解析度是兩倍。
    """

    LAT = 23.026901        # 台南永康；zoom 21 涵蓋 43.97m、20 → 87.9m、19 → 175.8m

    def test_小尺寸選最高zoom(self):
        import webapp
        self.assertEqual(webapp.best_zoom_for_size(self.LAT, 25.0), 21)

    def test_剛好放得下仍選最高zoom(self):
        """38m < 43.97m，必須留在 zoom 21——這正是使用者踩到的那格。"""
        import webapp
        self.assertEqual(webapp.best_zoom_for_size(self.LAT, 38.0), 21)

    def test_超過最高zoom涵蓋範圍才降級(self):
        import webapp
        self.assertEqual(webapp.best_zoom_for_size(self.LAT, 60.0), 20)
        self.assertEqual(webapp.best_zoom_for_size(self.LAT, 100.0), 19)

    def test_大到全部裝不下就回最低zoom(self):
        import webapp
        self.assertEqual(webapp.best_zoom_for_size(self.LAT, 9999.0), 19)


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class LockSizeTest(unittest.TestCase):
    """確認鎖定：所有變體裁中央到 size_m、meta 更新，且不同像素密度的變體按比例裁。"""

    def _seed(self, out_dir, ppm=29.0, genai=False):
        out_dir.mkdir(parents=True)
        _noise_img(1280, 1280, 1).save(out_dir / "sat_raw.png")
        _noise_img(2560, 2560, 2).save(out_dir / "sat_clean.png")   # 2x 增強版
        if genai:
            # genai_enhance 會把產出縮回來源尺寸，所以 sat_genai 是 1x（與 raw 同尺寸）
            _noise_img(1280, 1280, 5).save(out_dir / "sat_genai.png")
        (out_dir / "meta.json").write_text(json.dumps({
            "px_per_meter": ppm, "img_w": 1280, "img_h": 1280, "size_m": 1280 / ppm}))

    def test_genai變體是1x_裁切後與raw同尺寸(self):
        """三種變體像素密度各不同（raw 1x、clean 2x、genai 1x），裁切必須各自按比例。"""
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir, genai=True)
            webapp.lock_size(out_dir, 25.0)
            sizes = {n: Image.open(out_dir / n).size
                     for n in ("sat_raw.png", "sat_clean.png", "sat_genai.png")}
        side = round(25.0 * 29.0)
        self.assertEqual(sizes["sat_raw.png"], (side, side))
        self.assertEqual(sizes["sat_genai.png"], (side, side))      # 1x，與 raw 相同
        self.assertEqual(sizes["sat_clean.png"], (side * 2, side * 2))

    def test_鎖定後各變體涵蓋同一公尺數(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            meta = webapp.lock_size(out_dir, 25.0)
            raw = Image.open(out_dir / "sat_raw.png").size
            clean = Image.open(out_dir / "sat_clean.png").size
        side = round(25.0 * 29.0)
        self.assertEqual(raw, (side, side))
        self.assertEqual(clean, (side * 2, side * 2))
        self.assertEqual(meta["size_m"], 25.0)
        self.assertEqual((meta["img_w"], meta["img_h"]), (side, side))
        self.assertTrue(meta["locked"])

    def test_超過涵蓋範圍拒絕鎖定(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            with self.assertRaises(ValueError):
                webapp.lock_size(out_dir, 60.0)   # 1280/29 ≈ 44m，60m 超出

    def test_鎖定後跑enhance仍保留locked與size(self):
        """新流程是先鎖定再去車：enhance() 回寫 meta 時不能洗掉鎖定資訊。"""
        import image_enhance
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            webapp.lock_size(out_dir, 25.0)
            image_enhance.enhance("loc", key="", upscale=2, out_dir=out_dir)
            meta = json.loads((out_dir / "meta.json").read_text())
        self.assertTrue(meta["locked"])
        self.assertEqual(meta["size_m"], 25.0)
        self.assertEqual(meta["decar_status"], "no_key")
        self.assertEqual(meta["enhanced_px"], round(25.0 * 29.0) * 2)

    def test_鎖定必定產出銳化版且不去車(self):
        """鎖定後標註馬上要用得到清楚的底圖，所以銳化是必做的（本機 1 秒、無隨機性）。
        去車是另一回事（Gemini、有隨機性、要等）——維持選配。
        """
        import image_enhance
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            image_enhance.enhance("loc", key="FAKE", upscale=2, out_dir=out_dir, decar=False)
            meta = json.loads((out_dir / "meta.json").read_text())
            clean = Image.open(out_dir / "sat_clean.png")
        self.assertEqual(meta["decar_status"], "skipped")
        self.assertEqual(clean.size, (2560, 2560))

    def test_多一次重取樣是純損失(self):
        """為什麼銳化不放大：2x 會把一次重取樣**烤進檔案**，之後不論縮小顯示或放大檢視
        都在那個損失之上；瀏覽器要放大自己會放，而且是從更銳利的來源放。

        這裡釘的是機制而不是統計量——放大再縮回來必然回不到原樣。
        （真實底圖 tainan_yongkong 的實測，Laplacian 變異數，1x 銳化 vs 交付的 2x 版：
         顯示 400px 407 vs 162、554px 624 vs 260、815px 658 vs 208、1630px 69 vs 47、
         2400px 18 vs 13——每個尺寸 1x 都贏 2–3 倍。合成圖沒有這個特性，別拿它當依據。）
        """
        import numpy as np
        src = _noise_img(300, 300, 11)
        roundtrip = src.resize((600, 600), Image.LANCZOS).resize((300, 300), Image.LANCZOS)
        a = np.asarray(src.convert("L"), np.float32)
        b = np.asarray(roundtrip.convert("L"), np.float32)
        self.assertGreater(np.abs(a - b).mean(), 0.5, "放大再縮回竟然無損？那前提就不成立")

    def test_鎖定產出的銳化底圖與原圖同尺寸(self):
        """鎖定＝裁切 + 銳化，**不放大**。同尺寸代表 px_per_meter 不必乘倍率。"""
        import webapp
        out_dir = webapp.OUTPUT_DIR / "unittest_1x_tmp"
        self.addCleanup(lambda: __import__("shutil").rmtree(out_dir, ignore_errors=True))
        out_dir.mkdir(parents=True, exist_ok=True)
        _noise_img(1280, 1280, 12).save(out_dir / "sat_raw.png")
        (out_dir / "meta.json").write_text(json.dumps({
            "lat": 23.0, "lon": 120.0, "zoom": 21, "scale": 2,
            "px_per_meter": 29.0, "img_w": 1280, "img_h": 1280, "size_m": 1280 / 29.0}))
        st = webapp.run_lock("unittest_1x_tmp", 25.0)
        side = round(25.0 * 29.0)
        self.assertEqual(st["variants"]["sat_clean.png"]["w"], side)   # 1x，不是 side*2
        self.assertEqual(st["variants"]["sat_raw.png"]["w"], side)

    def test_run_lock必定留下可標註的銳化底圖(self):
        """整合層：鎖定完就要能直接標註，所以 run_lock 一定要留下 sat_clean。

        （seed 成 zoom 21＝最高，best_zoom_for_size 不會想升級，所以這條路不碰網路。）
        """
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = webapp.OUTPUT_DIR / "unittest_lock_tmp"
            self.addCleanup(lambda: __import__("shutil").rmtree(out_dir, ignore_errors=True))
            out_dir.mkdir(parents=True, exist_ok=True)
            _noise_img(1280, 1280, 7).save(out_dir / "sat_raw.png")
            (out_dir / "meta.json").write_text(json.dumps({
                "lat": 23.0, "lon": 120.0, "zoom": 21, "scale": 2,
                "px_per_meter": 29.0, "img_w": 1280, "img_h": 1280, "size_m": 1280 / 29.0}))
            st = webapp.run_lock("unittest_lock_tmp", 25.0)
            side = round(25.0 * 29.0)
            self.assertIn("sat_clean.png", st["variants"], "鎖定後沒有銳化底圖，標註會拿到原圖")
            self.assertEqual(st["variants"]["sat_clean.png"]["w"], side)   # 1x
            self.assertEqual(st["meta"]["decar_status"], "skipped")   # 銳化做、去車不做

    def test_run_lock對已鎖定的地點要直接拒絕(self):
        """繞過路徑（Codex 審查抓到）：`run_lock` 若先做 zoom 升級才檢查 locked，
        重抓寫出的新 meta **不含 locked**，接著 `lock_size` 就能用不同尺寸再鎖一次，
        整個「鎖定後只能重新擷取」的約定就被繞過去了。所以第一件事就是擋。
        """
        import webapp
        out_dir = webapp.OUTPUT_DIR / "unittest_relock_tmp"
        self.addCleanup(lambda: __import__("shutil").rmtree(out_dir, ignore_errors=True))
        out_dir.mkdir(parents=True, exist_ok=True)
        _noise_img(600, 600, 9).save(out_dir / "sat_raw.png")
        # zoom 20 + 已鎖定：若先跑升級就會重抓並洗掉 locked
        (out_dir / "meta.json").write_text(json.dumps({
            "lat": 23.0, "lon": 120.0, "zoom": 20, "scale": 2,
            "px_per_meter": 14.5, "img_w": 600, "img_h": 600,
            "size_m": 600 / 14.5, "locked": True}))
        with self.assertRaises(ValueError):
            webapp.run_lock("unittest_relock_tmp", 25.0)
        meta = json.loads((out_dir / "meta.json").read_text())
        self.assertTrue(meta["locked"])              # 沒有被重抓洗掉
        self.assertEqual(meta["zoom"], 20)

    def test_已鎖定不可再鎖(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            webapp.lock_size(out_dir, 30.0)
            with self.assertRaises(ValueError):
                webapp.lock_size(out_dir, 20.0)


class UploadPathTest(unittest.TestCase):
    """`/api/handoff` 的 video / cctv_image 是**用戶端給的字串**，直接拿去接路徑會穿越。

    兩條實際打通過的路：
      1. `"/tmp/x"` —— pathlib 的 `Path("/a/b") / "/tmp/x"` 會**整個丟掉前綴**變成 `/tmp/x`
      2. `"../../../..."` —— 一般的相對路徑上跳
    後果：`shutil.copy2` 把機器上任意檔案複製進 repo；`cctv_image` 那條還會被
    `Image.open(...).save(cctv_<code>.png)` 轉存並經 `/location/...` 對外提供。
    這支 server 預設只綁 127.0.0.1，但 `--host` 可以改，而且瀏覽器裡任何網頁都打得到本機。
    """

    def test_絕對路徑會被擋下(self):
        import webapp
        for bad in ("/tmp/x.mp4", "/etc/passwd"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                webapp.resolve_upload("loc", bad)

    def test_相對上跳會被擋下(self):
        import webapp
        for bad in ("../x.mp4", "../../etc/passwd", "a/../../../x.mp4", "sub/x.mp4"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                webapp.resolve_upload("loc", bad)

    def test_正常檔名可通過且落在上傳目錄內(self):
        import webapp
        got = webapp.resolve_upload("loc", "clip.mp4")
        self.assertEqual(got, webapp.UPLOAD_DIR / "loc" / "clip.mp4")
        self.assertTrue(str(got).startswith(str(webapp.UPLOAD_DIR / "loc")))

    def test_代號本身也要驗(self):
        import webapp
        with self.assertRaises(ValueError):
            webapp.resolve_upload("../evil", "clip.mp4")

    def test_空字串與None回None(self):
        import webapp
        self.assertIsNone(webapp.resolve_upload("loc", None))
        self.assertIsNone(webapp.resolve_upload("loc", ""))

    def test_檔案不存在要給看得懂的訊息而不是內部路徑(self):
        """上傳檔可能已被清掉（換 code、清暫存、重開機）。原本會漏出
        `FileNotFoundError: ... /workbench/output/_uploads/...` 這種內部路徑，
        使用者只看得到一串跟自己無關的路徑，也不知道該做什麼。
        """
        import webapp
        with self.assertRaises(ValueError) as cm:
            webapp.resolve_upload("loc", "gone.mp4", must_exist=True)
        text = str(cm.exception)
        self.assertIn("gone.mp4", text)
        self.assertIn("重新選", text)
        self.assertNotIn("_uploads", text)      # 不吐內部路徑
        self.assertNotIn("Errno", text)


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class SaveGateTest(unittest.TestCase):
    """4 組點的「誤差 0.00」是假的（被解死），不能讓它就這樣進推論。

    前端已經警告，但後端也要擋——警告可以被忽略，而這份 G_projection 之後會決定
    所有 position_m。
    """

    PAIRS4 = [{"coords_cctv": [0, 0], "coords_sat": [10, 20]},
              {"coords_cctv": [300, 0], "coords_sat": [610, 20]},
              {"coords_cctv": [300, 200], "coords_sat": [610, 420]},
              {"coords_cctv": [0, 200], "coords_sat": [10, 420]}]

    def test_四點不得存檔(self):
        import annotate
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as cm:
                annotate.save_g_projection(Path(d), "abc", self.PAIRS4, px_per_meter=29.0)
        self.assertIn("5", str(cm.exception))

    def test_五點可存檔(self):
        import annotate
        pairs = self.PAIRS4 + [{"coords_cctv": [150, 100], "coords_sat": [310, 220]}]
        with tempfile.TemporaryDirectory() as d:
            path = annotate.save_g_projection(Path(d), "abc", pairs, px_per_meter=29.0)
            exists = Path(path).exists()
        self.assertTrue(exists)


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class FramePreviewTest(unittest.TestCase):
    """碰撞幀是整條鏈唯二的人工判斷，但沒有畫面就只是在猜一個數字。"""

    def _video(self, d, n=10):
        import cv2
        import numpy as np
        path = Path(d) / "clip.mp4"
        w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
        for i in range(n):
            w.write(np.full((48, 64, 3), 10 + i * 20, np.uint8))
        w.release()
        return path

    def test_取得指定影格(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            png = webapp.extract_frame(self._video(d), 3)
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_超出範圍的影格要報錯而不是回空白(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                webapp.extract_frame(self._video(d, 5), 999)

    def test_負數影格要擋(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                webapp.extract_frame(self._video(d), -1)


class StaticServeTest(unittest.TestCase):
    """播放器要能從這台 server 開，所以得服務 player/ 與 scenes/。

    這是第二個「用戶端字串接路徑」的地方（第一個是上傳檔名），同樣要擋穿越——
    而且靜態檔是 GET，任何網頁都能誘導瀏覽器去讀。
    """

    def test_正常路徑可通過(self):
        import webapp
        got = webapp.safe_static("player", "index.html")
        self.assertEqual(got, webapp.REPO_ROOT / "player" / "index.html")
        self.assertEqual(webapp.safe_static("scenes", "test1/scene.json"),
                         webapp.REPO_ROOT / "scenes" / "test1" / "scene.json")

    def test_穿越會被擋下(self):
        import webapp
        for bad in ("../workbench/.env", "../../etc/passwd", "/etc/passwd",
                    "a/../../.env"):
            with self.subTest(bad=bad):
                self.assertIsNone(webapp.safe_static("player", bad))

    def test_只開放白名單目錄(self):
        import webapp
        self.assertIsNone(webapp.safe_static("workbench", "webapp.py"))
        self.assertIsNone(webapp.safe_static("..", "x"))


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class HandoffTest(unittest.TestCase):
    """② 鎖定完 → 交給 trafficlab 標註 GUI（③）。

    trafficlab 的 Calibration 分頁直接列 `location/*`，所以 handoff 要把檔案擺成它認得的樣子：
    `location/<code>/sat_<code>.png`（必）、`cctv_<code>.png`（影片首幀）、`footage/*.mp4`。
    另外寫 `sat_meta_<code>.json` 把**已知的 px/m** 帶過去——DistStage 原本要人手量兩點，
    現在可以直接採用，少一個人為誤差來源。
    """

    def _seed(self, out_dir, ppm=29.0, side=400):
        out_dir.mkdir(parents=True)
        _noise_img(side, side, 1).save(out_dir / "sat_raw.png")
        _noise_img(side * 2, side * 2, 2).save(out_dir / "sat_clean.png")   # 2x
        _noise_img(side, side, 3).save(out_dir / "sat_genai.png")
        (out_dir / "meta.json").write_text(json.dumps({
            "lat": 23.0, "lon": 120.0, "zoom": 21, "px_per_meter": ppm,
            "img_w": side, "img_h": side, "size_m": side / ppm, "locked": True}))

    def test_交付給標註的比例尺跟著實際尺寸走(self):
        """sat_clean 現在是 1x，px_per_meter 就等於 raw 的值，upscale_factor = 1。
        （這條刻意用「跟著實際寬度算」的方式驗，將來若又改倍率也不會靜默失準。）"""
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            out_dir.mkdir(parents=True)
            _noise_img(400, 400, 1).save(out_dir / "sat_raw.png")
            _noise_img(400, 400, 2).save(out_dir / "sat_clean.png")     # 1x
            (out_dir / "meta.json").write_text(json.dumps({
                "lat": 23.0, "lon": 120.0, "zoom": 21, "px_per_meter": 29.0,
                "img_w": 400, "img_h": 400, "size_m": 400 / 29.0, "locked": True}))
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")
        self.assertEqual(info["sat_meta"]["sat_variant"], "sat_clean.png")
        self.assertAlmostEqual(info["sat_meta"]["px_per_meter"], 29.0)
        self.assertEqual(info["sat_meta"]["upscale_factor"], 1.0)

    def test_交付給標註的是2x銳化版而不是原圖(self):
        """標註要在圖上點準位置，786px 的原圖糊到點不準。

        銳化是**本機、確定性、不動幾何**的（UnsharpMask + LANCZOS 整數倍放大，
        image_enhance 內有尺寸 assert），跟去車／生圖那些會亂動內容的步驟不同類，
        所以標註底圖一律用它；px_per_meter 跟著 ×2 一起帶過去，座標才對得上。
        """
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            (out_dir / "sat_genai.png").unlink()
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")
            sat = Image.open(loc_root / "loc" / "sat_loc.png")
        self.assertEqual(sat.size, (800, 800))                  # sat_clean，raw 的 2 倍
        self.assertEqual(info["sat_meta"]["sat_variant"], "sat_clean.png")
        self.assertAlmostEqual(info["sat_meta"]["px_per_meter"], 58.0)
        self.assertEqual(info["sat_meta"]["upscale_factor"], 2.0)

    def test_沒有增強版時交付原圖(self):
        """使用者決定不去車也不銳化 → 只有 sat_raw。交付要用它，比例尺就是 raw 的 px/m。"""
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            (out_dir / "sat_clean.png").unlink()
            (out_dir / "sat_genai.png").unlink()
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")
            sat = Image.open(loc_root / "loc" / "sat_loc.png")
            meta = json.loads((loc_root / "loc" / "sat_meta_loc.json").read_text())
        self.assertEqual(sat.size, (400, 400))
        self.assertEqual(meta["sat_variant"], "sat_raw.png")
        self.assertAlmostEqual(meta["px_per_meter"], 29.0)        # 沒放大，就是 raw 的值
        self.assertEqual(meta["upscale_factor"], 1.0)

    def test_交付sat_clean並帶已知比例尺(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")
            sat = Image.open(loc_root / "loc" / "sat_loc.png")
            meta = json.loads((loc_root / "loc" / "sat_meta_loc.json").read_text())
        self.assertEqual(sat.size, (800, 800))                   # 用的是 sat_clean（2x）
        self.assertAlmostEqual(meta["px_per_meter"], 58.0)       # 29 × 2
        self.assertEqual(meta["sat_variant"], "sat_clean.png")
        self.assertEqual(meta["size_m"], 400 / 29.0)
        self.assertIn("sat_loc.png", info["written"])

    def test_預設不會自己挑genai版本(self):
        """genai 是重畫的，**預設**絕不自動採用——即使它存在也只拿 sat_clean。
        （要用它必須明示 variant，見 test_明示variant就交付那一張。）"""
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")
            sat = Image.open(loc_root / "loc" / "sat_loc.png")
            genai = Image.open(out_dir / "sat_genai.png")
        self.assertNotEqual(sat.size, genai.size)
        self.assertEqual(info["sat_meta"]["sat_variant"], "sat_clean.png")

    def test_明示variant就交付那一張(self):
        """使用者在 ① 看著 AI 高清版按下交付，標註頁就要拿到那一張。

        代價（重畫的幾何會傳進 G_projection）由 UI 負責講清楚，這裡只驗「說到做到」，
        並且驗 sat_meta 有留下出處——下游只看得到一張 sat_<code>.png，
        不寫 geometry 就沒人知道那是生圖畫出來的路面。
        """
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            (out_dir / "meta.json").write_text(json.dumps({
                "lat": 23.0, "lon": 120.0, "zoom": 21, "px_per_meter": 29.0,
                "img_w": 400, "img_h": 400, "size_m": 400 / 29.0, "locked": True,
                "genai_provider": "gemini", "genai_model": "gemini-3.1-flash-image",
                "genai_prompt": "sharp"}))
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc",
                                                variant="sat_genai.png")
            sat = Image.open(loc_root / "loc" / "sat_loc.png")
            genai = Image.open(out_dir / "sat_genai.png")
        self.assertEqual(sat.size, genai.size)
        meta = info["sat_meta"]
        self.assertEqual(meta["sat_variant"], "sat_genai.png")
        self.assertEqual(meta["geometry"], "rewritten_by_genai")
        self.assertEqual(meta["genai_provider"], "gemini")
        self.assertAlmostEqual(meta["px_per_meter"], 29.0)     # genai 與 raw 同尺寸
        self.assertEqual(meta["upscale_factor"], 1.0)

    def test_明示不存在或未知的variant要報錯(self):
        """按鈕沒按過就沒有 genai。報「不存在」比默默降級成忠實版好——
        默默降級正是使用者以為高清沒進標註頁的那個失敗模式。"""
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            (out_dir / "sat_genai.png").unlink()
            with self.assertRaisesRegex(ValueError, "不存在"):
                webapp.handoff_to_trafficlab(out_dir, loc_root, "loc",
                                             variant="sat_genai.png")
            with self.assertRaisesRegex(ValueError, "未知的底圖版本"):
                webapp.handoff_to_trafficlab(out_dir, loc_root, "loc",
                                             variant="../../etc/passwd")

    def test_未鎖定拒絕交付(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            m = json.loads((out_dir / "meta.json").read_text()); m["locked"] = False
            (out_dir / "meta.json").write_text(json.dumps(m))
            with self.assertRaises(ValueError):
                webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")

    def test_已有G_projection時拒絕覆蓋(self):
        """已經標過的地點，覆蓋 sat 會讓既有 G_projection 的座標全部失效。"""
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            (loc_root / "loc").mkdir(parents=True)
            (loc_root / "loc" / "G_projection_loc.json").write_text("{}")
            with self.assertRaises(ValueError):
                webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")
            webapp.handoff_to_trafficlab(out_dir, loc_root, "loc", force=True)   # 明示才放行
            self.assertTrue((loc_root / "loc" / "sat_loc.png").exists())

    def test_force覆蓋時舊的G_projection不可留下(self):
        """底圖被換掉，舊 G_projection 的像素座標就失效了。

        留著它最危險：trafficlab 的 pick_stage 會**自動載入**同名檔，網頁標註也會把錨點
        帶回來——兩邊都會拿舊座標配新底圖，而且完全不報錯。改名成 .superseded 保留證據。
        """
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            (loc_root / "loc").mkdir(parents=True)
            gp = loc_root / "loc" / "G_projection_loc.json"
            gp.write_text('{"old": true}')
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc", force=True)
            still_there = gp.exists()
            backups = list((loc_root / "loc").glob("G_projection_loc.json.superseded*"))
        self.assertFalse(still_there, "舊 G_projection 必須移走")
        self.assertEqual(len(backups), 1, "但要保留成 .superseded 當證據")
        self.assertIn("superseded", " ".join(info["written"]))

    def test_沒有cctv時標示為不可標註(self):
        """標註需要兩張圖對點；只有底圖是標不了的，要講清楚而不是讓人點進去才發現。"""
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")
        self.assertFalse(info["has_cctv"])
        self.assertFalse(info["annotation_ready"])

    def test_去車狀態要跟著交付過去(self):
        """sat_clean 可能是「想去車但沒 key」的產物，下游看不到狀態就會誤以為路面乾淨。"""
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            m = json.loads((out_dir / "meta.json").read_text())
            m["decar_status"] = "failed"
            (out_dir / "meta.json").write_text(json.dumps(m))
            webapp.handoff_to_trafficlab(out_dir, loc_root, "loc")
            sm = json.loads((loc_root / "loc" / "sat_meta_loc.json").read_text())
        self.assertEqual(sm["decar_status"], "failed")

    def test_影片抽首幀成cctv(self):
        import cv2
        import numpy as np
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir, loc_root = Path(d) / "out" / "loc", Path(d) / "location"
            self._seed(out_dir)
            vid = Path(d) / "clip.mp4"
            w = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
            for i in range(5):
                w.write(np.full((48, 64, 3), 40 + i * 40, np.uint8))
            w.release()
            info = webapp.handoff_to_trafficlab(out_dir, loc_root, "loc", video=vid)
            cctv = Image.open(loc_root / "loc" / "cctv_loc.png")
            footage_ok = (loc_root / "loc" / "footage" / "clip.mp4").exists()
        self.assertEqual(cctv.size, (64, 48))
        self.assertTrue(footage_ok)
        self.assertIn("cctv_loc.png", info["written"])


if __name__ == "__main__":
    unittest.main()

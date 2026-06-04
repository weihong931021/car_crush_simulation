"""
車輛規格表 — 尺寸來源：filtered_output.json 實測 + 標準參考值
length_m 是縮放基準（最長水平維度）
"""

VEHICLE_SPECS = {
    # ── 轎車 ──────────────────────────────────────────────
    "Car": {
        "length_m": 3.8,    # from filtered_output.json
        "width_m":  1.8,
        "height_m": 1.55,
        "mass_kg":  1500,
        "sketchfab_uid": "5ef9b845aaf44203b6d04e2c677e444f",  # Tesla 2018 Model 3
        "glb_filename": "car.glb",
    },
    # ── 機車 / 自行車 ──────────────────────────────────────
    "Two_Wheeler": {
        "length_m": 1.7,    # from filtered_output.json（含騎士）
        "width_m":  0.6,
        "height_m": 1.6,    # 含騎士坐姿高度
        "mass_kg":  200,
        "sketchfab_uid": None,  # TODO: 找合適的機車模型 UID
        "glb_filename": "moto.glb",
    },
    # ── SUV ───────────────────────────────────────────────
    "SUV": {
        "length_m": 4.7,
        "width_m":  1.9,
        "height_m": 1.65,
        "mass_kg":  2000,
        "sketchfab_uid": None,
        "glb_filename": "suv.glb",
    },
    # ── 廂型車 / 小貨車 ────────────────────────────────────
    "Van": {
        "length_m": 5.2,
        "width_m":  2.0,
        "height_m": 2.0,
        "mass_kg":  2500,
        "sketchfab_uid": None,
        "glb_filename": "van.glb",
    },
    # ── 大卡車 ────────────────────────────────────────────
    "Truck": {
        "length_m": 12.0,
        "width_m":  2.5,
        "height_m": 4.0,
        "mass_kg":  15000,
        "sketchfab_uid": None,
        "glb_filename": "truck.glb",
    },
    # ── 巴士 ──────────────────────────────────────────────
    "Bus": {
        "length_m": 12.0,
        "width_m":  2.5,
        "height_m": 3.5,
        "mass_kg":  12000,
        "sketchfab_uid": None,
        "glb_filename": "bus.glb",
    },
}

# filtered_output.json class 名稱 → VEHICLE_SPECS key 的映射
CLASS_ALIAS = {
    "car":        "Car",
    "Car":        "Car",
    "two_wheeler":"Two_Wheeler",
    "Two_Wheeler":"Two_Wheeler",
    "motorcycle": "Two_Wheeler",
    "bike":       "Two_Wheeler",
    "suv":        "SUV",
    "van":        "Van",
    "truck":      "Truck",
    "bus":        "Bus",
}


def get_spec(vehicle_class: str) -> dict:
    key = CLASS_ALIAS.get(vehicle_class, vehicle_class)
    spec = VEHICLE_SPECS.get(key)
    if spec is None:
        raise KeyError(f"Unknown vehicle class: {vehicle_class!r}. Available: {list(VEHICLE_SPECS)}")
    return spec

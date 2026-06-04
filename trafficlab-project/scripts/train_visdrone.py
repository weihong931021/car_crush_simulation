"""
Fine-tune yolo11l on VisDrone2019-DET dataset.
First run will auto-download VisDrone (~2.3GB) to ~/datasets/VisDrone/

Usage:
    python scripts/train_visdrone.py
"""
import os
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"   # MPS tensor bug workaround
from pathlib import Path
from ultralytics import YOLO

BASE_MODEL  = "/Users/weihong/Documents/TrafficLab-3D/yolo11l.pt"
PROJECT_DIR = Path(__file__).parent.parent / "models" / "training"
RUN_NAME    = "yolo11l-visdrone-ft"

model = YOLO(BASE_MODEL)

results = model.train(
    data="VisDrone.yaml",
    epochs=50,
    imgsz=640,
    batch=8,
    device="cpu",
    project=str(PROJECT_DIR),
    name=RUN_NAME,
    exist_ok=True,

    # fine-tune learning rates (smaller than scratch)
    lr0=0.001,
    lrf=0.01,
    warmup_epochs=3,

    # stop early if no improvement
    patience=15,

    # freeze backbone (layers 0-9) so only detection head adapts
    freeze=10,

    # augmentation — keep moderate for fine-tune
    hsv_h=0.015,
    hsv_s=0.7,
    hsv_v=0.4,
    flipud=0.0,
    fliplr=0.5,
    mosaic=0.5,   # reduced from default 1.0 for fine-tune stability

    save=True,
    plots=True,
    verbose=True,
)

best = PROJECT_DIR / RUN_NAME / "weights" / "best.pt"
dest = Path(__file__).parent.parent / "models" / "yolo11l-visdrone-ft.pt"
if best.exists():
    import shutil
    shutil.copy(best, dest)
    print(f"\nBest model copied → {dest}")

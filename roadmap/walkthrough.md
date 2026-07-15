# ZED 2i Street Sign Geolocation — Walkthrough

## What Was Built

The complete software scaffolding for a **ZED 2i + GPS RTK street sign geolocation system** — 7 Python/config files covering all 6 phases. The code is structured so you can incrementally test each component as hardware arrives.

---

## Project Tree

```
c:\Temp\coding\open3d\
├── zed_sign_config.json        ← Central configuration
├── requirements_zed.txt        ← Python dependencies
│
├── zed_capture.py              ← Phase 1: Live stereo + depth preview
├── zed_record.py               ← Phase 1: SVO2 recording
├── gnss_reader.py              ← Phase 2: GPS RTK NMEA parser
├── prepare_dataset.py          ← Phase 3: Dataset preparation tool
├── train_sign_detector.py      ← Phase 3: YOLO training + export
├── zed_sign_pipeline.py        ← Phase 4: Full end-to-end pipeline
│
├── datasets/
│   └── traffic_signs/          ← YOLO dataset (you populate this)
│       ├── train/images/
│       ├── train/labels/
│       ├── val/images/
│       ├── val/labels/
│       └── test/images/ & labels/
│
├── models/                     ← ONNX model output goes here
├── recordings/                 ← SVO2 drive recordings
├── output/                     ← GeoJSON/CSV pipeline results
│
└── roadmap/
    └── zed2i_street_sign_geolocation.md  ← Full technical roadmap
```

---

## Files Detail

### Configuration
- [zed_sign_config.json](file:///c:/Temp/coding/open3d/zed_sign_config.json) — All parameters: camera (resolution, FPS, depth mode), GNSS (port, baud, lever arm), detection (model path, confidence, max depth, classes), de-duplication (distance threshold, min observations), output paths
- [requirements_zed.txt](file:///c:/Temp/coding/open3d/requirements_zed.txt) — Python dependencies for the project

### Phase 1 — Camera Capture
- [zed_capture.py](file:///c:/Temp/coding/open3d/zed_capture.py) — Live preview: stereo image + depth colormap, IMU readout, depth probing, frame save
- [zed_record.py](file:///c:/Temp/coding/open3d/zed_record.py) — SVO2 recording: H265 compression, duration limit, file size tracking, red-dot indicator

### Phase 2 — GNSS Reader
- [gnss_reader.py](file:///c:/Temp/coding/open3d/gnss_reader.py) — Standalone NMEA parser: GNSSFix dataclass, RTK fix detection, port listing, JSON output mode

### Phase 3 — YOLO Training
- [prepare_dataset.py](file:///c:/Temp/coding/open3d/prepare_dataset.py) — Dataset tool with 5 modes:
  - `--scaffold` — Create empty directory structure + data.yaml
  - `--from-roboflow` — Download from Roboflow via API
  - `--from-local` — Import local images with auto train/val/test splitting
  - `--verify` — Validate labels, check class distribution, report issues
  - `--preview` — Generate annotated sample grid
- [train_sign_detector.py](file:///c:/Temp/coding/open3d/train_sign_detector.py) — Training pipeline:
  - Augmentation tuned for signs (no vertical flip, small rotation)
  - Auto evaluation with mAP target check (≥0.85)
  - ONNX export with FP16 for RTX 5060
  - Visual inference test on sample images
  - Supports `--eval-only`, `--export-only`, `--resume`

### Phase 4 — Main Pipeline
- [zed_sign_pipeline.py](file:///c:/Temp/coding/open3d/zed_sign_pipeline.py) — End-to-end: ZED capture → GPS fusion → YOLO detection → 3D localization → `camera_to_geo()` → de-duplication → GeoJSON/CSV

---

## Usage Guide

### Step 1: Install Dependencies
```bash
pip install -r requirements_zed.txt
# Then install pyzed from ZED SDK: python <SDK_PATH>/get_python_api.py
```

### Step 2: Test Camera (once hardware arrives)
```bash
python zed_capture.py          # Live preview
python zed_record.py           # Record a test drive
```

### Step 3: Test GPS RTK
```bash
python gnss_reader.py --list   # Find your COM port
python gnss_reader.py --port COM3  # Watch fixes come in
```

### Step 4: Prepare Dataset (can do now, no camera needed)
```bash
python prepare_dataset.py --scaffold                  # Create structure
# Add images + labels, then:
python prepare_dataset.py --verify                    # Check integrity
python prepare_dataset.py --preview                   # Visual check
```

### Step 5: Train Model
```bash
python train_sign_detector.py                         # Train + eval + export
python train_sign_detector.py --model yolo11m.pt      # Use YOLO v11
python train_sign_detector.py --export-only            # Re-export existing model
```

### Step 6: Run Full Pipeline
```bash
python zed_sign_pipeline.py                           # Live camera + GPS
python zed_sign_pipeline.py --svo recordings/drive.svo2  # Offline replay
python zed_sign_pipeline.py --no-display --no-gnss    # Headless test
```

### Output
- `output/signs.geojson` — Load into QGIS or [geojson.io](https://geojson.io)
- `output/signs.csv` — Open in Excel
- `output/session.log` — Debug log

---

## What Requires Hardware

| Task | Requires |
|---|---|
| Camera capture/recording | ZED 2i + USB 3.0 |
| GPS testing | RTK receiver + serial cable |
| Depth verification | ZED 2i |
| Full pipeline test | All hardware |
| **YOLO training** | **GPU only — no camera needed** |
| **Dataset preparation** | **No hardware needed** |

> [!TIP]
> Start with Phase 3 (dataset + training) immediately — this is the most time-consuming step and requires zero hardware. You can download datasets from Roboflow Universe while waiting for your camera/GPS setup.

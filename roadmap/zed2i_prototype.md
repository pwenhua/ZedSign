# ZED 2i Street Sign Detection — Simplified Prototype Roadmap

> **Goal**: Prove the end-to-end pipeline works — detect street signs with YOLO and locate them in 3D using **only** the ZED 2i's stereo depth and built-in VIO (Visual-Inertial Odometry). No RTK receiver, no GNSS Fusion, no lever-arm calibration.

> [!NOTE]
> This prototype deliberately **excludes** all RTK / GNSS related processes. The camera's VIO tracking gives a local coordinate frame (meters from the start position), which is sufficient to verify detection + 3D localisation. RTK integration can be layered on later once the core pipeline is validated.

---

## What Is Kept vs. Removed

| Full Roadmap Item | Prototype? | Reason |
|---|---|---|
| ZED 2i capture (stereo + depth + IMU) | ✅ Kept | Core sensor |
| YOLOv8/v11 sign detection | ✅ Kept | Core AI |
| ZED positional tracking (VIO) | ✅ Kept | Gives local 3D pose — no GPS needed |
| ZED Custom Object Detection (3D boxes) | ✅ Kept | Maps 2D detections → 3D positions |
| SVO2 recording / offline replay | ✅ Kept | Essential for desk development |
| De-duplication & multi-frame averaging | ✅ Kept (basic) | Reduces noise even without GPS |
| Output to JSON + visualisation | ✅ Kept | Proves the pipeline produces results |
| GPS RTK receiver & NMEA parsing | ❌ Removed | Not needed for doability check |
| Fusion module (`sl.Fusion`) | ❌ Removed | Required for GNSS ingestion — not needed here |
| `camera_to_geo()` → lat/lng conversion | ❌ Removed | Requires Fusion + GNSS data |
| Lever-arm calibration | ❌ Removed | Only relevant with GPS antenna |
| GeoJSON output (lat/lng) | ❌ Removed | Replaced with local XYZ JSON |
| Timestamp sync (camera ↔ GPS) | ❌ Removed | No GPS to sync |

---

## Simplified Architecture

```
┌─────────────┐    USB 3.0    ┌────────────────────────────────────────┐
│  ZED 2i     │──────────────▶│  PC (RTX 5060)                        │
│  Camera     │               │                                        │
│  (stereo +  │               │  ┌────────────┐    ┌───────────────┐   │
│   IMU)      │               │  │ ZED SDK    │    │ YOLO Sign     │   │
│             │               │  │ • depth    │    │ Detector      │   │
└─────────────┘               │  │ • VIO pose │    │ (ONNX/TRT)    │   │
                              │  └─────┬──────┘    └───────┬───────┘   │
                              │        │        2D bbox    │           │
                              │  ┌─────▼───────────────────▼────────┐  │
                              │  │  ZED Custom Object Detection     │  │
                              │  │  • 2D → 3D via depth map         │  │
                              │  │  • Object tracking across frames │  │
                              │  └─────────────┬────────────────────┘  │
                              │                │                       │
                              │  ┌─────────────▼────────────────────┐  │
                              │  │  Local 3D Sign Map (JSON)        │  │
                              │  │  { class, x, y, z, confidence,   │  │
                              │  │    observation_count, timestamp } │  │
                              │  └──────────────────────────────────┘  │
                              └────────────────────────────────────────┘
```

---

## Hardware Checklist (Prototype)

| Component | Spec | Notes |
|---|---|---|
| **ZED 2i** | Stereo + IMU, IP65 | Built-in IMU drives VIO tracking |
| **RTX 5060** | Blackwell, CUDA 12, 8 GB VRAM | Runs ZED SDK + YOLO simultaneously |
| **USB 3.0 Cable** | High quality, ≤3 m | ZED 2i requires USB 3.0 bandwidth |
| **Mount** | Tripod or suction cup | Stationary tests first, car mount later |
| ~~GPS RTK Receiver~~ | — | **Not needed for prototype** |

---

## Software Stack (Prototype)

| Layer | Technology | Version |
|---|---|---|
| **GPU Driver** | NVIDIA R560+ | For Blackwell / compute 12.0 |
| **CUDA** | 12.x | Matches RTX 5060 |
| **ZED SDK** | 5.x+ | Must support Blackwell |
| **pyzed** | Matching SDK version | `python get_python_api.py` |
| **Ultralytics** | Latest (YOLOv8/v11) | Training + ONNX export |
| **TensorRT** | 10.x+ | Optimised inference |
| **OpenCV** | 4.x | Visualisation |
| ~~pyserial~~ | — | **Not needed — no GPS** |
| ~~pynmea2~~ | — | **Not needed — no NMEA** |

---

## Prototype Milestones

### P1 — Environment Setup & Basic Capture (3–4 days)

**Goal**: ZED 2i streaming on RTX 5060, verify depth + IMU.

- [ ] Install NVIDIA driver R560+, CUDA 12.x
- [ ] Install ZED SDK 5.x
- [ ] Install pyzed (`python get_python_api.py`)
- [ ] Verify camera is recognised (`ZED_Diagnostic` tool)
- [ ] Run basic capture:

```python
import pyzed.sl as sl

zed = sl.Camera()
init = sl.InitParameters()
init.camera_resolution = sl.RESOLUTION.HD720
init.camera_fps = 30
init.depth_mode = sl.DEPTH_MODE.NEURAL        # Best quality depth
init.coordinate_units = sl.UNIT.METER

err = zed.open(init)
assert err == sl.ERROR_CODE.SUCCESS, f"Camera open failed: {err}"

image = sl.Mat()
depth = sl.Mat()

while True:
    if zed.grab() == sl.ERROR_CODE.SUCCESS:
        zed.retrieve_image(image, sl.VIEW.LEFT)
        zed.retrieve_measure(depth, sl.MEASURE.DEPTH)
        frame = image.get_data()      # numpy HxWx4 (BGRA)
        depth_map = depth.get_data()  # numpy HxW   (float32, meters)
```

- [ ] Record an SVO2 file for offline development:

```python
rec_param = sl.RecordingParameters()
rec_param.video_filename = "test_capture.svo2"
rec_param.compression_mode = sl.SVO_COMPRESSION_MODE.H265
zed.enable_recording(rec_param)
# ... grab loop ... then:
zed.disable_recording()
```

- [ ] Point at an object at a known distance, read depth — verify ±10 cm at 5 m

**Deliverable**: Working capture, SVO2 recordings, confirmed depth accuracy.

---

### P2 — VIO Positional Tracking (1–2 days)

**Goal**: Enable VIO so we know the camera's pose (position + orientation) in a local coordinate frame — no GPS required.

- [ ] Enable positional tracking:

```python
tracking_params = sl.PositionalTrackingParameters()
tracking_params.enable_imu_fusion = True      # fuse IMU + stereo
tracking_params.set_as_static = False          # camera will move
zed.enable_positional_tracking(tracking_params)
```

- [ ] Read camera pose each frame:

```python
camera_pose = sl.Pose()

if zed.grab() == sl.ERROR_CODE.SUCCESS:
    state = zed.get_position(camera_pose, sl.REFERENCE_FRAME.WORLD)
    
    if state == sl.POSITIONAL_TRACKING_STATE.OK:
        translation = camera_pose.get_translation(sl.Translation())
        rotation    = camera_pose.get_orientation(sl.Orientation())
        
        x, y, z = translation.get()  # meters from start position
        print(f"Camera at: x={x:.2f}, y={y:.2f}, z={z:.2f}")
```

- [ ] Walk the camera ~10 m, verify the translation tracks roughly correctly
- [ ] Test on an SVO2 file — confirm tracking works in offline replay

**Deliverable**: Local 3D camera poses working; we can locate ourselves without GPS.

> [!TIP]
> VIO will drift over long distances (~1–2% of distance travelled). This is fine for a prototype — RTK GPS corrects drift in the full system.

---

### P3 — YOLO Sign Detection Model (3–5 days)

**Goal**: Train or use a pre-trained YOLO model that detects street signs.

#### Option A — Use an existing model (fastest for prototype)

- [ ] Download a traffic-sign dataset from [Roboflow Universe](https://universe.roboflow.com/search?q=traffic%20sign) in YOLO format
- [ ] Fine-tune YOLOv8m or YOLOv11m:

```python
from ultralytics import YOLO

model = YOLO('yolov8m.pt')
results = model.train(
    data='traffic_signs.yaml',
    epochs=50,           # fewer epochs for prototype
    imgsz=640,
    batch=16,
    device=0,
    project='sign_detector',
    name='proto_v1'
)
```

#### Option B — Use pretrained COCO model (quickest sanity check)

- [ ] YOLOv8's COCO weights already detect `stop sign` (class 11). Use this as a zero-effort sanity check before training a custom model.

```python
model = YOLO('yolov8m.pt')
results = model.predict('test_frame.jpg', conf=0.5)
```

- [ ] Export chosen model to ONNX:

```python
model.export(format='onnx', imgsz=640, half=True)
```

- [ ] Verify inference on sample frames — target ≥ 15 FPS on RTX 5060

**Deliverable**: YOLO `.onnx` model detecting signs in driving footage.

---

### P4 — Integration: Detection + 3D Localisation (3–4 days)

**Goal**: Combine YOLO + ZED depth + VIO to produce 3D positions of detected signs in the local coordinate frame.

- [ ] Configure ZED Custom Object Detection with the YOLO ONNX model:

```python
obj_params = sl.ObjectDetectionParameters()
obj_params.detection_model = sl.OBJECT_DETECTION_MODEL.CUSTOM_YOLOLIKE_BOX_OBJECTS
obj_params.custom_onnx_file = "sign_detector/proto_v1/best.onnx"
obj_params.custom_onnx_dynamic_input_shape = sl.Resolution(640, 640)
obj_params.enable_tracking = True   # track signs across frames

zed.enable_object_detection(obj_params)
```

- [ ] Retrieve detected signs with 3D positions:

```python
objects = sl.Objects()
obj_runtime = sl.ObjectDetectionRuntimeParameters()
obj_runtime.detection_confidence_threshold = 0.5

detections = []   # accumulate across frames

while True:
    if zed.grab() == sl.ERROR_CODE.SUCCESS:
        zed.retrieve_objects(objects, obj_runtime)
        
        # Get current camera pose for reference
        zed.get_position(camera_pose, sl.REFERENCE_FRAME.WORLD)
        cam_x, cam_y, cam_z = camera_pose.get_translation(sl.Translation()).get()
        
        for obj in objects.object_list:
            label   = obj.raw_label        # class ID
            conf    = obj.confidence       # 0–100
            pos3d   = obj.position         # [x, y, z] meters, camera frame
            obj_id  = obj.id               # tracking ID across frames
            
            # pos3d is in the WORLD reference frame when tracking is on
            print(f"[ID {obj_id}] Sign class={label}, "
                  f"pos=({pos3d[0]:.2f}, {pos3d[1]:.2f}, {pos3d[2]:.2f}), "
                  f"conf={conf:.0f}%")
            
            detections.append({
                "track_id":   obj_id,
                "class_id":   label,
                "confidence": conf,
                "x": pos3d[0], "y": pos3d[1], "z": pos3d[2],
                "cam_x": cam_x, "cam_y": cam_y, "cam_z": cam_z,
                "timestamp":  zed.get_timestamp(sl.TIME_REFERENCE.IMAGE).get_milliseconds()
            })
```

- [ ] Basic de-duplication — group by `track_id`, average positions:

```python
import json
from collections import defaultdict

grouped = defaultdict(list)
for d in detections:
    grouped[d["track_id"]].append(d)

sign_map = []
for track_id, obs in grouped.items():
    avg_x = sum(o["x"] for o in obs) / len(obs)
    avg_y = sum(o["y"] for o in obs) / len(obs)
    avg_z = sum(o["z"] for o in obs) / len(obs)
    best  = max(obs, key=lambda o: o["confidence"])
    
    sign_map.append({
        "track_id":    track_id,
        "class_id":    best["class_id"],
        "position_m":  {"x": round(avg_x, 3), "y": round(avg_y, 3), "z": round(avg_z, 3)},
        "confidence":  round(best["confidence"], 1),
        "observations": len(obs),
        "first_seen_ms": obs[0]["timestamp"],
        "last_seen_ms":  obs[-1]["timestamp"]
    })

with open("output/sign_map_local.json", "w") as f:
    json.dump(sign_map, f, indent=2)
```

- [ ] Verify: place a sign at a known location (e.g., 5 m away, 2 m to the right). Compare detected 3D position against measured position.

**Deliverable**: JSON file with 3D sign positions in local coordinates, verified against physical measurements.

---

### P5 — Visualisation & Validation (2–3 days)

**Goal**: See it working — live bounding boxes + 3D overlay + local map.

- [ ] Live OpenCV display:

```python
import cv2
import numpy as np

while True:
    if zed.grab() == sl.ERROR_CODE.SUCCESS:
        zed.retrieve_image(image, sl.VIEW.LEFT)
        zed.retrieve_objects(objects, obj_runtime)
        
        frame = image.get_data()[:, :, :3].copy()  # BGRA → BGR
        
        for obj in objects.object_list:
            bbox = obj.bounding_box_2d          # 4 corners
            tl = (int(bbox[0][0]), int(bbox[0][1]))
            br = (int(bbox[2][0]), int(bbox[2][1]))
            
            cv2.rectangle(frame, tl, br, (0, 255, 0), 2)
            
            pos = obj.position
            text = f"cls={obj.raw_label} d={pos[2]:.1f}m c={obj.confidence:.0f}%"
            cv2.putText(frame, text, (tl[0], tl[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        cv2.imshow("ZED Sign Prototype", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
```

- [ ] Simple top-down plot of sign positions using matplotlib:

```python
import matplotlib.pyplot as plt

xs = [s["position_m"]["x"] for s in sign_map]
zs = [s["position_m"]["z"] for s in sign_map]

plt.figure(figsize=(10, 10))
plt.scatter(xs, zs, c='red', s=100, marker='^', label='Signs')
plt.xlabel("X (meters)")
plt.ylabel("Z (meters, forward)")
plt.title("Detected Signs — Local Coordinate Map")
plt.legend()
plt.grid(True)
plt.savefig("output/sign_map_local.png")
plt.show()
```

- [ ] Ground-truth validation: measure known sign positions, compare with detected positions, compute error

**Deliverable**: Live visualisation, local sign map plot, accuracy measurements.

---

## Prototype Data Flow (One Frame)

```
1. zed.grab()                        → stereo frame + depth + IMU
2. VIO tracking                      → camera pose in local XYZ (meters from start)
3. YOLO inference on left image      → 2D bounding boxes of signs
4. ZED SDK maps 2D boxes → depth     → 3D position (x, y, z) per sign in WORLD frame
5. Track signs across frames (by ID) → de-duplicate same physical sign
6. Average position over observations → refined sign position
7. Output JSON + visualisation       → verify results
```

> [!IMPORTANT]
> **Key difference from full pipeline**: Steps 2–4 produce positions in a **local** coordinate frame (meters from start), not lat/lng. This is perfectly fine for proving the pipeline works. Adding RTK GPS later converts these local positions to global coordinates.

---

## Success Criteria

| Criterion | Target |
|---|---|
| Camera capture + depth works | ✅ Verified at known distances |
| VIO tracking produces stable poses | Translation tracks within ~5% over 50 m |
| YOLO detects signs in driving footage | mAP@0.5 > 0.7 on test set |
| 3D positions match physical measurements | Within 0.5 m at 10 m range |
| Pipeline runs at ≥ 10 FPS | End-to-end on RTX 5060 |
| JSON output contains all detected signs | With position, class, confidence |

---

## What Comes After the Prototype

Once this prototype validates the core pipeline, layer on the full roadmap items:

1. **RTK GPS receiver** → hardware + NMEA parsing (Phase 2 of full roadmap)
2. **Fusion module** → `sl.Fusion` + `ingest_gnss_data()` → global camera poses
3. **`camera_to_geo()`** → convert local 3D positions to lat/lng
4. **GeoJSON output** → globally referenced sign map
5. **Accuracy hardening** → lever-arm calibration, timestamp sync, Kalman filtering

---

## Estimated Timeline

| Milestone | Duration | Cumulative |
|---|---|---|
| P1 — Setup & Capture | 3–4 days | ~4 days |
| P2 — VIO Tracking | 1–2 days | ~6 days |
| P3 — YOLO Model | 3–5 days | ~11 days |
| P4 — Integration | 3–4 days | ~15 days |
| P5 — Visualisation | 2–3 days | ~18 days |
| **Total** | | **~2.5–3 weeks** |

---

## Key API Reference (Prototype Subset)

| Function | Purpose |
|---|---|
| `zed.grab()` | Capture stereo frame + depth |
| `zed.retrieve_image()` | Get left/right camera image |
| `zed.retrieve_measure(DEPTH)` | Get depth map |
| `zed.enable_positional_tracking()` | Start VIO tracking (local pose) |
| `zed.get_position()` | Get camera pose in WORLD frame |
| `zed.enable_object_detection()` | Start YOLO-based detection |
| `zed.retrieve_objects()` | Get detected objects with 3D positions |
| `zed.enable_recording()` | Record to SVO2 for offline replay |
| ~~`fusion.ingest_gnss_data()`~~ | *Not used in prototype* |
| ~~`fusion.camera_to_geo()`~~ | *Not used in prototype* |

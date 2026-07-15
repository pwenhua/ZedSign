# ZED 2i Street Sign Geolocation Roadmap

> **Goal**: Mount a ZED 2i stereo camera + GPS RTK on a car, capture driving video, detect street signs with AI, and calculate each sign's real-world latitude/longitude.

---

## System Architecture Overview

```
┌─────────────┐    USB 3.0    ┌──────────────────────────────────┐
│  ZED 2i     │──────────────▶│  PC (RTX 5060)                   │
│  Camera     │               │                                  │
│  (stereo +  │               │  ┌────────────┐  ┌────────────┐  │
│   IMU)      │               │  │ ZED SDK    │  │ YOLO Sign  │  │
│             │               │  │ (depth,    │  │ Detector   │  │
└─────────────┘               │  │  tracking, │  │ (TensorRT) │  │
                              │  │  fusion)   │  └──────┬─────┘  │
┌─────────────┐   Serial/USB  │  └─────┬──────┘         │        │
│  GPS RTK    │──────────────▶│        │          2D bbox│        │
│  Receiver   │  (NMEA data)  │        │                 │        │
│  (e.g.      │               │  ┌─────▼─────────────────▼─────┐ │
│  SparkFun   │               │  │  Fusion Module               │ │
│  u-blox)    │               │  │  • VIO + GNSS fusion         │ │
└─────────────┘               │  │  • 2D → 3D via depth map     │ │
                              │  │  • camera_to_geo() → lat/lng │ │
                              │  └─────────────┬───────────────┘ │
                              │                │                  │
                              │  ┌─────────────▼───────────────┐ │
                              │  │  Output: Sign GeoJSON        │ │
                              │  │  { type, lat, lng, class,    │ │
                              │  │    confidence, timestamp }   │ │
                              │  └─────────────────────────────┘ │
                              └──────────────────────────────────┘
```

---

## Hardware Checklist

| Component | Spec | Notes |
|---|---|---|
| **ZED 2i** | Stereo + IMU, IP65 rated | Built-in IMU is critical for VIO; IP65 means outdoor-ready |
| **GPS RTK Receiver** | u-blox F9P or similar | Must output NMEA sentences (GGA/RMC) at ≥5 Hz; RTK gives ~2 cm accuracy |
| **RTX 5060** | Blackwell, CUDA 12.0, 8 GB VRAM | Exceeds ZED SDK min (compute 7.5); runs TensorRT + ZED simultaneously |
| **USB 3.0 Cable** | High quality, ≤3 m | ZED 2i requires USB 3.0 bandwidth for stereo + depth |
| **Car Mount** | Suction cup or roof bar | Camera should face forward, GPS antenna on roof with clear sky view |
| **Power** | DC-AC inverter or laptop battery | PC must stay powered during driving |

---

## Software Stack

| Layer | Technology | Version Notes |
|---|---|---|
| **GPU Driver** | NVIDIA R560+ | Required for Blackwell / compute 12.0 |
| **CUDA** | 12.x | Matches RTX 5060 architecture |
| **ZED SDK** | 5.x+ | Must support Blackwell GPUs |
| **pyzed** | Matching SDK version | Install via `get_python_api.py` in SDK folder |
| **TensorRT** | 10.x+ | For optimized YOLO inference on Blackwell |
| **Ultralytics** | Latest (YOLOv8/v11) | Training + export to ONNX → TensorRT |
| **Python** | 3.10–3.12 | Compatibility with pyzed + ultralytics |
| **OpenCV** | 4.x | Frame manipulation and visualization |
| **pyserial** | Latest | Reading NMEA from RTK receiver |

---

## Milestone Roadmap

### Phase 1 — Environment Setup & Basic Capture (Week 1–2)

**Goal**: Get ZED 2i streaming on the RTX 5060 PC, verify depth + IMU.

- [ ] Install NVIDIA driver R560+, CUDA 12.x
- [ ] Install ZED SDK 5.x (run the installer from stereolabs.com)
- [ ] Install pyzed Python API (`python get_python_api.py` from SDK folder)
- [ ] Run ZED SDK diagnostic tools — verify camera is recognized
- [ ] Write basic capture script:

```python
import pyzed.sl as sl

zed = sl.Camera()
init = sl.InitParameters()
init.camera_resolution = sl.RESOLUTION.HD720
init.camera_fps = 30
init.depth_mode = sl.DEPTH_MODE.NEURAL  # Best quality depth
init.coordinate_units = sl.UNIT.METER

err = zed.open(init)
assert err == sl.ERROR_CODE.SUCCESS, f"Camera open failed: {err}"

image = sl.Mat()
depth = sl.Mat()

while True:
    if zed.grab() == sl.ERROR_CODE.SUCCESS:
        zed.retrieve_image(image, sl.VIEW.LEFT)
        zed.retrieve_measure(depth, sl.MEASURE.DEPTH)
        # image.get_data() → numpy array for OpenCV
```

- [ ] Record a test SVO2 file for offline development:

```python
rec_param = sl.RecordingParameters()
rec_param.video_filename = "test_drive.svo2"
rec_param.compression_mode = sl.SVO_COMPRESSION_MODE.H265
zed.enable_recording(rec_param)
```

- [ ] Verify depth quality — point at objects at known distances

**Deliverable**: Working capture pipeline, SVO2 test recordings.

---

### Phase 2 — GPS RTK Integration & Sensor Fusion (Week 2–3)

**Goal**: Ingest RTK NMEA data into ZED SDK, get globally-referenced camera poses.

- [ ] Connect RTK receiver via USB/Serial
- [ ] Write NMEA parser (or use `pynmea2` library) to read GGA sentences:

```python
import serial
import pynmea2

ser = serial.Serial('COM3', 115200, timeout=1)  # Adjust COM port

def read_gnss():
    line = ser.readline().decode('ascii', errors='replace').strip()
    if line.startswith('$GNGGA') or line.startswith('$GPGGA'):
        msg = pynmea2.parse(line)
        return msg.latitude, msg.longitude, msg.altitude, msg.gps_qual
    return None
```

- [ ] Enable ZED Positional Tracking:

```python
tracking_params = sl.PositionalTrackingParameters()
tracking_params.enable_imu_fusion = True
zed.enable_positional_tracking(tracking_params)
```

- [ ] Set up Fusion module and ingest GNSS data:

```python
fusion = sl.Fusion()
fusion_params = sl.InitFusionParameters()
fusion.init(fusion_params)

# Subscribe the camera
fusion.subscribe(sl.CameraIdentifier(0), ...)

# Ingest GNSS data each frame
gnss_data = sl.GNSSData()
gnss_data.set_coordinates(lat, lng, alt, sl.COORDINATE_SYSTEM.IMAGE)
gnss_data.ts = sl.Timestamp()  # sync with camera timestamp
fusion.ingest_gnss_data(gnss_data)
```

- [ ] Test `camera_to_geo()` — point camera at a known landmark, verify lat/lng:

```python
pose = sl.Pose()
geopose = sl.GeoPose()

# Get current camera pose
zed.get_position(pose)

# Convert to global coordinates
status = fusion.camera_to_geo(pose, geopose)
if status == sl.GNSS_FUSION_STATUS.OK:
    lat, lng, alt = geopose.latlng_coordinates.get_coordinates(False)
    print(f"Camera at: {lat:.7f}, {lng:.7f}, alt={alt:.2f}m")
```

- [ ] Record GNSS-tagged SVO2 for offline replays

**Deliverable**: Camera poses with global lat/lng, verified against known GPS ground truth.

> [!IMPORTANT]
> **Calibration is critical.** You must measure the physical offset (lever arm) between the GPS antenna and the ZED 2i camera, and configure it in the Fusion module. Even a 30 cm error here propagates directly to sign positions.

---

### Phase 3 — Street Sign Detection Model (Week 3–5)

**Goal**: Train a YOLO model to detect street signs with high accuracy.

#### 3a. Dataset Preparation

- [ ] Select and download training datasets:

| Dataset | Signs | Format | Use Case |
|---|---|---|---|
| **TT100K** | 221 categories, 16K images | Custom → convert to YOLO | Best overall diversity |
| **LISA** | US signs (Stop, Speed Limit, etc.) | YOLO-ready on Roboflow | Best for American roads |
| **GTSRB** | 43 German sign classes | Available on Roboflow | Good benchmark baseline |
| **Mapillary Traffic Sign** | 400+ categories | Custom | Highest diversity, global |
| **Custom Collection** | Your local signs | Manual + CVAT/Roboflow | Essential for AU/local signs |

- [ ] If Australian road signs needed, collect and annotate ~500–1000 images using [CVAT](https://www.cvat.ai/) or [Roboflow](https://roboflow.com/)
- [ ] Merge datasets, normalize to YOLO format (`class cx cy w h`)
- [ ] Split: 80% train / 10% val / 10% test
- [ ] Apply data augmentation (brightness, blur, rotation, weather overlays)

#### 3b. Model Training

- [ ] Install ultralytics: `pip install ultralytics`
- [ ] Train YOLOv8m or YOLOv11m (medium — good balance for RTX 5060):

```python
from ultralytics import YOLO

model = YOLO('yolov8m.pt')  # or yolo11m.pt
results = model.train(
    data='traffic_signs.yaml',
    epochs=100,
    imgsz=640,
    batch=16,
    device=0,
    project='sign_detector',
    name='v1'
)
```

- [ ] Evaluate on test set — target mAP@0.5 > 0.85
- [ ] Export to ONNX for ZED SDK integration:

```python
model.export(format='onnx', imgsz=640, half=True)
```

#### 3c. Inference Test

- [ ] Run inference on sample driving footage
- [ ] Verify detection of: Speed Limit, Stop, Give Way, street name plates, etc.
- [ ] Measure FPS — target ≥ 15 FPS on RTX 5060 alongside ZED SDK

**Deliverable**: Trained YOLO model (.onnx), validated on driving footage.

---

### Phase 4 — Integration: Detection + 3D Localization (Week 5–7)

**Goal**: Combine YOLO detection with ZED depth to get 3D positions of signs.

- [ ] Use ZED SDK Custom Object Detection pipeline:

```python
# Configure object detection with custom model
obj_params = sl.ObjectDetectionParameters()
obj_params.detection_model = sl.OBJECT_DETECTION_MODEL.CUSTOM_YOLOLIKE_BOX_OBJECTS
obj_params.custom_onnx_file = "sign_detector/v1/best.onnx"
obj_params.custom_onnx_dynamic_input_shape = sl.Resolution(640, 640)
obj_params.enable_tracking = True  # Track signs across frames

zed.enable_object_detection(obj_params)
```

- [ ] Retrieve detected objects with 3D positions:

```python
objects = sl.Objects()
obj_runtime = sl.ObjectDetectionRuntimeParameters()
obj_runtime.detection_confidence_threshold = 0.5

while True:
    if zed.grab() == sl.ERROR_CODE.SUCCESS:
        zed.retrieve_objects(objects, obj_runtime)
        
        for obj in objects.object_list:
            label = obj.raw_label       # Sign class ID
            conf  = obj.confidence      # Detection confidence
            pos3d = obj.position        # [x, y, z] in meters (camera frame)
            
            # Convert 3D camera-frame position to GeoPose
            obj_pose = sl.Pose()
            obj_pose.set_translation(sl.Translation(pos3d[0], pos3d[1], pos3d[2]))
            
            geo = sl.GeoPose()
            status = fusion.camera_to_geo(obj_pose, geo)
            
            if status == sl.GNSS_FUSION_STATUS.OK:
                lat, lng, alt = geo.latlng_coordinates.get_coordinates(False)
                print(f"Sign '{label}' at ({lat:.7f}, {lng:.7f}), alt={alt:.1f}m, conf={conf:.0f}%")
```

- [ ] Implement de-duplication: same physical sign seen across multiple frames
  - Track by ZED object ID
  - Average position over multiple observations to improve accuracy
  - Store "first seen" and "last seen" timestamps

- [ ] Output results as GeoJSON:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [151.2093, -33.8688]
      },
      "properties": {
        "sign_class": "speed_limit_60",
        "confidence": 0.94,
        "observations": 12,
        "first_seen": "2026-07-15T10:23:45Z",
        "altitude_m": 42.3
      }
    }
  ]
}
```

**Deliverable**: End-to-end pipeline producing geo-tagged sign detections.

---

### Phase 5 — Accuracy Improvement & Multi-Frame Fusion (Week 7–9)

**Goal**: Improve geolocation accuracy from ~1–2 m to sub-meter.

- [ ] **Multi-frame position averaging**: Weighted average by confidence and distance
- [ ] **Kalman filter** on sign positions observed across frames
- [ ] **Depth quality filtering**: Reject signs with depth > 25 m (stereo degrades)
- [ ] **RTK fix quality check**: Only use GPS readings with RTK Fix status (quality = 4)
- [ ] **Lever arm calibration**: Precisely measure GPS antenna ↔ camera offset
- [ ] **Timestamp synchronization**: Align RTK timestamps with ZED frame timestamps (critical!)
- [ ] **Point cloud validation**: Use ZED point cloud to verify sign surface geometry

**Expected accuracy budget**:

| Source | Error |
|---|---|
| RTK GPS | ~2 cm |
| ZED stereo depth (at 10 m) | ~5–15 cm |
| Lever arm calibration | ~5 cm |
| Timestamp sync | ~5–10 cm at 50 km/h |
| **Total (RSS)** | **~20–40 cm** |

---

### Phase 6 — Real-Time Dashboard & Output (Week 9–10)

**Goal**: Visualize results in real-time during driving.

- [ ] Live OpenCV window showing:
  - Left camera feed with bounding boxes
  - Sign class labels + confidence
  - GPS coordinates overlay
  - Minimap with sign positions (using folium or matplotlib)
- [ ] Log all detections to CSV/GeoJSON in real-time
- [ ] Optional: push to web dashboard (Flask + Leaflet.js)
- [ ] Post-processing script to load GeoJSON into QGIS or Google Earth

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| RTK signal loss in urban canyons | Signs get wrong GPS | Fall back to VIO; flag low-confidence positions |
| YOLO misclassifies signs | Wrong data in output | High confidence threshold; manual review pass |
| Depth inaccurate at long range | Position error > 1 m | Filter signs > 20 m; prefer closer observations |
| USB bandwidth issues | Frame drops | Use HD720 instead of HD1080; quality USB 3.0 cable |
| TensorRT/Blackwell compatibility | Model won't load | Use latest TensorRT 10.x; test before field work |
| Vibration on car | Blurry frames | Use camera's built-in IMU; mount with vibration dampers |
| Power loss while driving | Lost recordings | UPS/battery backup; auto-save SVO2 periodically |

---

## Key API Reference

| Function | Purpose |
|---|---|
| `zed.grab()` | Capture a stereo frame + depth |
| `zed.retrieve_image()` | Get left/right camera image |
| `zed.retrieve_measure(DEPTH)` | Get depth map |
| `zed.enable_positional_tracking()` | Start VIO tracking |
| `zed.enable_object_detection()` | Start YOLO-based detection |
| `zed.retrieve_objects()` | Get detected objects with 3D positions |
| `zed.enable_recording()` | Record to SVO2 for offline replay |
| `fusion.ingest_gnss_data()` | Feed RTK readings into fusion |
| `fusion.camera_to_geo()` | Convert camera-frame XYZ → lat/lng/alt |

---

## Resources

- [ZED SDK Documentation](https://www.stereolabs.com/docs/)
- [ZED SDK GitHub Samples](https://github.com/stereolabs/zed-sdk) — esp. `global_localization/` and `object detection/`
- [ZED + YOLO Integration](https://github.com/stereolabs/zed-yolo) — YOLOv8–v12 samples
- [Ultralytics YOLOv8 Docs](https://docs.ultralytics.com/)
- [Roboflow Universe - Traffic Signs](https://universe.roboflow.com/search?q=traffic%20sign)
- [Stereolabs Community Forum](https://community.stereolabs.com/)
- [pynmea2 - NMEA Parser](https://github.com/Knio/pynmea2)

---

## Summary: Data Flow in One Frame

```
1. zed.grab()                          → stereo frame + depth + IMU
2. GPS RTK serial read                 → NMEA GGA sentence (lat, lng, alt)
3. fusion.ingest_gnss_data()           → fuse VIO + GNSS → global camera pose
4. YOLO inference on left image        → 2D bounding boxes of signs
5. ZED SDK maps 2D boxes → depth map   → 3D position (x, y, z) per sign
6. fusion.camera_to_geo(sign_pose)     → sign latitude, longitude, altitude
7. De-duplicate & average across frames → refined sign position
8. Output GeoJSON / CSV / dashboard    → final deliverable
```

**Timeline**: ~10 weeks from setup to field-validated system.

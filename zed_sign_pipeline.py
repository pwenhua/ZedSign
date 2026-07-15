"""
ZED 2i Street Sign Geolocation — Main Pipeline
=================================================
Phase 4: Full integration of ZED camera + GPS RTK + YOLO sign detection.

This is the main entry point that combines:
  1. ZED 2i stereo capture + depth
  2. GPS RTK fusion for global positioning
  3. YOLO street sign detection (custom ONNX model)
  4. 3D localization of signs via depth map
  5. camera_to_geo() conversion to latitude/longitude
  6. De-duplication across frames
  7. GeoJSON output

Usage:
    python zed_sign_pipeline.py                    # Live camera mode
    python zed_sign_pipeline.py --svo test.svo2    # Replay from SVO2 file
    python zed_sign_pipeline.py --no-display       # Headless mode

Requirements:
    - ZED SDK 5.x with pyzed
    - Custom YOLO sign detection model (ONNX)
    - GPS RTK receiver (for live mode)
"""

import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import math

try:
    import pyzed.sl as sl
except ImportError:
    print("ERROR: pyzed not found. Install via ZED SDK get_python_api.py")
    sys.exit(1)

try:
    import cv2
    import numpy as np
except ImportError:
    print("ERROR: opencv-python and numpy required. pip install opencv-python numpy")
    sys.exit(1)

from gnss_reader import GNSSReader, GNSSFix

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("output/session.log", mode="a")
    ]
)
log = logging.getLogger("sign_pipeline")


# ============================================================
# Data Structures
# ============================================================

@dataclass
class SignDetection:
    """A single detection of a street sign in one frame."""
    sign_class: str
    class_id: int
    confidence: float
    bbox_2d: tuple  # (x1, y1, x2, y2) in pixels
    position_3d: tuple  # (x, y, z) in meters, camera frame
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    has_geo: bool = False
    frame_id: int = 0
    timestamp: str = ""
    tracking_id: int = -1


@dataclass
class TrackedSign:
    """A physical sign tracked across multiple frames."""
    sign_id: int
    sign_class: str
    observations: List[SignDetection] = field(default_factory=list)
    avg_latitude: float = 0.0
    avg_longitude: float = 0.0
    avg_altitude: float = 0.0
    total_confidence: float = 0.0

    def add_observation(self, det: SignDetection):
        """Add a new observation and update weighted average position."""
        self.observations.append(det)
        if det.has_geo:
            self._update_average()

    def _update_average(self):
        """Weighted average of positions by confidence."""
        geo_obs = [o for o in self.observations if o.has_geo]
        if not geo_obs:
            return

        total_weight = sum(o.confidence for o in geo_obs)
        if total_weight == 0:
            return

        self.avg_latitude = sum(o.latitude * o.confidence for o in geo_obs) / total_weight
        self.avg_longitude = sum(o.longitude * o.confidence for o in geo_obs) / total_weight
        self.avg_altitude = sum(o.altitude * o.confidence for o in geo_obs) / total_weight
        self.total_confidence = max(o.confidence for o in geo_obs)

    @property
    def num_observations(self) -> int:
        return len(self.observations)

    def to_geojson_feature(self) -> dict:
        """Convert to a GeoJSON Feature."""
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.avg_longitude, self.avg_latitude, self.avg_altitude]
            },
            "properties": {
                "sign_id": self.sign_id,
                "sign_class": self.sign_class,
                "confidence": round(self.total_confidence, 3),
                "observations": self.num_observations,
                "first_seen": self.observations[0].timestamp if self.observations else "",
                "last_seen": self.observations[-1].timestamp if self.observations else "",
                "altitude_m": round(self.avg_altitude, 2)
            }
        }


# ============================================================
# Sign De-duplication Manager
# ============================================================

class SignManager:
    """Manages detected signs, de-duplicates across frames."""

    def __init__(self, distance_threshold_m: float = 3.0, min_observations: int = 3):
        self.signs: Dict[int, TrackedSign] = {}
        self.distance_threshold = distance_threshold_m
        self.min_observations = min_observations
        self._next_id = 0

    def add_detection(self, det: SignDetection) -> int:
        """
        Add a detection. If a matching sign exists nearby, merge.
        Otherwise, create a new tracked sign.
        Returns the sign_id.
        """
        # If ZED SDK gave us a tracking ID, use it for matching
        if det.tracking_id >= 0 and det.tracking_id in self.signs:
            self.signs[det.tracking_id].add_observation(det)
            return det.tracking_id

        # Otherwise, find nearest existing sign of the same class
        if det.has_geo:
            for sid, sign in self.signs.items():
                if sign.sign_class != det.sign_class:
                    continue
                if sign.avg_latitude == 0:
                    continue
                dist = self._haversine_m(
                    det.latitude, det.longitude,
                    sign.avg_latitude, sign.avg_longitude
                )
                if dist < self.distance_threshold:
                    sign.add_observation(det)
                    return sid

        # Create new tracked sign
        sign_id = det.tracking_id if det.tracking_id >= 0 else self._next_id
        self._next_id = max(self._next_id, sign_id + 1)

        new_sign = TrackedSign(sign_id=sign_id, sign_class=det.sign_class)
        new_sign.add_observation(det)
        self.signs[sign_id] = new_sign
        return sign_id

    def get_confirmed_signs(self) -> List[TrackedSign]:
        """Return signs with enough observations to be considered real."""
        return [s for s in self.signs.values()
                if s.num_observations >= self.min_observations and s.avg_latitude != 0]

    def to_geojson(self) -> dict:
        """Export all confirmed signs as GeoJSON FeatureCollection."""
        confirmed = self.get_confirmed_signs()
        return {
            "type": "FeatureCollection",
            "properties": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_signs": len(confirmed),
                "min_observations": self.min_observations
            },
            "features": [s.to_geojson_feature() for s in confirmed]
        }

    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2) -> float:
        """Calculate distance in meters between two lat/lng points."""
        R = 6371000  # Earth radius in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = (math.sin(dphi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ============================================================
# Main Pipeline
# ============================================================

def load_config(path: str = "zed_sign_config.json") -> dict:
    with open(path, "r") as f:
        return json.load(f)


def init_camera(config: dict, svo_path: Optional[str] = None) -> sl.Camera:
    """Initialize the ZED camera (live or SVO2 replay)."""
    zed = sl.Camera()
    init_params = sl.InitParameters()

    cam_cfg = config["zed_camera"]

    if svo_path:
        init_params.set_from_svo_file(svo_path)
        log.info(f"Replaying from SVO2: {svo_path}")
    else:
        res_map = {
            "HD2K": sl.RESOLUTION.HD2K, "HD1080": sl.RESOLUTION.HD1080,
            "HD720": sl.RESOLUTION.HD720, "SVGA": sl.RESOLUTION.SVGA,
        }
        init_params.camera_resolution = res_map.get(cam_cfg["resolution"], sl.RESOLUTION.HD720)
        init_params.camera_fps = cam_cfg["fps"]

    depth_map = {
        "NEURAL": sl.DEPTH_MODE.NEURAL, "ULTRA": sl.DEPTH_MODE.ULTRA,
        "QUALITY": sl.DEPTH_MODE.QUALITY, "PERFORMANCE": sl.DEPTH_MODE.PERFORMANCE,
    }
    init_params.depth_mode = depth_map.get(cam_cfg["depth_mode"], sl.DEPTH_MODE.NEURAL)
    init_params.coordinate_units = sl.UNIT.METER
    init_params.coordinate_system = sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP
    init_params.depth_minimum_distance = 0.3

    err = zed.open(init_params)
    if err != sl.ERROR_CODE.SUCCESS:
        log.error(f"Failed to open camera: {err}")
        sys.exit(1)

    cam_info = zed.get_camera_information()
    log.info(f"Camera: {cam_info.camera_model} (SN: {cam_info.serial_number})")
    return zed


def init_tracking(zed: sl.Camera):
    """Enable positional tracking (VIO)."""
    tracking_params = sl.PositionalTrackingParameters()
    tracking_params.enable_imu_fusion = True
    err = zed.enable_positional_tracking(tracking_params)
    if err != sl.ERROR_CODE.SUCCESS:
        log.warning(f"Positional tracking failed: {err}")
    else:
        log.info("Positional tracking enabled (VIO + IMU)")


def init_object_detection(zed: sl.Camera, config: dict):
    """Enable custom YOLO-based object detection."""
    det_cfg = config["sign_detection"]
    model_path = det_cfg["model_path"]

    if not Path(model_path).exists():
        log.error(f"Model not found: {model_path}")
        log.error("Train a YOLO model first (see Phase 3 in roadmap)")
        return False

    obj_params = sl.ObjectDetectionParameters()
    obj_params.detection_model = sl.OBJECT_DETECTION_MODEL.CUSTOM_YOLOLIKE_BOX_OBJECTS
    obj_params.custom_onnx_file = model_path
    obj_params.custom_onnx_dynamic_input_shape = sl.Resolution(
        det_cfg["input_size"], det_cfg["input_size"]
    )
    obj_params.enable_tracking = det_cfg["enable_tracking"]

    err = zed.enable_object_detection(obj_params)
    if err != sl.ERROR_CODE.SUCCESS:
        log.error(f"Object detection failed to initialize: {err}")
        return False

    log.info(f"Object detection enabled with: {model_path}")
    return True


def init_fusion(config: dict) -> Optional[sl.Fusion]:
    """Initialize the Fusion module for GNSS integration."""
    try:
        fusion = sl.Fusion()
        fusion_params = sl.InitFusionParameters()
        err = fusion.init(fusion_params)
        if err != sl.FUSION_ERROR_CODE.SUCCESS:
            log.warning(f"Fusion init failed: {err}")
            return None
        log.info("Fusion module initialized for GNSS integration")
        return fusion
    except Exception as e:
        log.warning(f"Fusion not available: {e}")
        return None


def draw_detections(frame, detections: List[SignDetection], class_names: List[str]):
    """Draw bounding boxes and labels on the frame."""
    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det.bbox_2d]

        # Color based on geo availability
        color = (0, 255, 0) if det.has_geo else (0, 165, 255)  # Green if geo, orange if not

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Label
        label = f"{det.sign_class} {det.confidence:.0%}"
        if det.has_geo:
            label += f" ({det.latitude:.5f}, {det.longitude:.5f})"

        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        cv2.rectangle(frame, (x1, y1 - label_size[1] - 8), (x1 + label_size[0], y1), color, -1)
        cv2.putText(frame, label, (x1, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    return frame


def main():
    parser = argparse.ArgumentParser(description="ZED 2i Street Sign Geolocation Pipeline")
    parser.add_argument("--svo", type=str, default=None, help="SVO2 file for offline replay")
    parser.add_argument("--no-display", action="store_true", help="Headless mode")
    parser.add_argument("--config", type=str, default="zed_sign_config.json", help="Config file")
    parser.add_argument("--no-gnss", action="store_true", help="Skip GNSS reader")
    args = parser.parse_args()

    # --- Load Config ---
    config = load_config(args.config)
    det_cfg = config["sign_detection"]
    gnss_cfg = config["gnss"]
    output_cfg = config["output"]
    dedup_cfg = config["deduplication"]

    # Create output directories
    Path("output").mkdir(exist_ok=True)

    log.info("=" * 60)
    log.info("ZED 2i Street Sign Geolocation Pipeline")
    log.info("=" * 60)

    # --- Initialize Components ---
    zed = init_camera(config, args.svo)
    init_tracking(zed)

    # Object detection (may fail if model not trained yet)
    has_detection = init_object_detection(zed, config)

    # GNSS reader (skip for SVO replay without GPS, or if --no-gnss)
    gnss_reader = None
    if not args.no_gnss and not args.svo:
        gnss_reader = GNSSReader(
            port=gnss_cfg["serial_port"],
            baud_rate=gnss_cfg["baud_rate"]
        )
        if not gnss_reader.open():
            log.warning("GNSS reader failed to open — running without GPS")
            gnss_reader = None

    # Fusion module
    fusion = init_fusion(config)

    # Sign manager
    sign_manager = SignManager(
        distance_threshold_m=dedup_cfg["distance_threshold_m"],
        min_observations=dedup_cfg["min_observations"]
    )

    # --- Buffers ---
    image = sl.Mat()
    depth = sl.Mat()
    objects = sl.Objects()
    obj_runtime = sl.ObjectDetectionRuntimeParameters()
    obj_runtime.detection_confidence_threshold = det_cfg["confidence_threshold"]
    pose = sl.Pose()

    frame_count = 0
    detection_count = 0
    start_time = time.time()

    log.info("Pipeline running. Press 'q' to stop.\n")

    try:
        while True:
            # --- Grab Frame ---
            if zed.grab() != sl.ERROR_CODE.SUCCESS:
                if args.svo:
                    log.info("End of SVO2 file reached.")
                    break
                continue

            frame_count += 1
            now_str = datetime.now(timezone.utc).isoformat()

            # --- Read GNSS ---
            if gnss_reader:
                gnss_fix = gnss_reader.read_fix()
                if gnss_fix and gnss_fix.is_valid and fusion:
                    # Ingest GNSS data into fusion module
                    gnss_data = sl.GNSSData()
                    gnss_data.set_coordinates(
                        gnss_fix.latitude, gnss_fix.longitude, gnss_fix.altitude,
                        sl.COORDINATE_SYSTEM.IMAGE
                    )
                    fusion.ingest_gnss_data(gnss_data)

            # --- Get Camera Pose ---
            tracking_state = zed.get_position(pose, sl.REFERENCE_FRAME.WORLD)

            # --- Detect Signs ---
            frame_detections: List[SignDetection] = []

            if has_detection:
                zed.retrieve_objects(objects, obj_runtime)

                for obj in objects.object_list:
                    class_id = obj.raw_label
                    class_name = (det_cfg["classes"][class_id]
                                  if class_id < len(det_cfg["classes"])
                                  else f"class_{class_id}")

                    # Get 2D bounding box
                    bbox = obj.bounding_box_2d
                    if len(bbox) >= 4:
                        x1, y1 = int(bbox[0][0]), int(bbox[0][1])
                        x2, y2 = int(bbox[2][0]), int(bbox[2][1])
                    else:
                        continue

                    # Get 3D position
                    pos3d = obj.position  # [x, y, z] meters

                    # Check depth threshold
                    depth_val = math.sqrt(pos3d[0]**2 + pos3d[1]**2 + pos3d[2]**2)
                    if depth_val > det_cfg["max_depth_m"]:
                        continue  # Too far — unreliable depth

                    det = SignDetection(
                        sign_class=class_name,
                        class_id=class_id,
                        confidence=obj.confidence / 100.0,
                        bbox_2d=(x1, y1, x2, y2),
                        position_3d=(pos3d[0], pos3d[1], pos3d[2]),
                        frame_id=frame_count,
                        timestamp=now_str,
                        tracking_id=obj.id
                    )

                    # --- Convert to Geo Coordinates ---
                    if fusion:
                        obj_pose = sl.Pose()
                        obj_pose.set_translation(
                            sl.Translation(pos3d[0], pos3d[1], pos3d[2])
                        )
                        geopose = sl.GeoPose()
                        status = fusion.camera_to_geo(obj_pose, geopose)

                        if status == sl.GNSS_FUSION_STATUS.OK:
                            lat, lng, alt = geopose.latlng_coordinates.get_coordinates(False)
                            det.latitude = lat
                            det.longitude = lng
                            det.altitude = alt
                            det.has_geo = True

                    # Add to sign manager
                    sign_manager.add_detection(det)
                    frame_detections.append(det)
                    detection_count += 1

            # --- Display ---
            if not args.no_display:
                zed.retrieve_image(image, sl.VIEW.LEFT)
                frame = image.get_data()
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                # Draw detections
                if frame_detections:
                    frame_bgr = draw_detections(frame_bgr, frame_detections, det_cfg["classes"])

                # HUD overlay
                elapsed = time.time() - start_time
                fps = zed.get_current_fps()
                confirmed = len(sign_manager.get_confirmed_signs())

                cv2.putText(frame_bgr, f"Frame: {frame_count} | FPS: {fps:.1f}",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.putText(frame_bgr, f"Detections: {detection_count} | Confirmed signs: {confirmed}",
                            (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

                if gnss_reader and gnss_reader.last_fix.is_valid:
                    fix = gnss_reader.last_fix
                    cv2.putText(frame_bgr,
                                f"GPS: {fix.latitude:.6f}, {fix.longitude:.6f} [{fix.fix_type_str}]",
                                (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

                cv2.imshow("ZED 2i Sign Detection", frame_bgr)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            # --- Periodic logging ---
            if frame_count % 100 == 0:
                confirmed = sign_manager.get_confirmed_signs()
                log.info(f"Frame {frame_count} | "
                         f"Total detections: {detection_count} | "
                         f"Confirmed signs: {len(confirmed)}")

    except KeyboardInterrupt:
        log.info("Stopped by user.")

    finally:
        # --- Save Results ---
        geojson = sign_manager.to_geojson()
        geojson_path = output_cfg["geojson_path"]
        Path(geojson_path).parent.mkdir(parents=True, exist_ok=True)

        with open(geojson_path, "w") as f:
            json.dump(geojson, f, indent=2)

        confirmed = sign_manager.get_confirmed_signs()
        log.info(f"\n{'='*60}")
        log.info(f"Session Complete")
        log.info(f"  Total frames:     {frame_count}")
        log.info(f"  Total detections: {detection_count}")
        log.info(f"  Confirmed signs:  {len(confirmed)}")
        log.info(f"  GeoJSON saved:    {geojson_path}")
        log.info(f"{'='*60}")

        # Print confirmed signs
        if confirmed:
            log.info("\nConfirmed Street Signs:")
            log.info("-" * 80)
            for sign in confirmed:
                log.info(f"  [{sign.sign_id:3d}] {sign.sign_class:25s} | "
                         f"({sign.avg_latitude:.7f}, {sign.avg_longitude:.7f}) | "
                         f"obs: {sign.num_observations} | "
                         f"conf: {sign.total_confidence:.0%}")

        # Also save CSV
        csv_path = output_cfg["csv_path"]
        with open(csv_path, "w") as f:
            f.write("sign_id,sign_class,latitude,longitude,altitude,observations,confidence\n")
            for sign in confirmed:
                f.write(f"{sign.sign_id},{sign.sign_class},"
                        f"{sign.avg_latitude:.7f},{sign.avg_longitude:.7f},"
                        f"{sign.avg_altitude:.2f},{sign.num_observations},"
                        f"{sign.total_confidence:.3f}\n")
        log.info(f"  CSV saved: {csv_path}")

        # Cleanup
        zed.close()
        if gnss_reader:
            gnss_reader.close()
        if not args.no_display:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

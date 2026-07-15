"""
ZED 2i Basic Capture Script
============================
Phase 1: Captures stereo frames + depth from the ZED 2i camera.
Displays live preview with depth overlay. Press 'q' to quit.

Requirements:
    - ZED SDK 5.x installed
    - pyzed Python API installed (run get_python_api.py from SDK folder)
    - NVIDIA GPU with compute capability >= 7.5
"""

import sys
import json
import numpy as np

try:
    import pyzed.sl as sl
except ImportError:
    print("ERROR: pyzed not found.")
    print("Install it by running: python <ZED_SDK_PATH>/get_python_api.py")
    print("Typical path: C:\\Program Files (x86)\\ZED SDK\\get_python_api.py")
    sys.exit(1)

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python not found. Install with: pip install opencv-python")
    sys.exit(1)


def load_config(config_path="zed_sign_config.json"):
    """Load camera configuration from JSON file."""
    with open(config_path, "r") as f:
        return json.load(f)


def resolution_from_string(res_str):
    """Convert resolution string to sl.RESOLUTION enum."""
    mapping = {
        "HD2K": sl.RESOLUTION.HD2K,
        "HD1080": sl.RESOLUTION.HD1080,
        "HD1200": sl.RESOLUTION.HD1200,
        "HD720": sl.RESOLUTION.HD720,
        "SVGA": sl.RESOLUTION.SVGA,
        "VGA": sl.RESOLUTION.VGA,
    }
    return mapping.get(res_str.upper(), sl.RESOLUTION.HD720)


def depth_mode_from_string(mode_str):
    """Convert depth mode string to sl.DEPTH_MODE enum."""
    mapping = {
        "NEURAL": sl.DEPTH_MODE.NEURAL,
        "NEURAL_PLUS": sl.DEPTH_MODE.NEURAL_PLUS,
        "ULTRA": sl.DEPTH_MODE.ULTRA,
        "QUALITY": sl.DEPTH_MODE.QUALITY,
        "PERFORMANCE": sl.DEPTH_MODE.PERFORMANCE,
        "NONE": sl.DEPTH_MODE.NONE,
    }
    return mapping.get(mode_str.upper(), sl.DEPTH_MODE.NEURAL)


def create_depth_colormap(depth_array, max_depth=20.0):
    """Convert depth array to a colorized visualization."""
    # Clamp and normalize depth values
    depth_clamped = np.clip(depth_array, 0, max_depth)
    # Handle NaN/Inf from stereo occlusions
    depth_clamped = np.nan_to_num(depth_clamped, nan=max_depth, posinf=max_depth)
    depth_normalized = (depth_clamped / max_depth * 255).astype(np.uint8)
    # Apply colormap (TURBO gives intuitive near=red, far=blue)
    depth_colormap = cv2.applyColorMap(depth_normalized, cv2.COLORMAP_TURBO)
    return depth_colormap


def main():
    config = load_config()
    cam_cfg = config["zed_camera"]

    # --- Initialize ZED Camera ---
    zed = sl.Camera()

    init_params = sl.InitParameters()
    init_params.camera_resolution = resolution_from_string(cam_cfg["resolution"])
    init_params.camera_fps = cam_cfg["fps"]
    init_params.depth_mode = depth_mode_from_string(cam_cfg["depth_mode"])
    init_params.coordinate_units = sl.UNIT.METER
    init_params.coordinate_system = sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP
    init_params.depth_minimum_distance = 0.3  # 30 cm minimum depth

    print(f"Opening ZED 2i at {cam_cfg['resolution']} @ {cam_cfg['fps']} FPS...")
    print(f"Depth mode: {cam_cfg['depth_mode']}")

    err = zed.open(init_params)
    if err != sl.ERROR_CODE.SUCCESS:
        print(f"ERROR: Failed to open ZED camera: {err}")
        print("Make sure the camera is connected via USB 3.0 and drivers are installed.")
        sys.exit(1)

    # Print camera info
    cam_info = zed.get_camera_information()
    print(f"Camera Model: {cam_info.camera_model}")
    print(f"Serial Number: {cam_info.serial_number}")
    print(f"Firmware: {cam_info.camera_configuration.firmware_version}")
    print(f"Resolution: {cam_info.camera_configuration.resolution.width}x"
          f"{cam_info.camera_configuration.resolution.height}")

    # --- Allocate buffers ---
    image_left = sl.Mat()
    image_right = sl.Mat()
    depth_map = sl.Mat()
    point_cloud = sl.Mat()

    # --- Runtime parameters ---
    runtime_params = sl.RuntimeParameters()

    print("\n--- Live Preview ---")
    print("Press 'q' to quit")
    print("Press 'd' to toggle depth overlay")
    print("Press 'p' to print depth at center pixel")
    print("Press 's' to save current frame")

    show_depth = True
    frame_count = 0

    try:
        while True:
            # Grab a frame
            grab_status = zed.grab(runtime_params)
            if grab_status != sl.ERROR_CODE.SUCCESS:
                print(f"Grab failed: {grab_status}")
                continue

            frame_count += 1

            # Retrieve left image
            zed.retrieve_image(image_left, sl.VIEW.LEFT)
            left_np = image_left.get_data()  # BGRA numpy array

            if show_depth:
                # Retrieve depth map
                zed.retrieve_measure(depth_map, sl.MEASURE.DEPTH)
                depth_np = depth_map.get_data()  # float32 numpy array (meters)

                # Create side-by-side display
                left_bgr = cv2.cvtColor(left_np, cv2.COLOR_BGRA2BGR)
                depth_color = create_depth_colormap(depth_np)

                # Resize depth to match left image
                depth_color = cv2.resize(depth_color,
                                         (left_bgr.shape[1], left_bgr.shape[0]))

                display = np.hstack([left_bgr, depth_color])
            else:
                display = cv2.cvtColor(left_np, cv2.COLOR_BGRA2BGR)

            # Add frame counter and FPS indicator
            fps = zed.get_current_fps()
            cv2.putText(display, f"Frame: {frame_count} | FPS: {fps:.1f}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Show IMU data if available
            sensors = sl.SensorsData()
            if zed.get_sensors_data(sensors, sl.TIME_REFERENCE.CURRENT) == sl.ERROR_CODE.SUCCESS:
                imu = sensors.get_imu_data()
                orientation = imu.get_pose().get_euler_angles()
                cv2.putText(display,
                            f"IMU Roll:{orientation[0]:.1f} Pitch:{orientation[1]:.1f} Yaw:{orientation[2]:.1f}",
                            (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

            cv2.imshow("ZED 2i Capture", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('d'):
                show_depth = not show_depth
                print(f"Depth overlay: {'ON' if show_depth else 'OFF'}")
            elif key == ord('p'):
                # Print depth at center pixel
                cx = depth_map.get_width() // 2
                cy = depth_map.get_height() // 2
                err_code, depth_val = depth_map.get_value(cx, cy)
                print(f"Depth at center ({cx},{cy}): {depth_val:.3f} m")
            elif key == ord('s'):
                # Save current frame
                fname = f"frame_{frame_count:06d}.png"
                left_bgr = cv2.cvtColor(left_np, cv2.COLOR_BGRA2BGR)
                cv2.imwrite(fname, left_bgr)
                print(f"Saved: {fname}")

    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    finally:
        print(f"\nTotal frames captured: {frame_count}")
        zed.close()
        cv2.destroyAllWindows()
        print("Camera closed.")


if __name__ == "__main__":
    main()

"""
ZED 2i SVO2 Recording Script
==============================
Phase 1: Records stereo video + depth + IMU to SVO2 file format.
SVO2 files can be replayed offline for development without the physical camera.

Usage:
    python zed_record.py                         # Record with defaults
    python zed_record.py --output my_drive.svo2  # Custom output filename
    python zed_record.py --duration 300          # Record for 5 minutes

Press 'q' or Ctrl+C to stop recording.

Requirements:
    - ZED SDK 5.x installed
    - pyzed Python API installed
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

try:
    import pyzed.sl as sl
except ImportError:
    print("ERROR: pyzed not found.")
    print("Install it by running: python <ZED_SDK_PATH>/get_python_api.py")
    sys.exit(1)

try:
    import cv2
except ImportError:
    cv2 = None  # Preview will be disabled


def load_config(config_path="zed_sign_config.json"):
    """Load configuration from JSON file."""
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


def compression_from_string(comp_str):
    """Convert compression string to sl.SVO_COMPRESSION_MODE enum."""
    mapping = {
        "H264": sl.SVO_COMPRESSION_MODE.H264,
        "H265": sl.SVO_COMPRESSION_MODE.H265,
        "H264_LOSSLESS": sl.SVO_COMPRESSION_MODE.H264_LOSSLESS,
        "H265_LOSSLESS": sl.SVO_COMPRESSION_MODE.H265_LOSSLESS,
        "LOSSLESS": sl.SVO_COMPRESSION_MODE.LOSSLESS,
    }
    return mapping.get(comp_str.upper(), sl.SVO_COMPRESSION_MODE.H265)


def format_duration(seconds):
    """Format seconds into HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_filesize(bytes_val):
    """Format bytes into human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"


def main():
    parser = argparse.ArgumentParser(description="Record ZED 2i video to SVO2 file")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output SVO2 filename (default: auto-generated)")
    parser.add_argument("--duration", "-d", type=int, default=0,
                        help="Recording duration in seconds (0 = unlimited)")
    parser.add_argument("--no-preview", action="store_true",
                        help="Disable live preview window")
    parser.add_argument("--config", type=str, default="zed_sign_config.json",
                        help="Path to config JSON file")
    args = parser.parse_args()

    config = load_config(args.config)
    cam_cfg = config["zed_camera"]
    rec_cfg = config["recording"]

    # --- Generate output filename ---
    output_dir = Path(rec_cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = str(output_dir / args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(output_dir / f"{rec_cfg['filename_prefix']}_{timestamp}.svo2")

    # --- Initialize ZED Camera ---
    zed = sl.Camera()

    init_params = sl.InitParameters()
    init_params.camera_resolution = resolution_from_string(cam_cfg["resolution"])
    init_params.camera_fps = cam_cfg["fps"]
    init_params.depth_mode = sl.DEPTH_MODE.NONE  # No depth during recording (saves CPU)
    init_params.coordinate_units = sl.UNIT.METER

    print(f"Opening ZED 2i at {cam_cfg['resolution']} @ {cam_cfg['fps']} FPS...")

    err = zed.open(init_params)
    if err != sl.ERROR_CODE.SUCCESS:
        print(f"ERROR: Failed to open ZED camera: {err}")
        sys.exit(1)

    cam_info = zed.get_camera_information()
    print(f"Camera: {cam_info.camera_model} (SN: {cam_info.serial_number})")

    # --- Enable Recording ---
    rec_params = sl.RecordingParameters()
    rec_params.video_filename = output_path
    rec_params.compression_mode = compression_from_string(rec_cfg["compression"])

    err = zed.enable_recording(rec_params)
    if err != sl.ERROR_CODE.SUCCESS:
        print(f"ERROR: Failed to enable recording: {err}")
        zed.close()
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  RECORDING to: {output_path}")
    print(f"  Compression:  {rec_cfg['compression']}")
    print(f"  Duration:     {'unlimited' if args.duration == 0 else f'{args.duration}s'}")
    print(f"{'='*60}")
    print("Press 'q' or Ctrl+C to stop recording.\n")

    # --- Recording Loop ---
    image = sl.Mat()
    runtime_params = sl.RuntimeParameters()
    frame_count = 0
    start_time = time.time()
    show_preview = (cv2 is not None) and (not args.no_preview)

    try:
        while True:
            grab_status = zed.grab(runtime_params)
            if grab_status != sl.ERROR_CODE.SUCCESS:
                continue

            frame_count += 1
            elapsed = time.time() - start_time

            # Check duration limit
            if args.duration > 0 and elapsed >= args.duration:
                print(f"\nDuration limit reached ({args.duration}s).")
                break

            # Status update every 30 frames (~1 second at 30fps)
            if frame_count % 30 == 0:
                rec_status = zed.get_recording_status()
                fps = zed.get_current_fps()
                print(f"\r  Recording: {format_duration(elapsed)} | "
                      f"Frames: {frame_count} | "
                      f"FPS: {fps:.1f} | "
                      f"Status: {'OK' if rec_status.is_recording else 'PAUSED'}",
                      end="", flush=True)

            # Optional live preview
            if show_preview:
                zed.retrieve_image(image, sl.VIEW.LEFT)
                frame = image.get_data()
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                # Add recording indicator
                cv2.circle(frame_bgr, (30, 30), 12, (0, 0, 255), -1)  # Red dot
                cv2.putText(frame_bgr, f"REC {format_duration(elapsed)}",
                            (50, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.putText(frame_bgr, f"Frame: {frame_count}",
                            (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                cv2.imshow("ZED 2i Recording", frame_bgr)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    except KeyboardInterrupt:
        print("\n\nRecording stopped by user.")

    finally:
        elapsed = time.time() - start_time

        # Disable recording and close
        zed.disable_recording()
        zed.close()
        if show_preview:
            cv2.destroyAllWindows()

        # Print summary
        output_file = Path(output_path)
        file_size = output_file.stat().st_size if output_file.exists() else 0

        print(f"\n{'='*60}")
        print(f"  Recording Complete!")
        print(f"  File:      {output_path}")
        print(f"  Size:      {format_filesize(file_size)}")
        print(f"  Duration:  {format_duration(elapsed)}")
        print(f"  Frames:    {frame_count}")
        print(f"  Avg FPS:   {frame_count / elapsed:.1f}" if elapsed > 0 else "")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()

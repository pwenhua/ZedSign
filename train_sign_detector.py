"""
Street Sign YOLO Training Script
==================================
Phase 3: Train a YOLOv8/v11 model to detect street signs.

This script handles:
  1. Dataset validation
  2. Model training with configurable hyperparameters
  3. Evaluation on test set
  4. Export to ONNX for ZED SDK integration

Usage:
    python train_sign_detector.py                          # Train with defaults
    python train_sign_detector.py --model yolo11m.pt       # Use YOLO v11
    python train_sign_detector.py --epochs 200 --batch 8   # Custom training
    python train_sign_detector.py --resume                 # Resume interrupted training
    python train_sign_detector.py --export-only            # Just export existing model

Prerequisites:
    pip install ultralytics
    Dataset in YOLO format at datasets/traffic_signs/
"""

import sys
import argparse
import shutil
from pathlib import Path
from datetime import datetime

try:
    from ultralytics import YOLO
except ImportError:
    print("ERROR: ultralytics not found. Install with: pip install ultralytics")
    sys.exit(1)


# ============================================================
# Default Paths
# ============================================================

DATASET_DIR = Path("datasets/traffic_signs")
DATASET_YAML = DATASET_DIR / "data.yaml"
PROJECT_DIR = Path("models/training_runs")
EXPORT_DIR = Path("models")


def validate_dataset(dataset_yaml: Path) -> bool:
    """Check that the dataset directory structure is valid."""
    if not dataset_yaml.exists():
        print(f"ERROR: Dataset YAML not found: {dataset_yaml}")
        print(f"\nExpected directory structure:")
        print(f"  {DATASET_DIR}/")
        print(f"  ├── data.yaml")
        print(f"  ├── train/")
        print(f"  │   ├── images/")
        print(f"  │   └── labels/")
        print(f"  ├── val/")
        print(f"  │   ├── images/")
        print(f"  │   └── labels/")
        print(f"  └── test/        (optional)")
        print(f"      ├── images/")
        print(f"      └── labels/")
        print(f"\nRun 'python prepare_dataset.py' to set up the dataset structure.")
        return False

    # Check for train/val splits
    for split in ["train", "val"]:
        img_dir = DATASET_DIR / split / "images"
        lbl_dir = DATASET_DIR / split / "labels"
        if not img_dir.exists():
            print(f"ERROR: Missing {img_dir}")
            return False
        if not lbl_dir.exists():
            print(f"ERROR: Missing {lbl_dir}")
            return False

        num_images = len(list(img_dir.glob("*.*")))
        num_labels = len(list(lbl_dir.glob("*.txt")))
        print(f"  {split}: {num_images} images, {num_labels} labels")

        if num_images == 0:
            print(f"ERROR: No images found in {img_dir}")
            return False
        if num_labels == 0:
            print(f"ERROR: No labels found in {lbl_dir}")
            return False

    return True


def train(args):
    """Train the YOLO model."""
    print("=" * 60)
    print("  Street Sign Detection — YOLO Training")
    print("=" * 60)

    # Validate dataset
    print(f"\nDataset: {DATASET_YAML}")
    if not validate_dataset(DATASET_YAML):
        sys.exit(1)
    print("Dataset OK ✓\n")

    # Load model
    print(f"Loading base model: {args.model}")
    model = YOLO(args.model)

    # Training run name
    run_name = args.name or f"signs_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Train
    print(f"\nTraining Configuration:")
    print(f"  Model:      {args.model}")
    print(f"  Epochs:     {args.epochs}")
    print(f"  Batch size: {args.batch}")
    print(f"  Image size: {args.imgsz}")
    print(f"  Device:     {args.device}")
    print(f"  Run name:   {run_name}")
    print(f"  Project:    {PROJECT_DIR}")
    print()

    results = model.train(
        data=str(DATASET_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(PROJECT_DIR),
        name=run_name,
        # Optimization
        optimizer="AdamW",
        lr0=0.001,
        lrf=0.01,
        weight_decay=0.0005,
        warmup_epochs=3,
        # Augmentation — tuned for street signs
        hsv_h=0.015,      # Hue augmentation
        hsv_s=0.7,         # Saturation augmentation
        hsv_v=0.4,         # Value/brightness augmentation
        degrees=5.0,       # Small rotation (signs are mostly upright)
        translate=0.1,     # Translation
        scale=0.5,         # Scale augmentation
        flipud=0.0,        # No vertical flip (signs don't appear upside down)
        fliplr=0.5,        # Horizontal flip
        mosaic=1.0,        # Mosaic augmentation
        mixup=0.1,         # Mixup augmentation
        # Saving
        save=True,
        save_period=10,    # Save checkpoint every 10 epochs
        plots=True,
        # Early stopping
        patience=20,       # Stop if no improvement for 20 epochs
        # Resume
        resume=args.resume,
        # Workers
        workers=args.workers,
        verbose=True,
    )

    print(f"\n{'='*60}")
    print(f"  Training Complete!")
    print(f"  Best model: {PROJECT_DIR / run_name / 'weights' / 'best.pt'}")
    print(f"{'='*60}")

    return PROJECT_DIR / run_name


def evaluate(model_path: Path, args):
    """Evaluate the trained model on validation/test set."""
    print(f"\nEvaluating: {model_path}")
    model = YOLO(str(model_path))

    # Validate on val set
    print("\n--- Validation Set Results ---")
    val_results = model.val(
        data=str(DATASET_YAML),
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        split="val",
        plots=True,
        verbose=True,
    )

    # Print key metrics
    print(f"\n  mAP@0.5:      {val_results.box.map50:.4f}")
    print(f"  mAP@0.5:0.95: {val_results.box.map:.4f}")
    print(f"  Precision:     {val_results.box.mp:.4f}")
    print(f"  Recall:        {val_results.box.mr:.4f}")

    # Check if test set exists
    test_dir = DATASET_DIR / "test" / "images"
    if test_dir.exists() and len(list(test_dir.glob("*.*"))) > 0:
        print("\n--- Test Set Results ---")
        test_results = model.val(
            data=str(DATASET_YAML),
            imgsz=args.imgsz,
            batch=args.batch,
            device=args.device,
            split="test",
            plots=True,
            verbose=True,
        )
        print(f"\n  mAP@0.5:      {test_results.box.map50:.4f}")
        print(f"  mAP@0.5:0.95: {test_results.box.map:.4f}")

    # Pass/fail check
    target_map = 0.85
    if val_results.box.map50 >= target_map:
        print(f"\n✅ PASS: mAP@0.5 = {val_results.box.map50:.4f} >= {target_map}")
    else:
        print(f"\n⚠️  BELOW TARGET: mAP@0.5 = {val_results.box.map50:.4f} < {target_map}")
        print("   Consider: more training data, more epochs, or a larger model variant")

    return val_results


def export_onnx(model_path: Path, args):
    """Export trained model to ONNX for ZED SDK integration."""
    print(f"\nExporting to ONNX: {model_path}")
    model = YOLO(str(model_path))

    # Export
    export_path = model.export(
        format="onnx",
        imgsz=args.imgsz,
        half=True,          # FP16 for faster inference on RTX 5060
        simplify=True,      # Simplify ONNX graph
        dynamic=False,      # Fixed input shape for TensorRT optimization
        opset=17,           # ONNX opset version
    )

    print(f"  Exported: {export_path}")

    # Copy to models directory for the pipeline
    dest = EXPORT_DIR / "sign_detector.onnx"
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(export_path, dest)
    print(f"  Copied to: {dest}")
    print(f"\n  The pipeline (zed_sign_pipeline.py) will use: {dest}")

    return dest


def inference_test(model_path: Path, args):
    """Run inference on sample images to visually verify detections."""
    print(f"\nRunning inference test with: {model_path}")
    model = YOLO(str(model_path))

    # Look for test images
    test_dirs = [
        DATASET_DIR / "test" / "images",
        DATASET_DIR / "val" / "images",
        Path("test_images"),
    ]

    test_images = []
    for d in test_dirs:
        if d.exists():
            imgs = list(d.glob("*.jpg")) + list(d.glob("*.png"))
            test_images.extend(imgs[:10])  # Max 10 per directory
            if test_images:
                break

    if not test_images:
        print("  No test images found. Skipping inference test.")
        return

    print(f"  Testing on {len(test_images)} images...")

    # Run inference
    results = model.predict(
        source=test_images,
        imgsz=args.imgsz,
        conf=0.5,
        save=True,
        project=str(PROJECT_DIR),
        name="inference_test",
        device=args.device,
    )

    # Summary
    total_dets = sum(len(r.boxes) for r in results)
    print(f"  Total detections: {total_dets} across {len(test_images)} images")
    print(f"  Results saved to: {PROJECT_DIR / 'inference_test'}")


def main():
    parser = argparse.ArgumentParser(description="Train YOLO Street Sign Detector")

    # Model
    parser.add_argument("--model", type=str, default="yolov8m.pt",
                        help="Base model (yolov8n/s/m/l/x.pt or yolo11n/s/m/l/x.pt)")

    # Training
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--device", type=str, default="0", help="CUDA device (0, cpu)")
    parser.add_argument("--workers", type=int, default=8, help="Data loader workers")
    parser.add_argument("--name", type=str, default=None, help="Run name")
    parser.add_argument("--resume", action="store_true", help="Resume training")

    # Modes
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate")
    parser.add_argument("--export-only", action="store_true", help="Only export to ONNX")
    parser.add_argument("--test-only", action="store_true", help="Only run inference test")
    parser.add_argument("--weights", type=str, default=None,
                        help="Path to trained weights (for eval/export/test)")

    args = parser.parse_args()

    # Determine model path
    if args.weights:
        model_path = Path(args.weights)
    elif args.eval_only or args.export_only or args.test_only:
        # Find latest best.pt
        runs = sorted(PROJECT_DIR.glob("signs_*/weights/best.pt"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if runs:
            model_path = runs[0]
            print(f"Using latest model: {model_path}")
        else:
            print("ERROR: No trained model found. Train first or specify --weights")
            sys.exit(1)
    else:
        model_path = None

    # Execute requested mode
    if args.export_only:
        export_onnx(model_path, args)
    elif args.eval_only:
        evaluate(model_path, args)
    elif args.test_only:
        inference_test(model_path, args)
    else:
        # Full pipeline: train → evaluate → export
        run_dir = train(args)
        best_pt = run_dir / "weights" / "best.pt"

        if best_pt.exists():
            evaluate(best_pt, args)
            export_onnx(best_pt, args)
            inference_test(best_pt, args)
        else:
            print("WARNING: best.pt not found after training. Check training logs.")


if __name__ == "__main__":
    main()

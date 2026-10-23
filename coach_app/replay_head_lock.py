"""Recorded-image calculation check. No capture, sockets or mouse posting."""
import argparse
import json
from pathlib import Path

from .aimbot import HeadTracker, center
from .controlled_assist import load_calibration, plan_step, Limits


def analyze_image(path, model, calibration):
    import cv2
    image = cv2.imread(str(path))
    if image is None: raise ValueError(f'Cannot read recorded image: {path}')
    h, w = image.shape[:2]
    result = model.predict(image, device='cpu', imgsz=640, conf=.5, classes=[0], verbose=False, save=False)[0]
    boxes = result.boxes.xyxy.cpu().tolist()
    scores = result.boxes.conf.cpu().tolist()
    tracker = HeadTracker()
    selected = None
    for i in range(3): selected = tracker.update(boxes, scores, w, h, i*.05)
    summary = {'image': str(path), 'size': [w, h], 'heads': len(boxes),
               'input_events_posted': False, 'live_authorized': False}
    if selected:
        x, y = center(selected[0]); dx, dy = x-w/2, y-h/2
        summary.update(confidence=selected[1], dx=dx, dy=dy)
        try:
            summary['proposed_delta'] = plan_step(dx, dy, w, h, calibration['fingerprint'][1],
                                                 calibration['fingerprint'][2], calibration['gains'], Limits())
        except ValueError as error:
            summary['blocked'] = str(error)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+', type=Path)
    parser.add_argument('--calibration-report', type=Path)
    args = parser.parse_args()
    from ultralytics import YOLO
    from .runtime_paths import resolve_model
    calibration = load_calibration(explicit=args.calibration_report)
    model = YOLO(str(resolve_model()))
    if model.names.get(0) != 'xbot_head': raise ValueError('Expected XBot head model')
    print(json.dumps([analyze_image(p, model, calibration) for p in args.images], indent=2))


if __name__ == '__main__':
    main()

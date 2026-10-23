"""Import/device checks only. Never loads weights or starts training."""

import importlib
import importlib.metadata
import os
from pathlib import Path
import platform
import sys


def main() -> int:
    cache = Path(__file__).resolve().parent / ".cache"
    cache.mkdir(exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(cache / "ultralytics"))
    os.environ.setdefault("MPLCONFIGDIR", str(cache / "matplotlib"))
    print("Python version:", platform.python_version())
    print("Architecture:", platform.machine())
    print("Python executable:", sys.executable)
    failures = []
    for name, module in (("torch", "torch"), ("torchvision", "torchvision"),
                         ("ultralytics", "ultralytics"), ("opencv-python", "cv2"),
                         ("mss", "mss"), ("openai", "openai"), ("keyring", "keyring"),
                         ("pyobjc-framework-Cocoa", "AppKit"), ("pyobjc-framework-Quartz", "Quartz")):
        try:
            importlib.import_module(module)
            print(name + " version:", importlib.metadata.version(name), "[import OK]")
        except Exception as error:
            failures.append(name)
            print(name + " FAILED:", type(error).__name__, str(error))
    try:
        import torch
        print("PyTorch version:", torch.__version__)
        print("MPS built:", torch.backends.mps.is_built())
        available = torch.backends.mps.is_available()
        print("MPS available:", available)
        if available:
            matrix = torch.arange(16, dtype=torch.float32).reshape(4, 4)
            gpu = matrix.to("mps")
            result = gpu @ gpu.T
            torch.mps.synchronize()
            if not torch.allclose(result.cpu(), matrix @ matrix.T):
                raise RuntimeError("MPS calculation did not match CPU result")
            print("MPS tensor operation: PASS")
        else:
            failures.append("MPS acceleration unavailable")
        import torchvision
        boxes = torch.tensor([[0., 0., 10., 10.], [1., 1., 9., 9.]])
        kept = torchvision.ops.nms(boxes, torch.tensor([0.9, 0.8]), 0.5)
        assert kept.tolist() == [0]
        print("torchvision compiled operator: PASS")
    except Exception as error:
        failures.append("device/operator check")
        print("Device/operator check FAILED:", type(error).__name__, str(error))
    print("Training started: NO; weights downloaded: NO; screenshots captured: NO")
    print("Result:", "PASS" if not failures else "FAILED: " + ", ".join(failures))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())

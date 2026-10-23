"""Explicit offline bundle smoke test. No input, capture, key reads or API calls."""
import os


def smoke_test():
    from coach_app.runtime_paths import cache_root
    cache = cache_root()
    os.environ.setdefault('YOLO_CONFIG_DIR', str(cache / 'ultralytics'))
    os.environ.setdefault('MPLCONFIGDIR', str(cache / 'matplotlib'))
    from coach_app.overlay import CoachWindow
    from coach_app.ipc_server import CoachServer
    from coach_app.credentials import macos_backend
    from coach_app.telemetry import CorrectionLog
    import tkinter as tk
    import AppKit
    import Quartz
    import openai
    import numpy as np
    import torch
    from ultralytics import YOLO
    from yolo_dev.live_detect import resolve_model, capture_config, region_for_window
    DEFAULT_MODEL = resolve_model()
    from yolo_dev.capture_unity import DEFAULT_CONFIG
    result = {'model_exists': DEFAULT_MODEL.is_file(), 'model_path': str(DEFAULT_MODEL), 'crop_path': str(DEFAULT_CONFIG),
              'mps_available': torch.backends.mps.is_available(),
              'keychain_backend': type(macos_backend()).__name__}
    standalone = {'app':'AI-Aim-Trainer'}
    result['standalone_crop_required'] = capture_config(standalone) is not None
    result['standalone_roi_retina'] = list(region_for_window(standalone, 3024, 1768))
    result['standalone_roi_resized'] = list(region_for_window(standalone, 1920, 1080))
    server = CoachServer(0)  # Bind loopback without reading the actual Keychain item.
    result['ipc_bind'] = server.server_address[0] == '127.0.0.1'
    server.server_close()
    root = tk.Tk()
    app = CoachWindow(root)
    try:
        root.update()
        result['widget_size'] = [root.winfo_width(), root.winfo_height()]
        app.show_window()
        root.update()
        result['panel_size'] = [root.winfo_width(), root.winfo_height()]
        app.select_mode(2)
        root.update()
        button = app.verify_camera_button
        result['mode2_verify_visible'] = (button.winfo_ismapped() and
            button.winfo_rooty() + button.winfo_height() <= root.winfo_rooty() + root.winfo_height() and
            button.winfo_height() >= button.winfo_reqheight())
        entry = app.window_id_entry
        entry.event_generate('<Button-1>', x=8, y=8)
        root.update()
        for key in ('1', '2', '3'):
            entry.event_generate('<KeyPress>', keysym=key)
        root.update()
        result['mode2_numeric_input'] = entry.get() == '123' and root.focus_get() == entry
        app.select_window_id_text(None)
        entry.event_generate('<KeyPress>', keysym='BackSpace')
        root.update()
        result['mode2_delete_selection'] = entry.get() == ''
        result['mode2_native_key_window'] = bool(app.floating_policy.window.isKeyWindow())
        result['assist_stays_off'] = app.assist.snapshot()[0] == 'OFF'
        app.close()
        root.update()
        result['single_root'] = not any(isinstance(child, tk.Toplevel) for child in root.winfo_children())
    finally:
        app.shutdown()
        root.destroy()
    log = CorrectionLog()
    log.write({'event': 'packaging_smoke_test', 'input_events_posted': False})
    log.close()
    result['telemetry_path'] = str(log.path)
    model = YOLO(str(DEFAULT_MODEL))
    prediction = model.predict(np.zeros((320, 320, 3), dtype=np.uint8),
                               device='mps' if result['mps_available'] else 'cpu',
                               imgsz=320, verbose=False, save=False)[0]
    result['model_names'] = model.names
    result['inference_completed'] = prediction.boxes is not None
    result['input_events_posted'] = False
    return result

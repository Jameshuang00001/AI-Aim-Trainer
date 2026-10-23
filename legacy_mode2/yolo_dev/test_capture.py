"""Offline collector tests. Never invokes real screen capture or input automation."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from yolo_dev import capture_unity as capture


class CaptureTests(unittest.TestCase):
    def test_game_view_first_run_selects_once_then_reuses_crop(self):
        import cv2
        window = dict(id=123, pid=456, app="Unity", window_size_points=[200, 100])
        frame = np.zeros((200, 400, 3), dtype=np.uint8)
        frame[40:160, 60:340] = 200
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "crop.json"
            args = ["--window-id", "123", "--game-view-only", "--preview-only",
                    "--config", str(config), "--output", directory]
            with patch.object(capture.sys, "platform", "darwin"), patch.object(capture, "unity_windows", return_value=[window]):
                with patch.object(capture, "check_permission"), patch.object(capture, "capture_window", return_value=frame):
                    with patch.object(capture, "select_region", return_value=(60, 40, 280, 120)) as select:
                        self.assertEqual(capture.main(["--select-region" if arg == "--game-view-only" else arg for arg in args]), 0)
                        self.assertEqual(capture.main(args), 0)
                        select.assert_called_once()
            for image in Path(directory).glob("*.png"):
                saved = cv2.imread(str(image))
                self.assertEqual(saved.shape, (120, 280, 3))
                self.assertTrue((saved == 200).all())

    def test_saved_crop_retina_scaling_and_layout_change(self):
        window = dict(app="Unity", window_size_points=[1200, 800])
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "crop.json"
            capture.save_game_crop(config, window, (100, 100, 800, 600), 1200, 800)
            self.assertEqual(capture.load_game_crop(config, window, 2400, 1600), (200, 200, 1600, 1200))
            changed = dict(app="Unity", window_size_points=[1500, 1000])
            with self.assertRaises(capture.CaptureError):
                capture.load_game_crop(config, changed, 2400, 1600)
            with self.assertRaises(capture.CaptureError):
                capture.load_game_crop(config, dict(app="Other"), 1200, 800)

    def test_crop_validation(self):
        self.assertEqual(capture.validate_region([10, 20, 30, 40], 100, 100), (10, 20, 30, 40))
        for region in ([0, 0, 0, 1], [-1, 0, 1, 1], [90, 0, 20, 20], [1.5, 0, 2, 2], None):
            with self.assertRaises(capture.CaptureError):
                capture.validate_region(region, 100, 100)

    def test_native_command_targets_window_not_desktop(self):
        from types import SimpleNamespace
        with patch.object(capture.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            with patch.object(Path, "is_file", return_value=True), patch("cv2.imread", return_value=np.zeros((40, 60, 3), dtype=np.uint8)):
                capture.capture_window({"id": 123})
        command = run.call_args.args[0]
        self.assertIn("-l", command)
        self.assertEqual(command[command.index("-l") + 1], "123")
        self.assertNotIn("-S", command)
        self.assertNotIn("-R", command)

    def test_collection_writes_only_cropped_frames_with_unique_names(self):
        import cv2
        window = dict(id=123, pid=456, app="Unity", title="Game")
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:60, 10:40] = 255
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "raw"
            config = Path(directory) / "crop.json"
            with patch.object(capture.sys, "platform", "darwin"), patch.object(capture, "unity_windows", return_value=[window]):
                with patch.object(capture, "check_permission"), patch.object(capture, "capture_window", return_value=frame):
                    result = capture.main(["--window-id", "123", "--region", "10", "20", "30", "40",
                                           "--count", "2", "--yes", "--interval", "0.1", "--output", str(output), "--config", str(config)])
            self.assertEqual(result, 0)
            images = [path for path in output.glob("*.png") if not path.name.endswith("_preview.png")]
            self.assertEqual(len(images), 2)
            for image in images:
                cropped = cv2.imread(str(image))
                self.assertEqual(cropped.shape, (40, 30, 3))
                self.assertTrue((cropped == 255).all())
            manifest = json.loads(next(output.glob("*.json")).read_text())
            self.assertEqual(len(manifest["files"]), 2)
            self.assertTrue((output / manifest["preview"]).is_file())

    def test_retina_two_x_preview_mapping(self):
        self.assertEqual(capture.preview_to_image_region((100, 200, 300, 400), 1200, 800, 2400, 1600),
                         (200, 400, 600, 800))

    def test_one_x_preview_and_odd_sizes_keep_edges(self):
        self.assertEqual(capture.preview_to_image_region((10, 20, 30, 40), 800, 600, 800, 600),
                         (10, 20, 30, 40))
        self.assertEqual(capture.preview_to_image_region((0, 0, 500, 333), 500, 333, 1001, 667),
                         (0, 0, 1001, 667))
        self.assertEqual(capture.preview_to_image_region((499, 332, 1, 1), 500, 333, 1001, 667),
                         (998, 664, 3, 3))

    def test_select_region_uses_tk_image_local_result_not_opencv(self):
        frame = np.zeros((1800, 2880, 3), dtype=np.uint8)
        with patch("yolo_dev.roi_selector.choose_crop", return_value=(240, 120, 2160, 1440)) as select:
            with patch("cv2.selectROI") as opencv:
                region = capture.select_region(frame)
        self.assertEqual(region, (240, 120, 2160, 1440))
        self.assertIs(select.call_args.args[0], frame)
        opencv.assert_not_called()

    def test_invalid_roi_shows_actual_coordinates_and_bounds(self):
        with self.assertRaises(capture.CaptureError) as error:
            capture.validate_region((100, 50, 3000, 500), 2400, 1600)
        for detail in ("x=100", "y=50", "width=3000", "right=3100", "width=2400", "height=1600"):
            self.assertIn(detail, str(error.exception))

    def test_full_window_preview_only_ignores_logical_bounds_and_config(self):
        import cv2
        window = dict(id=123, pid=456, app="Unity", title="Game",
                      logical_bounds=dict(x=500, y=300, width=600, height=400))
        frame = np.zeros((800, 1200, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(capture.sys, "platform", "darwin"), patch.object(capture, "unity_windows", return_value=[window]):
                with patch.object(capture, "check_permission"), patch.object(capture, "capture_window", return_value=frame) as screenshot:
                    with patch.object(capture, "select_region") as select:
                        result = capture.main(["--window-id", "123", "--capture-full-window", "--preview-only",
                                               "--output", directory, "--config", str(Path(directory)/"missing.json")])
            self.assertEqual(result, 0)
            select.assert_not_called()
            screenshot.assert_called_once()
            images = list(Path(directory).glob("*.png"))
            self.assertEqual(len(images), 1)
            self.assertEqual(cv2.imread(str(images[0])).shape, frame.shape)

    def test_cancelled_selection_is_explicit(self):
        with patch("yolo_dev.roi_selector.choose_crop", return_value=None):
            with self.assertRaisesRegex(capture.CaptureError, "cancelled"):
                capture.select_region(np.zeros((100, 200, 3), dtype=np.uint8))

    def test_manual_crop_saves_and_reuses_without_selector(self):
        window = dict(id=123, pid=456, app="Unity", window_size_points=[1200, 800])
        with tempfile.TemporaryDirectory() as directory:
            for width, height in ((800, 600), (2400, 1600), (2880, 1800)):
                config = Path(directory) / f"{width}.json"
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                common = ["--window-id", "123", "--preview-only", "--config", str(config), "--output", directory]
                with patch.object(capture.sys, "platform", "darwin"), patch.object(capture, "unity_windows", return_value=[window]):
                    with patch.object(capture, "check_permission"), patch.object(capture, "capture_window", return_value=frame):
                        with patch.object(capture, "select_region") as select:
                            self.assertEqual(capture.main(common + ["--crop", "100", "50", "400", "300", "--save-crop"]), 0)
                            self.assertEqual(capture.main(common + ["--game-view-only"]), 0)
                            select.assert_not_called()
                self.assertEqual(json.loads(config.read_text())["region"], [100, 50, 400, 300])

    def test_missing_config_explains_manual_setup_without_opening_selector(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(capture.sys, "platform", "darwin"), patch.object(capture, "unity_windows", return_value=[dict(id=123, app="Unity")]):
                with patch.object(capture, "check_permission"), patch.object(capture, "capture_window", return_value=np.zeros((600, 800, 3), dtype=np.uint8)):
                    with patch.object(capture, "select_region") as select:
                        self.assertEqual(capture.main(["--window-id", "123", "--game-view-only", "--config", str(Path(directory)/"none.json")]), 1)
                        select.assert_not_called()

    def test_permission_failure_never_captures(self):
        with patch.object(capture.sys, "platform", "darwin"), patch.object(capture, "unity_windows", return_value=[dict(id=123)]):
            with patch.object(capture, "check_permission", side_effect=capture.CaptureError("permission missing")):
                with patch.object(capture, "capture_window") as screenshot:
                    self.assertEqual(capture.main(["--window-id", "123"]), 1)
                    screenshot.assert_not_called()

    def test_non_unity_window_rejected(self):
        with patch.object(capture.sys, "platform", "darwin"), patch.object(capture, "unity_windows", return_value=[]):
            with patch.object(capture, "capture_window") as screenshot:
                self.assertEqual(capture.main(["--window-id", "123"]), 1)
                screenshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()

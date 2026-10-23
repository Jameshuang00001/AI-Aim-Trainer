import queue
import unittest
from pathlib import Path
from unittest.mock import patch

from yolo_dev.live_detect import nearest_head, publish, capture_config, region_for_window


class LiveDetectionTests(unittest.TestCase):
    def test_standalone_needs_no_crop_and_uses_physical_image_bounds(self):
        window = {'app':'AI-Aim-Trainer'}
        with patch('yolo_dev.live_detect.resolve_editor_crop', side_effect=AssertionError('Editor config accessed')):
            self.assertIsNone(capture_config(window))
            for width, height in ((3024,1768),(1920,1080),(1512,884)):
                self.assertEqual(region_for_window(window,width,height,Path('/missing/editor.json')),
                                 (0,0,width,height))

    def test_editor_requires_config_and_missing_error_includes_exact_path(self):
        window = {'app':'Unity'}
        with self.assertRaisesRegex(Exception, '/missing/editor.json'):
            region_for_window(window,1920,1080,Path('/missing/editor.json'))

    def test_empty(self):
        self.assertIsNone(nearest_head([], 200, 100))

    def test_nearest_and_signed_offsets(self):
        result = nearest_head([[0, 0, 20, 20], [105, 55, 115, 65]], 200, 100)
        self.assertEqual(result, (1, (110, 60), (10, 10)))

    def test_retina_coordinates_remain_crop_local(self):
        self.assertEqual(nearest_head([[980, 480, 1000, 500]], 2000, 1000),
                         (0, (990, 490), (-10, -10)))

    def test_latest_frame_replaces_stale(self):
        messages = queue.Queue(maxsize=1)
        publish(messages, ("frame", "old"))
        publish(messages, ("status", "retry"))
        self.assertEqual(messages.get_nowait(), ("status", "retry"))


if __name__ == "__main__":
    unittest.main()

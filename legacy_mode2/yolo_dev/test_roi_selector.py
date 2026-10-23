"""Opt-in real Tk checks with synthetic images and no OS mouse movement."""

import os
import tkinter as tk
import unittest
from unittest.mock import patch
import numpy as np

from yolo_dev.capture_unity import preview_to_image_region, validate_region
from yolo_dev.roi_selector import choose_crop


@unittest.skipUnless(os.environ.get("YOLO_GUI_TESTS") == "1", "Opt-in Tk selector tests")
class SelectorTests(unittest.TestCase):
    def test_numeric_entry_without_drag_on_standard_and_retina_images(self):
        original_loop = tk.Tk.mainloop
        for width, height in ((800, 600), (2880, 1800)):
            errors = []

            def run(root):
                def populate():
                    try:
                        def descendants(widget):
                            for child in widget.winfo_children():
                                yield child
                                yield from descendants(child)
                        widgets = list(descendants(root))
                        canvas = next(widget for widget in widgets if isinstance(widget, tk.Canvas))
                        self.assertTrue(canvas.bind("<B1-Motion>"))
                        entries = [widget for widget in widgets if widget.winfo_class() == "TEntry"]
                        for entry, value in zip(entries, (100, 50, 400, 300)):
                            entry.delete(0, "end")
                            entry.insert(0, str(value))
                        button = next(widget for widget in widgets if widget.winfo_class() == "TButton" and widget.cget("text") == "Use Crop")
                        button.invoke()
                    except Exception as error:
                        errors.append(error)
                        root.destroy()
                root.after(50, populate)
                original_loop(root)

            with patch.object(tk.Tk, "mainloop", run):
                result = choose_crop(np.zeros((height, width, 3), dtype=np.uint8), validate_region, preview_to_image_region)
            self.assertFalse(errors, str(errors))
            self.assertEqual(result, (100, 50, 400, 300))


if __name__ == "__main__":
    unittest.main()

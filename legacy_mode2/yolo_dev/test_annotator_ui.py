"""Opt-in Tk tests using synthetic images, no screen capture or model calls."""

import os
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from PIL import Image

from yolo_dev.annotate import Annotator
from yolo_dev.annotation_data import AnnotationStore


@unittest.skipUnless(os.environ.get("YOLO_GUI_TESTS") == "1", "Opt-in annotation GUI test")
class AnnotatorUITests(unittest.TestCase):
    def test_boxes_delete_undo_navigation_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory)
            (dataset/"raw").mkdir()
            for name in ("one.png", "two.png"):
                Image.new("RGB", (2400, 1600)).save(dataset/"raw"/name)
            root = tk.Tk()
            errors = []
            root.report_callback_exception = lambda *error: errors.append(error)
            try:
                store = AnnotationStore(dataset)
                app = Annotator(root, store)
                root.update()

                def event(x, y):
                    return SimpleNamespace(x=app.ox+x*app.sx, y=app.oy+y*app.sy)

                # Invoke local widget callbacks only; never moves the OS mouse.
                for x in (100, 300):
                    app.press(event(x, 100))
                    app.drag(event(x+80, 180))
                    app.release(event(x+80, 180))
                self.assertEqual(len(app.boxes), 2)
                self.assertEqual(len(store.load(app.path)), 2)
                app.delete()
                self.assertEqual(len(app.boxes), 1)
                app.undo()
                self.assertEqual(len(app.boxes), 2)
                app.review_next()
                self.assertEqual(app.index, 1)
                self.assertTrue(store.reviewed(store.images[0]))
                app.navigate(-1)
                self.assertEqual(len(app.boxes), 2)
                self.assertTrue(app.reviewed.get())
                self.assertEqual(len(AnnotationStore(dataset).load(store.images[0])), 2)
                self.assertEqual(errors, [])
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()

"""Synthetic-file tests. No gameplay capture, network, or training."""

import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from yolo_dev.annotation_data import AnnotationStore, encode_boxes, decode_boxes, find_images


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.dataset = Path(self.directory.name)
        (self.dataset / "raw").mkdir()

    def image(self, name, size=(2400, 1600)):
        path = self.dataset / "raw" / name
        Image.new("RGB", size).save(path)
        return path

    def test_multiple_boxes_roundtrip_at_retina_resolution(self):
        boxes = [(0, 0, 2400, 1600), (100, 200, 200, 300)]
        text = encode_boxes(boxes, 2400, 1600)
        self.assertEqual(len(text.splitlines()), 2)
        self.assertEqual(text.splitlines()[0], "0 0.50000000 0.50000000 1.00000000 1.00000000")
        restored = decode_boxes(text, 2400, 1600)
        for original, actual in zip(boxes, restored):
            for a, b in zip(original, actual):
                self.assertAlmostEqual(a, b, places=3)

    def test_skips_preview_metadata_and_duplicate_stems(self):
        self.image("real.JPG")
        self.image("run_preview.png")
        (self.dataset / "raw" / "run.json").write_text("{}")
        self.assertEqual([p.name for p in find_images(self.dataset/"raw")], ["real.JPG"])
        self.image("real.png")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            find_images(self.dataset/"raw")

    def test_autosave_resume_and_explicit_negative_review(self):
        image = self.image("one.png")
        store = AnnotationStore(self.dataset)
        store.save(image, [(10, 20, 30, 40)], False)
        resumed = AnnotationStore(self.dataset)
        self.assertEqual(len(resumed.load(image)), 1)
        self.assertFalse(resumed.reviewed(image))
        resumed.save(image, [], True)
        self.assertEqual(resumed.label_path(image).read_text(), "")
        self.assertTrue(AnnotationStore(self.dataset).reviewed(image))

    def test_bad_boxes_and_class_are_rejected(self):
        with self.assertRaises(ValueError):
            encode_boxes([(0, 0, 0, 10)], 100, 100)
        with self.assertRaises(ValueError):
            decode_boxes("1 .5 .5 .1 .1", 100, 100)
        with self.assertRaises(ValueError):
            decode_boxes("0 nan .5 .1 .1", 100, 100)

    def test_split_pairs_ratio_reproducibility_and_backup(self):
        for i in range(10):
            self.image(f"image-{i}.png", (100, 80))
        store = AnnotationStore(self.dataset)
        with self.assertRaisesRegex(ValueError, "Review every"):
            store.export()
        for i, image in enumerate(store.images):
            store.save(image, [(10, 10, 20, 20)] if i % 2 else [], True)
        result = store.export()
        self.assertEqual((result["train"], result["val"]), (8, 2))
        for split, count in (("train", 8), ("val", 2)):
            images = list((self.dataset/"images"/split).glob("*.png"))
            labels = list((self.dataset/"labels"/split).glob("*.txt"))
            self.assertEqual(len(images), count)
            self.assertEqual({p.stem for p in images}, {p.stem for p in labels})
        again = store.export()
        self.assertEqual(result["files"], again["files"])
        self.assertTrue(list((self.dataset/"annotation_backups").iterdir()))
        self.assertEqual(len(list((self.dataset/"raw").glob("*.png"))), 10)

    def test_grouped_capture_split(self):
        for group, count in (("aaaaaaaa", 8), ("bbbbbbbb", 2)):
            for i in range(count):
                self.image(f"20261016T120000Z_{group}_{i:05d}_12345678.png", (100, 80))
        store = AnnotationStore(self.dataset)
        for image in store.images:
            store.save(image, [], True)
        result = store.export()
        self.assertTrue(result["grouped_by_capture_run"])
        self.assertEqual((result["train"], result["val"]), (8, 2))


if __name__ == "__main__":
    unittest.main()

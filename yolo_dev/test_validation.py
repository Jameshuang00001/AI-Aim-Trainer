"""Dataset validator tests with temporary synthetic files only."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from PIL import Image
import yaml

from yolo_dev.validate_dataset import audit, digest


class ValidationTests(unittest.TestCase):
    def test_pairing_negatives_duplicate_detection_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for split in ("train", "val"):
                (root/"images"/split).mkdir(parents=True)
                (root/"labels"/split).mkdir(parents=True)
            Image.new("RGB", (100,80), "red").save(root/"images/train/one.png")
            Image.new("RGB", (100,80), "blue").save(root/"images/train/negative.png")
            Image.new("RGB", (100,80), "red").save(root/"images/val/copy.png")
            (root/"labels/train/one.txt").write_text("0 .5 .5 .2 .2\n")
            (root/"labels/train/negative.txt").write_text("")
            (root/"labels/val/copy.txt").write_text("0 .5 .5 .2 .2\n")
            (root/"data.yaml").write_text(yaml.safe_dump(dict(path=str(root),train="images/train",val="images/val",names={0:"xbot_head"})))
            before = digest(root/"labels/train/one.txt")
            with redirect_stdout(io.StringIO()):
                report = audit(root, root/"validation")
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["splits"]["train"]["empty_labels"], 1)
            self.assertEqual(len(report["exact_duplicates"]), 1)
            self.assertTrue(report["exact_duplicates"][0]["cross_split"])
            self.assertTrue(report["source_files_unchanged"])
            self.assertEqual(digest(root/"labels/train/one.txt"), before)
            self.assertTrue((root/"validation/annotated_01.jpg").is_file())
            (root/"labels/train/one.txt").write_text("1 .5 .5 .2 .2\n0 .99 .5 .5 .2\n")
            (root/"labels/train/orphan.txt").write_text("")
            (root/"labels/val/copy.txt").unlink()
            with redirect_stdout(io.StringIO()):
                invalid = audit(root, root/"invalid_validation")
            errors = "\n".join(invalid["errors"])
            for phrase in ("class ID 0", "edges extend", "Orphan label", "Missing label"):
                self.assertIn(phrase, errors)


if __name__ == "__main__":
    unittest.main()

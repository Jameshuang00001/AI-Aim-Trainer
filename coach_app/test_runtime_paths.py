import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from coach_app import runtime_paths as paths


class RuntimePathsTests(unittest.TestCase):
    def test_packaged_model_ignores_unrelated_standalone_project_root(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)/'Coach.app/Contents/Frameworks'
            model = bundle/paths.MODEL_RELATIVE
            model.parent.mkdir(parents=True)
            model.write_bytes(b'fixture')
            with patch.object(paths.sys, '_MEIPASS', str(bundle), create=True), \
                 patch.object(paths.sys, 'frozen', True, create=True), \
                 patch.dict(os.environ, {'COACH_APP_ROOT': str(Path(directory)/'StandaloneGame.app')}):
                self.assertEqual(paths.resolve_model(), model)

    def test_missing_model_lists_exact_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory)/'missing.pt'
            with self.assertRaisesRegex(FileNotFoundError, str(missing)):
                paths.resolve_model(missing)

    def test_editor_crop_stays_separate_from_standalone_legacy_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root/'yolo_dev/capture_region.json'
            legacy.parent.mkdir()
            legacy.write_text(json.dumps({'app':'AI-Aim-Trainer'}))
            editor = root/'yolo_dev/capture_region.editor.json'
            with patch.dict(os.environ, {'COACH_APP_ROOT': directory}), patch.object(paths.Path, 'home', return_value=root):
                with self.assertRaises(FileNotFoundError) as error:
                    paths.resolve_editor_crop()
                self.assertIn(str(legacy), str(error.exception))
                self.assertIn('not a Unity Editor crop', str(error.exception))
                editor.write_text(json.dumps({'app':'Unity'}))
                self.assertEqual(paths.resolve_editor_crop(), editor.resolve())
            self.assertEqual(json.loads(legacy.read_text())['app'], 'AI-Aim-Trainer')

    def test_frozen_resources_and_writable_cache_are_separate(self):
        with patch.object(paths.sys, '_MEIPASS', '/app/Contents/Frameworks', create=True), \
             patch.object(paths.sys, 'frozen', True, create=True), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(paths.resource_root(), Path('/app/Contents/Frameworks'))
            self.assertEqual(paths.project_root(), paths.resource_root())
            self.assertNotIn('/app/', str(paths.cache_root()))
            self.assertNotIn('/app/', str(paths.crop_path()))

    def test_external_project_preserves_saved_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory)/'yolo_dev/capture_region.json'
            expected.parent.mkdir()
            expected.write_text('{}')
            with patch.dict(os.environ, {'COACH_APP_ROOT': directory}):
                self.assertEqual(paths.crop_path(), expected.resolve())


if __name__ == '__main__':
    unittest.main()

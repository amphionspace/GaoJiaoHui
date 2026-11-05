import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import tts_settings


class TtsSettingsTests(unittest.TestCase):
    def test_switch_is_persisted_and_used_by_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            with patch.dict(os.environ, {'JOURNEY_TTS_SETTINGS_FILE': str(path), 'JOURNEY_TTS_ORDER': 'bailian'}):
                self.assertEqual(tts_settings.mode(), 'bailian')
                self.assertEqual(tts_settings.order(), ['bailian'])
                tts_settings.set_mode('voxcpm2')
                self.assertEqual(tts_settings.mode(), 'voxcpm2')
                self.assertEqual(tts_settings.order(), ['voxcpm2', 'bailian'])
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.read_text().strip(), '{"mode": "voxcpm2"}')
                self.assertEqual(tts_settings.label(), 'VoxCPM2 + 百炼')

    def test_unknown_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            with patch.dict(os.environ, {'JOURNEY_TTS_SETTINGS_FILE': str(path)}):
                with self.assertRaises(ValueError):
                    tts_settings.set_mode('unknown')
                self.assertFalse(path.exists())

    def test_environment_order_is_the_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.json'
            with patch.dict(os.environ, {'JOURNEY_TTS_SETTINGS_FILE': str(path), 'JOURNEY_TTS_ORDER': 'fireredtts3,bailian'}):
                self.assertEqual(tts_settings.mode(), 'fireredtts3')
                self.assertEqual(tts_settings.order(), ['fireredtts3', 'bailian'])

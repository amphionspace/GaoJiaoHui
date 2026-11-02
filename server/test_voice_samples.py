import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from server import voice_samples

VOICE = 'journey_' + 'a' * 32


class VoiceSampleTests(unittest.TestCase):
    def env(self, directory, **extra):
        values = {'JOURNEY_TTS_SAMPLE_DIR': str(Path(directory) / 'tts'),
                  'JOURNEY_TTS_SAMPLE_TTL': '7200', 'JOURNEY_TTS_SAMPLE_MAX': '5'}
        values.update(extra)
        return values

    def test_sample_round_trip_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', self.env(directory)):
                self.assertTrue(voice_samples.save(VOICE, b'RIFFsample'))
                self.assertEqual(voice_samples.load(VOICE), b'RIFFsample')
                voice_samples.delete(VOICE)
                self.assertIsNone(voice_samples.load(VOICE))

    def test_invalid_names_and_oversize_samples_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', self.env(directory)):
                self.assertFalse(voice_samples.save('not-a-voice', b'x'))
                self.assertFalse(voice_samples.save(VOICE, b''))
                self.assertFalse(voice_samples.save(VOICE, b'x' * (2 * 1024 * 1024 + 1)))
                self.assertIsNone(voice_samples.load('not-a-voice'))

    def test_old_samples_expire(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', self.env(directory)):
                voice_samples.save(VOICE, b'RIFFold')
                path = Path(directory) / 'tts' / f'{VOICE}.wav'
                old = time.time() - 9000
                import os
                os.utime(path, (old, old))
                self.assertIsNone(voice_samples.load(VOICE))

    def test_only_the_newest_samples_are_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', self.env(directory, JOURNEY_TTS_SAMPLE_MAX='5')):
                names = ['journey_' + char * 32 for char in 'abcdef']
                for name in names:
                    voice_samples.save(name, b'RIFF')
                remaining = list((Path(directory) / 'tts').glob('*.wav'))
                self.assertEqual(len(remaining), 5)


if __name__ == '__main__':
    unittest.main()

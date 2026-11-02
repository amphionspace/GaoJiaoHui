import unittest
from unittest.mock import AsyncMock, patch

from server import main
from server.amphion_tts import AmphionError

VOICE = 'journey_' + 'a' * 32
BODY = {'voice': VOICE, 'input': '你好', 'language': 'Chinese'}


class TtsFailoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_primary_success_skips_bailian(self):
        with patch.object(main.bailian_tts, 'check_voice', AsyncMock(return_value='key')), \
             patch.object(main.amphion_tts, 'enabled', return_value=True), \
             patch.object(main.amphion_tts, 'cooling_down', return_value=False), \
             patch.object(main.voice_samples, 'load', return_value=b'RIFF'), \
             patch.object(main.amphion_tts, 'synthesize', AsyncMock(return_value=b'RIFFprimary')), \
             patch.object(main.bailian_tts, 'synthesize', AsyncMock()) as fallback:
            audio = await main.synthesize_journey_speech(None, dict(BODY))
        self.assertEqual(audio, b'RIFFprimary')
        fallback.assert_not_awaited()

    async def test_primary_failure_falls_back_to_bailian(self):
        with patch.object(main.bailian_tts, 'check_voice', AsyncMock(return_value='key')), \
             patch.object(main.amphion_tts, 'enabled', return_value=True), \
             patch.object(main.amphion_tts, 'cooling_down', return_value=False), \
             patch.object(main.voice_samples, 'load', return_value=b'RIFF'), \
             patch.object(main.amphion_tts, 'synthesize', AsyncMock(side_effect=AmphionError('http 502'))), \
             patch.object(main.bailian_tts, 'synthesize', AsyncMock(return_value=b'RIFFfallback')) as fallback:
            audio = await main.synthesize_journey_speech(None, dict(BODY))
        self.assertEqual(audio, b'RIFFfallback')
        self.assertEqual(fallback.await_args.kwargs.get('key'), 'key')

    async def test_missing_sample_goes_straight_to_bailian(self):
        with patch.object(main.bailian_tts, 'check_voice', AsyncMock(return_value='key')), \
             patch.object(main.amphion_tts, 'enabled', return_value=True), \
             patch.object(main.amphion_tts, 'cooling_down', return_value=False), \
             patch.object(main.voice_samples, 'load', return_value=None), \
             patch.object(main.amphion_tts, 'synthesize', AsyncMock()) as primary, \
             patch.object(main.bailian_tts, 'synthesize', AsyncMock(return_value=b'RIFFfallback')):
            audio = await main.synthesize_journey_speech(None, dict(BODY))
        self.assertEqual(audio, b'RIFFfallback')
        primary.assert_not_awaited()

    async def test_disclaimers_are_removed_before_synthesis(self):
        captured = {}

        async def primary(text, sample, language):
            captured['text'] = text
            return b'RIFFprimary'

        with patch.object(main.bailian_tts, 'check_voice', AsyncMock(return_value='key')), \
             patch.object(main.amphion_tts, 'enabled', return_value=True), \
             patch.object(main.amphion_tts, 'cooling_down', return_value=False), \
             patch.object(main.voice_samples, 'load', return_value=b'RIFF'), \
             patch.object(main.amphion_tts, 'synthesize', primary):
            body = {**BODY, 'input': '这是 AI 合成语音情景演示。你好。'}
            await main.synthesize_journey_speech(None, body)
        self.assertEqual(captured['text'], '你好。')

import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from server import journey_text
from server.evaluate_journey import CASES, check_note


RAW = "嗯，我今天看到了机器人。一开始只觉得新奇。后来想到爸爸搬东西很吃力，我想弄清它能不能帮上忙。"
NOTE = {
    "summary": "我想了解展会上的机器人能不能替爸爸搬重物。希望它真的能让爸爸轻松一点。",
    "message": "你想带回家的，是爸爸不用再费劲的日子。这份惦记，比机器人本身更动人。",
    "keywords": ["爸爸", "机器人", "搬重物"],
    "takeaway": "你想带回家的，是爸爸不用再费劲的日子。",
    "anchors": ["爸爸搬东西很吃力", "我想弄清它能不能帮上忙"],
}
CONFIG = {"url": "https://text.example.test/v1/chat/completions", "model": "test-model", "api_key": "test-only-key"}


class JourneyTextTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(journey_text, "configuration", return_value=CONFIG), patch.object(journey_text.httpx, "AsyncClient", return_value=client):
            return await journey_text.compose(journey_text.ComposeRequest(transcript=RAW, topic="product"))

    async def test_full_asr_and_selected_topic_reach_model_without_leaking_key(self):
        def handler(request):
            payload = json.loads(request.content)
            source = json.loads(payload["messages"][1]["content"])
            self.assertEqual(source["完整讲述"], RAW)
            self.assertEqual(source["主题"], "最惊喜的产品")
            self.assertEqual(payload["model"], "test-model")
            self.assertEqual(request.headers["Authorization"], "Bearer test-only-key")
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(NOTE, ensure_ascii=False)}}]})

        result = await self.invoke(handler)
        self.assertEqual(result["summary"], NOTE["summary"])
        self.assertEqual(result["note_text"], NOTE["summary"])
        self.assertEqual(result["message"], NOTE["message"])
        self.assertNotIn("api_key", result)
        self.assertNotIn("anchors", result)

    async def test_english_request_selects_english_prompt_and_accepts_longer_keywords(self):
        calls = []
        note = {
            "summary": "I want a robot to help my father carry things. I need to know if it can.",
            "message": "You saw your father's tired hands.",
            "keywords": ["father", "robot", "future care"],
            "takeaway": "You saw your father's tired hands.",
            "anchors": ["爸爸搬东西很吃力"],
        }

        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(note)}}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(journey_text, "configuration", return_value=CONFIG), patch.object(journey_text.httpx, "AsyncClient", return_value=client):
            result = await journey_text.compose(journey_text.ComposeRequest(transcript=RAW, topic="product", language="en"))
        source = json.loads(calls[0]["messages"][1]["content"])
        self.assertEqual(source["transcript"], RAW)
        self.assertEqual(source["topic"], journey_text.TOPICS_EN["product"])
        self.assertIn("Write all user-facing fields in English", calls[1]["messages"][-1]["content"])
        self.assertEqual(result["message"], note["message"])

    def test_note_text_is_the_personal_keepsake_body(self):
        for note_text in (
            "我想让机器人替爸爸搬重物。",
            "我想了解展会上的机器人能不能替爸爸搬重物。希望它真的能让爸爸轻松一点。",
            "我想让机器人替爸爸搬重物。希望它真的能让爸爸轻松一点。也许先试试再决定。",
        ):
            with self.subTest(note_text=note_text):
                note = journey_text.parse_note(json.dumps({**NOTE, "note_text": note_text}, ensure_ascii=False), RAW)
                self.assertEqual(note.note_text, note_text)
        self.assertIn("note_text", journey_text.SYSTEM_PROMPT)
        self.assertIn("40至70字", journey_text.SYSTEM_PROMPT)
        self.assertIn("最多80字", journey_text.SYSTEM_PROMPT)
        self.assertIn("优先收敛为两句", journey_text.SYSTEM_PROMPT)
        self.assertIn("sketch_prompt", journey_text.SYSTEM_PROMPT)

    def test_note_text_rejects_four_sentences(self):
        payload = {**NOTE, "note_text": "第一句。第二句。第三句。第四句。"}
        with self.assertRaisesRegex(ValueError, "1至3句"):
            journey_text.parse_note(json.dumps(payload, ensure_ascii=False), RAW)

    async def test_bad_output_retries_once_and_never_returns_a_template(self):
        calls = []

        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary": "呃"}'}}]})

        with self.assertRaises(HTTPException) as caught:
            await self.invoke(handler)
        self.assertEqual(caught.exception.detail["code"], "text_invalid_result")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["messages"][1], calls[1]["messages"][1])

    async def test_editorial_pass_replaces_unsupported_action_before_returning(self):
        calls = []
        draft = {**NOTE, 'message': '你站在展台前很久，想起爸爸搬东西时的吃力。先问问工作人员它能搬多重。', 'takeaway': '先问问工作人员它能搬多重。'}
        def handler(request):
            calls.append(json.loads(request.content))
            result = draft if len(calls) == 1 else NOTE
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(result)}}]})
        result = await self.invoke(handler)
        self.assertEqual(len(calls), 2)
        self.assertIn('事实审校', calls[1]['messages'][-1]['content'])
        self.assertEqual(result['message'], NOTE['message'])
        self.assertNotIn('站在展台前', result['message'])

    async def test_review_preserves_conversational_reply_without_identity_or_task(self):
        calls = []

        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(NOTE)}}]})

        result = await self.invoke(handler)
        self.assertEqual(len(calls), 2)
        reviewed_draft = json.loads(calls[1]['messages'][2]['content'])
        self.assertEqual(reviewed_draft['message'], NOTE['message'])
        self.assertEqual(result['message'], NOTE['message'])
        self.assertEqual(result['takeaway'], NOTE['takeaway'])

    async def test_invalid_review_retries_full_pipeline_and_preserves_source(self):
        for change in ({'message': NOTE['message'] + '不必一次定死，做个低门槛的尝试。'},
                       {'anchors': ['爸爸已经买了机器人']}):
            with self.subTest(change=change):
                calls = []

                def handler(request):
                    calls.append(json.loads(request.content))
                    result = {**NOTE, **change} if len(calls) == 2 else NOTE
                    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(result)}}]})

                result = await self.invoke(handler)
                self.assertEqual(len(calls), 4)
                self.assertEqual(result['message'], NOTE['message'])
                for call in calls:
                    self.assertEqual(json.loads(call['messages'][1]['content'])['完整讲述'], RAW)

    async def test_review_can_remove_objective_guarantee_without_losing_subjective_support(self):
        support = '想让爸爸搬东西省些力，这份惦记值得留下。'
        reviewed = {**NOTE, 'message': support, 'takeaway': support}
        draft = {**reviewed, 'message': support + '这台机器人以后一定会解决他的搬运问题。'}
        calls = []

        def handler(request):
            calls.append(json.loads(request.content))
            result = draft if len(calls) == 1 else reviewed
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(result)}}]})

        result = await self.invoke(handler)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['message'], reviewed['message'])
        self.assertEqual(result['takeaway'], support)
        self.assertNotIn('一定会解决', result['message'])
        self.assertNotIn(support, RAW)

    async def test_unavailable_review_never_returns_unreviewed_draft(self):
        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(NOTE)}}]})
            return httpx.Response(503, text='test-only-key')

        with self.assertRaises(HTTPException) as caught:
            await self.invoke(handler)
        self.assertEqual(caught.exception.detail['code'], 'text_review_failed')
        self.assertNotIn('test-only-key', str(caught.exception.detail))
        self.assertEqual(len(calls), 2)

    async def test_no_credentials_are_forwarded_in_upstream_error(self):
        with self.assertRaises(HTTPException) as caught:
            await self.invoke(lambda request: httpx.Response(401, json={"error": "request contains test-only-key"}))
        self.assertEqual(caught.exception.detail["upstream_status"], 401)
        self.assertNotIn("test-only-key", str(caught.exception.detail))

    async def test_missing_configuration_is_explicit_and_makes_no_external_call(self):
        with patch.object(journey_text, "configuration", return_value={"url": "", "model": "", "api_key": ""}), patch.object(journey_text.httpx, "AsyncClient") as client:
            with self.assertRaises(HTTPException) as caught:
                await journey_text.compose(journey_text.ComposeRequest(transcript=RAW, topic="story"))
            self.assertEqual(caught.exception.detail["code"], "text_not_configured")
            client.assert_not_called()

    def test_filler_repetition_wrong_direction_and_fabricated_evidence_are_rejected(self):
        for change in [
            {"summary": "呃，我看到了机器人。"},
            {"message": "未来的我，希望你一定会取得成功，也不要忘记今天。"},
            {"message": NOTE["summary"]},
            {"anchors": ["爸爸摔倒住院"]},
            {"summary": "我" * 111},
            {"keywords": ["机器人", "机器人"]},
            {"message": NOTE['message'] + '你一定可以。'},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                journey_text.parse_note(json.dumps({**NOTE, **change}), RAW)

    def test_future_theme_and_receipt_quote(self):
        request = journey_text.ComposeRequest(transcript=RAW)
        self.assertEqual(request.topic, 'future')
        note = journey_text.parse_note(json.dumps(NOTE), RAW)
        self.assertIn(note.takeaway, note.message)

    def test_natural_particles_are_kept_without_requiring_future_words(self):
        message = '你想让爸爸搬东西时少费点劲啊。这份惦记，比机器人本身更动人呢。'
        note = journey_text.parse_note(json.dumps({**NOTE, 'message': message}), RAW)
        self.assertEqual(note.message, message)
        self.assertIn(note.takeaway, message)

    def test_product_review_language_is_rejected_even_with_future_identity(self):
        for phrase in ('不必一次定死', '不用一次定死', '低门槛', '方向具体', '方向很具体', '方向已经很具体'):
            with self.subTest(phrase=phrase), self.assertRaisesRegex(ValueError, '书面产品评审腔'):
                journey_text.parse_note(json.dumps({**NOTE, 'message': '我是以后的你。想帮爸爸省力，' + phrase + '。'}), RAW)

    def test_paraphrased_quote_is_replaced_by_a_complete_reviewed_sentence(self):
        note = journey_text.parse_note(json.dumps({**NOTE, 'takeaway': '你一定可以，未来可期。'}), RAW)
        self.assertIn(note.takeaway, note.message)
        self.assertNotIn('未来可期', note.takeaway)
        self.assertEqual(note.takeaway, '这份惦记，比机器人本身更动人。')

    def test_reply_accepts_50_characters_and_rejects_51_without_truncation(self):
        message = NOTE['message']
        boundary = message + '啊' * (50 - len(message) - 1) + '。'
        note = journey_text.parse_note(json.dumps({**NOTE, 'message': boundary}), RAW)
        self.assertEqual(note.message, boundary)
        self.assertEqual(len(note.message), 50)
        with self.assertRaises(ValueError):
            journey_text.parse_note(json.dumps({**NOTE, 'message': boundary + '呀'}), RAW)

    async def test_overlong_draft_or_review_is_rewritten_before_delivery(self):
        for overlong_call in (1, 2):
            with self.subTest(overlong_call=overlong_call):
                calls = []

                def handler(request):
                    calls.append(json.loads(request.content))
                    result = {**NOTE, 'message': NOTE['message'] * 2} if len(calls) == overlong_call else NOTE
                    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(result)}}]})

                result = await self.invoke(handler)
                self.assertEqual(result['message'], NOTE['message'])
                self.assertLessEqual(len(result['message']), 50)
                self.assertEqual(len(calls), overlong_call + 2)
                self.assertIn('最多50', calls[-2]['messages'][-1]['content'])


class EvaluationChecksTests(unittest.TestCase):
    def test_full_duplex_case_accepts_direct_response_without_identity_or_advice(self):
        case = next(case for case in CASES if case['id'] == 'user-full-duplex')
        note = {
            'summary': '第一次聊天测试时，我不知道说什么、做什么，觉得可以考虑全语音或全双工语音。',
            'message': '嗨，你在想全双工能不能让聊天时不知道怎么接话的那一下顺一点，对吧？你连自己卡在哪里都留意到了，这次真的很用心。这次没想明白也没关系，我相信你能继续找办法，让聊天更接近你想要的样子。',
            'takeaway': '你连自己卡在哪里都留意到了，这次真的很用心。',
        }
        self.assertTrue(all(check_note(case, note).values()))
        direct_confusion = {**note, 'message': '第一次聊天不知道要说什么、做什么，你把这一下留意到了，对吧？' + note['message']}
        self.assertTrue(check_note(case, direct_confusion)['opening_addresses_specific_content'])
        for summary in ('我觉得可以考虑全语音或全双工语音。',
                        '第一次聊天测试时，我不知道说什么、做什么，想试全双工语音。'):
            with self.subTest(summary=summary):
                checks = check_note(case, {**note, 'summary': summary})
                self.assertFalse(checks['summary_covers_expected_terms'])

    def test_actual_cold_page_reply_is_not_accepted_as_support(self):
        case = next(case for case in CASES if case['id'] == 'user-full-duplex')
        note = {
            'summary': '第一次测试时，我不知道说什么、做什么，想试试全语音或全双工对话。',
            'message': '嗨，第一次测试时聊着聊着不知道要说什么、做什么，那一下卡住的感觉，你还挺当回事的。你说要做全双工，又说要么全语音，琢磨的都是怎么让对话能顺顺地接下去。这次你留意得挺细的。',
            'takeaway': '',
        }
        checks = check_note(case, note)
        self.assertTrue(checks['reply_covers_expected_terms'])
        self.assertFalse(checks['support_beyond_restatement_hint'])
        warm = {**note, 'message': note['message'] + '这次没想明白也没关系，我相信你能继续找办法。'}
        self.assertTrue(all(check_note(case, warm).values()))

    def test_belief_prefix_does_not_excuse_objective_success_guarantees(self):
        case = next(case for case in CASES if case['id'] == 'user-full-duplex')
        note = {
            'summary': '第一次测试时，我不知道说什么、做什么，想试试全语音或全双工对话。',
            'message': '不知道怎么接话的那一下，你惦记着呢。我相信全双工一定能解决这个问题。',
            'takeaway': '',
        }
        self.assertTrue(check_note(case, note)['support_beyond_restatement_hint'])
        self.assertFalse(check_note(case, note)['tone_boundaries'])

    def test_listening_is_support_without_a_new_task(self):
        case = next(case for case in CASES if case['id'] == 'story-discouraged')
        note = {
            'summary': '给爸妈看的挂号教程重录了两遍，他们还是跟不上。我很泄气，今天不想再改，只想说完。',
            'message': '挂号教程重录了两遍，他们还是跟不上，难怪你泄气啊。今天不想再改就先不改，你不用马上振作。我听着，你慢慢说。',
            'takeaway': '',
        }
        self.assertTrue(all(check_note(case, note).values()))

    def test_identity_first_or_late_topic_mention_does_not_pass_opening_check(self):
        case = next(case for case in CASES if case['id'] == 'product-care')
        self.assertTrue(all(check_note(case, NOTE).values()))
        checks = check_note(case, {**NOTE, 'message': '嗨，我是以后的你。' + NOTE['message']})
        self.assertFalse(checks['no_identity_lead'])
        self.assertFalse(checks['opening_addresses_specific_content'])
        self.assertTrue(checks['reply_covers_expected_terms'])

    def test_explicit_listening_request_does_not_pass_with_an_added_task(self):
        case = next(case for case in CASES if case['id'] == 'story-discouraged')
        note = {
            'summary': '给爸妈看的挂号教程重录了两遍，他们还是跟不上。我很泄气，今天不想再改，只想说完。',
            'message': '挂号教程录了两遍，爸妈还是跟不上，听着确实让人泄气啊。今天你可以先列出他们没看懂的地方。',
            'takeaway': '',
        }
        self.assertFalse(check_note(case, note)['tone_boundaries'])

    def test_negated_unwanted_encouragement_is_not_treated_as_a_promise(self):
        case = next(case for case in CASES if case['id'] == 'story-discouraged')
        note = {
            'summary': '给爸妈看的挂号教程重录了两遍，他们还是跟不上。我很泄气，今天不想再改，只想说完。',
            'message': '挂号教程录了两遍，他们还是跟不上，难怪你泄气啊。不用听那些坚持就会成功的话。',
            'takeaway': '',
        }
        self.assertTrue(check_note(case, note)['tone_boundaries'])
        self.assertFalse(check_note(case, {**note, 'message': note['message'] + '但坚持就会成功。'})['tone_boundaries'])


if __name__ == "__main__":
    unittest.main()

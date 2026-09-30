import json
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from tasks.FrogBoss.frog_dashen import (
    FEED_DETAIL_URL,
    FEED_LIST_URL,
    _feed_body,
    fetch_follow_decision,
    is_current_round,
    parse_side,
    parse_uids,
    retry_time_before_round_end,
)


class DashenFollowTests(unittest.TestCase):
    def test_parse_uid_list_and_reject_invalid_values(self):
        self.assertEqual(parse_uids('a' * 32 + '\n' + 'b' * 32 + ',' + 'a' * 32), ['a' * 32, 'b' * 32])
        with self.assertRaises(ValueError):
            parse_uids('not-a-uid')
        with self.assertRaises(ValueError):
            parse_uids('')

    def test_parse_side_requires_one_clear_direction(self):
        self.assertEqual(parse_side('10:00 左(红) 100%'), 'LEFT')
        self.assertEqual(parse_side('本轮建议压蓝'), 'RIGHT')
        self.assertIsNone(parse_side('竞猜内容仅供参考'))
        self.assertIsNone(parse_side('建议押红，不要压蓝'))

    def test_feed_title_direction_is_included_in_parsed_content(self):
        detail = {'result': {'feed': {'content': json.dumps({'body': {
            'title': '18：00场 右 最快对弈竞猜',
            'text': '#对弈竞猜#',
        }})}}}
        self.assertEqual(parse_side(_feed_body(detail)), 'RIGHT')

    def test_current_round_requires_same_day_and_two_hour_slot(self):
        now = datetime(2026, 9, 30, 12, 31)
        self.assertTrue(is_current_round(datetime(2026, 9, 30, 13, 10).timestamp() * 1000, now))
        self.assertFalse(is_current_round(datetime(2026, 9, 30, 11, 59).timestamp() * 1000, now))
        self.assertFalse(is_current_round(datetime(2026, 9, 29, 13, 10).timestamp() * 1000, now))

    def test_retry_time_is_round_end_minus_fifteen_minutes(self):
        self.assertEqual(
            retry_time_before_round_end(datetime(2026, 9, 30, 11, 30)),
            datetime(2026, 9, 30, 11, 45),
        )
        self.assertEqual(
            retry_time_before_round_end(datetime(2026, 9, 30, 22, 30)),
            datetime(2026, 9, 30, 23, 45),
        )
        self.assertIsNone(retry_time_before_round_end(datetime(2026, 9, 30, 11, 45)))
        self.assertIsNone(retry_time_before_round_end(datetime(2026, 9, 30, 11, 46)))
        self.assertIsNone(retry_time_before_round_end(datetime(2026, 9, 30, 9, 30)))

    def test_fetch_current_round_votes_and_choose_majority(self):
        now = datetime(2026, 9, 30, 12, 31)
        uids = ['a' * 32, 'b' * 32, 'c' * 32]
        feeds = {
            uid: {'id': f'feed-{index}', 'createTime': datetime(2026, 9, 30, 12, 5).timestamp() * 1000}
            for index, uid in enumerate(uids)
        }
        sides = {'feed-0': '本轮押红', 'feed-1': '10:00 左(红)', 'feed-2': '本轮压蓝'}

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        def get(url, params, timeout):
            self.assertEqual(timeout, 6)
            if url == FEED_LIST_URL:
                return Response({'result': {'feeds': [feeds[params['someOneUid']]]}})
            self.assertEqual(url, FEED_DETAIL_URL)
            feed_id = params['feedId']
            return Response({'result': {'feed': {
                'createTime': feeds[uids[int(feed_id[-1])]]['createTime'],
                'content': json.dumps({'body': {'text': sides[feed_id]}}),
            }}})

        requests_stub = SimpleNamespace(get=get, RequestException=RuntimeError)
        with patch.dict(sys.modules, {'requests': requests_stub}):
            decision = fetch_follow_decision('\n'.join(uids), now)

        self.assertEqual(decision['side'], 'LEFT')
        self.assertEqual(decision['counts'], {'LEFT': 2, 'RIGHT': 1})

    def test_fetch_does_not_choose_on_tie(self):
        now = datetime(2026, 9, 30, 12, 31)
        uids = ['a' * 32, 'b' * 32]
        posts = {
            'a' * 32: ('feed-a', '本轮押红'),
            'b' * 32: ('feed-b', '本轮压蓝'),
        }
        create_time = datetime(2026, 9, 30, 12, 5).timestamp() * 1000

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        def get(url, params, timeout):
            if url == FEED_LIST_URL:
                feed_id, _ = posts[params['someOneUid']]
                return Response({'result': {'feeds': [{'id': feed_id, 'createTime': create_time}]}})
            feed_id, text = posts['a' * 32] if params['feedId'] == 'feed-a' else posts['b' * 32]
            return Response({'result': {'feed': {
                'createTime': create_time,
                'content': json.dumps({'body': {'text': text}}),
            }}})

        requests_stub = SimpleNamespace(get=get, RequestException=RuntimeError)
        with patch.dict(sys.modules, {'requests': requests_stub}):
            with self.assertRaisesRegex(ValueError, 'tied'):
                fetch_follow_decision('\n'.join(uids), now)


if __name__ == '__main__':
    unittest.main()
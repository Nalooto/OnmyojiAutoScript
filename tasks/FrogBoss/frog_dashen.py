import json
import re
from datetime import datetime, timedelta


FEED_LIST_URL = 'https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds'
FEED_DETAIL_URL = 'https://inf.ds.163.com/v1/web/feed/basic/facade'
FEED_TYPES = '1,2,3,4,6,7,10,11'
UID_PATTERN = re.compile(r'^[0-9a-fA-F]{32}$')


class NoDashenPredictionError(ValueError):
    pass


_STRONG_SIDE_PATTERNS = {
    'LEFT': re.compile(r'押\s*(?:红|左)|压\s*(?:红|左)|看好\s*(?:红|左)|支持\s*(?:红|左)|红方|红色|左方|左边|左侧|红队'),
    'RIGHT': re.compile(r'押\s*(?:蓝|右)|压\s*(?:蓝|右)|看好\s*(?:蓝|右)|支持\s*(?:蓝|右)|蓝方|蓝色|右方|右边|右侧|蓝队'),
}
_WEAK_SIDE_PATTERNS = {
    'LEFT': re.compile(r'红|左'),
    'RIGHT': re.compile(r'蓝|右'),
}


def parse_uids(value: str) -> list[str]:
    """Parse a multiline/comma-separated list of NetEase Dashen UIDs."""
    uids = []
    for uid in re.split(r'[\s,，;；]+', value.strip()):
        if not uid:
            continue
        if not UID_PATTERN.fullmatch(uid):
            raise ValueError(f'Invalid NetEase Dashen UID: {uid}')
        if uid not in uids:
            uids.append(uid)
    if not uids:
        raise ValueError('Please configure at least one NetEase Dashen UID')
    return uids


def round_key(value: datetime):
    """Return (local date, round start hour) for active two-hour rounds."""
    if not 10 <= value.hour < 24:
        return None
    return value.date(), value.hour - value.hour % 2


def retry_time_before_round_end(value: datetime, lead_time: timedelta = timedelta(minutes=15)):
    current_round = round_key(value)
    if current_round is None:
        return None
    round_date, start_hour = current_round
    end_hour = start_hour + 2
    if end_hour == 24:
        round_date += timedelta(days=1)
        end_hour = 0
    round_end = datetime.combine(round_date, datetime.min.time()).replace(hour=end_hour)
    retry_time = round_end - lead_time
    return retry_time if value < retry_time else None


def _timestamp_to_datetime(timestamp) -> datetime:
    timestamp = float(timestamp)
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp)


def is_current_round(timestamp, now: datetime | None = None) -> bool:
    try:
        post_time = _timestamp_to_datetime(timestamp)
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    return round_key(post_time) is not None and round_key(post_time) == round_key(now or datetime.now())


def parse_side(text: str) -> str | None:
    """Return a side only when the post contains one unambiguous direction."""
    if not text:
        return None
    strong_matches = {
        side: pattern.search(text)
        for side, pattern in _STRONG_SIDE_PATTERNS.items()
    }
    strong_sides = [side for side, match in strong_matches.items() if match]
    if len(strong_sides) == 1:
        return strong_sides[0]
    if len(strong_sides) > 1:
        return None

    weak_matches = {
        side: pattern.search(text)
        for side, pattern in _WEAK_SIDE_PATTERNS.items()
    }
    weak_sides = [side for side, match in weak_matches.items() if match]
    if len(weak_sides) == 1:
        return weak_sides[0]
    return None


def _feed_body(detail: dict) -> str:
    content = detail['result']['feed']['content']
    content_data = json.loads(content) if isinstance(content, str) else content
    body = content_data.get('body', {})
    return body.get('text', '') or ''


def fetch_follow_decision(uids_value: str, now: datetime | None = None) -> dict:
    """Fetch one current-round vote per configured blogger and return consensus."""
    import requests

    uids = parse_uids(uids_value)
    now = now or datetime.now()
    if round_key(now) is None:
        raise ValueError('FrogBoss is outside the active betting hours')

    predictions = []
    for uid in uids:
        try:
            response = requests.get(
                FEED_LIST_URL,
                params={'feedTypes': FEED_TYPES, 'someOneUid': uid},
                timeout=6,
            )
            response.raise_for_status()
            feeds = response.json().get('result', {}).get('feeds', [])
            current_feeds = sorted(
                (feed for feed in feeds if is_current_round(feed.get('createTime'), now)),
                key=lambda feed: float(feed.get('createTime', 0)),
                reverse=True,
            )

            for feed in current_feeds:
                feed_id = feed.get('id')
                if not feed_id:
                    continue
                detail_response = requests.get(
                    FEED_DETAIL_URL,
                    params={'feedId': feed_id},
                    timeout=6,
                )
                detail_response.raise_for_status()
                detail = detail_response.json()
                feed_detail = detail.get('result', {}).get('feed', {})
                if not is_current_round(feed_detail.get('createTime'), now):
                    continue
                side = parse_side(_feed_body(detail))
                if side:
                    predictions.append({'uid': uid, 'side': side})
                    break
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError, AttributeError):
            continue

    if not predictions:
        raise NoDashenPredictionError('No clear NetEase Dashen predictions found for the current round')

    counts = {
        'LEFT': sum(prediction['side'] == 'LEFT' for prediction in predictions),
        'RIGHT': sum(prediction['side'] == 'RIGHT' for prediction in predictions),
    }
    if counts['LEFT'] == counts['RIGHT']:
        raise NoDashenPredictionError(f'NetEase Dashen predictions are tied: {counts}')
    return {
        'side': 'LEFT' if counts['LEFT'] > counts['RIGHT'] else 'RIGHT',
        'counts': counts,
        'predictions': predictions,
    }
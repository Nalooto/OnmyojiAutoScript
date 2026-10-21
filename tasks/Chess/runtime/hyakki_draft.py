"""百鬼试行投掷：定位本人锁状态并优先选择阵容所需御魂。"""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import random
import time

import cv2
import numpy as np
from PIL import Image

from module.logger import logger


@dataclass
class HyakkiTurn:
    key: int
    seen_lock: bool = False
    unlocked_at: float | None = None
    absent_frames: int = 0
    throws: int = 0

    def ready(self, score: float | None, now: float) -> bool:
        if self.throws >= 2:
            return False
        if score is not None and score >= 0.8:
            self.seen_lock = True
            self.unlocked_at = None
            self.absent_frames = 0
        elif score is not None and score < 0.55 and self.seen_lock:
            if self.unlocked_at is None:
                self.unlocked_at = now
            self.absent_frames += 1
        else:
            self.unlocked_at = None
            self.absent_frames = 0
        return (
            self.unlocked_at is not None
            and self.absent_frames >= 2
            and now - self.unlocked_at >= 4
        )


def player_name_box(rule, image) -> tuple[str, tuple[int, int, int, int]] | None:
    """只按昵称文字框内的黄色像素定位本人，不依赖 OCR 昵称内容。"""
    results = rule.detect_and_ocr(image)
    candidates = []
    for result in results:
        text = ''.join(str(result.ocr_text).split())
        points = np.asarray(result.box)
        left, top = points.min(axis=0).astype(int)
        right, bottom = points.max(axis=0).astype(int)
        roi_x, roi_y = rule.roi[:2]
        box = (
            int(left + roi_x),
            int(top + roi_y),
            int(right - left),
            int(bottom - top),
        )
        x, y, width, height = box
        patch = image[y:y + height, x:x + width]
        if patch.size == 0:
            continue
        hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
        yellow = np.mean(
            (hsv[:, :, 0] >= 15)
            & (hsv[:, :, 0] <= 40)
            & (hsv[:, :, 1] >= 170)
            & (hsv[:, :, 2] >= 120)
        )
        if float(yellow) >= 0.08:
            candidates.append((text, box))
    return candidates[0] if len(candidates) == 1 else None


def read_rgb(path: str | Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB'))


def own_lock_score(
    image: np.ndarray,
    name_box: tuple[int, int, int, int],
    rule,
    front: np.ndarray,
) -> float | None:
    """只检测本人昵称下方的锁；None 表示局部范围不完整。"""
    _, name_y, _, name_height = name_box
    roi_x, roi_y, roi_width, roi_height = rule.roi_back
    left = max(0, roi_x)
    right = min(image.shape[1], roi_x + roi_width)
    top = max(roi_y, name_y + name_height - 2)
    bottom = min(
        image.shape[0],
        roi_y + roi_height,
        name_y + name_height + 40,
    )
    region = image[top:bottom, left:right]
    if (
        region.shape[0] < front.shape[0]
        or region.shape[1] < front.shape[1]
    ):
        return None
    return float(cv2.minMaxLoc(cv2.matchTemplate(
        region,
        front,
        cv2.TM_CCOEFF_NORMED,
    ))[1])


def load_soul_fronts(folder: Path) -> dict[str, np.ndarray]:
    return {
        path.stem.removeprefix('sou_'): read_rgb(path)
        for path in sorted(folder.glob('sou_*.png'))
    }


def find_souls(
    image: np.ndarray,
    roi: tuple[int, int, int, int],
    fronts: dict[str, np.ndarray],
    threshold: float = 0.85,
) -> list[dict]:
    """搜索圈定区域，同一图标只保留最高分且种类明确的匹配。"""
    x, y, width, height = roi
    region = image[y:y + height, x:x + width]
    candidates = []
    for name, front in fronts.items():
        front_height, front_width = front.shape[:2]
        if (
            region.shape[0] < front_height
            or region.shape[1] < front_width
        ):
            continue
        scores = cv2.matchTemplate(
            region,
            front,
            cv2.TM_CCOEFF_NORMED,
        )
        for _ in range(4):
            _, score, _, (point_x, point_y) = cv2.minMaxLoc(scores)
            if not np.isfinite(score) or score < threshold:
                break
            candidates.append({
                'name': name,
                'score': float(score),
                'center': (
                    x + point_x + front_width // 2,
                    y + point_y + front_height // 2,
                ),
            })
            scores[
                max(0, point_y - 20):point_y + 21,
                max(0, point_x - 20):point_x + 21,
            ] = -1

    found = []
    for candidate in sorted(
        candidates,
        key=lambda item: item['score'],
        reverse=True,
    ):
        center_x, center_y = candidate['center']
        neighbours = [
            item
            for item in candidates
            if item is not candidate
            and abs(item['center'][0] - center_x) < 25
            and abs(item['center'][1] - center_y) < 25
        ]
        if any(
            item['name'] != candidate['name']
            and candidate['score'] - item['score'] < 0.05
            for item in neighbours
        ):
            continue
        if any(
            abs(item['center'][0] - center_x) < 25
            and abs(item['center'][1] - center_y) < 25
            for item in found
        ):
            continue
        found.append(candidate)
    return found


def throw_point(
    previous: dict,
    latest: dict,
    elapsed: float,
    latency: float,
    roi: tuple[int, int, int, int],
) -> tuple[int, int] | None:
    """按最近两帧左移速度补偿识别耗时，落点限定在投掷区域内。"""
    x, y = latest['center']
    delta_x = x - previous['center'][0]
    delta_y = y - previous['center'][1]
    offset = 0
    if 0.03 <= elapsed <= 2 and -150 <= delta_x <= 0 and abs(delta_y) <= 45:
        offset = max(
            -35,
            min(0, round(delta_x / elapsed * min(latency + 0.05, 0.5))),
        )
    point = (x + offset, y + 150)
    roi_x, roi_y, roi_width, roi_height = roi
    if (
        roi_x <= point[0] < roi_x + roi_width
        and roi_y <= point[1] < roi_y + roi_height
    ):
        return point
    return None


class ChessHyakkiDraftMixin:
    @cached_property
    def hyakki_soul_fronts(self) -> dict[str, np.ndarray]:
        folder = Path(__file__).resolve().parents[1] / 'soul' / 'hyakki'
        return load_soul_fronts(folder)

    @cached_property
    def hyakki_wait_front(self) -> np.ndarray:
        return read_rgb(self.I_HYAKKI_WAIT.file)

    def _hyakki_own_lock(self) -> float | None:
        player = player_name_box(self.O_NAME_RANGE, self.device.image)
        if player is None:
            return None
        identity = (player[0], player[1][1])
        if getattr(self, '_hyakki_player_row', None) != identity:
            self._hyakki_player_row = identity
            logger.info(
                f'Chess Hyakki own player: name={player[0]}, box={player[1]}'
            )
        return own_lock_score(
            self.device.image,
            player[1],
            self.I_HYAKKI_WAIT,
            self.hyakki_wait_front,
        )

    def _hyakki_needed_souls(self) -> set[str]:
        needed = set()
        strategy = self.get_lineup_strategy()
        for name, config in strategy['shikigami'].items():
            _, first, second = self._shikigami_attributes(name)
            needed.update(
                soul
                for soul in config.get('preferred_souls', ())
                if soul not in (first, second)
            )
        return needed

    def _handle_hyakki_draft(self) -> None:
        config = getattr(
            getattr(self.config, 'chess', None),
            'chess_config',
            None,
        )
        if not getattr(config, 'hyakki_draft_enabled', True):
            return

        round_no = int(getattr(self, '_current_round_no', 0))
        state = getattr(self, '_hyakki_turn', None)
        if state is None or state.key != round_no:
            state = self._hyakki_turn = HyakkiTurn(round_no)
            logger.info(
                f'Chess Hyakki trial: waiting for own lock, round={round_no}'
            )
        if state.throws >= 2:
            return

        score = self._hyakki_own_lock()
        previous_unlock = state.unlocked_at
        now = time.monotonic()
        ready = state.ready(score, now)
        if previous_unlock is None and state.unlocked_at is not None:
            logger.info('Chess Hyakki own lock disappeared: wait 4 seconds')
        if not ready:
            return

        roi = self.C_HYAKKI_SOUL_SHIKI.roi_back
        first_at = time.monotonic()
        candidates = find_souls(
            self.device.image,
            roi,
            self.hyakki_soul_fronts,
        )
        candidates = [
            item
            for item in candidates
            if throw_point(item, item, 0, 0, roi) is not None
        ]
        if not candidates:
            return

        needed = self._hyakki_needed_souls()
        preferred = [
            item for item in candidates if item['name'] in needed
        ]
        chosen = random.choice(preferred or candidates)
        self.screenshot()
        captured_at = time.monotonic()
        if self._read_chess_mode() != '鬼':
            return
        if not state.ready(self._hyakki_own_lock(), time.monotonic()):
            return

        latest = [
            item
            for item in find_souls(
                self.device.image,
                roi,
                self.hyakki_soul_fronts,
            )
            if item['name'] == chosen['name']
            and abs(item['center'][0] - chosen['center'][0]) <= 150
            and abs(item['center'][1] - chosen['center'][1]) <= 45
        ]
        if not latest:
            return
        target = min(
            latest,
            key=lambda item: abs(
                item['center'][0] - chosen['center'][0]
            ),
        )
        point = throw_point(
            chosen,
            target,
            captured_at - first_at,
            time.monotonic() - captured_at,
            roi,
        )
        if point is None:
            return

        state.throws += 1
        self.device.click(
            x=point[0],
            y=point[1],
            control_name='CHESS_HYAKKI_THROW',
        )
        logger.info(
            f'Chess Hyakki throw attempted: soul={target["name"]}, '
            f'preferred={bool(preferred)}, score={target["score"]:.3f}, '
            f'icon={target["center"]}, point={point}, round={round_no}, '
            f'attempt={state.throws}/2'
        )

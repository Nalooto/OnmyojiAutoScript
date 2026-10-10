import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.exception import GameStuckError
from tasks.Exploration.base import BaseExploration
from tasks.Exploration.config import ExplorationLevel


class OpenExpectLevelTask(BaseExploration):
    def __init__(self, chapter_results):
        self.config = SimpleNamespace(
            exploration=SimpleNamespace(
                exploration_config=SimpleNamespace(
                    exploration_level=ExplorationLevel.EXPLORATION_27
                )
            )
        )
        self.device = SimpleNamespace(click_record_clear=lambda: None)
        self.O_E_EXPLORATION_LEVEL_NUMBER = SimpleNamespace(
            detect_and_ocr=lambda _image: next(chapter_results)
        )
        self.swipes = []
        self.chapter_selected = False

    def screenshot(self):
        self.device.image = object()

    def appear(self, rule):
        return rule == self.I_E_EXPLORATION_CLICK and self.chapter_selected

    def appear_then_click(self, *_args, **_kwargs):
        return False

    def swipe(self, rule):
        self.swipes.append(rule)

    def ocr_appear_click(self, _rule):
        self.chapter_selected = True
        return True

    def wait_until_appear(self, *_args, **_kwargs):
        return True


class OpenExpectLevelTests(unittest.TestCase):
    @patch('tasks.Exploration.base.time.sleep')
    def test_retries_empty_ocr_then_raises_without_swiping(self, _sleep):
        task = OpenExpectLevelTask(iter([[], [], [], [], []]))

        with self.assertRaisesRegex(
            GameStuckError,
            'Unable to recognize exploration chapter names after 5 attempts',
        ):
            task.open_expect_level()

        self.assertEqual(task.swipes, [])

    @patch('tasks.Exploration.base.time.sleep')
    def test_keeps_directional_navigation_when_chapters_are_recognized(self, _sleep):
        recognized_chapters = [
            SimpleNamespace(ocr_text=chapter.value)
            for chapter in (
                ExplorationLevel.EXPLORATION_1,
                ExplorationLevel.EXPLORATION_2,
                ExplorationLevel.EXPLORATION_3,
                ExplorationLevel.EXPLORATION_4,
            )
        ]
        target_chapter = [
            SimpleNamespace(ocr_text=ExplorationLevel.EXPLORATION_27.value)
        ]
        task = OpenExpectLevelTask(iter([recognized_chapters, target_chapter]))

        self.assertTrue(task.open_expect_level())
        self.assertEqual(task.swipes, [task.S_SWIPE_LEVEL_DOWN])


if __name__ == '__main__':
    unittest.main()

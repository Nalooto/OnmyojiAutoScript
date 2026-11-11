"""超鬼王门票刷取「突破券满时清个人突破」的离线单元测试（不需要模拟器）。

覆盖三段：
1. 突破券检测的判定分支（开关 / 身份 / 页码 / 阈值 / OCR 异常 / 节流 / 冷却）
2. 探索主循环在中断后能续跑
3. 内联清票不污染个人突破任务自身的调度

运行：./toolkit/python.exe -m unittest tests.test_meta_demon_ticket_realm_raid -v
"""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from module.exception import TaskEnd
import tasks.GameUi.page as pages
import tasks.Exploration.page as exp_pages
from tasks.Exploration.config import UserStatus
from tasks.MetaDemonTicket.ticket_farming import (
    ExplorationTicketTask, RealmRaidNeeded, RealmRaidTicketTask, run_exploration_farming,
)
from tasks.RealmRaid.script_task import ScriptTask as RealmRaidTask


class StubOcr:
    """替身 OCR，记录调用次数并返回固定读数。"""

    def __init__(self, current, total=30):
        self.value = (current, max(total - current, 0), total)
        self.calls = 0

    def ocr(self, image):
        self.calls += 1
        return self.value


def build_task(enable=True, threshold=20, user_status=UserStatus.ALONE,
               exploration_ocr=(25, 30), entrance_ocr=(0, 30)):
    task = object.__new__(ExplorationTicketTask)
    task.config = SimpleNamespace(
        meta_demon_ticket=SimpleNamespace(
            general_config=SimpleNamespace(realm_raid_enable=enable, realm_raid_threshold=threshold)))
    task.user_status = user_status
    task.device = SimpleNamespace(image=object())
    task.O_REALM_RAID_NUMBER = StubOcr(*exploration_ocr)
    task.O_REALM_RAID_NUMBER1 = StubOcr(*entrance_ocr)
    task._realm_raid_next = None
    task._realm_raid_ocr_next = None
    return task


class TicketRaidDetectTest(unittest.TestCase):

    def check(self, task, current_page=pages.page_exploration):
        return task.activate_realm_raid(None, None, current_page)

    def test_disabled_does_not_ocr(self):
        task = build_task(enable=False)
        self.check(task)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 0)

    def test_leader_skips(self):
        task = build_task(user_status=UserStatus.LEADER)
        self.check(task)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 0)
        self.assertEqual(task.O_REALM_RAID_NUMBER1.calls, 0)

    def test_member_skips(self):
        task = build_task(user_status=UserStatus.MEMBER)
        self.check(task)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 0)

    def test_other_page_skips(self):
        task = build_task()
        self.check(task, current_page=exp_pages.page_exp_main)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 0)

    def test_below_threshold_keeps_farming(self):
        task = build_task(exploration_ocr=(19, 30))
        self.check(task)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 1)

    def test_reach_threshold_raises(self):
        task = build_task(exploration_ocr=(20, 30))
        with self.assertRaises(RealmRaidNeeded):
            self.check(task)

    def test_entrance_page_uses_other_roi(self):
        task = build_task(entrance_ocr=(22, 30))
        with self.assertRaises(RealmRaidNeeded):
            self.check(task, current_page=exp_pages.page_exp_entrance)
        self.assertEqual(task.O_REALM_RAID_NUMBER1.calls, 1)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 0)

    def test_invalid_total_is_ignored(self):
        task = build_task(exploration_ocr=(25, 0))
        self.check(task)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 1)

    def test_ocr_throttled_between_frames(self):
        task = build_task(exploration_ocr=(1, 30))
        self.check(task)
        self.check(task)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 1)

    def test_cooldown_blocks_detection(self):
        task = build_task(exploration_ocr=(30, 30))
        task._realm_raid_next = datetime.now() + timedelta(minutes=10)
        self.check(task)
        self.assertEqual(task.O_REALM_RAID_NUMBER.calls, 0)


class ExplorationLoopTest(unittest.TestCase):

    class StubRunner:
        def __init__(self, interrupt_times):
            self.events = []
            self.interrupt_times = interrupt_times

        def exec_exp_page(self):
            self.events.append('explore')
            if self.events.count('explore') <= self.interrupt_times:
                raise RealmRaidNeeded

        def run_realm_raid_round(self):
            self.events.append('raid')

    def test_resumes_after_realm_raid(self):
        runner = self.StubRunner(interrupt_times=2)
        run_exploration_farming(runner)
        self.assertEqual(runner.events, ['explore', 'raid', 'explore', 'raid', 'explore'])

    def test_without_interrupt_runs_once(self):
        runner = self.StubRunner(interrupt_times=0)
        run_exploration_farming(runner)
        self.assertEqual(runner.events, ['explore'])

    def test_other_exception_propagates(self):
        class Broken(self.StubRunner):
            def exec_exp_page(self):
                raise RuntimeError('device stuck')

        with self.assertRaises(RuntimeError):
            run_exploration_farming(Broken(0))


class RealmRaidTicketTaskTest(unittest.TestCase):

    def setUp(self):
        self.task = object.__new__(RealmRaidTicketTask)
        self.calls = []
        self.original_next_run = RealmRaidTask.set_next_run
        calls = self.calls
        RealmRaidTask.set_next_run = lambda self, task, **kwargs: calls.append(task)

    def tearDown(self):
        RealmRaidTask.set_next_run = self.original_next_run

    def test_realm_raid_schedule_untouched(self):
        self.task.set_next_run(task='RealmRaid', success=True, finish=True)
        self.assertEqual(self.calls, [])

    def test_other_task_schedule_passes_through(self):
        self.task.set_next_run(task='Exploration', success=True)
        self.assertEqual(self.calls, ['Exploration'])

    def test_run_swallows_task_end(self):
        original_run = RealmRaidTask.run

        def raise_end(self):
            raise TaskEnd

        RealmRaidTask.run = raise_end
        try:
            self.task.run()
        finally:
            RealmRaidTask.run = original_run


if __name__ == '__main__':
    unittest.main()

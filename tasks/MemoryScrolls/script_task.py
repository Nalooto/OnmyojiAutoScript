# This Python file uses the following encoding: utf-8
# @author ghg11
# github https://github.com/ghg11
from time import sleep
from enum import Enum
import re
from module.atom.ocr import RuleOcr
from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer
from datetime import timedelta, datetime

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_summon, page_main
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.MemoryScrolls.assets import MemoryScrollsAssets
from tasks.MemoryScrolls.config import ScrollNumber


class ScriptTask(GameUi, MemoryScrollsAssets):

    def run(self):        
        self.goto_page(page_summon)
        con = self.config.memory_scrolls.memory_scrolls_config
        # 进入绘卷主界面
        self.goto_memoryscrolls_main(con)
        # 返回主界面
        self.goto_page(page_main)
        raise TaskEnd
    
    def goto_memoryscrolls_main(self, con):
        # 循环寻找&点击绘卷入口
        if self.wait_until_appear(self.I_MS_ENTER, wait_time=30):
            while 1:
                self.screenshot()
                if self.appear(self.I_MS_FRAGMENT_S):
                    logger.info('Entered Memory Scrolls main page')
                    # 在绘卷主界面读取自身拥有的碎片数量（用于后续通知）
                    if con.notification:
                        self._fragment_counts = self.get_fragment_counts()
                    break
                # 周年庆等时期会使用双绘卷
                if self.appear(self.I_MS_DOUBLE_SCROLLS_ENTER):
                    logger.info('Using Double Memory Scrolls')
                    if con.double_scrolls == con.double_scrolls.ONE:
                        logger.info('Choose Double Memory Scrolls One')
                    else:
                        logger.info('Choose Double Memory Scrolls Two')
                        self.click(self.C_MS_DOUBLE_SCROLLS_2, interval=1)
                    if self.appear_then_click(self.I_MS_DOUBLE_SCROLLS_ENTER, interval=1):
                        continue
                # 右上角绘卷铃铛
                if self.appear_then_click(self.I_MS_ENTER, interval=1):
                    continue
        else:
            logger.error('Failed to enter Memory Scrolls main page')
            self.set_next_run(task='MemoryScrolls', success=False)
            raise TaskEnd
        # 如果每天只刷小绘卷50，则先检测小绘卷数量
        if self.config.memory_scrolls.memory_scrolls_finish.auto_finish_exploration:
            self.ui_click(self.I_MS_FRAGMENT_S, self.I_MS_FRAGMENT_S_VERIFICATION, interval=1.5)
            self.screenshot()  # 再次截图刷新图像帧
            if self.appear(self.I_MS_FRAGMENT_S_50):
                logger.info('Small Memory Scrolls fragments reached 50, planning tomorrow exploration')
                self.custom_next_run(task='Exploration', custom_time=self.config.memory_scrolls.memory_scrolls_finish.next_exploration_time, time_delta=1)
            else:
                logger.warning('Small Memory Scrolls fragments not reached 50, task failed')
                # 先返回绘卷主界面
                self.ui_click_until_disappear(GlobalGameAssets.I_UI_BACK_YELLOW, interval=1.5)
                # 再返回庭院主界面
                self.goto_page(page_main)
                self.set_next_run(task='MemoryScrolls', success=False)
                raise TaskEnd

            if not self.close_small_fragment_page():
                logger.warning('Failed to close small Memory Scrolls fragment page cleanly')
        # 进入指定分卷
        self.goto_scroll(con)
        # 返回召唤界面
        self.ui_click_until_disappear(GlobalGameAssets.I_UI_BACK_YELLOW, interval=1)
        logger.info('Return to Summon page')
    
    def goto_scroll(self, con):
        """
        进入指定分卷
        :param scroll_number: 分卷编号
        """
        while 1:
            self.screenshot()
            if self.appear(GlobalGameAssets.I_UI_BACK_RED):
                logger.info('Entered Memory Scrolls contribution page')
                break
            match con.scroll_number:
                case ScrollNumber.ONE:
                    self.click(self.C_MS_SCROLL_1, interval=1)
                case ScrollNumber.TWO:
                    self.click(self.C_MS_SCROLL_2, interval=1)
                case ScrollNumber.THREE:
                    self.click(self.C_MS_SCROLL_3, interval=1)
                case ScrollNumber.FOUR:
                    self.click(self.C_MS_SCROLL_4, interval=1)
                case ScrollNumber.FIVE:
                    self.click(self.C_MS_SCROLL_5, interval=1)
                case ScrollNumber.SIX:
                    self.click(self.C_MS_SCROLL_6, interval=1)
                case _:
                    logger.error(f'Unknown scroll number: {con.scroll_number.name}')
                    self.set_next_run(task='MemoryScrolls', success=False)
                    raise TaskEnd
        
        # 到达指定进度时进行通知提示
        if con.notification:
            progress = self.get_memory_scroll_progress()
            if progress is not None:
                content = f'目标绘卷进度已达{progress:.2f}%'
                fragment_info = getattr(self, '_fragment_counts', None)
                if fragment_info:
                    content += f'\n碎片数量: 小×{fragment_info["s"]} 中×{fragment_info["m"]} 大×{fragment_info["l"]}'
                self.config.notifier.push(title='追忆绘卷进度：', content=content)
                

        # 判断是否需要捐献碎片
        # 在通知推送后重新截图，避免图像后端帧缓存过期导致 RemoteError
        self.screenshot()
        if self.appear(self.I_MS_CONTRIBUTE) or not self.appear(self.I_MS_COMPLETE):
            logger.info(f'Contributing Memory Scrolls for scroll {con.scroll_number.name}')
            if con.auto_contribute_memoryscrolls:
                # 自动捐献碎片
                logger.info('Auto contributing Memory Scrolls')
                self.contribute_memoryscrolls()
            # 设置下一次运行时间
            self.set_next_run(task='MemoryScrolls', success=True)
        else:
            logger.info(f'Scroll {con.scroll_number.name} is already completed')
            self.set_next_run(task='MemoryScrolls', success=False)
            if con.auto_close_exploration:
                # 自动关闭探索任务
                logger.info('Auto close exploration task after Memory Scrolls completion')
                self.config.exploration.scheduler.enable = False
                self.config.save()
                # next_run=datetime.now() + timedelta(days=1)
                # self.set_next_run(task='Exploration', success=False, finish=False, target=next_run)
        # 返回绘卷主界面
        self.ui_click_until_disappear(GlobalGameAssets.I_UI_BACK_RED, interval=1)
        logger.info('Closed Memory Scrolls contribution page')
    
    def close_small_fragment_page(self) -> bool:
        """
        关闭小绘卷碎片详情页。
        """
        timeout = Timer(10).start()
        while self.appear(self.I_MS_FRAGMENT_S_VERIFICATION):
            if timeout.reached():
                return False
            if self.appear_then_click(self.I_MS_FRAGMENT_S, interval=1.5):
                continue
            self.screenshot()
            sleep(0.5)
        return True

    def open_small_fragment_page(self) -> bool:
        """
        确认进入小绘卷碎片详情页。
        """
        timeout = Timer(10).start()
        while not timeout.reached():
            self.screenshot()
            if self.appear(self.I_MS_FRAGMENT_S_VERIFICATION):
                return True
            if self.appear_then_click(self.I_MS_FRAGMENT_S, interval=1.5):
                continue
            sleep(0.5)
        return False

    def contribute_memoryscrolls(self):
        """
        捐献碎片
        :return: None
        """
        while 1:
            self.screenshot()
            if self.appear(self.I_MS_ZERO_S) and self.appear(self.I_MS_ZERO_M) and self.appear(self.I_MS_ZERO_L):
                logger.info('Memory Scrolls contribution is already completed')
                return
            self.swipe(self.S_MS_SWIPE_S, interval=1)
            self.swipe(self.S_MS_SWIPE_M, interval=1)
            self.swipe(self.S_MS_SWIPE_L, interval=1)
            if self.appear_then_click(self.I_MS_CONTRIBUTE, interval=3):
                logger.info('Contributed Memory Scrolls')
                # 等待捐献动画结束
                while 1:
                    self.screenshot()
                    if self.wait_until_appear(self.I_MS_CONTRIBUTED, wait_time=5):
                        self.click(self.C_MS_CONTRIBUTED, interval=1)
                    else:
                        break

    def get_memory_scroll_progress(self) -> float | None:
        """
        使用 OCR 识别当前绘卷进度，并返回百分比。
        """
        self.screenshot()
        ocr_target = getattr(self, 'O_M_SCROLL_PROGRESS', None)
        if ocr_target is None:
            try:
                from tasks.MemoryScrolls.assets import MemoryScrollsAssets
                ocr_target = getattr(MemoryScrollsAssets, 'O_M_SCROLL_PROGRESS', None)
            except Exception as e:
                logger.warning(f'Failed to import MemoryScrollsAssets for OCR progress: {e}')

        if ocr_target is None:
            logger.warning('Memory Scrolls OCR asset O_M_SCROLL_PROGRESS is missing, using inline fallback')
            ocr_target = RuleOcr(
                roi=(401,591,89,27),
                area=(401,591,89,27),
                mode='Single',
                method='Default',
                keyword='',
                name='m_scroll_progress',
            )

        result = ocr_target.ocr(self.device.image)
        if not result:
            logger.warning('Memory Scrolls OCR progress not recognized')
            return None

        progress = self.parse_scroll_progress(result)
        if progress is None:
            logger.warning(f'Memory Scrolls OCR returned unexpected text: "{result}"')
            return None

        logger.info(f'Memory Scrolls OCR progress recognized: "{result}" -> {progress:.2f}%')
        return progress

    def get_fragment_counts(self) -> dict | None:
        """
        在绘卷主界面读取自身拥有的小、中、大碎片数量。
        返回 {'s': int, 'm': int, 'l': int}，读取失败返回 None。
        """
        self.screenshot()
        counts = {'s': 0, 'm': 0, 'l': 0}
        for key, attr_name in [('s', 'O_M_FRAGMENT_NUMS_S'),
                                ('m', 'O_M_FRAGMENT_NUMS_M'),
                                ('l', 'O_M_FRAGMENT_NUMS_L')]:
            ocr_target = getattr(self, attr_name, None)
            if ocr_target is None:
                logger.warning(f'OCR asset {attr_name} not available')
                continue
            result = ocr_target.ocr(self.device.image)
            if isinstance(result, int):
                # Digit 模式返回 int
                counts[key] = result
            elif isinstance(result, tuple) and len(result) >= 1:
                # DigitCounter 模式返回 (current, remaining, total)
                counts[key] = result[0]
            elif isinstance(result, str):
                # Single 模式返回字符串
                match = re.search(r'\d+', result)
                if match:
                    counts[key] = int(match.group())
            else:
                logger.warning(f'Unexpected OCR result for {key}: {result}')
        logger.info(f'Fragment counts - S: {counts["s"]}, M: {counts["m"]}, L: {counts["l"]}')
        return counts

    @staticmethod
    def parse_scroll_progress(text: str) -> float | None:
        if not text:
            return None
        match = re.search(r'([0-9]+(?:\.[0-9]+)?)', text)
        if not match:
            return None
        try:
            progress = float(match.group(1))
        except ValueError:
            return None
        return min(max(progress, 0.0), 100.0)
    



if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()







# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

import numpy as np

from tasks.Component.GeneralBuff.assets import GeneralBuffAssets
from module.atom.ocr import RuleOcr
from module.atom.image import RuleImage
from tasks.base_task import BaseTask
from module.logger import logger
from typing import Optional


# 2026-10 游戏更新后加成界面每一行变成了:
#   [加成图标] [描述文字] [剩余时间胶囊] [圆形开关按钮]
# 圆形开关按钮的横坐标是固定的, 纵坐标跟随所在行
SWITCH_X = 856
SWITCH_W = 34
SWITCH_H = 34


class GeneralBuff(BaseTask, GeneralBuffAssets):

    def open_buff(self):
        """
        打开buff的总界面
        :return:
        """
        logger.info('Open buff')
        while 1:
            self.screenshot()
            if self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF_1, interval=2):
                continue

        check_image = self.I_AWAKE
        while 1:
            self.screenshot()
            if self.appear(check_image):
                break

            self.swipe(self.S_BUFF_UP, interval=2)

    def close_buff(self):
        """
        关闭buff的总界面, 但是要确保buff界面已经打开了
        :return:
        """
        logger.info('Close buff')
        while 1:
            self.screenshot()
            if not self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF_1, interval=2):
                continue

    @staticmethod
    def switch_area(center_y: int) -> tuple[int, int, int, int]:
        """
        根据所在行的中心纵坐标, 计算圆形开关按钮的区域
        :param center_y: 行的中心纵坐标
        :return:
        """
        return SWITCH_X, int(center_y - SWITCH_H / 2), SWITCH_W, SWITCH_H

    def get_area(self, buff: RuleOcr) -> Optional[tuple[int, int, int, int]]:
        """
        获取要点击的开关buff的区域
        新版的开关不再是"文字右边 10 像素", 文字右边先是剩余时间的胶囊,
        胶囊右侧才是圆形开关, 所以这里只取文字的纵向中心来定位开关所在的行
        :param buff:
        :return:  如果没有就返回None
        """
        # 防止邀请框挡住BUFF框架
        self.reject_invite()
        self.screenshot()
        result_list = buff.detect_and_ocr(self.device.image)
        center_y = None
        for result in result_list:
            if result.ocr_text == buff.keyword:
                top = int(result.box[0, 1])
                bottom = int(result.box[2, 1])
                center_y = buff.roi[1] + top + (bottom - top) // 2
                break
        if center_y is None:
            return None
        return self.switch_area(center_y)

    def set_switch_area(self, area):
        """
        旧版接口, 仅作兼容保留: 动态设置开关模板的搜索区域
        :param area:
        :return:
        """
        self.I_OPEN_YELLOW.roi_back = list(area)  # 动态设置roi
        self.I_CLOSE_RED.roi_back = list(area)

    def get_area_image(self, target: RuleImage) -> Optional[tuple[int, int, int, int]]:
        """
        获取觉醒加成或者是御魂加成所要点击的区域
        因为实在的图片比ocr快
        :param target:
        :return:
        """
        self.reject_invite()
        self.screenshot()

        if not self.appear(target):
            logger.warning(f'No {target.name} buff')
            return None
        center_y = int(target.roi_front[1] + target.roi_front[3] // 2)
        return self.switch_area(center_y)

    def _crop_switch(self, area) -> np.ndarray:
        x, y, w, h = area
        return self.device.image[y:y + h, x:x + w].astype(np.float32)

    def _click_switch(self, area):
        x, y, w, h = area
        self.device.click(x + w // 2, y + h // 2, control_name='BUFF_SWITCH')

    def _click_and_measure(self, area, frame: np.ndarray, before: np.ndarray) -> Optional[float]:
        """
        点击开关并返回点击后开关区域的平均亮度
        :return: 点击无效(弹出了其他窗口或者开关点不动)时返回None
        """
        self._click_switch(area)
        time.sleep(1.2)
        self.screenshot()
        after = self._crop_switch(area)

        screen_diff = float(np.abs(self.device.image.astype(np.float32) -
                                   frame.astype(np.float32)).mean())
        if screen_diff > 25:
            logger.warning(f'点击加成开关后界面出现大面积变化(diff={screen_diff:.1f}), 可能弹出了其他窗口')
            return None

        switch_diff = float(np.abs(after - before).mean())
        if switch_diff < 2:
            logger.warning(f'点击加成开关无反应(diff={switch_diff:.2f}), 开关的位置可能又变了, 请截图反馈')
            return None
        return float(after.mean())

    def set_switch(self, area, is_open: bool = True) -> bool:
        """
        设置加成开关
        新版开关的开(金色)/关(灰色)样式不是固定模板, 无现成素材可以匹配, 所以这里用
        "点击前后开关区域是否变化 + 变化后更亮即为开启" 来判断状态, 保证最终状态正确
        :param area: 圆形开关按钮的区域
        :param is_open: 目标状态
        :return: 操作成功True
        """
        target = '开启' if is_open else '关闭'
        self.screenshot()
        frame = self.device.image.copy()
        before = self._crop_switch(area)
        bright_before = float(before.mean())

        bright_after = self._click_and_measure(area, frame, before)
        if bright_after is None:
            return False

        # 区域亮了说明刚才是关的, 变暗说明刚才是开的
        if abs(bright_after - bright_before) < 8:
            logger.warning(f'开关外观变化太小, 无法判断状态 (亮度 {bright_before:.0f}->{bright_after:.0f}), '
                           f'按已切换处理')
            return True
        if (bright_after > bright_before) == is_open:
            logger.info(f'加成开关已{target} (亮度 {bright_before:.0f}->{bright_after:.0f})')
            return True

        # 走到这里说明刚才的点击把本来就是目标状态的开关关掉了, 再点一次恢复
        logger.info(f'加成开关原本就是{target}, 点击后反而变化了, 恢复原状态')
        frame = self.device.image.copy()
        before = self._crop_switch(area)
        bright_restore = self._click_and_measure(area, frame, before)
        if bright_restore is None:
            return False
        if (bright_restore > float(before.mean())) == is_open:
            logger.info(f'加成开关已恢复为{target} (亮度 {bright_restore:.0f})')
            return True
        logger.warning(f'加成开关状态切换失败 (亮度 {bright_before:.0f}->{bright_after:.0f}->'
                       f'{bright_restore:.0f})')
        return False

    def _buff_ocr(self, name: str, buff: RuleOcr, is_open: bool, max_swipe: int = 0) -> bool:
        logger.info(f'{name} buff')
        area = self.get_area(buff)
        while area is None:
            if max_swipe <= 0:
                logger.warning(f'No {name} buff')
                return False
            max_swipe -= 1
            self.device.swipe(p2=(530, 240), p1=(580, 320))
            time.sleep(1)
            area = self.get_area(buff)
        return self.set_switch(area, is_open)

    def _buff_image(self, name: str, target: RuleImage, is_open: bool) -> bool:
        logger.info(f'{name} buff')
        area = self.get_area_image(target)
        if not area:
            logger.warning(f'No {name} buff')
            return False
        return self.set_switch(area, is_open)

    def gold_50(self, is_open: bool = True) -> bool:
        """
        金币50buff
        :param is_open: 是否打开
        :return: 识别到且操作成功True
        """
        return self._buff_ocr('Gold 50', self.O_GOLD_50, is_open)

    def gold_100(self, is_open: bool = True) -> bool:
        """
        金币100buff
        :param is_open: 是否打开
        :return:
        """
        return self._buff_ocr('Gold 100', self.O_GOLD_100, is_open)

    def exp_50(self, is_open: bool = True) -> bool:
        """
        经验50buff
        :param is_open: 是否打开
        :return:
        """
        return self._buff_ocr('Exp 50', self.O_EXP_50, is_open, max_swipe=2)

    def exp_100(self, is_open: bool = True) -> bool:
        """
        经验100buff
        :param is_open: 是否打开
        :return:
        """
        return self._buff_ocr('Exp 100', self.O_EXP_100, is_open, max_swipe=2)

    def awake(self, is_open: bool = True) -> bool:
        """
        觉醒buff
        :param is_open: 是否打开
        :return:
        """
        return self._buff_image('Awake', self.I_AWAKE, is_open)

    def soul(self, is_open: bool = True) -> bool:
        """
        御魂buff
        :param is_open: 是否打开
        :return:
        """
        return self._buff_image('Soul', self.I_SOUL, is_open)

    def reject_invite(self):
        from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
        while 1:
            self.screenshot()
            if not (self.appear(gia.I_I_REJECT_1) or self.appear(gia.I_I_REJECT_2) or self.appear(gia.I_I_REJECT_3)):
                break
            if self.appear(gia.I_I_REJECT_3):
                self.click(gia.I_I_REJECT_3, 6)
                continue
            if self.appear(gia.I_I_REJECT_2):
                self.click(gia.I_I_REJECT_2, 6)
                continue
            if self.appear(gia.I_I_REJECT_1):
                self.click(gia.I_I_REJECT_1, 6)
                continue


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常2')
    d = Device(c)
    t = GeneralBuff(c, d)

    t.open_buff()
    t.gold_100(is_open=True)

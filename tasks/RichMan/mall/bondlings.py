# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from module.logger import logger
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.base.timer import Timer

from tasks.RichMan.mall.navbar import MallNavbar
from tasks.Component.Buy.buy import Buy
from tasks.RichMan.config import Bondlings as BondlingsConfig


class Bondlings(Buy, MallNavbar):

    def execute_bondlings(self, con: BondlingsConfig = None):
        if not con:
            con = self.config.rich_man.bondlings
        if not con.enable:
            logger.info('Bondlings is disable')
            return
        self._enter_bondlings()

        # 购买石头
        self._bondlings_base(buy_button=self.I_BL_BUY_STONE, remain_number=self.O_BL_RES_STONE, check_class=2,
                             buy_number=con.bondling_stone, buy_max=10, buy_money=30)
        # 购买御魂: 每周限购 100, 单次兑换(拉满)最多 30 个
        self._bondlings_base(buy_button=self.I_BL_BUY_SOULS, remain_number=self.O_BL_RES_SOULS, check_class=1,
                             buy_number=con.random_soul, buy_max=30, buy_money=20)
        # 购买高级盘
        self._bondlings_base(buy_button=self.I_BL_BUY_HIGH, remain_number=self.O_BL_RES_HIGH, check_class=3,
                             buy_number=con.high_bondling_discs, buy_max=10, buy_money=50)
        # 购买中级盘
        self._bondlings_base(buy_button=self.I_BL_BUY_MEDIUM, remain_number=self.O_BL_RES_MEDIUM, check_class=4,
                             buy_number=con.medium_bondling_discs, buy_max=25, buy_money=20)

    def _bondlings_base(self, buy_button: RuleImage, remain_number: RuleOcr, check_class: int,
                       buy_number: int, buy_max: int, buy_money: int):
        """
        按"拉满"的方式买一种商品, 买到目标数量或本周售罄为止

        注意: 契灵商店兑换成功后弹窗不会关闭, 也不会弹奖励界面, 所以 buy_more() 等不到
        I_UI_REWARD 会一直点到次数上限再返回 False. 这里改用商品卡片上"每周限购 N"
        (实时剩余)的变化来确认每一笔兑换是否真的成交.

        :param buy_button: 该商品的兑换按钮
        :param remain_number: 商品卡片 "每周限购 N" 的 OCR, 读的是**实时剩余**可购数
        :param check_class: 预留参数, 当前未使用
        :param buy_number: 本周打算买多少个
        :param buy_max: 一次兑换最多能买多少个(拉满时的单次上限)
        :param buy_money: 每个需要多少契灵币
        :return:
        """
        logger.hr(buy_button.name, 3)
        if buy_number == 0:
            logger.info('Buy number is 0')
            return
        self.screenshot()

        # 检查是否出现了购买按钮
        if not self.appear(buy_button):
            logger.warning('Buy button is not appear')
            return
        # 商品卡片上的"每周限购 N"是实时剩余, 不是固定上限
        remain = remain_number.ocr(self.device.image)
        if remain == 0:
            logger.warning('本周该商品已经买光')
            return
        if remain < buy_number:
            logger.warning(f'Weekly remaining is {remain}, buy number is {buy_number}, 按剩余买')
            buy_number = remain
        # 检查金钱
        cu, re, total = self.O_BL_CHECK_MONEY.ocr(self.device.image)
        if cu + re != total:
            logger.warning('Check money is error')
            logger.warning(f'cu: {cu}, re: {re}, total: {total}')
            return
        if cu < buy_money:
            logger.warning(f'Money is not enough {cu}')
            return
        if cu // buy_money < buy_number:
            buy_number = cu // buy_money
            logger.warning(f'Money only enough for {buy_number}, 按余额买')

        # 打开兑换弹窗
        if not self._bondlings_open_popup(buy_button):
            logger.warning('Open purchase popup failed')
            return
        logger.info(f'Buy number is {buy_number}, per purchase {buy_max}')

        bought = 0
        fail = 0
        timeout = Timer(90).start()
        while bought < buy_number and fail < 3 and not timeout.reached():
            remain_before = remain_number.ocr(self.device.image)
            if remain_before <= 0:
                logger.warning('本周该商品已经买光')
                break
            # 拉满, 游戏会把数量限制到 "单次上限" 与 "本周剩余" 的较小值
            if self.appear(self.I_BUY_PLUS):
                self.appear_then_click(self.I_BUY_PLUS, interval=0.6)
                time.sleep(0.6)
            # 已达上限等提示会盖住弹窗, 先点掉
            if self.appear(self.I_UI_CONFIRM_SAMLL):
                self.ui_click_until_disappear(self.I_UI_CONFIRM_SAMLL, interval=1)
                logger.warning('Buy number limit')
                break
            if not self.click(self.C_BUY_MORE, interval=1.2):
                time.sleep(0.3)
                continue
            # 等兑换结算, 再用剩余数量复核是否真的买到
            time.sleep(1.2)
            self.screenshot()
            remain_after = remain_number.ocr(self.device.image)
            gained = remain_before - remain_after
            if gained <= 0:
                fail += 1
                logger.warning(f'兑换后剩余数量没有减少({remain_before}), 重试 {fail}/3')
                self.device.click_record_clear()
                continue
            fail = 0
            bought += gained
            if gained > buy_max:
                logger.warning(f'单次兑换 {gained} 个, 超过预期上限 {buy_max}, 请检查游戏机制')
            logger.info(f'本次兑换 {gained} 个, 累计 {bought}/{buy_number}, 本周剩余 {remain_after}')
            self.device.click_record_clear()
            if remain_after <= 0:
                break

        logger.info(f'{buy_button.name} 本次共兑换 {bought} 个(目标 {buy_number})')
        # 兑换弹窗不关会挡住下一个商品的兑换按钮
        self._bondlings_close_popup()

    def _bondlings_open_popup(self, buy_button: RuleImage, max_try: int = 3) -> bool:
        """
        点击兑换按钮直到购买弹窗出现(弹窗里会出现"拉满"按钮)

        :param buy_button: 商品的兑换按钮
        :param max_try: 最多点几次兑换按钮
        :return: 弹窗是否已打开
        """
        # 上一个商品可能留下没关的弹窗, 先关掉, 否则会误判成当前商品的弹窗
        self._bondlings_close_popup()
        self.screenshot()
        if self.appear(self.I_BUY_PLUS):
            logger.warning('上一个商品的兑换弹窗没有关掉, 跳过该商品, 避免买错')
            return False
        for _ in range(max_try):
            self.screenshot()
            if self.appear(self.I_BUY_PLUS):
                return True
            if self.appear_then_click(buy_button, interval=1):
                for _ in range(12):
                    time.sleep(0.25)
                    self.screenshot()
                    if self.appear(self.I_BUY_PLUS):
                        return True
        self.screenshot()
        return self.appear(self.I_BUY_PLUS)

    def _bondlings_close_popup(self, max_try: int = 3):
        """
        点弹窗外空白处关掉兑换弹窗

        :param max_try: 最多点几次空白处
        :return:
        """
        for _ in range(max_try):
            self.screenshot()
            if not self.appear(self.I_BUY_PLUS):
                return
            # 点弹窗外左侧的遮罩空白处, 不要点到顶部货币栏和底部导航
            self.device.click(330, 400)
            time.sleep(0.8)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Bondlings(c, d)

    t.execute_bondlings()

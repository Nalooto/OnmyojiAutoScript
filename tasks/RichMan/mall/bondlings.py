# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from module.logger import logger
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr

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
        # 购买御魂: 每周限购 100, 单次兑换(拉满)最多 25 个
        self._bondlings_base(buy_button=self.I_BL_BUY_SOULS, remain_number=self.O_BL_RES_SOULS, check_class=1,
                             buy_number=con.random_soul, buy_max=25, buy_money=20)
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

        :param buy_button: 该商品的兑换按钮
        :param remain_number: 商品上方 "每周限购 N" 标签的 OCR, 读到的是**本周上限**而不是实时剩余
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
        # 这个 OCR 读到的是"每周限购 N"的 N(本周上限), 不是实时剩余数量, 只用来兜底防止无限买
        weekly_limit = remain_number.ocr(self.device.image)
        if weekly_limit == 0:
            logger.warning('本周契灵御魂已经买光')
            return
        if weekly_limit < buy_number:
            logger.warning(f'Weekly limit is {weekly_limit}, buy number is {buy_number}')
            buy_number = weekly_limit
        # 检查金钱
        cu, re, total = self.O_BL_CHECK_MONEY.ocr(self.device.image)
        if cu + re != total:
            logger.warning('Check money is error')
            logger.warning(f'cu: {cu}, re: {re}, total: {total}')
            return
        if cu < buy_money * buy_number:
            logger.warning(f'Money is not enough {cu}')
            # 判断够不够买2个
            if cu < buy_money * 2:
                logger.warning('Money is not enough 2')
                return
            buy_number = cu // buy_money
        # 拉满购买: 每轮最多买 buy_max 个, 兑换按钮点不出购买框就说明本周已经售罄
        buy_rounds = (buy_number + buy_max - 1) // buy_max
        logger.info(f'Buy number is {buy_number}, per purchase {buy_max}, rounds {buy_rounds}')
        bought = 0
        for i in range(buy_rounds):
            if not self.buy_more(buy_button, max_try=3):
                logger.warning(f'第 {i + 1} 轮兑换没弹出购买框, 判定本周已经售罄, 结束该商品')
                break
            bought += buy_max
            self.device.click_record_clear()
            time.sleep(0.5)
        logger.info(f'{buy_button.name} 本次共兑换约 {bought} 个(目标 {buy_number})')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Bondlings(c, d)

    t.execute_bondlings()

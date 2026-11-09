# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from typing import Dict, List, Tuple, Optional, Any, Union
import numpy as np
import time

import random
import re
from cached_property import cached_property
from datetime import datetime, timedelta
from module.atom.click import RuleClick

from module.base.timer import Timer
from module.atom.image_grid import ImageGrid
from module.atom.image import RuleImage
from module.base.utils import point2str
from module.logger import logger
from module.exception import TaskEnd, GameStuckError
from tasks.KekkaiUtilize.page import page_guild_realm, page_guild_realm_growth, page_guild_card

from tasks.KekkaiUtilize.script_task import ScriptTask as KU
from tasks.KekkaiUtilize.utils import CardClass
from tasks.KekkaiActivation.assets import KekkaiActivationAssets
from tasks.KekkaiActivation.utils import parse_rule
from tasks.KekkaiActivation.config import ActivationConfig, CardType, CardStar
from tasks.Utils.config_enum import ShikigamiClass
from tasks.GameUi.page import page_main, page_guild

""" 结界挂卡 """
class ScriptTask(KU, KekkaiActivationAssets):

    def run(self):
        con = self.config.kekkai_activation.activation_config
        # 进入寮结界
        self.goto_page(page_guild_realm)

        if con.exchange_before:
            self.check_max_lv(con.shikigami_class, con.auto_fill)
        # 收取经验
        self.harvest_card()
        # 开始挂卡
        self.run_activation(con)
        self.goto_page(page_guild_realm)

        if con.exchange_max:
            self.check_max_lv(con.shikigami_class, con.auto_fill)
        self.goto_page(page_main)

        raise TaskEnd('KekkaiActivation')

    @cached_property
    def dict_card_image(self) -> dict:
        match_targets = {
            CardClass.TAIKO6: self.I_CARDS_KAIKO_6,
            CardClass.TAIKO5: self.I_CARDS_KAIKO_5,
            CardClass.TAIKO4: self.I_CARDS_KAIKO_4,
            CardClass.TAIKO3: self.I_CARDS_KAIKO_3,
            CardClass.FISH6: self.I_CARDS_FISH_6,
            CardClass.FISH5: self.I_CARDS_FISH_5,
            CardClass.FISH4: self.I_CARDS_FISH_4,
            CardClass.FISH3: self.I_CARDS_FISH_3,
            CardClass.MOON6: self.I_CARDS_MOON_6,
            CardClass.MOON5: self.I_CARDS_MOON_5,
            CardClass.MOON4: self.I_CARDS_MOON_4,
            CardClass.MOON3: self.I_CARDS_MOON_3,
            CardClass.MOON2: self.I_CARDS_MOON_2,
            CardClass.MOON1: self.I_CARDS_MOON_1
        }
        return match_targets

    @cached_property
    def dict_image_card(self) -> dict:
        return {v: k for k, v in self.dict_card_image.items()}
    
    @cached_property
    def card_star_images(self) -> List[Tuple[int, RuleImage]]:
        """当前卡种类下的全部星级模板，按星级从高到低排列

        挂卡界面的卡片列表是按星级排序的，拿到“每一行是哪一星”之后
        就能按单张卡判断是否满足 card_star，不需要整页跳过。
        """
        rule = self.config.kekkai_activation.activation_config.card_type
        prefix = 'fish' if rule == CardType.FISH else 'taiko'
        images = []
        for image, card_class in self.dict_image_card.items():
            family, _, star = card_class.value.rpartition('_')
            if family != prefix or not star.isdigit():
                continue
            images.append((int(star), image))
        images.sort(key=lambda item: item[0], reverse=True)
        return images

    def _detect_page_cards(self) -> List[Tuple[int, float, Tuple[int, int, int, int]]]:
        """识别当前页所有的结界卡，返回 [(星级, 置信度, 位置)]"""
        images = [image for _, image in self.card_star_images]
        if not images:
            return []
        raw = ImageGrid(images).find_everyone(
            self.device.image,
            frame_id=self.device.image_frame_id,
        )
        if not raw:
            return []
        matches = []
        for image, score, area in raw:
            card_class = self.dict_image_card.get(image)
            if card_class is None:
                continue
            star = int(card_class.value.rpartition('_')[2])
            matches.append((star, float(score), tuple(area)))
        return matches

    def _star_of_result(
        self,
        result: Any,
        matches: List[Tuple[int, float, Tuple[int, int, int, int]]],
        tolerance: int = 70,
        near: int = 8,
    ) -> Optional[int]:
        """把 OCR 到的收益文字按纵向位置对到具体卡片上，返回该卡星级

        列表行距只有 ~146px，下一行的模板命中很容易落进本行的容差里，
        所以必须先按“距离最近”归属，不能按置信度高低选：
        置信度高的往往是隔壁那张卡的模板，按它判会张冠李戴。

        :param result: 单条 OCR 结果（坐标为 ROI 内坐标）
        :param matches: _detect_page_cards 的结果
        :param tolerance: 收益文字与卡片区域的最大允许纵向偏差
        :param near: 认定“同一行”的距离容差
        :return: 星级，无法判定时返回 None
        """
        roi_y = self.O_CHECK_CARD_NUMBER.roi[1]
        y_center = roi_y + (result.box[0][1] + result.box[2][1]) / 2
        candidates = []
        for star, score, area in matches:
            top = area[1]
            bottom = area[1] + area[3]
            if top <= y_center <= bottom:
                distance = 0
            else:
                distance = min(abs(y_center - top), abs(y_center - bottom))
            if distance > tolerance:
                continue
            candidates.append((distance, score, star))
        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], -item[1]))
        nearest = candidates[0][0]
        tied = [item for item in candidates if item[0] <= nearest + near]
        stars = {item[2] for item in tied}
        if len(stars) > 1:
            # 同一行同时命中多个星级：取更高星，宁可漏挂也不挂错星
            chosen = max(stars)
            logger.warning(
                f'⚠️ 卡片星级判定冲突 {result.ocr_text}: '
                f'{[(star, round(score, 3), distance) for distance, score, star in tied]}'
                f' → 保守按{chosen}星处理'
            )
            return chosen
        return tied[0][2]

    def _select_best_card_from_results(
        self,
        filtered_results: List[Any],
        matches: List[Tuple[int, float, Tuple[int, int, int, int]]],
        min_card_num: int,
        target_star: int,
        ocr_count: int,
    ) -> Optional[RuleClick]:
        """
        从过滤后的OCR结果中选择最佳卡片

        判定顺序：收益达标 → 星级不高于配置星级 → 取收益最高。
        页面里出现更高星的卡不再整页跳过，只跳过那张卡本身。
        :param filtered_results: 过滤后的OCR结果列表
        :param matches: 当前页识别到的卡片（星级/置信度/位置）
        :param min_card_num: 最低收益阈值
        :param target_star: 配置允许的最高星级
        :param ocr_count: 当前OCR计数
        :return: 选中的RuleClick对象，或None
        """
        records = []
        best_seen = getattr(self, '_best_seen', (0, None))
        for result in filtered_results:
            numbers = [int(num) for num in re.findall(r'\d+', result.ocr_text)]
            if not numbers:
                continue
            value = numbers[0]
            star = self._star_of_result(result, matches)
            # 记录本轮见到的最高收益，未找到卡时用于说明"阈值是否定高了"
            if value > best_seen[0]:
                best_seen = (value, star)
            if value < min_card_num:
                logger.debug(f"卡牌收益 {value} 低于阈值 {min_card_num}，跳过")
                continue
            records.append((value, star, result))
        self._best_seen = best_seen

        logger.info(
            "第%s次滑动后识别到卡: %s" % (
                ocr_count,
                [
                    f'{result.ocr_text}@{star if star is not None else "?"}星'
                    for _, star, result in records
                ],
            )
        )
        if not records:
            return None

        eligible = [item for item in records if item[1] is not None and item[1] <= target_star]
        if eligible:
            value, star, result = max(eligible, key=lambda item: item[0])
            logger.info(f'✅ 命中{star}星卡片，收益 {value}')
            return self._create_click_target(result)

        unknown = [item for item in records if item[1] is None]
        if unknown and (not matches or target_star >= 6):
            # 整页都没识别到星级（模板整体失效），或配置本身就是“6星及以下”
            # （星级不构成限制）时，按收益兜底选择
            value, _, result = max(unknown, key=lambda item: item[0])
            logger.warning(f'⚠️ 星级无法判定，按收益兜底选择: {result.ocr_text}（{value}）')
            return self._create_click_target(result)

        if unknown:
            logger.warning(
                '⚠️ 达标但星级无法判定，按配置保守跳过: %s'
                % [result.ocr_text for _, _, result in unknown]
            )
        else:
            logger.info(f'本页达标卡片均高于配置的{target_star}星，继续滑动')
        return None


    def _create_click_target(self, ocr_result: Any) -> RuleClick:
        """
        创建点击目标
        :param ocr_result: OCR结果对象
        :return: RuleClick对象
        """
        box = ocr_result.box
        x_min = self.O_CHECK_CARD_NUMBER.roi[0] + box[0][0]
        y_min = self.O_CHECK_CARD_NUMBER.roi[1] + box[0][1]
        width = box[1][0] - box[0][0]
        height = box[2][1] - box[1][1]
        roi = int(x_min), int(y_min), int(width), int(height)
        
        return RuleClick(roi_front=roi, roi_back=roi, name="tmpclick")

    def _perform_swipe_action(self, current_ocr_count: int, swipe_limit: int, reason: str = "未找到符合条件的卡") -> Tuple[bool, int]:
        """
        执行滑动操作
        
        :param current_ocr_count: 当前OCR计数
        :param swipe_limit: 滑动次数限制
        :param reason: 滑动原因，用于日志记录
        :return: (是否成功, 新的OCR计数)
        """
        new_ocr_count = current_ocr_count + 1
        
        # 检查是否达到滑动上限
        if new_ocr_count >= swipe_limit:
            logger.warning(f'已达到滑动次数上限({swipe_limit})，{reason}')
            return False, new_ocr_count
        
        # 执行滑动操作
        logger.info(f"{reason}，准备第{new_ocr_count}次滑动")
        duration = 2
        safe_pos_x = random.randint(200, 400)
        safe_pos_y = random.randint(580, 600)
        p1 = (safe_pos_x, safe_pos_y)
        p2 = (safe_pos_x, safe_pos_y - 410)
        logger.info('Swipe %s -> %s, %sS ' % (point2str(*p1), point2str(*p2), duration))
        self.device.swipe_adb(p1, p2, duration=duration)
        time.sleep(1)
        self.screenshot()  # 确保截图更新
        return True, new_ocr_count

    def run_activation(self, _config: ActivationConfig) -> bool:
        """
        执行挂卡，要求在结界的界面
        顺便把下一次执行也设置了
        :return: 挂卡成功（）返回True，失败(时间没到提前来了)返回False
        退出的时候还是在挂卡界面而不是结界界面
        """
        self.goto_page(page_guild_card)
        # 太诡异了 为什么有这么长的动画, 那么长的动画先休息一会
        logger.hr('Start activation')
        time.sleep(0.5)
        while 1:
            self.screenshot()
            card_status = self.check_card_status()
            card_effect = self.check_card_effect()

            # 不稳定太，等待动画结束
            if not card_status and not card_effect:
                # 黄色的 ”激活“
                if self.appear(self.I_A_ACTIVATE_YELLOW, threshold=0.95):
                    continue
                if self.appear(self.I_A_DEMOUNT):
                    # 现在在动画里面
                    logger.info('Now in the animation')
                    logger.info('Now there is no card')
                    continue
            # 如果这张卡生效着，在使用中
            if card_status and card_effect:
                logger.info('Card is using')
                interval = self.ocr_time()
                self.set_next_run("KekkaiActivation", target=interval+datetime.now())
                return False
            # 如果已经选中这张卡了， 那就激活这张卡
            if card_status and not card_effect:
                logger.info('Card is selected but not using')
                while 1:
                    self.screenshot()
                    if self.appear(self.I_A_INVITE, threshold=0.8):
                        logger.info('Card is activated')
                        break
                    if self.appear_then_click(self.I_UI_CONFIRM, interval=0.6):
                        continue
                    if self.appear_then_click(self.I_A_ACTIVATE_YELLOW, interval=1):
                        continue
                interval = self.ocr_time(True)
                self.set_next_run("KekkaiActivation", target=interval + datetime.now())
                return True
            # 如果是什么都没有，那就是可以开始挂卡了
            if not card_status and not card_effect:
                logger.info('Card is not selected also not using')
                self.screening_card(_config.card_type)

    def check_card_status(self, screenshot=False) -> bool:
        """
        判断使用有挂卡在上面了， 判断依据就是如果没看就可以显示背景图
        :param screenshot:
        :return: 如果有卡在上面了返回True，否则返回False
        """
        if screenshot:
            self.screenshot()
        return not self.appear(self.I_A_EMPTY)

    def check_card_effect(self, screenshot=False) -> bool:
        """
        检查这张卡是否生效了, 如果是出现的“邀请”那就是生效了， 如果是“激活”那就是还没生效
        :param screenshot:
        :return: 生效返回True
        """
        if screenshot:
            self.screenshot()
        if self.appear(self.I_A_INVITE, threshold=0.8):
            return True
        elif self.appear(self.I_A_ACTIVATE_YELLOW):
            return False
        logger.info('Unknown card effect')
        while 1:
            self.screenshot()
            if self.appear(self.I_A_INVITE, threshold=0.7):
                return True
            elif self.appear(self.I_A_ACTIVATE_YELLOW):
                return False
            elif self.appear(self.I_A_ACTIVATE_GRAY):
                return False

    def ocr_time(self, screenshot=False) -> timedelta or None:
        if screenshot:
            self.screenshot()
        delta = self.O_CARD_ALL_TIME.ocr_duration(self.device.image)
        if not isinstance(delta, timedelta):
            logger.warning('OCR error')
            return None
        if delta == timedelta(0):
            logger.error('The remaining time detected for this card is 0')
            logger.error('This may be due to the fact that the card has not yet been collected')
            raise GameStuckError
        return delta

    def screening_card(self, rule: str):
        """
        开始挑选卡
        :return:
        """

        if rule == CardType.TAIKO:
            card_class = CardClass.TAIKO
            target_class = self.I_A_CARD_KAIKO
        elif rule == CardType.FISH:
            card_class = CardClass.FISH
            target_class = self.I_A_CARD_FISH
        else:
            logger.warning('Unknown card rule')
            self.push_notify(content='Unknown card rule')
            return

        while 1:
            self.screenshot()

            if self.appear(target_class):
                time.sleep(0.3)
                self.screenshot()
                if self.appear(target_class):
                    break
            if self.click(self.C_A_SELECT_CARD_LIST, interval=2.5):
                continue
        logger.info('Appear card class: {}'.format(card_class))
        while 1:
            self.screenshot()
            if not self.appear(target_class):
                break
            if self.appear_then_click(target_class, interval=1):
                continue
        logger.info('Selected card class: {}'.format(card_class))

        # 找最优卡
        while 1:
            self.screenshot()
            target = self.check_card_num()
            if target is None:
                # 未发现卡，处理逻辑
                self._card_not_found()
            if self.appear(self.I_A_EMPTY):
                while 1:
                    self.screenshot()
                    if not self.appear(self.I_A_EMPTY):
                        self.config.kekkai_activation.activation_config.card_not_found_count = 0
                        self.config.save()
                        message = f'✅ 确认挂卡: {rule}'
                        self.save_image(content=message, push_flag=False, wait_time=0)
                        return
                    if self.click(target, interval=1):
                        continue

    def check_card_num(self):
        """按“每张卡的星级 + 每小时收益”挑卡

        旧实现用“页面里出现更高星卡就整页跳过”来保证 card_star 语义，
        但列表首屏/混排页经常同时命中目标星和更高星模板，整页会被丢掉，
        结果永远选不到卡。这里改成先定位每张卡所在行，再逐张判断。
        """
        con = self.config.kekkai_activation.activation_config
        rule = con.card_type
        target_star = con.card_star.to_int()
        swipe_limit = con.swipe_retry_limit

        if rule == CardType.TAIKO:
            min_card_num = con.min_taiko_num
            check_card = "勾玉"
        elif rule == CardType.FISH:
            min_card_num = con.min_fish_num
            check_card = "体力"
        else:
            logger.error('Unknown utilize rule')
            raise ValueError('Unknown utilize rule')

        ocr_count = 0
        self._best_seen = (0, None)
        while True:
            self.screenshot()

            # 先定位当前页每张卡的星级，再把 OCR 到的收益对到卡上
            matches = self._detect_page_cards()
            if matches:
                logger.info(
                    '本页卡片: %s' % [
                        (star, round(score, 3), area[1]) for star, score, area in matches
                    ]
                )

            results = self.O_CHECK_CARD_NUMBER.detect_and_ocr(self.device.image)
            filtered_results = [result for result in results if check_card in result.ocr_text]

            result = self._select_best_card_from_results(
                filtered_results, matches, min_card_num, target_star, ocr_count
            )
            if result:
                logger.info(f"选择挂卡: [{result.name}]")
                return result

            success, ocr_count = self._perform_swipe_action(ocr_count, swipe_limit)
            if not success:
                return None
            continue

    def _card_not_found(self):
        # 获取配置引用
        activation_config = self.config.kekkai_activation.activation_config
        # 多少分钟后重试
        retry_minutes = 180
        retry_count = 3
        # 递增未找到卡的计数器
        activation_config.card_not_found_count += 1

        # 说明这次为什么没选到：本轮最高收益 vs 配置阈值 / 星级限制
        best_value, best_star = getattr(self, '_best_seen', (0, None))
        if best_value:
            min_num = (
                activation_config.min_taiko_num
                if activation_config.card_type == CardType.TAIKO
                else activation_config.min_fish_num
            )
            star_text = f'{best_star}星' if best_star is not None else '星级未知'
            logger.warning(
                f'本轮扫到的最高收益: {best_value}（{star_text}），'
                f'阈值 {min_num}，星级上限 {activation_config.card_star.value}'
            )
            if best_value < min_num:
                logger.warning('收益阈值高于卡池实际收益，任务会一直失败，请调低阈值或放宽星级')
        else:
            logger.warning('本轮没有 OCR 到任何结界卡收益，可能列表为空或界面不在挂卡页')

        if activation_config.card_not_found_count >= retry_count:
            # 达到重试上限时的处理
            log_msg = f"⚠️{activation_config.card_type}卡未检出（累计{retry_count}次），{retry_minutes}分钟后重试"
            activation_config.card_not_found_count = 0  # 重置计数器并延长下次执行时间
            next_run = datetime.now() + timedelta(minutes=retry_minutes)
        else:
            # # 未达上限切换卡类型
            new_type = (
                CardType.FISH
                if activation_config.card_type == CardType.TAIKO
                else CardType.TAIKO
            )
            log_msg = f"🔄{activation_config.card_type}卡未检出 → 切换{new_type}"
            activation_config.card_type = new_type
            next_run = datetime.now()

        # 统一记录日志和推送
        self.save_image(content=log_msg, push_flag=True)

        # 保存配置并设置下次执行
        self.config.save()
        self.set_next_run("KekkaiActivation", target=next_run)
        raise TaskEnd

    def harvest_card(self):
        """
        收卡的经验
        :return:
        """
        self.appear_then_click(self.I_A_HARVEST_EXP)  # 如果到最后没有领的话有下面的一些图片
        self.appear_then_click(self.I_A_HARVEST_FISH4)  # 斗鱼4/5区别不大 斗鱼的如果一直没有领的话
        self.appear_then_click(self.I_A_HARVEST_KAIKO_4)  # 太鼓4
        self.appear_then_click(self.I_A_HARVEST_KAIKO_3)  # 太鼓3
        self.appear_then_click(self.I_A_HARVEST_KAIKO_6)  # 太鼓6
        self.appear_then_click(self.I_A_HARVEST_FISH_6)  # 斗鱼6
        self.appear_then_click(self.I_A_HARVEST_MOON_3)  # 太阴3
        self.appear_then_click(self.I_A_HARVEST_FISH_3)  # 斗鱼三

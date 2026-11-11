"""超鬼王门票刷取，复用觉醒和探索的战斗流程。"""
from datetime import datetime, timedelta
from cached_property import cached_property

from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.EvoZone.config import EvoZone, EvoZoneConfig, UserStatus as AwakeUserStatus
from tasks.EvoZone.script_task import ScriptTask as AwakeTask
from tasks.Exploration.config import (
    AutoRotate, Exploration, ExplorationConfig, ExplorationLevel,
    UpType, UserStatus as ExplorationUserStatus,
)
from tasks.Exploration.script_task import ScriptTask as ExplorationTask
import tasks.Exploration.page as exp_pages
from tasks.GameUi.default_pages import page_reward
import tasks.GameUi.page as pages
from tasks.MetaDemonTicket.config import TicketMode, ExplorationTarget
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.RealmRaid.script_task import ScriptTask as RealmRaidTask


class TicketsFull(Exception):
    """达到单刷或协同满票目标，停止开启下一场战斗。"""


class TicketPartnerFinished(Exception):
    """协同伙伴结束门票阶段。"""


class RealmRaidNeeded(Exception):
    """突破券达到阈值，先中断探索清个人突破再继续刷票。"""


# 突破券 OCR 间隔与清票冷却，避免识别抖动或清不干净时反复中断探索
REALM_RAID_OCR_INTERVAL = 5
REALM_RAID_RETRY_INTERVAL = timedelta(minutes=10)


def metademon_tickets_full(task) -> bool:
    """读取当前奖励截图的门票/上限；无有效上限时不判满。"""
    # I_REWARD is the red-daruma settlement image; I_UI_REWARD is the
    # separate "获得奖励" banner and does not identify this battle reward screen.
    if not task.appear(GeneralBattleAssets.I_REWARD):
        return False
    current, remaining, total = GeneralBattleAssets.O_METADEMON_PASS.ocr_digit_counter(task.device.image)
    if total <= 0 or current < 0:
        logger.warning('超鬼王门票 OCR 未识别到有效计数')
        return False
    logger.info(f'超鬼王门票: {current}/{total}')
    return current >= total


class TicketRewardMixin:
    def screenshot(self):
        result = super().screenshot()
        peer = getattr(self, '_ticket_peer', '')
        if peer and not self._ticket_farming_complete and self._battle_context is None:
            status = self.config.cooperation_runtime.peer_task_completion(
                'MetaDemonTicket', peer, self._ticket_phase_started)
            if status == 'tickets_full' and self._ticket_full:
                raise TicketsFull
            if status == 'ticket_finished':
                raise TicketPartnerFinished
        return result

    def check_ticket_reward(self):
        # 个人突破的结算页不是超鬼王门票界面，跳过避免误读门票计数
        if getattr(self, '_ticket_raid_running', False):
            return
        if getattr(self, '_ticket_farming_complete', False) or getattr(self, '_ticket_full', False):
            return
        if metademon_tickets_full(self):
            logger.info('门票已满')
            peer = getattr(self, '_ticket_peer', '')
            if not peer:
                raise TicketsFull
            self._ticket_full = True
            self.config.cooperation_runtime.notify_task_completion('MetaDemonTicket', peer, 'tickets_full')
            logger.info('本号门票已满，继续组队直到对方满票')

    def _handle_reward(self, context, config):
        self.check_ticket_reward()
        return super()._handle_reward(context, config)

    def install_ticket_reward_hook(self):
        reward = self.navigator.resolve_page(page_reward)
        # 导航进入奖励页时也必须先 OCR，再执行原来的结算点击。
        reward.on_enter_success.insert(0, lambda task: task.check_ticket_reward())


class AwakeTicketTask(TicketRewardMixin, AwakeTask):
    @cached_property
    def _config(self):
        return ticket_farming_config(self.config.meta_demon_ticket, TicketMode.AWAKE)

    def _infer_task_category(self):
        return 'evo_zone'


class ExplorationTicketTask(TicketRewardMixin, ExplorationTask):
    """探索刷票；可在突破券达到阈值时中断探索去清个人突破，清完继续刷票。"""

    _realm_raid_next: datetime = None
    _realm_raid_ocr_next: datetime = None
    _ticket_raid_running: bool = False

    @cached_property
    def _config(self):
        return ticket_farming_config(self.config.meta_demon_ticket, TicketMode.EXPLORATION)

    def _infer_task_category(self):
        return 'exploration'

    @property
    def exp_page_handle_dict(self):
        handlers = super().exp_page_handle_dict
        original = handlers[page_reward]

        def reward():
            self.check_ticket_reward()
            return original()

        handlers[page_reward] = reward
        return handlers

    def activate_realm_raid(self, con_scrolls, con, current_page):
        """检测突破券，达到阈值时中断探索循环去清个人突破。"""
        meta = self.config.meta_demon_ticket.general_config
        if not meta.realm_raid_enable:
            return
        if self.user_status != ExplorationUserStatus.ALONE:
            return
        if current_page not in (pages.page_exploration, exp_pages.page_exp_entrance):
            return
        now = datetime.now()
        if self._realm_raid_next and now < self._realm_raid_next:
            return
        if self._realm_raid_ocr_next and now < self._realm_raid_ocr_next:
            return
        self._realm_raid_ocr_next = now + timedelta(seconds=REALM_RAID_OCR_INTERVAL)
        counter = self.O_REALM_RAID_NUMBER1 if current_page == exp_pages.page_exp_entrance else self.O_REALM_RAID_NUMBER
        current, _, total = counter.ocr(self.device.image)
        if total <= 0 or current < 0:
            return
        if current >= meta.realm_raid_threshold:
            logger.info(f'突破券 {current}/{total} 达到阈值 {meta.realm_raid_threshold}，先清个人突破')
            raise RealmRaidNeeded

    def run_realm_raid_round(self):
        """复用个人突破任务配置清一次突破券，结束后切回门票御魂继续探索。"""
        logger.hr('meta demon ticket realm raid', level=2)
        self._realm_raid_next = datetime.now() + REALM_RAID_RETRY_INTERVAL
        self._realm_raid_ocr_next = None
        self._ticket_raid_running = True
        try:
            # 先用探索侧的导航退回探索入口，再交给个人突破流程接管页面跳转
            self.goto_page(pages.page_exploration)
            raid = RealmRaidTicketTask(self.config, self.device)
            raid.start_time = datetime.now()
            raid.current_count = 0
            raid.run()
        finally:
            self._ticket_raid_running = False
        # 只有个人突破实际切过御魂时才需要切回，避免多余的一次式神录往返
        raid_soul = self.config.realm_raid.switch_soul_config
        if raid_soul.enable or raid_soul.enable_switch_by_name:
            self.restore_ticket_soul()
        else:
            logger.info('个人突破未启用切换御魂，个突结束后不切回')
        self.goto_page(pages.page_exploration)
        self.device.click_record_clear()

    def restore_ticket_soul(self):
        """个突会切成突破御魂，结束必须切回门票任务的御魂再继续刷探索。"""
        soul = self._config.switch_soul_config
        if not (soul.enable or soul.enable_switch_by_name):
            logger.info('门票任务未启用切换御魂，个突结束后沿用突破御魂继续探索')
            return
        logger.info('切换回门票任务的御魂')
        self.goto_page(pages.page_shikigami_records)
        if soul.enable_switch_by_name:
            self.run_switch_soul_by_name(soul.group_name, soul.team_name)
        else:
            self.run_switch_soul(soul.switch_group_team)


class RealmRaidTicketTask(RealmRaidTask):
    """门票刷取内联清突破券，不改动个人突破任务自身的调度时间。"""

    def set_next_run(self, task: str, finish: bool = False,
                     success: bool = None, server: bool = True, target: datetime = None) -> None:
        if task == 'RealmRaid':
            return
        super().set_next_run(task=task, finish=finish, success=success, server=server, target=target)

    def run(self):
        try:
            super().run()
        except TaskEnd:
            pass


def ticket_farming_config(meta, mode):
    """仅把超鬼王专用字段适配为复用流程需要的设置，不读取独立任务配置。"""
    common = meta.general_config
    soul = meta.switch_soul_config.model_copy()
    battle = meta.general_battle_config
    if mode == TicketMode.AWAKE:
        return EvoZone(
            evo_zone_config=EvoZoneConfig(user_status=AwakeUserStatus(common.user_status.value),
                layer=common.awake_layer, kirin_type=common.awake_kirin_type,
                limit_time=common.limit_time, limit_count=2 ** 31 - 1,
                soul_buff_enable=common.awake_buff_enable),
            switch_soul_config=soul, general_battle_config=battle, invite_config=meta.invite_config)
    if mode == TicketMode.EXPLORATION:
        target = {ExplorationTarget.ALL: UpType.ALL, ExplorationTarget.COIN: UpType.COIN,
                  ExplorationTarget.EXP: UpType.EXP, ExplorationTarget.DARUMA: UpType.DARUMAA}
        if common.exploration_rotate and battle.lock_team_enable:
            battle = battle.model_copy(update={'lock_team_enable': False})
        return Exploration(
            exploration_config=ExplorationConfig(user_status=ExplorationUserStatus(common.user_status.value),
                exploration_level=ExplorationLevel.EXPLORATION_28,
                limit_time=common.limit_time, minions_cnt=2 ** 31 - 1,
                auto_rotate=AutoRotate.yes if common.exploration_rotate else AutoRotate.no,
                up_type=target[common.exploration_target]),
            switch_soul_config=soul, general_battle_config=battle, invite_config=meta.invite_config)
    raise ValueError(f'未知门票刷取模式: {mode}')


def tickets_full_before_farming(owner) -> bool:
    """Check the courtyard's exploration landing page before any farming setup."""
    owner.goto_page(pages.page_exploration)
    for _ in range(3):
        owner.screenshot()
        if not owner.appear(GameUiAssets.I_CHECK_EXPLORATION):
            continue
        current, _, total = MetaDemonAssets.O_METADEMON_PASS_EXP.ocr_digit_counter(owner.device.image)
        if current >= 0 and total > 0:
            logger.info(f'门票刷取前检测: {current}/{total}')
            return current >= total
    logger.warning('探索入口未识别到有效超鬼王门票计数，继续刷取并由奖励页检测满票')
    return False


def run_exploration_farming(runner) -> None:
    """探索刷票主循环；突破券达到阈值时先清一轮个人突破，再继续刷票。"""
    while True:
        try:
            runner.exec_exp_page()
            return
        except RealmRaidNeeded:
            runner.run_realm_raid_round()


def run_ticket_farming(owner, mode) -> bool:
    """共享运行环境；御魂和战斗参数直接使用超鬼王门票刷取配置。"""
    if mode not in (TicketMode.AWAKE, TicketMode.EXPLORATION):
        raise ValueError(f'未知门票刷取模式: {mode}')
    config = getattr(owner, 'config', None)
    runtime = getattr(config, 'cooperation_runtime', None)
    peer = ''
    if runtime is not None:
        meta = config.meta_demon_ticket
        target = meta.invite_config.cooperation_script or runtime.peers.get('MetaDemonTicket', '')
        if target and meta.general_config.user_status != ExplorationUserStatus.ALONE:
            if runtime.matches_meta_demon_tickets(target):
                peer = target
            else:
                logger.warning(f'超鬼王门票刷取协同配置不匹配：{target}，跳过本轮，避免按本号满票提前退出')
                return False
    local_full = tickets_full_before_farming(owner)
    if local_full and not peer:
        logger.info('超鬼王门票已满，跳过门票刷取')
        return True
    role = config.meta_demon_ticket.general_config.user_status
    limit_time = config.meta_demon_ticket.general_config.limit_time_v
    if mode == TicketMode.AWAKE:
        runner = AwakeTicketTask(config, owner.device)
    elif mode == TicketMode.EXPLORATION:
        runner = ExplorationTicketTask(config, owner.device)
    else:
        raise ValueError(f'未知门票刷取模式: {mode}')
    runner.start_time = datetime.now()
    runner.current_count = 0
    runner.limit_count = 2 ** 31 - 1
    # 避免复用流程按独立觉醒或探索任务名发起协同。
    runner._battle_cooperation_prepared = True
    runner._ticket_farming_complete = False
    runner._ticket_full = local_full
    runner.install_ticket_reward_hook()
    buff_opened = False
    cooperation_started = False
    result = False
    try:
        if peer:
            runner._ticket_phase_started = runtime.begin_completion_phase('MetaDemonTicket', peer)
            if not runtime.prepare(config, 'MetaDemonTicket', peer, defer=False):
                return False
            cooperation_started = True
            runtime.peers['MetaDemonTicket'] = peer
            runner._ticket_peer = peer
            runner._battle_cooperation_task = 'MetaDemonTicket'
            if local_full:
                runtime.notify_task_completion('MetaDemonTicket', peer, 'tickets_full')
                logger.info('本号门票已满，继续组队直到对方满票')
        if mode == TicketMode.AWAKE:
            if config.meta_demon_ticket.general_config.realm_raid_enable:
                logger.warning('突破券清理仅在「门票刷取：探索」下生效，本次觉醒刷票不检测突破券')
            soul = runner._config.switch_soul_config
            if soul.enable or soul.enable_switch_by_name:
                runner.goto_page(pages.page_shikigami_records)
                if soul.enable_switch_by_name:
                    runner.run_switch_soul_by_name(soul.group_name, soul.team_name)
                else:
                    runner.run_switch_soul(soul.switch_group_team)
            if config.meta_demon_ticket.general_config.awake_buff_enable:
                runner.goto_page(pages.page_main)
                runner.open_buff()
                runner.awake(is_open=True)
                buff_opened = True
                runner.close_buff()
            runner.limit_time = limit_time
            if role == ExplorationUserStatus.LEADER:
                runner.run_leader()
            elif role == ExplorationUserStatus.MEMBER:
                runner.run_member()
            else:
                runner.run_alone()
        else:
            runner.pre_process()
            runner.limit_time = limit_time
            run_exploration_farming(runner)
    except TicketsFull:
        result = True
        if cooperation_started:
            logger.info('双方门票已满，结束协同刷取')
    except TicketPartnerFinished:
        logger.info('协同伙伴已结束门票刷取，退出组队')
    finally:
        runner._ticket_farming_complete = True
        if cooperation_started:
            runtime.notify_task_completion('MetaDemonTicket', peer, 'tickets_full' if result else 'ticket_finished')
        if cooperation_started or (not peer and role != ExplorationUserStatus.ALONE) or buff_opened:
            runner.goto_page(pages.page_main)
        if buff_opened:
            runner.open_buff()
            runner.awake(is_open=False)
            runner.close_buff()
    return result

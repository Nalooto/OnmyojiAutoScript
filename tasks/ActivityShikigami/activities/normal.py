from module.logger import logger
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.ActivityShikigami.base_act import BaseAct
import tasks.ActivityShikigami.page as pages
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import ExitMatcher


class NormalClimbAct(BaseAct):
    """普通爬塔活动"""

    def _exit_matcher(self) -> ExitMatcher | None:
        return pages.any_of(self.I_ACT_FIRE, self.I_AS_BOSS_FIRE)

    def before_run(self):
        super().before_run()
        page_act_pass = self.navigator.resolve_page(pages.page_act_pass)
        page_act_ap = self.navigator.resolve_page(pages.page_act_ap)

        # 体力爬塔进入是门票则切换
        page_act_ap.add_enter_failure_hooks(
            pages.conditional_action(
                condition=ActivityShikigamiAssets.I_CLIMB_MODE_PASS,
                action=ActivityShikigamiAssets.I_CLIMB_MODE_SWITCH,
            )
        )

        # 门票爬塔进入是体力则切换
        page_act_pass.add_enter_failure_hooks(
            pages.conditional_action(
                condition=ActivityShikigamiAssets.I_CLIMB_MODE_AP,
                action=ActivityShikigamiAssets.I_CLIMB_MODE_SWITCH,
            )
        )
        # 门票和体力互相切换
        page_act_pass.connect(
            page_act_ap,
            ActivityShikigamiAssets.I_CLIMB_MODE_SWITCH,
            key="page_act_pass->page_act_ap",
        )
        page_act_ap.connect(
            page_act_pass,
            ActivityShikigamiAssets.I_CLIMB_MODE_SWITCH,
            key="page_act_ap->page_act_pass",
        )

    def lock_team(self, battle_conf: GeneralBattleConfig):
        enable = battle_conf.lock_team_enable
        match self.climb_type:
            case "pass":
                lock_rule = self.I_LOCK
                unlock_rule = self.I_UNLOCK
            case "ap":
                lock_rule = self.I_AP_LOCK
                unlock_rule = self.I_AP_UNLOCK
            case "ap100":
                lock_rule = self.I_AP100_LOCK
                unlock_rule = self.I_AP100_UNLOCK
            case _:
                lock_rule = self.I_LOCK
                unlock_rule = self.I_UNLOCK
                
        if enable:
            logger.info(f"Lock {self.climb_type} team")
            self._set_team_lock_state(unlock_rule, lock_rule, "lock")
            return
        logger.info(f"Unlock {self.climb_type} team")
        self._set_team_lock_state(lock_rule, unlock_rule, "unlock")

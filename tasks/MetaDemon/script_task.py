# This Python file uses the following encoding: utf-8
from datetime import datetime
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import MetaDemonMode


class ScriptTask(BossBattle):
    """超鬼王战斗和协助入口。"""

    def run(self):
        mode = self.config.meta_demon.meta_demon_config.mode
        if mode == MetaDemonMode.BOSS_ASSIST:
            from tasks.MetaDemon.assistance import run_assistance
            self.start_time = datetime.now()
            return run_assistance(self)
        self.start_time = datetime.now()
        return super().run()

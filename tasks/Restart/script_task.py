# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import datetime

from module.exception import RequestHumanTakeover, TaskEnd
from module.logger import logger
from tasks.Component.Login.service import LoginService
from tasks.Restart.server_update import delay_pending_tasks_for_server_update, is_server_update_window
from tasks.base_task import BaseTask

# 启动游戏后黑屏时，重启模拟器实例的最大尝试次数
BLACK_SCREEN_RECOVER_ATTEMPTS = 2
# 画面未就绪时，先只重启游戏（不动模拟器）的次数
APP_ONLY_RESTART_ATTEMPTS = 1


class ScriptTask(BaseTask):
    def _set_runtime_outcome(self, status: str, wait_until: datetime | None = None) -> None:
        outcome = {
            'task': 'Restart',
            'status': status,
        }
        if wait_until is not None:
            outcome['wait_until'] = wait_until
        self.config.task_runtime_outcome = outcome

    def run(self) -> None:
        """
        主要就是登录的模块
        :return:
        """
        try:
            self.recover_app()
            self.finish_recovery()
        except RequestHumanTakeover:
            if not self.delay_pending_tasks(reason='login failed during Restart recovery'):
                raise
        raise TaskEnd

    def app_stop(self):
        logger.hr('App stop')
        self.device.app_stop()

    def _login_after_ready(self) -> bool:
        """
        等待游戏首帧就绪后执行登录。

        Returns:
            bool: True 表示画面已就绪并完成登录；False 表示画面未就绪。
        """
        if not self.device.wait_app_start_ready():
            return False
        LoginService(config=self.config, device=self.device).app_handle_login()
        return True

    def app_start(self):
        logger.hr('App start')
        self.device.app_start()
        if self._login_after_ready():
            return

        reason = getattr(self.device, 'app_start_failure_reason', None)
        logger.warning(f'[black-screen] game not ready after app start, reason={reason}')

        # 先只重启游戏：模拟器冷启动要 30s 左右，四开时还会和其它实例抢 CPU 与磁盘，
        # 而大多数「卡在加载」只是游戏进程自身没起来，重启游戏就能恢复。
        for attempt in range(1, APP_ONLY_RESTART_ATTEMPTS + 1):
            logger.warning(f'[black-screen] restart app only, attempt {attempt}/{APP_ONLY_RESTART_ATTEMPTS}')
            self.device.app_stop()
            self.device.app_start()
            if self._login_after_ready():
                logger.info('[black-screen] recovered after restarting app')
                return

        # 重启游戏仍然不行，才认为模拟器渲染 / 图形驱动异常，强杀并重启模拟器实例
        logger.warning('[black-screen] app restart did not help, recover by restarting emulator')
        self.recover_black_screen()
        LoginService(config=self.config, device=self.device).app_handle_login()

    def recover_black_screen(self):
        """
        黑屏恢复：强杀并重启当前模拟器实例，再重新启动游戏。

        与 LoginService 的“重启游戏一次”不同，这里解决的是模拟器侧的渲染异常，
        只有重启模拟器实例才能恢复。

        Raises:
            RequestHumanTakeover: 重启模拟器后依然黑屏。
        """
        restart = getattr(self.device, 'emulator_restart_stuck', None)
        if restart is None:
            raise RequestHumanTakeover('Game screen stayed black and current platform cannot restart emulator')

        for attempt in range(1, BLACK_SCREEN_RECOVER_ATTEMPTS + 1):
            logger.warning(f'[black-screen] recovery attempt {attempt}/{BLACK_SCREEN_RECOVER_ATTEMPTS}')
            if not restart():
                logger.warning('[black-screen] restart emulator failed, try next attempt')
                continue

            self.device.app_start()
            if self.device.wait_app_start_ready():
                logger.info('[black-screen] recovered after restarting emulator')
                return

        logger.critical('Game screen is still black after restarting emulator')
        raise RequestHumanTakeover('Game screen stayed black after restarting emulator')

    def app_restart(self):
        logger.hr('App restart')
        self.device.app_stop()
        self.app_start()

    def recover_app(self):
        if not self.device.app_is_alive():
            logger.info('Recovery branch: game process not alive and not in foreground -> full restart')
            self.app_restart()
            return

        if self.device.app_is_running():
            logger.info('Recovery branch: game process alive and in foreground -> full restart')
            self.app_restart()
            return

        logger.info('Recovery branch: game process alive but in background -> bring to foreground')
        self.app_start()

    def finish_recovery(self):
        self.set_next_run(task='Restart', success=True, finish=True, server=True)
        if self.config.model.restart.restart_config.enable_daily:
            self.config.task_call('DailyTrifles')
        self._set_runtime_outcome(status='recovered')

    def delay_pending_tasks(self, reason: str) -> bool:
        """
        仅在早间登录失败时，统一延后待执行任务。
        @return:
        """
        if not is_server_update_window():
            return False
        delay_target = delay_pending_tasks_for_server_update(self.config, reason=reason)
        self._set_runtime_outcome(status='server_update_delayed', wait_until=delay_target)
        return True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    config = Config('oas1')
    device = Device(config)
    task = ScriptTask(config, device)
    task.app_restart()

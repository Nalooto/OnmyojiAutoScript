
from collections import deque
from datetime import datetime
import time

# Patch pkg_resources before importing adbutils and uiautomator2
from module.device.pkg_resources import get_distribution
# Just avoid being removed by import optimization
_ = get_distribution

from module.base.utils import get_color
from module.device.env import IS_WINDOWS
from module.base.timer import Timer
from module.config.utils import get_server_next_update
from module.device.app_control import AppControl
from module.device.control import Control
from module.device.platform2 import Platform
from module.device.screenshot import Screenshot
from module.exception import (GameNotRunningError,
                              GameStuckError,
                              GameTooManyClickError,
                              RequestHumanTakeover,
                              EmulatorNotRunningError)
from module.logger import logger


class Device(Platform, Screenshot, Control, AppControl):
    _screen_size_checked = False
    # 启动游戏后，画面三通道均值之和低于该值视为黑屏
    # 实测：纯黑屏接近 0，游戏加载界面约 67，主界面 190+，取 20 有足够余量
    APP_START_MIN_COLOR_SUM = 20.0
    # 等待游戏首帧的总时长上限。四开冷启动时单次截图/adb 调用会卡住数秒，
    # 45s 在满载机器上会被一两轮探测直接吃光，放宽到 90s。
    APP_START_TIMEOUT = 90.0
    # 连续多少次「截图通道异常」判定为通道故障，需要重建截图连接。
    # 探针异常只说明“看不到”，不是黑屏证据，不能计入黑屏超时。
    APP_START_PROBE_FAIL_LIMIT = 3
    # 单轮探测耗时超过该值时打印告警，便于定位是卡在截图还是卡在 adb
    APP_START_SLOW_ITERATION = 10.0
    # 上一次 wait_app_start_ready() 的失败原因：'black' / 'probe' / 'app_not_running'
    app_start_failure_reason = None
    detect_record = set()
    click_record = deque(maxlen=15)
    stuck_timer = Timer(60, count=60).start()
    stuck_timer_long = Timer(300, count=300).start()
    stuck_long_wait_list = ['BATTLE_STATUS_S', 'PAUSE', 'LOGIN_CHECK', 'PREPARE_BEFORE_BATTLE']

    def __init__(self, *args, **kwargs):
        # emulator_start() 内部已经带了“关机 + 强制结束进程 + 重启”的多轮重试，
        # 外层只需要再兜一轮，否则启动失败时会连续重试非常久
        max_trials = 2
        for trial in range(max_trials):
            try:
                super().__init__(*args, **kwargs)
                break
            except EmulatorNotRunningError:
                if trial >= max_trials - 1:
                    logger.critical(f'Failed to start emulator after {max_trials} trial')
                    raise RequestHumanTakeover
                # Try to start emulator
                if self.emulator_instance is not None:
                    self.emulator_start()
                else:
                    logger.critical(
                        f'No emulator with serial "{self.config.Emulator_Serial}" found, '
                        f'please set a correct serial'
                    )
                    raise RequestHumanTakeover

        # Auto-fill emulator info
        if IS_WINDOWS and self.config.script.device.emulatorinfo_type == 'auto':
            _ = self.emulator_instance

        self.screenshot_interval_set()
        self._image_batch_cache_frame_id: str | None = None
        self._image_batch_cache: dict[int, dict] = {}

        # Auto-select the fastest screenshot method
        if self.config.script.device.screenshot_method == 'auto':
            self.run_simple_screenshot_benchmark()

    def reset_image_batch_cache(self, frame_id: str | None = None) -> None:
        self._image_batch_cache_frame_id = frame_id
        self._image_batch_cache = {}

    def invalidate_image_batch_cache(self) -> None:
        self.reset_image_batch_cache()

    def get_image_batch_cache(self, target, frame_id: str | None = None) -> dict | None:
        active_frame_id = self.image_frame_id if frame_id is None else frame_id
        if active_frame_id is None:
            return None
        if self._image_batch_cache_frame_id != active_frame_id:
            return None
        return self._image_batch_cache.get(id(target))

    def update_image_batch_cache(self, targets: list, results: list[dict], frame_id: str | None = None) -> None:
        active_frame_id = self.image_frame_id if frame_id is None else frame_id
        if active_frame_id is None:
            return
        if self._image_batch_cache_frame_id != active_frame_id:
            self.reset_image_batch_cache(active_frame_id)
        for target, result in zip(targets, results):
            self._image_batch_cache[id(target)] = dict(result)

    def run_simple_screenshot_benchmark(self):
        """
        Perform a screenshot method benchmark, test 3 times on each method.
        The fastest one will be set into config.
        """
        logger.info('run_simple_screenshot_benchmark')
        # Check resolution first
        # self.resolution_check_uiautomator2()
        # Perform benchmark
        from module.daemon.benchmark import Benchmark
        bench = Benchmark(config=self.config, device=self)
        method = bench.run_simple_screenshot_benchmark()
        # Set
        self.config.script.device.screenshot_method = method
        self.config.save()

    def handle_night_commission(self, daily_trigger='21:00', threshold=30):
        """
        Args:
            daily_trigger (int): Time for commission refresh.
            threshold (int): Seconds around refresh time.

        Returns:
            bool: If handled.
        """
        update = get_server_next_update(daily_trigger=daily_trigger)
        now = datetime.now()
        diff = (update.timestamp() - now.timestamp()) % 86400
        if threshold < diff < 86400 - threshold:
            return False

        # if GET_MISSION.match(self.image, offset=True):
        #     logger.info('Night commission appear.')
        #     self.click(GET_MISSION)
        #     return True

        return False

    def screenshot(self):
        """
        Returns:
            np.ndarray:
        """
        self.stuck_record_check()

        try:
            super().screenshot()
        except RequestHumanTakeover as e:
            raise RequestHumanTakeover

        if self.handle_night_commission():
            super().screenshot()

        self.reset_image_batch_cache(self.image_frame_id)
        return self.image

    def release_during_wait(self):
        # Scrcpy server is still sending video stream,
        # stop it during wait
        # self.config.script.device.screenshot_method = 'scrcpy'
        if self.config.script.device.screenshot_method == 'scrcpy':
            self._scrcpy_server_stop()
        if self.config.Emulator_ScreenshotMethod == 'nemu_ipc':
            self.nemu_ipc_release()

    def stuck_record_add(self, button):
        """
        当你要设置这个时候检测为长时间的时候，你需要在这里添加
        如果取消后，需要在`stuck_record_clear`中清除
        :param button:
        :return:
        """
        self.detect_record.add(str(button))
        logger.info(f'Add stuck record: {button}')

    def stuck_record_clear(self):
        self.detect_record = set()
        self.stuck_timer.reset()
        self.stuck_timer_long.reset()

    def stuck_record_check(self):
        """
        Raises:
            GameStuckError:
        """
        reached = self.stuck_timer.reached()
        reached_long = self.stuck_timer_long.reached()

        if not reached:
            return False
        if not reached_long:
            for button in self.stuck_long_wait_list:
                if button in self.detect_record:
                    return False

        logger.warning('Wait too long')
        logger.warning(f'Waiting for {self.detect_record}')
        self.stuck_record_clear()

        if self.app_is_running():
            raise GameStuckError(f'Wait too long')
        else:
            raise GameNotRunningError('Game died')

    def handle_control_check(self, button):
        self.stuck_record_clear()
        self.click_record_add(button)
        self.click_record_check()

    def click_record_add(self, button):
        self.click_record.append(str(button))

    def click_record_clear(self):
        self.click_record.clear()

    def click_record_remove(self, button):
        """
        Remove a button from `click_record`

        Args:
            button (Button):

        Returns:
            int: Number of button removed
        """
        removed = 0
        for _ in range(self.click_record.maxlen):
            try:
                self.click_record.remove(str(button))
                removed += 1
            except ValueError:
                # Value not in queue
                break

        return removed

    def click_record_check(self):
        """
        Raises:
            GameTooManyClickError:
        """
        count = {}
        for key in self.click_record:
            count[key] = count.get(key, 0) + 1
        count = sorted(count.items(), key=lambda item: item[1], reverse=True)
        if count[0][1] >= 10:
            logger.warning(f'Too many click for a button: {count[0][0]}')
            logger.warning(f'History click: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise GameTooManyClickError(f'Too many click for a button: {count[0][0]}')
        if len(count) >= 2 and count[0][1] >= 6 and count[1][1] >= 6:
            logger.warning(f'Too many click between 2 buttons: {count[0][0]}, {count[1][0]}')
            logger.warning(f'History click: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise GameTooManyClickError(f'Too many click between 2 buttons: {count[0][0]}, {count[1][0]}')

    def disable_stuck_detection(self):
        """
        Disable stuck detection and its handler. Usually uses in semi auto and debugging.
        """
        logger.info('Disable stuck detection')

        def empty_function(*arg, **kwargs):
            return False

        self.click_record_check = empty_function
        self.stuck_record_check = empty_function

    def app_start(self):
        if not self.config.script.error.handle_error:
            logger.critical('No app stop/start, because HandleError disabled')
            logger.critical('Please enable Alas.Error.HandleError or manually login to AzurLane')
            raise RequestHumanTakeover
        super().app_start()
        self.stuck_record_clear()
        self.click_record_clear()

    def app_stop(self):
        if not self.config.script.error.handle_error:
            logger.critical('No app stop/start, because HandleError disabled')
            logger.critical('Please enable Alas.Error.HandleError or manually login to AzurLane')
            raise RequestHumanTakeover
        super().app_stop()
        self.stuck_record_clear()
        self.click_record_clear()

    def rebuild_screenshot_channel(self):
        """
        重建 nemu_ipc 截图通道。

        模拟器实例被重启后，旧的 rpc 连接失效，而 nemu_ipc 的 retry 里
        ``except Exception`` 分支不会重连，导致后续截图永久失败，只能重启脚本进程恢复。
        这里主动释放并重新建立连接。
        """
        if self.config.script.device.screenshot_method != 'nemu_ipc':
            return
        if not hasattr(self, 'nemu_ipc_release'):
            return

        logger.warning('[app-start] rebuilding nemu_ipc screenshot channel')
        try:
            self.nemu_ipc_release()
        except Exception as e:
            logger.warning(f'[app-start] release nemu_ipc failed: {e}')
        try:
            _ = self.nemu_ipc
            logger.info('[app-start] nemu_ipc reconnected')
        except Exception as e:
            logger.warning(f'[app-start] reconnect nemu_ipc failed: {e}')

    def wait_app_start_ready(self, timeout: float = None, interval: float = 0.5) -> bool:
        """
        在启动app后，等待包名切换成功且画面脱离纯黑状态。

        这里直接调用底层截图方法做静默探测，避免app刚启动时首屏黑场造成成批告警。
        正常画面（哪怕是加载界面）三通道均值之和通常在 60 以上，纯黑屏接近 0，
        因此用 APP_START_MIN_COLOR_SUM 作为“黑屏”判据。

        只有“成功截到图且画面为黑”才算黑屏证据；截图通道异常时本轮探测无效，
        不累计黑屏超时，连续多次异常会重建截图连接。避免出现
        「截图通道挂掉 → 误判黑屏 → 重启模拟器 → 更慢」的雪崩。

        Args:
            timeout: 最大等待秒数，默认取 APP_START_TIMEOUT。
            interval: 每轮探测的间隔秒数。

        Returns:
            bool: True 表示画面已经有内容，False 表示超时仍未就绪。
            失败原因记录在 self.app_start_failure_reason，取值 'black' / 'probe' / 'app_not_running'。
        """
        timeout = self.APP_START_TIMEOUT if timeout is None else timeout
        deadline = time.time() + timeout
        screenshot_method = self.screenshot_methods.get(
            self.config.script.device.screenshot_method,
            self.screenshot_adb
        )

        valid_black = 0         # 成功截图且判定为黑的次数
        probe_fail = 0          # 连续截图异常次数
        total_probe_fail = 0    # 截图异常总次数
        app_down = 0            # app 不在前台的次数
        next_black_log = 1      # 下一次打印黑屏进度所需的 valid_black
        self.app_start_failure_reason = None

        while time.time() < deadline:
            start = time.time()

            try:
                running = self.app_is_running()
            except Exception as e:
                logger.info(f'Wait game start ready: foreground check failed: {e}')
                running = None

            if running is False:
                app_down += 1
                if app_down % 10 == 0:
                    logger.info(f'Wait game start ready: game not in foreground, '
                                f'checks={app_down}, elapsed={time.time() - (deadline - timeout):.1f}s')
                time.sleep(interval)
                continue

            try:
                image = screenshot_method()
            except Exception as e:
                probe_fail += 1
                total_probe_fail += 1
                logger.warning(
                    f'Wait game start ready: screenshot probe failed '
                    f'({probe_fail}/{self.APP_START_PROBE_FAIL_LIMIT}): {e}')
                if probe_fail >= self.APP_START_PROBE_FAIL_LIMIT:
                    try:
                        self.rebuild_screenshot_channel()
                    except Exception as rebuild_error:
                        logger.warning(f'[app-start] rebuild screenshot channel failed: {rebuild_error}')
                    probe_fail = 0
                time.sleep(interval)
                continue

            probe_fail = 0
            color = get_color(image, area=(0, 0, 1280, 720))
            if sum(color) >= self.APP_START_MIN_COLOR_SUM:
                logger.info(f'Game start ready, frame color: {color}')
                return True

            valid_black += 1
            # 首帧之后按指数退避打印，避免刷屏又保留进度
            if valid_black >= next_black_log:
                logger.info(
                    f'Game screen is black, keep waiting: frame color: {color}, '
                    f'black frames={valid_black}, elapsed={time.time() - (deadline - timeout):.1f}s')
                next_black_log = max(next_black_log * 2, 20)

            cost = time.time() - start
            if cost >= self.APP_START_SLOW_ITERATION:
                logger.warning(f'Wait game start ready: slow probe iteration took {cost:.1f}s')
            time.sleep(interval)

        if valid_black > 0:
            self.app_start_failure_reason = 'black'
            detail = f'screen is still black ({valid_black} black frames)'
        elif total_probe_fail > 0:
            self.app_start_failure_reason = 'probe'
            detail = f'screenshot channel kept failing ({total_probe_fail} failures)'
        else:
            self.app_start_failure_reason = 'app_not_running'
            detail = 'game process never reached foreground'
        logger.warning(f'Wait game start ready timeout after {timeout:.0f}s, {detail}')
        return False


if __name__ == "__main__":
    device = Device(config="oas1")
    # cv2.imshow("imgSrceen", device.screenshot())  # 显示
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()

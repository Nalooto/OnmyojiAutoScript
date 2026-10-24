import json
import os
import re
import subprocess
import typing as t

from module.device.platform2.handlers.base import EmulatorHandler
from module.logger import logger

# MuMuManager 查询实例信息的超时时间（秒），查询只是本地 RPC，正常在 1s 内返回
MUMU_INFO_TIMEOUT = 10


class MuMu12Handler(EmulatorHandler):
    """现代 MuMu（Android 12/15）Handler，保留原配置类型以兼容旧配置。"""
    MuMuPlayer12 = 'MuMuPlayer12'
    INSTANCE_NAME_PATTERNS = (
        re.compile(r'MuMuPlayer(?:Global)?-\d+(?:\.\d+)*-(\d+)'),
        re.compile(r'YXArkNights-\d+(?:\.\d+)*-(\d+)'),
    )

    @staticmethod
    def type_names() -> list[str]:
        return ['MuMuPlayer12']

    @staticmethod
    def path_to_type(path: str, exe: str, dir1: str, dir2: str) -> str:
        if exe in ['mumuplayer.exe', 'mumunxmain.exe']:
            return 'MuMuPlayer12'
        return ''

    @staticmethod
    def multi_to_single(exe: str) -> list[str]:
        if 'MuMuMultiPlayer.exe' in exe:
            return [exe.replace('MuMuMultiPlayer.exe', 'MuMuPlayer.exe')]
        if 'MuMuManager.exe' in exe:
            return [exe.replace('MuMuManager.exe', 'MuMuPlayer.exe')]
        return []

    @staticmethod
    def single_to_console(exe: str) -> t.Optional[str]:
        if 'MuMuPlayer.exe' in exe:
            return exe.replace('MuMuPlayer.exe', 'MuMuManager.exe')
        if 'MuMuNxMain.exe' in exe:
            return exe.replace('MuMuNxMain.exe', 'MuMuManager.exe')
        return None

    def get_instance_id(self, instance) -> t.Optional[int]:
        name = getattr(instance, 'name', '')
        if not isinstance(name, str):
            return None
        for pattern in self.INSTANCE_NAME_PATTERNS:
            res = pattern.fullmatch(name)
            if res:
                return int(res.group(1))
        return None

    def _console_path(self, instance) -> t.Optional[str]:
        """静默解析 MuMuManager.exe 路径，解析失败返回 None（不打印日志，供轮询调用）。"""
        exe = getattr(getattr(instance, 'emulator', None), 'path', '')
        console = self.single_to_console(exe) if isinstance(exe, str) else None
        if not console or not os.path.isfile(console):
            return None
        return console

    def _resolve_console(self, instance) -> t.Optional[str]:
        console = self._console_path(instance)
        if console is None:
            exe = getattr(getattr(instance, 'emulator', None), 'path', '')
            logger.warning(f'Cannot resolve MuMu control executable from path {exe}')
        return console

    @staticmethod
    def run_console(console: str, args: list[str]) -> t.Optional[str]:
        """
        同步执行 MuMuManager 并返回标准输出（失败返回 None）。

        Args:
            console: MuMuManager.exe 路径。
            args: 子命令参数。

        Returns:
            str: 标准输出；执行失败返回 None。
        """
        command = [console, *args]
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                timeout=MUMU_INFO_TIMEOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except Exception as e:
            logger.info(f'[mumu] run console command failed: {command}, error={e}')
            return None

        if proc.returncode != 0:
            stderr = proc.stderr.decode('utf-8', errors='ignore').strip()
            logger.info(f'[mumu] console command returned {proc.returncode}: {command}, stderr={stderr}')
            return None
        return proc.stdout.decode('utf-8', errors='ignore').strip()

    def iter_instances(self, emulator) -> t.Iterable:
        from module.device.platform2.emulator_windows import EmulatorInstance, Emulator
        from module.device.platform2.utils import iter_folder

        # vms/MuMuPlayer-12.0-0 or vms/MuMuPlayer-15.0-0
        for folder in emulator.list_folder('../vms', is_dir=True):
            for file in iter_folder(folder, ext='.nemu'):
                serial = Emulator.vbox_file_to_serial(file)
                name = os.path.basename(folder)
                if serial:
                    yield EmulatorInstance(
                        serial=serial,
                        name=name,
                        path=emulator.path,
                    )
                else:
                    # Fix for MuMu12 v4.0.4
                    instance = EmulatorInstance(
                        serial=serial,
                        name=name,
                        path=emulator.path,
                    )
                    mumu_id = self.get_instance_id(instance)
                    if mumu_id is not None:
                        instance.serial = f'127.0.0.1:{16384 + 32 * mumu_id}'
                        yield instance

    def iter_adb_binaries(self, emulator) -> t.Iterable[str]:
        # MuMu12 特有: ../vmonitor/bin/adb_server.exe
        exe = emulator.abspath('../vmonitor/bin/adb_server.exe')
        if os.path.exists(exe):
            yield exe
        yield from self._iter_common_adb(emulator)

    def start_show_window(self) -> bool:
        # MuMu12 通过 MuMuManager 启动，命令本身不需要窗口
        return False

    def build_start_command(self, instance) -> t.Optional[str]:
        mumu_id = self.get_instance_id(instance)
        if mumu_id is None:
            logger.warning(f'Cannot get MuMu instance index from name {instance.name}')
            return None
        console = self._resolve_console(instance)
        if console is None:
            return None
        # MuMuManager.exe control -v 0 launch
        return f'"{console}" control -v {mumu_id} launch'

    def build_stop_command(self, instance) -> t.Optional[str]:
        mumu_id = self.get_instance_id(instance)
        if mumu_id is None:
            logger.warning(f'Cannot get MuMu instance index from name {instance.name}')
            return None
        console = self._resolve_console(instance)
        if console is None:
            return None
        # MuMuManager.exe control -v 1 shutdown
        return f'"{console}" control -v {mumu_id} shutdown'

    def query_state(self, instance) -> t.Optional[dict]:
        """
        通过 `MuMuManager.exe info -v N` 获取实例的真实启动状态。

        通过 is_process_started / is_android_started 可以区分三种典型情况：
        - 未启动：两者都是 False
        - 启动中或卡在启动动画（如 98%）：进程已起但安卓未起
        - 启动完成：两者都是 True

        Args:
            instance: 模拟器实例。

        Returns:
            dict: 状态字典，查询失败返回 None。
        """
        mumu_id = self.get_instance_id(instance)
        console = self._console_path(instance)
        if mumu_id is None or console is None:
            return None

        output = self.run_console(console, ['info', '-v', str(mumu_id)])
        if not output or not output.startswith('{'):
            return None
        try:
            data = json.loads(output)
        except json.JSONDecodeError as e:
            logger.info(f'[mumu] decode instance info failed: {e}')
            return None

        launch_err_code = data.get('launch_err_code') or 0
        launch_err_msg = str(data.get('launch_err_msg') or '')
        if launch_err_msg:
            error = launch_err_msg
        elif launch_err_code:
            error = f'launch_err_code={launch_err_code}'
        else:
            error = ''

        return {
            'process_started': bool(data.get('is_process_started')),
            'android_started': bool(data.get('is_android_started')),
            'phase': str(data.get('player_state') or ''),
            'error': error,
            'pid': data.get('pid'),
            'vt_enabled': data.get('vt_enabled'),
            'hyperv_enabled': data.get('hyperv_enabled'),
        }

    def force_kill_regex(self, instance) -> t.Optional[str]:
        """
        构造仅命中该实例的进程正则。

        MuMu12(nx) 的进程结构：
        - MuMuNxMain.exe：多开共用的主进程，绝对不能杀
        - MuMuNxDevice.exe -v N --vm MuMuPlayer-12.0-N：每实例一个设备进程
        - MuMuVMMHeadless.exe --comment MuMuPlayer-12.0-N：每实例一个虚拟机进程
          注意它的父进程是共用的 MuMuVMMSVC.exe，所以不能用 /t 连带 kill

        Args:
            instance: 模拟器实例。

        Returns:
            str: cmdline 正则，无法构造时返回 None。
        """
        mumu_id = self.get_instance_id(instance)
        name = getattr(instance, 'name', '')
        patterns = []
        if isinstance(name, str) and name:
            # cmdline 里的反斜杠会被替换成 /，参数之间仍是空格
            quoted = re.escape(name)
            patterns.append(rf'--vm[\s/]+{quoted}\b')
            patterns.append(rf'--comment[\s/]+{quoted}\b')
        if mumu_id is not None:
            patterns.append(rf'MuMuNxDevice\.exe[\s/]+-v[\s/]+{mumu_id}\b')
            patterns.append(rf'MuMuHeadless\.exe[\s/]+-v[\s/]+{mumu_id}\b')
        if not patterns:
            return None
        return '(' + '|'.join(patterns) + ')'

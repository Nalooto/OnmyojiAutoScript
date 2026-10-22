# This Python file uses the following encoding: utf-8
"""角色资产统计：在游戏进程内读取资产数据。

实现方式与 平安志 的 MuMu 快照一致：把 frida-server 推进模拟器，attach 到游戏
进程后通过 libclient.so 导出的 CPython API 执行一段 Python，让游戏自己把
`Globals.player1.currency` 等数据序列化成 JSON，再拉回本机。

与 OCR 方案相比，这里拿到的都是游戏内存里的原始数值，不受界面分辨率、遮挡、
字体和识别误差影响。
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

from module.logger import logger

REMOTE_FRIDA = '/data/local/tmp/frida-server'
REMOTE_LOG = '/data/local/tmp/frida-server.log'
FRIDA_PORT = 27042

# （key, 显示名, 游戏图标名, 取值方式）
#   currency:<id>  -> player1.currency[id]
#   hero:<heroId>  -> player1.heroes 中该 heroId 的数量
#   name:<名称>    -> 在货币配置里按名称反查 id 后取值
ASSET_ITEMS = [
    ('gold', '金币', 'icon_jinbi', 'currency:900001'),
    ('ap', '体力', 'icon_tili', 'currency:900003'),
    ('jade', '勾玉', 'icon_gouyu', 'currency:900002'),
    ('mystery_amulet', '神秘的符咒', 'icon_choukaquan', 'currency:490001'),
    ('black_daruma', '御行达摩', 'damobudaoweng_hei', 'hero:411'),
    ('black_daruma_shard', '御行达摩碎片', 'damobudaoweng_hei', 'currency:434111'),
    ('real_amulet', '现世符咒', 'icon_choukaquan03', 'currency:490004'),
    ('soul_jade', '魂玉', '', 'name:魂玉'),
    ('oro_scale', '大蛇的逆鳞', 'icon_shelin_01', 'currency:900217'),
    ('demon_soul', '逢魔之魂', 'icon_shoulingsuipian', 'currency:900218'),
    ('yuling_key', '御灵境之钥', 'icon_yulingquan', 'currency:900215'),
    ('hyakki_ticket', '百鬼夜行门票', 'icon_baiguiyexingmenpiao', 'currency:900007'),
    ('honor', '荣誉', 'icon_rongyu', 'currency:900012'),
    ('medal', '勋章', 'icon_doufajifen', 'currency:900016'),
    ('contrib', '功勋', 'icon_liaozha', 'currency:900090'),
    ('scroll_shard_large', '绘卷碎片·大', 'pic_suipian3', 'currency:903519'),
    ('scroll_shard_medium', '绘卷碎片·中', 'pic_suipian2', 'currency:903518'),
    ('scroll_shard_small', '绘卷碎片·小', 'pic_suipian', 'currency:903517'),
]


class AssetStats:
    """DailyTrifles 的角色资产采集能力。"""

    _asset_stats_started_frida = False
    _asset_stats_rooted = False
    _asset_stats_root_mode = None

    # ------------------------------------------------------------------ 对外入口
    def run_asset_stats(self) -> bool:
        """读取一次角色资产并落盘，返回是否成功。"""
        logger.hr('asset stats', 2)
        try:
            currency, heroes, account, named = self._asset_stats_read_game()
        except Exception as e:
            logger.error(f'角色资产读取失败: {e}')
            return False
        finally:
            self._asset_stats_cleanup()

        items = []
        currency = {int(k): v for k, v in currency.items() if str(k).lstrip('-').isdigit()}
        heroes = {int(k): v for k, v in heroes.items() if str(k).lstrip('-').isdigit()}
        for key, label, icon, source in ASSET_ITEMS:
            kind, _, raw_id = source.partition(':')
            if kind == 'currency':
                value = currency.get(int(raw_id), 0)
            elif kind == 'hero':
                value = heroes.get(int(raw_id), 0)
            elif kind == 'name':
                value = named.get(raw_id, 0)
            else:
                value = 0
            items.append({'key': key, 'label': label, 'icon': icon, 'value': int(value or 0)})

        data = {
            'updated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'source': 'mumu-frida',
            'account': account,
            'items': items,
        }
        self._asset_stats_save(data)
        logger.info('角色资产: ' + ', '.join(f'{i["label"]}={i["value"]}' for i in items))
        return True

    # ------------------------------------------------------------------ 采集流程
    def _asset_stats_read_game(self):
        dev = self.device
        package = dev.package
        pid = self._asset_stats_pid(package)
        logger.info(f'AssetStats: package={package} pid={pid}')
        self._asset_stats_ensure_root()
        self._asset_stats_ensure_frida_server()
        port = dev.adb_forward(f'tcp:{FRIDA_PORT}')

        remote = f'/data/user/0/{package}/cache/oas_asset_stats.json'
        local = Path(self._asset_stats_state_dir()) / '_latest.json'
        local.parent.mkdir(parents=True, exist_ok=True)
        dev.adb_shell(f'rm -f {remote}', timeout=5)

        payload = self._asset_stats_payload(remote)
        self._asset_stats_run_python(port, pid, payload)

        # su 模式下 adbd 仍是 shell，读不到应用私有目录：先拷到 /data/local/tmp
        pull_path = remote
        tmp_path = None
        if self._asset_stats_root_mode == 'su':
            tmp_path = f'/data/local/tmp/oas_asset_stats_{os.getpid()}.json'
            self._asset_stats_root_shell(
                f'cp {remote} {tmp_path} && chmod 644 {tmp_path}', timeout=10)
            pull_path = tmp_path
        try:
            dev.adb_command(['pull', pull_path, str(local)], timeout=30)
        finally:
            if tmp_path:
                try:
                    self._asset_stats_root_shell(f'rm -f {tmp_path}', timeout=5)
                except Exception:
                    pass
        if not local.exists():
            raise RuntimeError('未能从模拟器取回资产数据')
        with open(local, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        local.unlink(missing_ok=True)
        if raw.get('error'):
            raise RuntimeError(f'游戏内执行失败: {raw["error"]}')
        return (raw.get('currency', {}), raw.get('heroes', {}),
                raw.get('account', {}), raw.get('named', {}))

    def _asset_stats_pid(self, package: str) -> int:
        dev = self.device
        out = dev.adb_shell(['pidof', package], timeout=5).strip()
        if out:
            return int(out.split()[0])
        # 部分模拟器没有 pidof，退回 ps
        out = dev.adb_shell(f'ps -A | grep {package}', timeout=5)
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0].isdigit():
                return int(parts[0])
        raise RuntimeError(f'游戏进程未运行: {package}')

    def _asset_stats_ensure_root(self):
        dev = self.device
        uid = dev.adb_shell('id', timeout=5)
        if 'uid=0' in uid:
            self._asset_stats_root_mode = 'adb'
            return
        # MuMu 自带 su：用 su 执行特权命令，避免 adb root 重启 adbd 打断正在运行的任务
        try:
            if 'uid=0' in dev.adb_shell(['su', '-c', 'id'], timeout=5):
                self._asset_stats_root_mode = 'su'
                logger.info('AssetStats: 使用 su 提权（不重启 adbd）')
                return
        except Exception:
            pass
        logger.info('AssetStats: 切换 adb root')
        dev.adb_command(['root'], timeout=15)
        time.sleep(2)
        try:
            dev.adb_connect(dev.serial)
        except Exception:
            pass
        for _ in range(10):
            time.sleep(1)
            try:
                if 'uid=0' in dev.adb_shell('id', timeout=5):
                    self._asset_stats_rooted = True
                    self._asset_stats_root_mode = 'adb'
                    return
            except Exception:
                continue
        raise RuntimeError('adb root 失败，无法读取游戏进程（MuMu 需要允许 root）')

    def _asset_stats_root_shell(self, cmd: str, timeout=10) -> str:
        """以 root 执行命令；su 模式下不重启 adbd，不影响正在运行的任务。"""
        if self._asset_stats_root_mode == 'su':
            return self.device.adb_shell(['su', '-c', cmd], timeout=timeout)
        return self.device.adb_shell(cmd, timeout=timeout)

    def _asset_stats_ensure_frida_server(self):
        dev = self.device
        abi = dev.adb_shell('getprop ro.product.cpu.abi', timeout=5).strip()
        override = getattr(self.config.daily_trifles.asset_stats, 'frida_server_path', '').strip()
        if abi and 'x86' not in abi.lower() and not override:
            raise RuntimeError(f'当前模拟器架构为 {abi}，请配置对应架构的 frida_server_path')
        binary = self._asset_stats_frida_binary()
        if not self._asset_stats_remote_server_ok(binary):
            logger.info(f'AssetStats: 推送 frida-server ({binary.name})')
            dev.adb_push(str(binary), REMOTE_FRIDA)
            dev.adb_shell(['chmod', '755', REMOTE_FRIDA], timeout=10)
        if not self._asset_stats_server_running():
            self._asset_stats_root_shell(
                f'nohup {REMOTE_FRIDA} -l 0.0.0.0:{FRIDA_PORT} > {REMOTE_LOG} 2>&1 &',
                timeout=10,
            )
            self._asset_stats_started_frida = True
            for _ in range(20):
                time.sleep(0.5)
                if self._asset_stats_server_running():
                    time.sleep(1)
                    return
            log = dev.adb_shell(f'cat {REMOTE_LOG}', timeout=5)
            raise RuntimeError(f'frida-server 启动失败: {log[-400:]}')

    def _asset_stats_remote_server_ok(self, binary: Path) -> bool:
        size = self.device.adb_shell(f'ls -l {REMOTE_FRIDA}', timeout=5).strip()
        return bool(size) and str(binary.stat().st_size) in size

    def _asset_stats_server_running(self) -> bool:
        out = self.device.adb_shell('ps -A | grep frida-server', timeout=5)
        return 'frida-server' in out

    def _asset_stats_frida_binary(self) -> Path:
        override = getattr(self.config.daily_trifles.asset_stats, 'frida_server_path', '').strip()
        if override:
            path = Path(override)
            if path.exists():
                return path
            raise FileNotFoundError(f'frida_server_path 不存在: {override}')
        root = Path(__file__).resolve().parents[2]
        candidates = [root / 'bin' / 'frida-server']
        candidates += sorted((root / 'tasks' / 'AutoCheckinBigGod').glob('frida-server-*'))
        for path in candidates:
            if path.is_file() and path.stat().st_size > 1_000_000:
                return path
        # 退回 oas-checkin-biggod 自带的 xz 包，按需解压到运行时目录
        try:
            import lzma
            from oas_checkin_biggod import FRIDA_SERVER_XZ

            target = root / 'config' / 'asset_stats' / 'frida-server'
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with lzma.open(FRIDA_SERVER_XZ, 'rb') as src, open(target, 'wb') as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
                target.chmod(0o755)
            return target
        except Exception:
            pass
        raise FileNotFoundError(
            '未找到 frida-server。请把对应架构的 frida-server 放到 bin/frida-server，'
            '或在每日琐事配置里填写 frida_server_path'
        )

    def _asset_stats_run_python(self, port: int, pid: int, payload: str):
        import frida  # 延迟导入，未安装 frida 时不影响其它任务

        address = f'127.0.0.1:{port}'
        last_error = None
        for attempt in range(3):
            manager = frida.get_device_manager()
            try:
                manager.remove_remote_device(address)
            except Exception:
                pass
            try:
                device = manager.add_remote_device(address)
                session = device.attach(pid)
                script = session.create_script(_FRIDA_JS)
                script.load()
                try:
                    result = script.exports_sync.run(payload)
                finally:
                    try:
                        session.detach()
                    except Exception:
                        pass
                if not result:
                    raise RuntimeError('注入执行失败：没有返回结果')
                if result.get('stage') == 'python-not-initialized':
                    raise RuntimeError('游戏 Python 尚未初始化，请确认已登录并进入庭院')
                if not result.get('ok'):
                    logger.warning(f'AssetStats: 注入返回 rc={result.get("rc")}，尝试读取错误详情')
                return
            except Exception as e:
                last_error = e
                logger.warning(f'AssetStats: 第 {attempt + 1} 次注入失败: {e}')
                time.sleep(1.5)
        raise RuntimeError(f'注入执行失败: {last_error}')

    def _asset_stats_payload(self, remote_path: str) -> str:
        return _PAYLOAD_TEMPLATE.replace('__OUT__', json.dumps(remote_path))

    # ------------------------------------------------------------------ 结果落盘
    def _asset_stats_state_dir(self) -> str:
        root = Path(__file__).resolve().parents[2]
        return str(root / 'config' / 'asset_stats')

    def _asset_stats_save(self, data: dict):
        directory = Path(self._asset_stats_state_dir())
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f'{self.config.config_name}.json'
        history = []
        days = {}
        if target.exists():
            try:
                with open(target, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                history = old.get('history', [])
                days = old.get('days', {})
                prev = {i['key']: i['value'] for i in old.get('items', [])}
                for item in data['items']:
                    item['prev'] = prev.get(item['key'])
            except Exception:
                pass
        snapshot = {i['key']: i['value'] for i in data['items']}
        history.append({'updated_at': data['updated_at'], 'items': snapshot})
        # 每天保留最后一次，便于按日期对比
        day_key = data['updated_at'][:10]
        days[day_key] = {'updated_at': data['updated_at'], 'items': snapshot}
        days = dict(sorted(days.items())[-90:])
        data['history'] = history[-30:]
        data['days'] = days
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def _asset_stats_cleanup(self):
        try:
            if getattr(self.config.daily_trifles.asset_stats, 'keep_frida_running', False):
                return
            if self._asset_stats_started_frida:
                try:
                    self._asset_stats_root_shell('killall frida-server', timeout=5)
                except Exception:
                    pass
                # 不把 frida-server 留在设备上，降低被检测/残留的概率
                self._asset_stats_root_shell(f'rm -f {REMOTE_FRIDA} {REMOTE_LOG}', timeout=10)
            self._asset_stats_started_frida = False
            if self._asset_stats_rooted:
                self.device.adb_command(['unroot'], timeout=15)
                self._asset_stats_rooted = False
        except Exception:
            pass


_FRIDA_JS = r"""
rpc.exports = {
  run: function (payload) {
    var mod = Process.getModuleByName('libclient.so');
    function exp(n) {
      if (mod.getExportByName) return mod.getExportByName(n);
      if (mod.findExportByName) return mod.findExportByName(n);
      throw new Error('no export api on module');
    }
    var ensure = new NativeFunction(exp('PyGILState_Ensure'), 'pointer', []);
    var release = new NativeFunction(exp('PyGILState_Release'), 'void', ['pointer']);
    var run = new NativeFunction(exp('PyRun_SimpleString'), 'int', ['pointer']);
    var isInit = new NativeFunction(exp('Py_IsInitialized'), 'int', []);
    if (!isInit()) return {ok: false, stage: 'python-not-initialized'};
    var g = ensure();
    var rc = run(Memory.allocUtf8String(payload + "\n"));
    release(g);
    return {ok: rc === 0, rc: rc};
  }
};
"""

_PAYLOAD_TEMPLATE = r"""
import json, sys, traceback
out = __OUT__
try:
    player = sys.modules['Globals'].player1
    currency = {}
    for k, v in (getattr(player, 'currency', {}) or {}).items():
        currency[str(k)] = int(v)
    heroes = {}
    for h in (getattr(player, 'heroes', {}) or {}).values():
        hid = int(getattr(h, 'heroId', 0) or 0)
        heroes[str(hid)] = heroes.get(str(hid), 0) + 1
    account = {
        'name': str(getattr(player, '_name', '') or ''),
        'level': int(getattr(player, 'level', 0) or 0),
        'avatar_id': str(getattr(sys.modules['Globals'], 'AVATAR_ID', '') or ''),
    }
    named = {}
    wanted = set(['魂玉'])
    for cid, cfg in sys.modules['com.data.cdata.currency'].data.items():
        n = str(cfg.get('name', '')).strip()
        if n in wanted:
            named[n] = int(currency.get(str(cid), 0))
    result = {'currency': currency, 'heroes': heroes, 'account': account, 'named': named}
except Exception:
    result = {'error': traceback.format_exc()[-800:]}
open(out, 'w', encoding='utf-8').write(json.dumps(result, ensure_ascii=False))
"""

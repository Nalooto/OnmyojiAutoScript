"""独立执行一次角色资产读取。

供 OAS 后端在脚本运行期间按需调用（不跑完整每日琐事）：
    python -m tasks.DailyTrifles.asset_cli oas1

只做 ADB/注入读取，不操作游戏界面；优先使用 su 提权，避免 adb root 重启 adbd
影响正在运行的任务。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from module.config.config import Config  # noqa: E402
from module.device.device import Device  # noqa: E402
from tasks.DailyTrifles.asset_stats import AssetStats  # noqa: E402


class _Runner(AssetStats):
    def __init__(self, config, device):
        self.config = config
        self.device = device


def main() -> int:
    config_name = sys.argv[1] if len(sys.argv) > 1 else 'oas1'
    cfg = Config(config_name)
    dev = Device(cfg)
    ok = _Runner(cfg, dev).run_asset_stats()
    print(json.dumps({'ok': bool(ok), 'config': config_name}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

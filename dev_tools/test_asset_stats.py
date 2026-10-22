"""手动触发一次角色资产读取，便于在不跑完整每日琐事时调试。

用法：
    toolkit\\python.exe dev_tools\\test_asset_stats.py [配置名]
默认使用 oas1。
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from module.config.config import Config
from module.device.device import Device
from tasks.DailyTrifles.script_task import ScriptTask

config_name = sys.argv[1] if len(sys.argv) > 1 else 'oas1'
c = Config(config_name)
d = Device(c)
t = ScriptTask(c, d)
t.config.daily_trifles.asset_stats.enable = True
ok = t.run_asset_stats()
print('RESULT', ok)

"""单独验证超鬼王门票刷取的「清个人突破」子流程，不依赖门票是否已满。

门票满了以后 `run_ticket_farming()` 会在入口直接跳过，整条链路没法触发；
这个脚本绕开门票检查，只跑「突破券检测 / 清一轮个突 / 切回门票御魂 / 回探索入口」。

前提：
1. 目标实例必须已经停止（用 oasx 停），否则会和正在跑的实例抢同一个模拟器。
2. 模拟器已启动且能连上（`adb devices` 能看到 serial）。

用法：
  ./toolkit/python.exe dev_tools/ticket_realm_raid_round.py oas3 --ocr-only
  ./toolkit/python.exe dev_tools/ticket_realm_raid_round.py oas3
  ./toolkit/python.exe dev_tools/ticket_realm_raid_round.py oas3 --threshold 24
"""
import sys
from argparse import ArgumentParser
from datetime import datetime

if '.' not in sys.path:
    sys.path.insert(0, '.')

from module.config.config import Config
from module.device.device import Device
from module.logger import logger
import tasks.GameUi.page as pages
import tasks.Exploration.page as exp_pages
from tasks.MetaDemonTicket.ticket_farming import ExplorationTicketTask


def build_task(config, device) -> ExplorationTicketTask:
    """按门票任务的方式装配探索刷票 runner，但不进入刷票主循环。"""
    task = ExplorationTicketTask(config, device)
    task.start_time = datetime.now()
    task.current_count = 0
    task.limit_time = config.meta_demon_ticket.general_config.limit_time_v
    task.user_status = config.meta_demon_ticket.general_config.user_status
    # 门票刷取期间不发起协同
    task._battle_cooperation_prepared = True
    task._ticket_farming_complete = False
    task._ticket_full = False
    task._ticket_peer = ''
    return task


def read_ticket_count(task) -> None:
    """在探索入口/探索界面各读一次突破券，确认 OCR ROI 与游戏显示一致。"""
    task.goto_page(pages.page_exploration)
    task.screenshot()
    current, _, total = task.O_REALM_RAID_NUMBER.ocr(task.device.image)
    logger.info(f'探索界面突破券: {current}/{total}')
    task.goto_page(exp_pages.page_exp_entrance)
    task.screenshot()
    current, _, total = task.O_REALM_RAID_NUMBER1.ocr(task.device.image)
    logger.info(f'探索入口突破券: {current}/{total}')
    logger.info('请对照游戏界面核对上面两个读数；读数不对说明 ROI 需要重新标定')


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument('config_name', help='实例配置名，如 oas3 / 大号1')
    parser.add_argument('--ocr-only', action='store_true', help='只读突破券计数，不清票')
    parser.add_argument('--threshold', type=int, default=None, help='临时覆盖突破券阈值，仅本次生效')
    args = parser.parse_args()

    config = Config(args.config_name)
    meta = config.meta_demon_ticket.general_config
    if args.threshold is not None:
        meta.realm_raid_threshold = args.threshold
    logger.info(f'实例 {args.config_name}: 突破券清理开关={meta.realm_raid_enable} '
                f'阈值={meta.realm_raid_threshold} 身份={meta.user_status.value}')
    if meta.user_status.value != 'alone':
        logger.warning('清票只在单人身份生效，当前身份非 alone，activate_realm_raid 不会触发')

    device = Device(config)
    task = build_task(config, device)

    if args.ocr_only:
        read_ticket_count(task)
        return

    logger.hr('ticket realm raid round', level=2)
    task.run_realm_raid_round()
    logger.info('清票子流程结束：应为「已切回门票御魂 + 停回探索入口」')


if __name__ == '__main__':
    main()

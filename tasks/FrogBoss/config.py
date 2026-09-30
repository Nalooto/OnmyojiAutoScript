# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

from enum import Enum
from pydantic import BaseModel, Field

from tasks.Component.config_base import ConfigBase, MultiLine, Time
from tasks.Component.config_scheduler import Scheduler


class Strategy(str, Enum):
    Majority = 'frog_majority'
    Minority = 'frog_minority'
    Bilibili = 'frog_bilibili'
    Dashen = 'frog_dashen'
    DashenFollow = 'frog_dashen_follow'
    Oas = 'frog_oas'
    AlwaysRed = 'frog_always_red'
    AlwaysBlue = 'frog_always_blue'

class FrogBossConfig(ConfigBase):
    before_end_frog: Time = Field(default=Time(0, 15, 0), description='before_end_frog_help')
    strategy_frog: Strategy = Field(default=Strategy.Majority, description='strategy_frog_help')
    dashen_follow_uids: MultiLine = Field(
        default='',
        title='网易大神博主 UID',
        description='每行填写一个博主的 someOneUid（32位 UID）。仅统计当前两小时场次中方向明确的竞猜；无有效竞猜时，剩余15分钟内按多数派下注，更早则延迟到结束前15分钟重试。',
    )

class FrogBoss(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    frog_boss_config: FrogBossConfig = Field(default_factory=FrogBossConfig)




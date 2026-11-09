# This Python file uses the following encoding: utf-8
"""
标注工具「文件」面板的目录名中文显示。

只影响界面上显示的名字，选中/保存用的仍然是真实目录名，
所以这里做纯映射，不做任何重命名，加新任务时补一条即可。
"""
from __future__ import annotations

# 任务级目录（tasks/<TaskName>）
TASK_LABELS: dict[str, str] = {
    "AbyssShadows": "狭间暗域",
    "ActivityShikigami": "活动爬塔",
    "AreaBoss": "地域鬼王",
    "AutoCheckinBigGod": "大神签到",
    "BondlingFairyland": "契灵之境",
    "Chess": "百鬼棋局",
    "CollectiveMissions": "寮集体任务",
    "Component": "通用组件",
    "DailyTrifles": "每日杂务",
    "Delegation": "式神委派",
    "DemonEncounter": "逢魔之时",
    "DemonRetreat": "妖怪退治",
    "Dokan": "道馆突破",
    "Duel": "斗技",
    "DyeTrials": "灵染试炼",
    "EternitySea": "永生之海",
    "EvoZone": "觉醒副本",
    "ExperienceYoukai": "经验妖怪",
    "Exploration": "探索",
    "FallenSun": "日轮之城",
    "FindJade": "协作任务邀请",
    "FloatParade": "花车巡游",
    "FrogBoss": "对弈竞猜",
    "GameUi": "游戏界面",
    "GlobalGame": "全局界面",
    "GoldYoukai": "金币妖怪",
    "GoryouRealm": "御灵",
    "GotoMain": "返回主界面",
    "GuguArtStudio": "呱呱画室",
    "GuildActivityMonitor": "寮活动监控",
    "GuildBanquet": "寮宴会",
    "HeroTest": "技能本",
    "Hunt": "狩猎战",
    "Hyakkiyakou": "百鬼夜行",
    "KekkaiActivation": "结界上卡",
    "KekkaiUtilize": "结界寄养",
    "KittyShop": "猫咪经营",
    "MartialTournament": "武道大会",
    "MemoryScrolls": "记忆绘卷",
    "MetaDemon": "超鬼王",
    "MetaDemonTicket": "超鬼王门票",
    "MysteryShop": "神秘商店",
    "Nian": "年兽",
    "Orochi": "八岐大蛇",
    "OrochiMoans": "八岐大蛇悲鸣",
    "OtherWorldTwilight": "彼世逢魔",
    "Pets": "小动物",
    "Quiz": "智力答题",
    "RealmRaid": "个人突破",
    "Restart": "重启游戏",
    "RichMan": "商店采购",
    "RyouToppa": "寮突破",
    "Script": "脚本",
    "Secret": "秘闻副本",
    "SixRealms": "六道之门",
    "Sougenbi": "业原火",
    "SoulsTidy": "御魂整理",
    "Tako": "石距",
    "TalismanPass": "花合战",
    "TrueOrochi": "真·八岐大蛇",
    "Utils": "工具",
    "WantedQuests": "悬赏封印",
    "WeeklyTrifles": "每周杂务",
}

# Component 下的通用子模块（tasks/Component/<Name>）
COMPONENT_LABELS: dict[str, str] = {
    "BaseActivity": "基础活动",
    "Buy": "购买确认",
    "CooperativeBattle": "协同战斗",
    "Costume": "庭院装饰",
    "CostumeBattle": "战斗皮肤",
    "CostumeShikigami": "式神皮肤",
    "CustomCourtyardAffair": "自定义庭院事务",
    "GeneralBattle": "通用战斗",
    "GeneralBuff": "通用加成",
    "GeneralInvite": "通用邀请",
    "GeneralRoom": "通用房间",
    "Login": "登录",
    "LootStatistics": "掉落统计",
    "QuickLoadout": "快捷预设",
    "ReplaceShikigami": "替换式神",
    "RightActivity": "活动入口",
    "Summon": "召唤",
    "SwitchAccount": "切换账号",
    "SwitchOnmyoji": "切换阴阳师",
    "SwitchSoul": "切换御魂",
}

# 各任务下通用的子目录（缩写居多，含义在各任务里基本一致）
SUBDIR_LABELS: dict[str, str] = {
    "a": "结界卡",
    "activities": "活动",
    "additional": "额外入口",
    "agent": "代理",
    "area_boss": "地域鬼王",
    "as": "活动",
    "ball": "灵契球",
    "ban": "禁用",
    "bf": "逢魔原野",
    "boss": "首领",
    "broken_amulet": "破碎符咒",
    "c": "图片素材",
    "capture": "结契",
    "cards": "结界卡",
    "chanllenge": "挑战",
    "cm": "集体任务",
    "collect": "收集分享",
    "d": "委派",
    "data": "数据",
    "demon": "逢魔入口",
    "dev": "安全点击区",
    "dt": "每日杂务",
    "duel": "斗技",
    "ey": "经验妖怪",
    "f": "副本",
    "feed": "提交材料",
    "fp": "活动页",
    "gas": "呱呱画室",
    "gg": "全局",
    "gr": "御灵",
    "guild": "功勋商店",
    "gy": "金币妖怪",
    "harvest": "签到收益",
    "highlight": "高亮标记",
    "hunt": "狩猎战",
    "hya": "百鬼夜行",
    "invite": "邀请",
    "kirin": "麒麟",
    "ks": "猫咪经营",
    "ku": "寮结界",
    "login": "登录",
    "love": "吉闻祝福",
    "mail": "邮件问答",
    "mall": "兑换商店",
    "md": "超鬼王",
    "moon_sea": "月之海",
    "nian": "年兽",
    "netherworld": "阴界之门",
    "o": "副本",
    "owt": "彼世逢魔",
    "page": "页面",
    "peacock_kingdom": "孔雀国",
    "pet": "宠物小屋",
    "prepare": "准备",
    "quiz": "答题",
    "realm": "结界",
    "res": "资源",
    "resource": "资源",
    "rewards": "奖励",
    "runtime": "运行时",
    "s": "副本",
    "se": "秘闻",
    "secret": "秘闻",
    "shrine": "神龛",
    "simple": "御魂整理",
    "slave": "小号",
    "soul": "御魂",
    "sr": "六道之门",
    "st": "真蛇",
    "stone": "契灵石",
    "store": "商店",
    "strategy": "策略",
    "summonRecall": "今忆召唤",
    "touch_fish": "摸鱼",
    "tp": "花合战",
    "train": "车厢",
    "tt": "千物宝库",
    "ui": "界面",
    "utils": "工具",
    "utilize": "寄养",
    "wq": "悬赏封印",
    "MT": "武道大会",
    "DemonRetreat": "首领退治",
}

# 各任务里同名子目录含义不同，按任务单独覆盖
TASK_SUBDIR_LABELS: dict[str, dict[str, str]] = {
    "ActivityShikigami": {"as": "活动爬塔"},
    "HeroTest": {"as": "英杰活动"},
    "DyeTrials": {"fp": "灵染试炼"},
    "FloatParade": {"fp": "花车巡游"},
    "MemoryScrolls": {"ms": "绘卷"},
    "MysteryShop": {"ms": "神秘商店"},
}


def dir_label(name: str, parent_dir: str = "") -> str:
    """
    取目录的中文显示名，取不到就返回原名。
    :param name: 目录名
    :param parent_dir: 父目录相对 tasks 的路径（如 'Component/GeneralRoom'、'Chess'），用于兜底判定
    :return: 中文显示名或原名
    """
    task_name = parent_dir.split("/")[0] if parent_dir else ""

    specific = TASK_SUBDIR_LABELS.get(task_name)
    if specific and name in specific:
        return specific[name]

    if parent_dir == "Component" and name in COMPONENT_LABELS:
        return COMPONENT_LABELS[name]

    if not parent_dir:
        return TASK_LABELS.get(name, name)

    return SUBDIR_LABELS.get(name, name)


def build_dir_labels(names: list[str], parent_dir: str = "") -> dict[str, str]:
    """
    为一批目录名生成 显示名 映射，未命中的不返回（前端回退成原名）。
    :param names: 目录名列表
    :param parent_dir: 父目录相对 tasks 的路径
    :return: {真实目录名: 中文显示名}
    """
    labels: dict[str, str] = {}
    for name in names:
        label = dir_label(name, parent_dir)
        if label != name:
            labels[name] = label
    return labels

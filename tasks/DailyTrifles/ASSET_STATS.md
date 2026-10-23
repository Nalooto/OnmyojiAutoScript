# 角色资产统计（每日琐事）

在每日琐事结束时，进入游戏进程读取账号资产，写入 `config/asset_stats/<配置名>.json`，
由 OASX 右侧栏的「资产」页签展示。

## 为什么不用 OCR

与 平安志 的 MuMu 快照同理：通过 `libclient.so` 导出的 CPython API，在游戏自己的解释器里
执行一段 Python，直接读取 `Globals.player1.currency`、`player1.heroes` 等对象。

- 数值来自游戏内存，不受分辨率、字体、遮挡、识别误差影响；
- 失败时会带回游戏内 traceback（写入结果 JSON 的 `error` 字段）；
- 代价是需要 root + 代码注入，属于对游戏进程的运行时干预。

## 链路

```
每日琐事 → AssetStats.run_asset_stats()
  或 OASX 刷新按钮 → POST /stats/{script}/assets/refresh
     → 子进程 python -m tasks.DailyTrifles.asset_cli <script>
  → 提权：adbd 已是 root 直接用；否则优先 su -c（不重启 adbd，不影响正在跑的任务）
  → 推送并启动 frida-server（结束后 kill + 删除）
  → frida attach 游戏进程 → PyGILState_Ensure → PyRun_SimpleString(payload)
  → payload 读取 player1.currency / heroes，写到 app cache
  → adb pull 回 config/asset_stats/_latest.json
  → 映射成 18 项资产，写 config/asset_stats/<配置名>.json
     （items=最新值，days=按日期，history=最近 30 次）
```

## 配置

`每日琐事 → asset_stats`：

| 字段 | 说明 |
|---|---|
| `enable` | 是否在每日任务结束后读取 |
| `frida_server_path` | 自定义 frida-server 路径，留空自动查找 |
| `keep_frida_running` | 读取后保留 frida-server 进程（默认关闭） |

frida-server 查找顺序：

1. `bin/frida-server`
2. `tasks/AutoCheckinBigGod/frida-server-*`
3. `oas_checkin_biggod` 自带的 xz 包（按需解压到 `config/asset_stats/frida-server`）

## 资产来源

| key | 名称 | 来源 |
|---|---|---|
| gold | 金币 | currency 900001 |
| ap | 体力 | currency 900003 |
| jade | 勾玉 | currency 900002 |
| mystery_amulet | 神秘的符咒 | currency 490001 |
| black_daruma | 御行达摩 | `heroes` 中 heroId=411 的数量 |
| black_daruma_shard | 御行达摩碎片 | currency 434111 |
| real_amulet | 现世符咒 | currency 490004 |
| soul_jade | 魂玉 | 按货币名「魂玉」反查 id |
| oro_scale | 大蛇的逆鳞 | currency 900217 |
| demon_soul | 逢魔之魂 | currency 900218 |
| yuling_key | 御灵境之钥 | currency 900215 |
| hyakki_ticket | 百鬼夜行门票 | currency 900007 |
| honor | 荣誉 | currency 900012 |
| medal | 勋章 | currency 900016 |
| contrib | 功勋 | currency 900090 |
| scroll_shard_* | 绘卷碎片（大/中/小） | currency 903519 / 903518 / 903517 |

游戏更新导致 id 变化时，改 `tasks/DailyTrifles/asset_stats.py` 里的 `ASSET_ITEMS` 即可；
`name:` 前缀支持按货币名反查，适合不稳定 id。

## 接口

`GET /stats/{script_name}/assets`：读取已落盘的快照。

`POST /stats/{script_name}/assets/refresh`：**按需触发一次真实读取**，独立子进程执行，
不依赖每日琐事任务，可在脚本运行期间调用；同一时间只允许一个刷新（409）。

```json
{
  "script_name": "oas1",
  "available": true,
  "updated_at": "2026-10-21T21:14:30+08:00",
  "source": "mumu-frida",
  "account": {"name": "...", "level": 60, "avatar_id": "..."},
  "items": [{"key": "gold", "label": "金币", "icon": "icon_jinbi", "value": 27974186, "prev": 27974186}],
  "days": [
    {"date": "2026-10-21", "updated_at": "2026-10-21T21:14:30+08:00",
     "items": {"gold": 27974186, "jade": 20634, "...": 0}}
  ]
}
```

- `items`：最新一次读数（`prev` 是上一次读数）；
- `days`：按日期保留每天最后一次读数，最多 90 天，供 OASX 选择日期对比；
- `history` 只存在文件里（最近 30 次），接口不返回。

## 提权方式

优先顺序：

1. adbd 已经是 root → 直接执行；
2. `su -c id` 成功（MuMu 自带）→ 用 `su -c` 执行启动/清理，**不重启 adbd**，
   因此可以在脚本运行中刷新资产；
3. 都不行才 `adb root`（会重启 adbd，可能短暂影响正在运行的任务），结束再 `unroot`。

su 模式下 adbd 仍是 shell，读不到应用私有目录，结果会先 `cp` 到 `/data/local/tmp`
再 pull。

## 手动测试

```bat
toolkit\python.exe dev_tools\test_asset_stats.py oas1
toolkit\python.exe -m tasks.DailyTrifles.asset_cli oas1
```

会走完整的 root → 启动 frida → 注入 → 取回 → 落盘流程，并在结束时还原 adb 权限、删除
设备上的 frida-server。

## 注意

- 需要 root 权限：adbd 已 root 或设备带 `su`（MuMu 12 两者都有）；
- `su -c` 的组合命令（带 `>` `&` 的启动/清理/拷贝）必须以 **str** 形式交给
  `adb_shell`；传 list 时 adbutils 会走 `subprocess.list2cmdline`，单元素含空格会被
  包成 `"..."` 原样送到设备，sh 会把整串当成一个文件名而报
  `inaccessible or not found`，日志里表现为「`cat: ...frida-server.log: No such file`」；
- 游戏需已登录并进入庭院，否则会返回「游戏 Python 尚未初始化」；
- 注入期间游戏可能短暂卡顿；
- 该方案违反游戏用户协议，存在封号风险，默认关闭，请自行评估。

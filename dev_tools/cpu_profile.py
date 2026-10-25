# -*- coding: utf-8 -*-
"""
OAS 四开 CPU 归因诊断

用法（4 开脚本正常运行中执行）：
    ./toolkit/python.exe dev_tools/cpu_profile.py
    ./toolkit/python.exe dev_tools/cpu_profile.py --seconds 60

输出：按进程组统计 CPU 占用，区分「模拟器 / 脚本实例 / 图像服务 / OCR 服务 / 其他」，
      直接告诉你瓶颈到底在模拟器侧还是脚本侧。
"""
import argparse
import os
import sys
import time
from collections import defaultdict

import psutil


def classify(name, cmdline, ppid):
    """把进程归到某一类"""
    n = (name or "").lower()
    c = " ".join(cmdline or []).lower()

    # 空闲进程 / 系统伪进程，必须排除，否则会占满统计
    if n in ("system idle process", "idle", "system", "registry", "memory compression") or ppid == 0:
        return "系统"

    emu_keys = ("mumuplayer", "mumuvmmheadless", "mumuheadless", "nemuplayer",
                "nemuheadless", "nx_main", "emulator")
    if any(k in n for k in emu_keys) or any(k in c for k in emu_keys):
        return "模拟器(MuMu)"

    if "python" in n or "python" in c:
        if "run_image_server" in c or "image_server" in c:
            return "图像服务"
        if "ocr" in c and "server" in c:
            return "OCR服务"
        if "script.py" in c:
            return "脚本实例"
        if "server.py" in c or "uvicorn" in c or "oas" in c:
            return "后端/WebUI"
        return "Python其他"

    if n in ("oas.exe",) or "oas.exe" in c:
        return "后端/WebUI"
    if n in ("dwm.exe", "explorer.exe", "svchost.exe", "system"):
        return "系统"
    return "其他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30.0, help="采样时长（秒）")
    ap.add_argument("--interval", type=float, default=1.0, help="采样间隔（秒）")
    args = ap.parse_args()

    total_cores = psutil.cpu_count(logical=True) or 1
    print(f"逻辑核心数: {total_cores}   采样 {args.seconds:.0f}s ...\n")

    # 预热一次
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except Exception:
            pass

    agg = defaultdict(float)          # 类别 -> CPU 秒
    per_proc = defaultdict(float)     # (类别, 进程名+pid) -> CPU 秒
    samples = 0
    t_end = time.time() + args.seconds

    while time.time() < t_end:
        time.sleep(args.interval)
        samples += 1
        for p in psutil.process_iter(["name", "cmdline", "ppid"]):
            try:
                pct = p.cpu_percent(None)   # 相对单核的百分比
                if pct <= 0:
                    continue
                info = p.info
                pname = (info.get("name") or "").lower()
                # 空闲进程代表"没被使用的 CPU"，不能计入占用
                if pname in ("system idle process", "idle") or p.pid == 0:
                    continue
                cat = classify(info.get("name"), info.get("cmdline"), info.get("ppid"))
                cpu_seconds = pct / 100.0 * args.interval
                agg[cat] += cpu_seconds
                per_proc[(cat, f'{info.get("name")}({p.pid})')] += cpu_seconds
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    elapsed = samples * args.interval
    total = sum(agg.values())
    if total <= 0:
        print("没有采样到 CPU 占用，请确认脚本正在运行。")
        return

    print(f"{'类别':<16}{'平均占用(核)':>14}{'占总CPU%':>12}{'占全机%':>10}")
    print("-" * 54)
    for cat, sec in sorted(agg.items(), key=lambda x: -x[1]):
        cores = sec / elapsed
        print(f"{cat:<16}{cores:>14.2f}{cores / total * 100:>11.1f}%{cores / total_cores * 100:>9.1f}%")
    print("-" * 54)
    print(f"{'合计':<16}{total / elapsed:>14.2f}{100.0:>11.1f}%{total / elapsed / total_cores * 100:>9.1f}%")

    print("\nTop 进程：")
    for (cat, nm), sec in sorted(per_proc.items(), key=lambda x: -x[1])[:12]:
        print(f"  {sec / elapsed:6.2f} 核  {cat:<12} {nm}")

    emu = agg.get("模拟器(MuMu)", 0) / elapsed
    script = (agg.get("脚本实例", 0) + agg.get("图像服务", 0) + agg.get("OCR服务", 0)) / elapsed
    print("\n结论：")
    if emu + script < 0.05:
        print("  未采到有效占用：请确认 OAS 与模拟器正在运行，或加大 --seconds 采样时长。")
    else:
        print(f"  模拟器 {emu:.2f} 核 vs 脚本链路 {script:.2f} 核  →  模拟器占 {(emu / (emu + script) * 100):.0f}%")
        if emu > script * 2:
            print("  瓶颈在模拟器侧：优先调帧率/渲染/每实例核数，脚本侧优化收益有限。")
        elif script > emu:
            print("  瓶颈在脚本侧：优先做图像服务批量化 + 灰度匹配 + 截图间隔。")
        else:
            print("  两侧接近：建议两边同时调优。")


if __name__ == "__main__":
    main()

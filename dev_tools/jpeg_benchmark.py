# This Python file uses the following encoding: utf-8
"""
JPEG 压缩对模板匹配精度影响的 A/B 测试工具。

运行方式:
  .venv/Scripts/python dev_tools/jpeg_benchmark.py
"""

from __future__ import annotations

import pickle
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# 编解码器
# ---------------------------------------------------------------------------


def encode_pickle(img: np.ndarray) -> bytes:
    return pickle.dumps(img, protocol=4)


def decode_pickle(buf: bytes) -> np.ndarray:
    return pickle.loads(buf)


def make_jpeg_codec(quality: int):
    def encode(img):
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

    def decode(buf):
        return cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)

    return encode, decode


# ---------------------------------------------------------------------------
# 测试核心
# ---------------------------------------------------------------------------


@dataclass
class Result:
    name: str
    encode_ms: float = 0
    decode_ms: float = 0
    size_kb: int = 0
    score_deltas: list[float] = field(default_factory=list)
    loc_mismatches: int = 0
    misses: int = 0  # 原图匹配到了但压缩后没匹配到


def load_template(path: str) -> np.ndarray | None:
    """加载模板，排除异常尺寸。"""
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if h < 10 or w < 10 or h > 500 or w > 500:
        return None
    return img


def build_scene(template: np.ndarray, size=(1280, 720)) -> tuple[np.ndarray, tuple]:
    """将模板放入 1280x720 随机位置，用边缘色填充背景。"""
    th, tw = template.shape[:2]
    sw, sh = size

    # 随机位置
    x = np.random.randint(20, max(21, sw - tw - 20))
    y = np.random.randint(20, max(21, sh - th - 20))

    # 背景色：模板边缘像素中位数
    edges = np.concatenate([
        template[0:3, :, :].reshape(-1, 3),
        template[-3:, :, :].reshape(-1, 3),
        template[:, 0:3, :].reshape(-1, 3),
        template[:, -3:, :].reshape(-1, 3),
    ], axis=0)
    bg = np.median(edges, axis=0).astype(np.uint8)
    scene = np.full((sh, sw, 3), bg.tolist(), dtype=np.uint8)
    scene[y:y + th, x:x + tw] = template
    return scene, (x, y, tw, th)


def run():
    print("=" * 60)
    print("  JPEG vs Pickle — 模板匹配精度 A/B 测试")
    print("=" * 60)

    # ---- 阶段1: 收集模板 ----
    print("\n[1/3] 扫描模板...")
    tasks_dir = Path(__file__).resolve().parent.parent / "tasks"
    template_paths = []
    for p in tasks_dir.rglob("*.png"):
        parts = p.relative_to(tasks_dir).parts
        if "res" not in parts and "highlight" not in parts:
            continue
        if p.stat().st_size > 500 * 1024:  # skip >500KB
            continue
        template_paths.append(str(p))

    # 只取前 30 个，且采样不同类型的尺寸
    valid_templates = []
    for tp in template_paths:
        t = load_template(tp)
        if t is not None:
            valid_templates.append((tp, t))
        if len(valid_templates) >= 30:
            break

    print(f"  有效模板: {len(valid_templates)}")
    if not valid_templates:
        print("  无有效模板，退出")
        return

    # ---- 阶段2: 性能基准 ----
    print("\n[2/3] 编解码性能基准...")
    # 用一张实际模板构建的 1280x720 场景图做基准
    sample_scene, _ = build_scene(valid_templates[0][1])

    codecs = {
        "pickle": (encode_pickle, decode_pickle),
        "jpeg_q95": make_jpeg_codec(95),
        "jpeg_q92": make_jpeg_codec(92),
        "jpeg_q85": make_jpeg_codec(85),
        "jpeg_q75": make_jpeg_codec(75),
    }

    results: dict[str, Result] = {}
    for name, (enc, dec) in codecs.items():
        # 预热
        buf = enc(sample_scene)
        _ = dec(buf)

        # 计时
        rounds = 30
        t0 = time.perf_counter()
        for _ in range(rounds):
            buf = enc(sample_scene)
        t1 = time.perf_counter()
        enc_ms = (t1 - t0) / rounds * 1000

        t0 = time.perf_counter()
        for _ in range(rounds):
            _ = dec(buf)
        t1 = time.perf_counter()
        dec_ms = (t1 - t0) / rounds * 1000

        r = Result(name=name, encode_ms=enc_ms, decode_ms=dec_ms,
                   size_kb=len(buf) // 1024)
        results[name] = r

    pickle_size = results["pickle"].size_kb
    print(f"  {'Codec':<12} {'enc_ms':>8} {'dec_ms':>8} {'total':>8} {'size_kb':>8} {'vs_pkl':>8}")
    print(f"  {'-'*52}")
    for name in ["pickle", "jpeg_q95", "jpeg_q92", "jpeg_q85", "jpeg_q75"]:
        r = results[name]
        ratio = r.size_kb / pickle_size * 100
        print(f"  {name:<12} {r.encode_ms:>7.1f}  {r.decode_ms:>7.1f}  "
              f"{r.encode_ms+r.decode_ms:>7.1f}  {r.size_kb:>7}  {ratio:>6.0f}%")

    # ---- 阶段3: 匹配精度测试 ----
    print(f"\n[3/3] 匹配精度测试 ({len(valid_templates)} 模板 × 3 场景 × 5 编码)...")

    scenes_per_template = 3
    total = len(valid_templates) * scenes_per_template

    for name, (enc, dec) in codecs.items():
        r = results[name]
        for idx, (path, template) in enumerate(valid_templates):
            for _ in range(scenes_per_template):
                scene, (gt_x, gt_y, gt_w, gt_h) = build_scene(template)

                # 编码→解码
                buf = enc(scene)
                decoded = dec(buf)

                # 在原始场景上匹配（基准）
                res_orig = cv2.matchTemplate(scene, template, cv2.TM_CCOEFF_NORMED)
                _, score_orig, _, loc_orig = cv2.minMaxLoc(res_orig)

                # 在压缩后场景上匹配
                res_comp = cv2.matchTemplate(decoded, template, cv2.TM_CCOEFF_NORMED)
                _, score_comp, _, loc_comp = cv2.minMaxLoc(res_comp)

                r.score_deltas.append(score_comp - score_orig)
                if loc_comp != loc_orig:
                    r.loc_mismatches += 1
                if score_orig >= 0.7 and score_comp < 0.7:
                    r.misses += 1

            # 进度
            done = (idx + 1) * scenes_per_template
            pct = done / total * 100
            print(f"\r    {name:<12} {done}/{total} ({pct:.0f}%)", end="")
            sys.stdout.flush()
        print()

    # ---- 汇总 ----
    print()
    print("=" * 60)
    print("  结果汇总")
    print("=" * 60)
    print()
    header = f"{'Codec':<12} {'n':>5} {'Δavg':>10} {'Δmax':>10} {'loc_err':>7} {'miss':>5} {'total_ms':>8}"
    print(header)
    print("-" * 60)

    for name in ["pickle", "jpeg_q95", "jpeg_q92", "jpeg_q85", "jpeg_q75"]:
        r = results[name]
        n = len(r.score_deltas)
        if n == 0:
            continue
        davg = np.mean(r.score_deltas)
        dmax = max(abs(d) for d in r.score_deltas)
        total_ms = r.encode_ms + r.decode_ms
        print(f"{name:<12} {n:>5} {davg:>+9.6f} {dmax:>9.6f} "
              f"{r.loc_mismatches:>4}/{n:<3} {r.misses:>5} {total_ms:>7.1f}")

    print()
    print("  Δavg: 平均 score 偏移 (负=下降)")
    print("  Δmax: 最大绝对偏移")
    print("  loc_err: 匹配位置偏移次数/总测试")
    print("  miss: 原图≥0.7但压缩后<0.7 的次数")

    # ---- 推荐 ----
    print()
    print("-" * 60)
    baseline = results["pickle"]
    for name in ["jpeg_q95", "jpeg_q92", "jpeg_q85"]:
        r = results[name]
        n = len(r.score_deltas)
        if n == 0:
            continue
        saving = (1 - r.size_kb / baseline.size_kb) * 100
        davg = np.mean(r.score_deltas)
        miss_pct = r.misses / n * 100

        print(f"\n  {name}:")
        print(f"    体积: {baseline.size_kb}KB → {r.size_kb}KB (↓{saving:.0f}%)")
        print(f"    平均 ScoreΔ: {davg:+.6f}")
        print(f"    位置错配: {r.loc_mismatches}/{n} ({r.loc_mismatches/n*100:.1f}%)")
        print(f"    匹配丢失: {r.misses}/{n} ({miss_pct:.1f}%)")
        overhead = (r.encode_ms + r.decode_ms) - (baseline.encode_ms + baseline.decode_ms)
        print(f"    CPU 开销: +{overhead:.1f}ms")

    j92 = results["jpeg_q92"]
    if len(j92.score_deltas) > 0 and j92.misses == 0 and j92.loc_mismatches == 0:
        print("\n  ✅ 推荐 JPEG q=92 — 零精度损失 + 95% 体积缩减")
    elif j92.misses / max(len(j92.score_deltas), 1) * 100 < 1:
        print("\n  ⚠️  JPEG q=92 有少量精度损失，建议提高至 q=95 或补充实测")
    else:
        print("\n  ❌ JPEG 影响较大，建议保留 pickle 或用 PNG")

    print()


if __name__ == "__main__":
    run()

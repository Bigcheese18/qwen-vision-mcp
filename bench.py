#!/usr/bin/env python3
"""基准测试：并行分析 vs 串行分析，验证"结果一致 + 耗时对比"。"""
import struct
import time
import zlib
from pathlib import Path

import server

HERE = Path(__file__).parent
PROMPT = "这张图左右两半分别是什么颜色？只回答颜色，用中文，用逗号分隔，不要解释。"


def make_png(path: Path, left, right, w=200, h=100):
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = bytearray()
    for _ in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(left if x < w // 2 else right)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


COLORS = {
    "a.png": ((255, 0, 0), (0, 0, 255)),
    "b.png": ((0, 128, 0), (255, 255, 0)),
    "c.png": ((128, 0, 128), (255, 165, 0)),
    "d.png": ((0, 255, 255), (255, 192, 203)),
}
for name, (l, r) in COLORS.items():
    make_png(HERE / name, l, r)
paths = [str(HERE / n) for n in COLORS]

# 并行（先跑，清缓存）
server._cache.clear()
t0 = time.time()
parallel = server._analyze_many(paths, PROMPT)
t_par = time.time() - t0

# 串行（清缓存后跑，保证都是真实 API 调用）
server._cache.clear()
t0 = time.time()
serial = {p: server.analyze_image(p, PROMPT) for p in paths}
t_ser = time.time() - t0

# 结果一致性
same = all(parallel[p] == serial[p] for p in paths)

print(f"并行 4 张: {t_par:.1f}s  |  串行 4 张: {t_ser:.1f}s  |  加速: {t_ser/t_par:.1f}x")
print(f"结果一致性: {'一致' if same else '不一致!'}")
for p in paths:
    print(f"  {Path(p).name} -> {serial[p].strip()}")

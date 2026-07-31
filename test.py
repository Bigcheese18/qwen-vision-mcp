#!/usr/bin/env python3
"""端到端测试：生成测试图 → 调用 server.analyze_image → 验证 Qwen3-VL 返回。"""
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).parent


def make_png(path: Path, w: int = 200, h: int = 100) -> None:
    """纯 Python 生成一张测试图：左半红色、右半蓝色。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = bytearray()
    for _ in range(h):
        raw.append(0)  # filter: None
        for x in range(w):
            raw += bytes((255, 0, 0)) if x < w // 2 else bytes((0, 0, 255))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8bit RGB
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"测试图已生成: {path}")


if __name__ == "__main__":
    test_img = HERE / "test.png"
    make_png(test_img)

    import server

    result = server.analyze_image(
        str(test_img), "这张图左右两半分别是什么颜色？只回答颜色，不要解释。"
    )
    print("=" * 40)
    print("Qwen3-VL 返回:")
    print(result)

#!/usr/bin/env python3
"""Upscale the game's Bink videos frame by frame for the d3d8 proxy.

usage: videos.py <game_dir> <out_dir>

Writes <out_dir>/<video name>/NNNN.jpg (1-based, 1920x1440). The game still plays the Bink file for
sound and timing; the proxy shows the matching upscaled frame instead of Bink's 640x480 one.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ESRGAN = Path.home() / ".local/share/devtools/realesrgan/realesrgan-ncnn-vulkan"
SIZE = "1920x1440"


def main(game, out):
    for bik in sorted(Path(game, "Videos").glob("*.bik")):
        dest = Path(out, bik.stem)
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            raw, big = Path(tmp, "raw"), Path(tmp, "big")
            raw.mkdir()
            big.mkdir()
            subprocess.run(["ffmpeg", "-v", "error", "-i", bik, "-fps_mode", "passthrough", raw / "%04d.png"], check=True)
            subprocess.run([ESRGAN, "-i", raw, "-o", big, "-n", "realesrgan-x4plus-anime", "-s", "4"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            frames = sorted(big.glob("*.png"))
            for f in frames:
                subprocess.run(["magick", f, "-filter", "lanczos", "-resize", SIZE, "-quality", "92",
                                dest / (f.stem + ".jpg")], check=True)
        print(f"{bik.stem}: {len(frames)} frames", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:3])

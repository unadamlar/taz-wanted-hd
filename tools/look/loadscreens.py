"""Remaster versions of the four loading screens, from the game's own art: the flat lilac backdrop becomes the
remaster's deep blue with a soft light, and the characters and logos keep their colours. The rules pages' books
(bonus, boss, guide) keep their painted book; the backdrop behind it goes soft and dim, as behind the pause menu.

  python3 tools/look/loadscreens.py <extracted/upscaled> <look folder>   # writes <look folder>/screens/splshscr/splashpc/*.png
"""
import os, sys
import numpy as np
from PIL import Image, ImageFilter

NAMES = ("splash", "splash02", "splash04", "splash5")
BOOKS = {"bonus": (0.76, 0.5, 0.1), "boss": (0.62, 0.34, 0.16), "guide": (0.5, 0.5, 0.56)}  # name: edge tint. The game lays its 3D page over the book painted here
WHITE_BACKDROP = "splash"  # its checker's white squares are cut off from the border by the lilac ones
STOPS = np.array([0.0, 0.25, 0.5, 0.72, 0.88, 1.0])
RAMP = np.array([(6, 11, 52), (15, 31, 120), (31, 79, 214), (63, 148, 242), (143, 208, 255), (233, 247, 255)]) / 255.0


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def border_white(white, step=4):
    """White that reaches the image border: the backdrop, not a white eye or cloud."""
    h, w = white.shape[0] // step, white.shape[1] // step
    low = white[:h * step, :w * step].reshape(h, step, w, step).all(axis=(1, 3))
    seen = np.zeros((h, w), bool)
    todo = [(y, x) for y in range(h) for x in (0, w - 1) if low[y, x]] + [(y, x) for x in range(w) for y in (0, h - 1) if low[y, x]]
    while todo:
        y, x = todo.pop()
        if seen[y, x]:
            continue
        seen[y, x] = True
        for v, u in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= v < h and 0 <= u < w and low[v, u] and not seen[v, u]:
                todo.append((v, u))
    grown = np.asarray(Image.fromarray(seen).resize((white.shape[1], white.shape[0]), Image.NEAREST).filter(ImageFilter.MaxFilter(2 * step + 1)))
    return grown & white


def regrade(rgb, white_backdrop=False):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lilac = smooth(0.03, 0.10, b - np.maximum(r, g)) * (1 - smooth(0.10, 0.22, np.abs(r - g)))
    pale = rgb.min(axis=2) > 0.78
    paper = border_white(pale | (lilac > 0.5)) & pale if white_backdrop else border_white(pale)
    soft = np.asarray(Image.fromarray((paper * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1)), np.float32) / 255
    mask = np.maximum(lilac, soft * paper)
    lum = rgb @ np.array((0.2126, 0.7152, 0.0722))
    new = np.stack([np.interp(lum * (1 - 0.2 * soft), STOPS, RAMP[:, c]) for c in range(3)], axis=2)  # paper must not stay white
    h, w = lum.shape
    y, x = np.mgrid[0:h, 0:w]
    d = ((x / w - 0.5) / 0.62) ** 2 + ((y / h - 0.42) / 0.62) ** 2
    band = 1 - 0.5 * smooth(0.72, 0.75, y / h) * (1 - smooth(0.88, 0.91, y / h))  # the game writes the level name here in grey
    new = np.clip(new * ((0.72 + 0.42 * np.exp(-d * 1.6)) * band)[..., None], 0, 1)
    return rgb * (1 - mask[..., None]) + new * mask[..., None]


def blur(a, r):
    return np.asarray(Image.fromarray(a).filter(ImageFilter.GaussianBlur(r)))


def regrade_book(rgb, tint):
    """The book (inside its black outline) stays as painted; the backdrop goes soft and dims toward the edges into
    `tint` (a multiply: warm keeps a yellow from going olive), with the book's shadow on it. The game puts the page
    here, so the book must not move."""
    full, rgb = rgb, rgb[:rgb.shape[0] * 15 // 16]  # the game shows 640x480 of the 640x512 image: the rest is clear padding
    h, w = rgb.shape[:2]
    lum = rgb @ np.array((0.2126, 0.7152, 0.0722))
    back = border_white(lum > 0.22, step=6)  # reachable from the border without crossing the book's outline
    book = np.asarray(Image.fromarray(~back).filter(ImageFilter.MaxFilter(5)))  # its outline stays crisp
    soft = np.stack([blur((rgb[..., c] * 255).astype(np.uint8), w / 400) for c in range(3)], axis=2) / 255.0
    y, x = np.mgrid[0:h, 0:w]
    by, bx = np.nonzero(book)
    cy, cx = by.mean() / h, bx.mean() / w
    edge = 1 - np.exp(-(((x / w - cx) / 0.62) ** 2 + ((y / h - cy) / 0.58) ** 2) * 1.6)  # 0 at the book, toward 1 in the corners
    shadow = np.zeros((h, w), np.float32)
    dy, dx = h // 70, w // 140
    shadow[dy:, dx:] = blur((book * 255).astype(np.uint8), w / 70)[:h - dy, :w - dx] / 255.0
    dim = (1 - edge[..., None] * (1 - np.array(tint))) * (1 - 0.42 * shadow[..., None])
    keep = blur((book * 255).astype(np.uint8), 1.5)[..., None] / 255.0
    out = full.copy()
    out[:h] = np.clip(rgb * keep + soft * dim * (1 - keep), 0, 1)
    return out


def main(src, look):
    out = os.path.join(look, "screens", "splshscr", "splashpc")
    os.makedirs(out, exist_ok=True)
    for n in NAMES:
        rgb = np.asarray(Image.open(os.path.join(src, "splshscr", "splashpc", n + ".png")).convert("RGB"), np.float32) / 255
        Image.fromarray((regrade(rgb, n == WHITE_BACKDROP) * 255 + 0.5).astype(np.uint8)).save(os.path.join(out, n + ".png"), compress_level=6)
    for n in BOOKS:
        rgba = np.asarray(Image.open(os.path.join(src, "splshscr", "splashpc", n + ".png")).convert("RGBA"))
        rgb = (regrade_book(rgba[..., :3] / np.float32(255), BOOKS[n]) * 255 + 0.5).astype(np.uint8)
        Image.fromarray(np.dstack([rgb, rgba[..., 3]])).save(os.path.join(out, n + ".png"), compress_level=6)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

#!/usr/bin/env python3
"""Generate a 45-second 16:9 promotional video for SINAU Braille.

All graphics and music are created procedurally. No external media assets are used.
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# -----------------------------------------------------------------------------
# Project configuration
# -----------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
SOURCE_W, SOURCE_H = 1280, 720
OUTPUT_W, OUTPUT_H = 1920, 1080
FPS = 30
DURATION = 45.0
TRANSITION = 0.62

RED = (153, 0, 0)
RED_2 = (181, 13, 13)
RED_DARK = (112, 0, 0)
NAVY = (18, 59, 99)
NAVY_DARK = (11, 36, 64)
WHITE = (255, 255, 255)
INK = (15, 24, 44)
MUTED = (103, 119, 137)
BG = (248, 246, 246)
BORDER = (225, 231, 237)
PALE_RED = (251, 238, 238)
PALE_BLUE = (237, 244, 250)
GOLD = (255, 194, 64)
GREEN = (24, 155, 111)

FONT_CANDIDATES = [
    Path("/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf"),
    Path("/usr/share/fonts/google-noto/NotoSans-Regular.ttf"),
    Path("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"),
]
FONT_PATH = next((p for p in FONT_CANDIDATES if p.exists()), None)
if FONT_PATH is None:
    raise RuntimeError("No suitable font was found on this system")


# -----------------------------------------------------------------------------
# General drawing helpers
# -----------------------------------------------------------------------------

def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def progress(t: float, start: float, length: float) -> float:
    return clamp((t - start) / length)


def ease_out(value: float) -> float:
    value = clamp(value)
    return 1.0 - (1.0 - value) ** 3


def ease_in_out(value: float) -> float:
    value = clamp(value)
    return value * value * (3.0 - 2.0 * value)


def pulse(value: float, speed: float = 1.0) -> float:
    return 0.5 + 0.5 * math.sin(value * math.tau * speed)


def mix(a: float, b: float, value: float) -> float:
    return a + (b - a) * value


def mix_color(a: tuple[int, int, int], b: tuple[int, int, int], value: float) -> tuple[int, int, int]:
    return tuple(int(mix(x, y, value)) for x, y in zip(a, b))


@lru_cache(maxsize=128)
def get_font(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    fnt = ImageFont.truetype(str(FONT_PATH), size=size)
    try:
        fnt.set_variation_by_name(weight)
    except (AttributeError, OSError, ValueError):
        pass
    return fnt


def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    value: str,
    size: int,
    fill: tuple[int, ...] = INK,
    weight: str = "Regular",
    anchor: str = "la",
    spacing: int = 4,
    align: str = "left",
    stroke_width: int = 0,
    stroke_fill: tuple[int, ...] | None = None,
) -> None:
    draw.multiline_text(
        xy,
        value,
        font=get_font(size, weight),
        fill=fill,
        anchor=anchor,
        spacing=spacing,
        align=align,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def text_width(value: str, size: int, weight: str = "Regular") -> float:
    box = get_font(size, weight).getbbox(value)
    return float(box[2] - box[0])


def rounded_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    radius: int = 18,
    fill: tuple[int, ...] = WHITE,
    outline: tuple[int, ...] | None = BORDER,
    width: int = 1,
    shadow: bool = True,
) -> None:
    x1, y1, x2, y2 = box
    if shadow:
        draw.rounded_rectangle(
            (x1 + 2, y1 + 8, x2 + 2, y2 + 8),
            radius=radius,
            fill=(8, 30, 54, 18),
        )
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    label: str,
    fill: tuple[int, ...],
    foreground: tuple[int, ...],
    size: int = 15,
    pad_x: int = 15,
    height: int = 32,
    outline: tuple[int, ...] | None = None,
    weight: str = "SemiBold",
) -> float:
    width = text_width(label, size, weight) + pad_x * 2
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=fill, outline=outline)
    text(draw, (x + width / 2, y + height / 2 - 1), label, size, foreground, weight, "mm")
    return width


def draw_progress(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    value: float,
    color: tuple[int, ...] = RED,
    background: tuple[int, ...] = (231, 235, 240),
) -> None:
    x1, y1, x2, y2 = box
    radius = max(1, int((y2 - y1) / 2))
    draw.rounded_rectangle(box, radius=radius, fill=background)
    if value > 0:
        draw.rounded_rectangle((x1, y1, mix(x1, x2, clamp(value)), y2), radius=radius, fill=color)


def draw_scan_icon(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, color: tuple[int, ...], width: int = 3) -> None:
    q = size * 0.34
    for sx, sy, dx, dy in [
        (x, y, 1, 1),
        (x + size, y, -1, 1),
        (x, y + size, 1, -1),
        (x + size, y + size, -1, -1),
    ]:
        draw.line((sx, sy, sx + dx * q, sy), fill=color, width=width)
        draw.line((sx, sy, sx, sy + dy * q), fill=color, width=width)


def draw_book_icon(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, color: tuple[int, ...]) -> None:
    mid = x + size / 2
    draw.line((mid, y + 5, mid, y + size - 4), fill=color, width=2)
    draw.rounded_rectangle((x, y + 3, mid - 2, y + size - 3), radius=4, outline=color, width=2)
    draw.rounded_rectangle((mid + 2, y + 3, x + size, y + size - 3), radius=4, outline=color, width=2)
    draw.line((x + 5, y + 10, mid - 7, y + 10), fill=color, width=1)
    draw.line((mid + 7, y + 10, x + size - 5, y + 10), fill=color, width=1)


def draw_check(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, color: tuple[int, ...], width: int = 3) -> None:
    draw.line((x, y + size * 0.52, x + size * 0.35, y + size * 0.82, x + size, y), fill=color, width=width, joint="curve")


def draw_people(draw: ImageDraw.ImageDraw, x: float, y: float, color: tuple[int, ...]) -> None:
    specs = [(0, 12, 14), (34, 0, 18), (76, 12, 14)]
    for dx, dy, r in specs:
        cx = x + dx + r
        cy = y + dy + r
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        draw.rounded_rectangle((cx - r * 1.25, cy + r + 8, cx + r * 1.25, cy + r + 50), radius=r, fill=color)


def draw_logo(img: Image.Image, x: float, y: float, light: bool = False, scale: float = 1.0) -> None:
    draw = ImageDraw.Draw(img, "RGBA")
    icon = 41 * scale
    fg = WHITE if light else RED
    secondary = (255, 255, 255, 190) if light else NAVY
    ix, iy = x, y
    draw.rounded_rectangle((ix, iy, ix + icon, iy + icon), radius=int(10 * scale), fill=WHITE if light else PALE_BLUE)
    draw_scan_icon(draw, ix + 7 * scale, iy + 7 * scale, 27 * scale, NAVY if not light else RED, max(1, int(2 * scale)))
    dots = [(0, 0), (0, 2), (1, 0), (1, 1)]
    for col, row in dots:
        cx = ix + (15 + col * 10) * scale
        cy = iy + (13 + row * 7) * scale
        r = 2.7 * scale
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED if not light else NAVY)
    tx = ix + icon + 12 * scale
    text(draw, (tx, iy + 1 * scale), "SINAU", max(13, int(24 * scale)), fg, "Bold", "la")
    text(draw, (tx, iy + 29 * scale), "BRAILLE UNTUK SEMUA", max(7, int(9 * scale)), secondary, "SemiBold", "la")


def background_gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    y = np.linspace(0.0, 1.0, SOURCE_H, dtype=np.float32)[:, None, None]
    top_arr = np.array(top, dtype=np.float32)[None, None, :]
    bottom_arr = np.array(bottom, dtype=np.float32)[None, None, :]
    row = top_arr * (1.0 - y) + bottom_arr * y
    full = np.repeat(row, SOURCE_W, axis=1).astype(np.uint8)
    return Image.fromarray(full, mode="RGB").convert("RGBA")


BG_RED = background_gradient(RED_DARK, RED_2)
BG_NAVY = background_gradient(NAVY_DARK, NAVY)
BG_LIGHT = background_gradient(WHITE, BG)


# -----------------------------------------------------------------------------
# Braille helpers
# -----------------------------------------------------------------------------

BRAILLE = {
    "a": (1,), "b": (1, 2), "c": (1, 4), "d": (1, 4, 5), "e": (1, 5),
    "f": (1, 2, 4), "g": (1, 2, 4, 5), "h": (1, 2, 5), "i": (2, 4), "j": (2, 4, 5),
    "k": (1, 3), "l": (1, 2, 3), "m": (1, 3, 4), "n": (1, 3, 4, 5), "o": (1, 3, 5),
    "p": (1, 2, 3, 4), "q": (1, 2, 3, 4, 5), "r": (1, 2, 3, 5), "s": (2, 3, 4), "t": (2, 3, 4, 5),
    "u": (1, 3, 6), "v": (1, 2, 3, 6), "w": (2, 4, 5, 6), "x": (1, 3, 4, 6),
    "y": (1, 3, 4, 5, 6), "z": (1, 3, 5, 6),
}
DOT_POS = {1: (0, 0), 2: (0, 1), 3: (0, 2), 4: (1, 0), 5: (1, 1), 6: (1, 2)}


def draw_braille_cell(
    draw: ImageDraw.ImageDraw,
    char: str,
    x: float,
    y: float,
    scale: float,
    color: tuple[int, ...],
    inactive: tuple[int, ...] | None = None,
    embossed: bool = False,
    glow: float = 0.0,
) -> None:
    active = set(BRAILLE.get(char.lower(), ()))
    for number in range(1, 7):
        col, row = DOT_POS[number]
        cx = x + col * 13 * scale
        cy = y + row * 13 * scale
        radius = 4.2 * scale
        if number in active:
            if glow > 0:
                gr = radius + 5 * glow
                draw.ellipse((cx - gr, cy - gr, cx + gr, cy + gr), fill=(*color[:3], int(35 * glow)))
            if embossed:
                draw.ellipse((cx - radius + 1.5, cy - radius + 2, cx + radius + 1.5, cy + radius + 2), fill=(40, 55, 70, 35))
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(244, 241, 234), outline=(184, 184, 178), width=1)
                draw.ellipse((cx - radius * 0.55, cy - radius * 0.7, cx + radius * 0.15, cy), fill=(255, 255, 255, 170))
            else:
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
        elif inactive is not None:
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=inactive)


def draw_braille_line(
    draw: ImageDraw.ImageDraw,
    value: str,
    x: float,
    y: float,
    scale: float = 1.0,
    color: tuple[int, ...] = NAVY,
    inactive: tuple[int, ...] | None = None,
    embossed: bool = False,
    reveal: float = 1.0,
    highlight_index: int | None = None,
) -> float:
    cursor = x
    visible = max(0, int(math.ceil(len(value) * clamp(reveal))))
    for index, char in enumerate(value):
        if char == " ":
            cursor += 18 * scale
            continue
        if index < visible:
            glow = 1.0 if highlight_index == index else 0.0
            cell_color = RED if highlight_index == index else color
            draw_braille_cell(draw, char, cursor, y, scale, cell_color, inactive, embossed, glow)
        cursor += 27 * scale
    return cursor


def braille_width(value: str, scale: float = 1.0) -> float:
    total = 0.0
    for char in value:
        total += (18 if char == " " else 27) * scale
    return total


# -----------------------------------------------------------------------------
# Scene renderers
# -----------------------------------------------------------------------------

def scene_intro(t: float, duration: float) -> Image.Image:
    img = BG_RED.copy()
    draw = ImageDraw.Draw(img, "RGBA")

    # Decorative Braille field, inspired by the dotted motif in the references.
    for row in range(7):
        for col in range(9):
            wave = pulse(t * 0.12 + row * 0.07 + col * 0.045)
            radius = 4 + 6 * wave
            cx = 940 + col * 47 + math.sin(t * 0.6 + row) * 8
            cy = 12 + row * 47
            alpha = int(18 + 30 * wave)
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(255, 255, 255, alpha))

    # Bottom-left dot texture.
    for row in range(4):
        for col in range(8):
            cx, cy = 38 + col * 25, 598 + row * 25
            draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=(255, 255, 255, 38))

    draw_logo(img, 72, 48, light=True, scale=0.88)
    enter = ease_out(progress(t, 0.12, 0.7))
    chip_y = mix(142, 118, enter)
    pill(draw, 74, chip_y, "AKSES BELAJAR INKLUSIF", (255, 255, 255, 26), WHITE, 13, 15, 30, (255, 255, 255, 75))

    p1 = ease_out(progress(t, 0.35, 0.82))
    x = mix(28, 74, p1)
    text(draw, (x, 195), "Sentuh titiknya.", 60, WHITE, "Bold")

    p2 = ease_out(progress(t, 0.72, 0.82))
    x2 = mix(28, 74, p2)
    text(draw, (x2, 267), "Temukan maknanya.", 60, GOLD, "Bold")

    p3 = ease_out(progress(t, 1.35, 0.8))
    sub_y = mix(385, 360, p3)
    text(
        draw,
        (76, sub_y),
        "Belajar dan menerjemahkan Braille\ndalam satu aplikasi.",
        24,
        (255, 255, 255, int(225 * p3)),
        "Regular",
        spacing=10,
    )

    # Hero Braille tile.
    card_p = ease_out(progress(t, 0.55, 1.0))
    card_x = mix(1250, 820, card_p)
    rounded_card(draw, (card_x, 330, card_x + 375, 612), 28, WHITE, None, shadow=True)
    text(draw, (card_x + 30, 361), "PESAN DALAM BRAILLE", 12, RED, "Bold")
    draw_braille_line(draw, "sinau", card_x + 35, 418, 1.45, NAVY, (218, 226, 234))
    draw.line((card_x + 30, 506, card_x + 345, 506), fill=BORDER, width=2)
    text(draw, (card_x + 30, 528), "SINAU", 32, INK, "Bold")
    text(draw, (card_x + 30, 571), "Titik menjadi kata.", 17, MUTED, "Regular")

    scan_y = 405 + (t * 88) % 95
    draw.line((card_x + 22, scan_y, card_x + 353, scan_y), fill=(*RED, 155), width=3)
    draw.ellipse((card_x + 337, scan_y - 4, card_x + 345, scan_y + 4), fill=RED)
    return img


def scene_purpose(t: float, duration: float) -> Image.Image:
    img = BG_LIGHT.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_logo(img, 70, 45, light=False, scale=0.78)
    pill(draw, 1010, 49, "BRAILLE UNTUK SEMUA", PALE_RED, RED, 12, 15, 29)

    p = ease_out(progress(t, 0.0, 0.85))
    left_x = mix(-80, 76, p)
    text(draw, (left_x, 145), "Satu titik,\nsatu makna.", 51, INK, "Bold", spacing=0)
    text(
        draw,
        (left_x + 3, 290),
        "Dukung proses belajar Braille sekaligus\npermudah penerjemahan karya berbasis titik.",
        21,
        MUTED,
        "Regular",
        spacing=8,
    )

    feature_y = 414
    features = [
        ("01", "Kenali pola", RED, PALE_RED),
        ("02", "Pahami huruf", NAVY, PALE_BLUE),
        ("03", "Baca makna", GREEN, (235, 248, 243)),
    ]
    for index, (number, label, color, pale) in enumerate(features):
        fp = ease_out(progress(t, 0.55 + index * 0.18, 0.55))
        bx = left_x + index * 177
        by = mix(feature_y + 28, feature_y, fp)
        rounded_card(draw, (bx, by, bx + 158, by + 92), 16, pale, None, shadow=False)
        text(draw, (bx + 17, by + 17), number, 12, color, "Bold")
        text(draw, (bx + 17, by + 48), label, 16, INK, "SemiBold")

    # Translation card.
    cp = ease_out(progress(t, 0.2, 0.8))
    cx = mix(1310, 700, cp)
    cy = 128
    rounded_card(draw, (cx, cy, cx + 500, cy + 500), 26, WHITE, BORDER, 1, True)
    text(draw, (cx + 34, cy + 31), "BRAILLE", 13, RED, "Bold")
    pill(draw, cx + 330, cy + 23, "TERDETEKSI", (232, 248, 241), GREEN, 11, 13, 27)

    reveal = ease_in_out(progress(t, 0.9, 1.2))
    draw_braille_line(draw, "selamat", cx + 38, cy + 102, 1.18, NAVY, (225, 231, 237), reveal=reveal)
    draw_braille_line(draw, "datang", cx + 38, cy + 171, 1.18, NAVY, (225, 231, 237), reveal=reveal)
    arrow_y = cy + 245
    draw.line((cx + 34, arrow_y, cx + 466, arrow_y), fill=BORDER, width=2)
    circle_x = cx + 250
    draw.ellipse((circle_x - 22, arrow_y - 22, circle_x + 22, arrow_y + 22), fill=RED)
    draw.line((circle_x - 7, arrow_y - 4, circle_x + 8, arrow_y - 4), fill=WHITE, width=3)
    draw.line((circle_x + 8, arrow_y - 4, circle_x + 2, arrow_y - 10), fill=WHITE, width=3)
    draw.line((circle_x + 8, arrow_y - 4, circle_x + 2, arrow_y + 2), fill=WHITE, width=3)

    result_p = ease_out(progress(t, 1.85, 0.7))
    text(draw, (cx + 34, cy + 290), "HASIL TERJEMAHAN", 13, NAVY, "Bold")
    result = "SELAMAT DATANG"
    letters = max(0, int(len(result) * result_p))
    text(draw, (cx + 34, cy + 332), result[:letters], 34, INK, "Bold")
    text(draw, (cx + 34, cy + 400), "Kini makna dapat dibaca lebih banyak orang.", 16, MUTED, "Regular")
    draw.rounded_rectangle((cx + 34, cy + 445, cx + 466, cy + 451), radius=3, fill=(232, 236, 240))
    draw.rounded_rectangle((cx + 34, cy + 445, cx + 34 + 432 * result_p, cy + 451), radius=3, fill=RED)
    return img


def _draw_phone_camera(draw: ImageDraw.ImageDraw, t: float, x: float, y: float, scan_active: bool) -> None:
    # Device shell.
    draw.rounded_rectangle((x, y, x + 420, y + 518), radius=36, fill=NAVY_DARK)
    draw.rounded_rectangle((x + 12, y + 12, x + 408, y + 506), radius=28, fill=(250, 248, 244))
    draw.rounded_rectangle((x + 163, y + 22, x + 257, y + 31), radius=5, fill=(35, 55, 74))

    page = (x + 34, y + 56, x + 386, y + 438)
    draw.rounded_rectangle(page, radius=16, fill=(245, 242, 234), outline=(221, 216, 205), width=1)
    text(draw, (x + 55, y + 77), "DOKUMEN BRAILLE", 11, (121, 115, 103), "SemiBold")
    phrases = [("selamat datang", 132), ("belajar braille", 211), ("untuk semua", 290)]

    phase = (t * 0.31) % 2.0
    phase = phase if phase <= 1.0 else 2.0 - phase
    scan_y = y + 105 + phase * 294
    for phrase, offset in phrases:
        width = braille_width(phrase, 0.77)
        start_x = x + 210 - width / 2
        draw_braille_line(draw, phrase, start_x, y + offset, 0.77, NAVY, None, embossed=True)

    # Camera guides.
    draw_scan_icon(draw, x + 52, y + 95, 316, (18, 59, 99, 155), 3)
    if scan_active:
        draw.rectangle((x + 35, scan_y - 18, x + 385, scan_y + 18), fill=(153, 0, 0, 12))
        draw.line((x + 36, scan_y, x + 384, scan_y), fill=(215, 31, 31, 220), width=4)
        draw.ellipse((x + 374, scan_y - 5, x + 384, scan_y + 5), fill=RED)

    # Bottom controls.
    draw.rounded_rectangle((x + 36, y + 457, x + 160, y + 487), radius=15, fill=PALE_BLUE)
    text(draw, (x + 98, y + 472), "AUTO FOCUS", 10, NAVY, "Bold", "mm")
    draw.ellipse((x + 190, y + 451, x + 238, y + 499), fill=WHITE, outline=RED, width=4)
    draw.ellipse((x + 202, y + 463, x + 226, y + 487), fill=RED)
    draw.rounded_rectangle((x + 267, y + 457, x + 384, y + 487), radius=15, fill=PALE_RED)
    text(draw, (x + 326, y + 472), "BRAILLE", 10, RED, "Bold", "mm")


def scene_scan(t: float, duration: float) -> Image.Image:
    img = BG_LIGHT.copy()
    draw = ImageDraw.Draw(img, "RGBA")

    # Strong red side panel keeps the visual language close to the supplied UI.
    draw.rounded_rectangle((-100, -60, 456, 780), radius=70, fill=RED)
    for row in range(8):
        for col in range(5):
            r = 3 + 2 * pulse(t * 0.15 + row * 0.12 + col * 0.05)
            cx, cy = 42 + col * 35, 65 + row * 35
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 25))

    phone_p = ease_out(progress(t, 0.15, 0.95))
    phone_x = mix(-470, 48, phone_p)
    _draw_phone_camera(draw, t, phone_x, 142, scan_active=t >= 2.6)

    title_p = ease_out(progress(t, 0.15, 0.7))
    title_x = mix(1320, 522, title_p)
    pill(draw, title_x, 49, "FITUR UTAMA 01", PALE_RED, RED, 12, 14, 29)
    text(draw, (title_x, 94), "Scan Braille,\nlangsung jadi teks.", 43, INK, "Bold", spacing=2)

    # Three-step indicator.
    step_y = 235
    steps = ["Arahkan kamera", "Pindai pola titik", "Baca hasilnya"]
    active_step = 0 if t < 2.8 else (1 if t < 6.0 else 2)
    for index, label in enumerate(steps):
        y = step_y + index * 58
        active = index <= active_step
        circle_fill = RED if active else (226, 231, 236)
        foreground = WHITE if active else MUTED
        draw.ellipse((title_x, y, title_x + 32, y + 32), fill=circle_fill)
        text(draw, (title_x + 16, y + 15), str(index + 1), 13, foreground, "Bold", "mm")
        text(draw, (title_x + 48, y + 15), label, 17, INK if active else MUTED, "SemiBold", "lm")
        if index < 2:
            draw.line((title_x + 16, y + 34, title_x + 16, y + 54), fill=RED if index < active_step else BORDER, width=3)

    # Result panel.
    result_y = 433
    rounded_card(draw, (title_x, result_y, title_x + 682, result_y + 205), 20, WHITE, BORDER, 1, True)
    icon_box = (title_x + 24, result_y + 24, title_x + 74, result_y + 74)
    draw.rounded_rectangle(icon_box, radius=13, fill=PALE_RED)
    draw_scan_icon(draw, title_x + 36, result_y + 36, 26, RED, 2)
    text(draw, (title_x + 91, result_y + 27), "HASIL TERJEMAHAN", 12, NAVY, "Bold")

    if t < 5.4:
        dots = "." * (1 + int(t * 2.5) % 3)
        text(draw, (title_x + 91, result_y + 56), f"Mengenali pola{dots}", 22, MUTED, "SemiBold")
        bar_value = 0.12 + 0.72 * progress(t, 2.3, 3.1)
        draw_progress(draw, (title_x + 24, result_y + 101, title_x + 658, result_y + 109), bar_value, RED)
        text(draw, (title_x + 24, result_y + 139), "Pastikan seluruh pola berada di dalam bingkai.", 14, MUTED)
    else:
        reveal = progress(t, 5.55, 1.15)
        result = "SELAMAT DATANG"
        letters = int(len(result) * reveal)
        text(draw, (title_x + 91, result_y + 55), result[:letters], 29, INK, "Bold")
        draw.ellipse((title_x + 26, result_y + 112, title_x + 46, result_y + 132), fill=GREEN)
        draw_check(draw, title_x + 31, result_y + 117, 10, WHITE, 2)
        text(draw, (title_x + 58, result_y + 121), "Pola Braille berhasil diterjemahkan", 15, GREEN, "SemiBold", "lm")
        labels = [("Cepat", PALE_RED, RED), ("Praktis", PALE_BLUE, NAVY), ("Mudah dibaca", (235, 248, 243), GREEN)]
        px = title_x + 24
        for index, (label, bg, fg) in enumerate(labels):
            if t > 6.3 + index * 0.18:
                px += pill(draw, px, result_y + 155, label, bg, fg, 12, 14, 29) + 9
    return img


def _sidebar_nav(draw: ImageDraw.ImageDraw, x: float, y: float, label: str, active: bool, icon: str) -> None:
    fill = RED if active else (255, 255, 255, 0)
    foreground = WHITE if active else NAVY
    if active:
        draw.rounded_rectangle((x, y, x + 188, y + 43), radius=11, fill=fill)
    if icon == "book":
        draw_book_icon(draw, x + 14, y + 11, 21, foreground)
    elif icon == "scan":
        draw_scan_icon(draw, x + 15, y + 11, 19, foreground, 2)
    elif icon == "progress":
        for i, h in enumerate((9, 17, 25)):
            draw.rounded_rectangle((x + 15 + i * 7, y + 31 - h, x + 19 + i * 7, y + 31), radius=2, fill=foreground)
    else:
        draw.ellipse((x + 15, y + 12, x + 34, y + 31), outline=foreground, width=2)
    text(draw, (x + 45, y + 21), label, 14, foreground, "SemiBold", "lm")


def scene_learning(t: float, duration: float) -> Image.Image:
    img = BG_LIGHT.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    panel_p = ease_out(progress(t, 0.0, 0.85))
    panel_x = mix(-230, 38, panel_p)

    # Sidebar copied in spirit—not content—from the supplied dashboard references.
    rounded_card(draw, (panel_x, 30, panel_x + 216, 690), 22, WHITE, BORDER, 1, True)
    draw_logo(img, panel_x + 22, 51, light=False, scale=0.63)
    text(draw, (panel_x + 22, 121), "BELAJAR", 10, MUTED, "Bold")
    _sidebar_nav(draw, panel_x + 14, 141, "Pusat Belajar", True, "book")
    _sidebar_nav(draw, panel_x + 14, 193, "Scan Braille", False, "scan")
    _sidebar_nav(draw, panel_x + 14, 245, "Latihan", False, "quiz")
    _sidebar_nav(draw, panel_x + 14, 297, "Progres", False, "progress")
    draw.line((panel_x + 22, 360, panel_x + 194, 360), fill=BORDER, width=1)
    text(draw, (panel_x + 22, 383), "PROGRES HARI INI", 10, MUTED, "Bold")
    draw_progress(draw, (panel_x + 22, 410, panel_x + 194, 419), 0.68 if t < 8.2 else 0.82, RED)
    text(draw, (panel_x + 22, 438), "3 aktivitas selesai", 13, NAVY, "SemiBold")

    main_p = ease_out(progress(t, 0.18, 0.9))
    mx = mix(1320, 286, main_p)
    pill(draw, mx, 44, "FITUR UTAMA 02", PALE_BLUE, NAVY, 12, 14, 29)
    text(draw, (mx, 88), "Belajar sesuai ritmemu.", 39, INK, "Bold")
    text(draw, (mx, 137), "Materi bertahap, latihan interaktif, dan progres yang terlihat.", 17, MUTED)

    # Course progress card.
    rounded_card(draw, (mx, 184, mx + 926, 270), 18, WHITE, BORDER, 1, True)
    draw.rounded_rectangle((mx + 22, 204, mx + 66, 248), radius=12, fill=PALE_RED)
    draw_book_icon(draw, mx + 32, 213, 24, RED)
    text(draw, (mx + 83, 202), "HURUF DASAR A–J", 12, RED, "Bold")
    text(draw, (mx + 83, 226), "Langkah 3 dari 5", 18, INK, "SemiBold")
    progress_value = mix(0.4, 0.6, ease_in_out(progress(t, 7.3, 1.2)))
    draw_progress(draw, (mx + 567, 218, mx + 882, 229), progress_value, RED)
    text(draw, (mx + 882, 204), f"{int(progress_value * 100)}%", 13, NAVY, "Bold", "ra")
    text(draw, (mx + 882, 244), "Teruskan", 13, RED, "SemiBold", "ra")

    # Interactive lesson.
    rounded_card(draw, (mx, 291, mx + 454, 642), 20, WHITE, BORDER, 1, True)
    text(draw, (mx + 25, 316), "KENALI POLA", 12, NAVY, "Bold")
    text(draw, (mx + 25, 347), "Huruf B", 29, INK, "Bold")
    text(draw, (mx + 25, 385), "Raba atau amati posisi titik aktif.", 14, MUTED)

    # Large six-dot Braille teaching cell.
    cell_x, cell_y = mx + 140, 444
    pattern_p = ease_out(progress(t, 1.9, 0.9))
    active_b = set(BRAILLE["b"])
    for number in range(1, 7):
        col, row = DOT_POS[number]
        cx = cell_x + col * 91
        cy = cell_y + row * 64
        radius = 19
        if number in active_b:
            grow = 0.65 + 0.35 * pattern_p
            rr = radius * grow
            draw.ellipse((cx - rr - 7, cy - rr - 7, cx + rr + 7, cy + rr + 7), fill=(153, 0, 0, int(20 + 18 * pulse(t * 0.7))))
            draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=RED)
        else:
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(238, 241, 244), outline=(208, 216, 224), width=2)
    text(draw, (mx + 25, 605), "Titik aktif: 1 dan 2", 13, RED, "SemiBold")

    # Quiz card.
    qx = mx + 478
    rounded_card(draw, (qx, 291, qx + 448, 642), 20, WHITE, BORDER, 1, True)
    text(draw, (qx + 25, 316), "LATIHAN CEPAT", 12, RED, "Bold")
    text(draw, (qx + 25, 352), "Pola di sebelah adalah huruf...", 21, INK, "SemiBold")
    text(draw, (qx + 25, 387), "Pilih satu jawaban", 13, MUTED)

    selected = t >= 5.6
    answer_p = ease_out(progress(t, 5.55, 0.55))
    for index, answer in enumerate(("A", "B", "C")):
        y = 428 + index * 58
        is_answer = answer == "B" and selected
        border = RED if is_answer else BORDER
        fill = PALE_RED if is_answer else WHITE
        draw.rounded_rectangle((qx + 25, y, qx + 423, y + 44), radius=11, fill=fill, outline=border, width=2 if is_answer else 1)
        draw.ellipse((qx + 39, y + 12, qx + 59, y + 32), outline=RED if is_answer else (185, 195, 205), width=2)
        if is_answer:
            dot_r = 5 * answer_p
            draw.ellipse((qx + 49 - dot_r, y + 22 - dot_r, qx + 49 + dot_r, y + 22 + dot_r), fill=RED)
        text(draw, (qx + 73, y + 21), answer, 16, INK, "SemiBold", "lm")
        if is_answer:
            draw_check(draw, qx + 379, y + 15, 15, RED, 3)

    if t >= 6.1:
        success_p = ease_out(progress(t, 6.1, 0.5))
        pill(draw, qx + 25, 607, "BENAR — LANJUTKAN", (232, 248, 241, int(255 * success_p)), GREEN, 11, 13, 28)

    # Benefit chips.
    labels = [
        ("Materi bertahap", RED, PALE_RED),
        ("Latihan interaktif", NAVY, PALE_BLUE),
        ("Pantau progres", GREEN, (235, 248, 243)),
    ]
    cx = 286
    for index, (label, fg, bg) in enumerate(labels):
        if t > 8.0 + index * 0.2:
            cx += pill(draw, cx, 667, label, bg, fg, 12, 14, 29) + 10
    return img


def scene_impact(t: float, duration: float) -> Image.Image:
    img = BG_NAVY.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_logo(img, 65, 42, light=True, scale=0.72)
    pill(draw, 1040, 48, "DAMPAK INKLUSIF", (255, 255, 255, 22), WHITE, 11, 14, 28, (255, 255, 255, 62))

    heading_p = ease_out(progress(t, 0.05, 0.7))
    text(draw, (640, mix(126, 104, heading_p)), "Satu jembatan, lebih banyak pembaca.", 39, WHITE, "Bold", "ma")
    text(
        draw,
        (640, 157),
        "Karya dalam Braille dapat diterjemahkan dan dipahami masyarakat lebih luas.",
        17,
        (255, 255, 255, 190),
        "Regular",
        "ma",
    )

    # Left source card.
    lp = ease_out(progress(t, 0.35, 0.8))
    lx = mix(-410, 78, lp)
    rounded_card(draw, (lx, 241, lx + 372, 560), 24, WHITE, None, shadow=True)
    text(draw, (lx + 29, 270), "KARYA DALAM BRAILLE", 12, RED, "Bold")
    draw_braille_line(draw, "cerita", lx + 35, 344, 1.22, NAVY, (224, 231, 237), reveal=progress(t, 0.8, 1.1))
    draw_braille_line(draw, "untuk semua", lx + 35, 422, 0.88, NAVY, (224, 231, 237), reveal=progress(t, 1.1, 1.2))
    text(draw, (lx + 29, 517), "Pola titik menyimpan cerita.", 15, MUTED, "Regular")

    # Right translated card.
    rp = ease_out(progress(t, 0.75, 0.8))
    rx = mix(1310, 830, rp)
    rounded_card(draw, (rx, 241, rx + 372, 560), 24, WHITE, None, shadow=True)
    text(draw, (rx + 29, 270), "TEKS UNTUK SEMUA", 12, GREEN, "Bold")
    text(draw, (rx + 29, 332), "“Cerita untuk\nsemua.”", 35, INK, "Bold", spacing=4)
    text(draw, (rx + 29, 451), "Lebih mudah dibaca,\ndibagikan, dan diapresiasi.", 16, MUTED, "Regular", spacing=6)
    draw_people(draw, rx + 232, 467, PALE_BLUE)

    # Animated bridge and scan token.
    bridge_start, bridge_end = 475, 804
    bridge_y = 400
    draw.line((bridge_start, bridge_y, bridge_end, bridge_y), fill=(255, 255, 255, 65), width=3)
    for index in range(8):
        phase = (t * 0.38 + index / 8.0) % 1.0
        cx = mix(bridge_start, bridge_end, phase)
        cy = bridge_y + math.sin(phase * math.pi * 2 + index) * 18
        alpha = int(80 + 150 * math.sin(phase * math.pi))
        r = 3 + 2 * math.sin(phase * math.pi)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 194, 64, alpha))

    token_x = mix(bridge_start, bridge_end, (t * 0.22) % 1.0)
    draw.ellipse((token_x - 31, bridge_y - 31, token_x + 31, bridge_y + 31), fill=RED)
    draw_scan_icon(draw, token_x - 15, bridge_y - 15, 30, WHITE, 2)
    text(draw, (640, 613), "Dari pola titik menjadi makna yang dapat menjangkau lebih banyak orang.", 17, (255, 255, 255, 205), "SemiBold", "ma")
    return img


def scene_final(t: float, duration: float) -> Image.Image:
    img = BG_RED.copy()
    draw = ImageDraw.Draw(img, "RGBA")

    # Concentric circles and floating Braille dots.
    center = (640, 340)
    for radius, alpha in [(295, 15), (235, 20), (175, 26)]:
        draw.ellipse((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius), outline=(255, 255, 255, alpha), width=2)
    for index in range(24):
        angle = index / 24 * math.tau + t * 0.12
        radius = 245 + 35 * math.sin(index * 1.7 + t)
        cx = center[0] + math.cos(angle) * radius
        cy = center[1] + math.sin(angle) * radius * 0.58
        rr = 3 + 2 * pulse(t * 0.2 + index * 0.08)
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(255, 255, 255, 42))

    logo_p = ease_out(progress(t, 0.05, 0.65))
    logo_x = mix(570, 542, logo_p)
    draw_logo(img, logo_x, 83, light=True, scale=1.0)

    hp = ease_out(progress(t, 0.45, 0.8))
    title_y = mix(270, 230, hp)
    text(draw, (640, title_y), "Belajar. Pindai. Pahami.", 52, WHITE, "Bold", "ma")
    text(draw, (640, title_y + 70), "Braille untuk semua.", 42, GOLD, "Bold", "ma")
    text(
        draw,
        (640, title_y + 133),
        "Pembelajaran dan penerjemahan Braille dalam satu aplikasi.",
        18,
        (255, 255, 255, 210),
        "Regular",
        "ma",
    )

    bp = ease_out(progress(t, 1.25, 0.65))
    button_w = mix(210, 286, bp)
    bx1, by1 = 640 - button_w / 2, 475
    draw.rounded_rectangle((bx1, by1, bx1 + button_w, by1 + 58), radius=16, fill=WHITE)
    text(draw, (640, by1 + 28), "MULAI BERSAMA SINAU", 15, RED, "Bold", "mm")
    draw.line((742, by1 + 28, 760, by1 + 28), fill=RED, width=3)
    draw.line((760, by1 + 28, 753, by1 + 21), fill=RED, width=3)
    draw.line((760, by1 + 28, 753, by1 + 35), fill=RED, width=3)

    text(draw, (640, 598), "PEMBELAJARAN   •   SCAN   •   TERJEMAHAN", 12, (255, 255, 255, 165), "SemiBold", "ma")
    draw_braille_line(draw, "sinau", 553, 649, 0.8, (255, 255, 255, 140), None, reveal=1.0)

    # Gentle ending fade keeps the final card visible, not abruptly cut.
    if t > duration - 0.9:
        alpha = int(58 * ease_in_out(progress(t, duration - 0.9, 0.9)))
        draw.rectangle((0, 0, SOURCE_W, SOURCE_H), fill=(65, 0, 0, alpha))
    return img


SCENES: list[tuple[str, float, Callable[[float, float], Image.Image]]] = [
    ("Pembuka", 5.5, scene_intro),
    ("Nilai Produk", 4.5, scene_purpose),
    ("Fitur Scan", 12.0, scene_scan),
    ("Fitur Belajar", 12.0, scene_learning),
    ("Dampak", 6.0, scene_impact),
    ("Penutup", 5.0, scene_final),
]


def frame_at(t: float) -> Image.Image:
    t = clamp(t, 0.0, DURATION - 1.0 / FPS)
    cursor = 0.0
    for index, (_, length, renderer) in enumerate(SCENES):
        if t < cursor + length or index == len(SCENES) - 1:
            local = t - cursor
            current = renderer(local, length)
            if index < len(SCENES) - 1 and local > length - TRANSITION:
                next_name, next_length, next_renderer = SCENES[index + 1]
                _ = next_name
                blend_value = ease_in_out((local - (length - TRANSITION)) / TRANSITION)
                next_local = local - (length - TRANSITION)
                following = next_renderer(next_local, next_length)
                current = Image.blend(current.convert("RGB"), following.convert("RGB"), blend_value).convert("RGBA")
            if t < 0.55:
                intro_fade = ease_in_out(t / 0.55)
                dark = Image.new("RGB", (SOURCE_W, SOURCE_H), RED_DARK)
                current = Image.blend(dark, current.convert("RGB"), intro_fade).convert("RGBA")
            return current
        cursor += length
    return scene_final(4.99, 5.0)


# -----------------------------------------------------------------------------
# Original music generator
# -----------------------------------------------------------------------------

def midi(note: float) -> float:
    return 440.0 * (2.0 ** ((note - 69.0) / 12.0))


def create_music(path: Path, duration: float = DURATION, sample_rate: int = 44100) -> None:
    rng = np.random.default_rng(990000)
    total = int(duration * sample_rate)
    left = np.zeros(total, dtype=np.float32)
    right = np.zeros(total, dtype=np.float32)

    def add_signal(start: float, signal: np.ndarray, pan: float = 0.0) -> None:
        begin = max(0, int(start * sample_rate))
        if begin >= total:
            return
        end = min(total, begin + len(signal))
        signal = signal[: end - begin]
        left_gain = math.sqrt((1.0 - pan) / 2.0)
        right_gain = math.sqrt((1.0 + pan) / 2.0)
        left[begin:end] += signal * left_gain
        right[begin:end] += signal * right_gain

    def tone(freq: float, length: float, amplitude: float, kind: str = "soft", attack: float = 0.02, release: float = 0.3) -> np.ndarray:
        count = max(1, int(length * sample_rate))
        tt = np.arange(count, dtype=np.float32) / sample_rate
        if kind == "pluck":
            base = np.sin(math.tau * freq * tt) + 0.32 * np.sin(math.tau * freq * 2.0 * tt) + 0.12 * np.sin(math.tau * freq * 3.0 * tt)
            env = np.exp(-tt * 4.8)
        elif kind == "bass":
            base = np.sin(math.tau * freq * tt) + 0.20 * np.sin(math.tau * freq * 2.0 * tt)
            env = (1.0 - np.exp(-tt * 18.0)) * np.exp(-tt * 1.9)
        else:
            base = np.sin(math.tau * freq * tt) + 0.22 * np.sin(math.tau * freq * 2.0 * tt) + 0.08 * np.sin(math.tau * freq * 0.5 * tt)
            attack_env = np.minimum(1.0, tt / max(attack, 0.001))
            release_env = np.minimum(1.0, (length - tt) / max(release, 0.001))
            env = np.maximum(0.0, attack_env * release_env)
        return (base * env * amplitude).astype(np.float32)

    bpm = 106.0
    beat = 60.0 / bpm
    bar = beat * 4.0
    progression = [
        (48, (60, 64, 67)),  # C
        (43, (59, 62, 67)),  # G
        (45, (57, 60, 64)),  # Am
        (41, (57, 60, 65)),  # F
    ]

    # Warm chord bed and bass.
    bar_index = 0
    start = 0.0
    while start < duration:
        root, chord = progression[bar_index % len(progression)]
        intensity = 0.52 if start < 5.5 else 1.0
        for note_index, note in enumerate(chord):
            add_signal(start, tone(midi(note), bar * 1.05, 0.055 * intensity, "soft", 0.24, 0.55), pan=(-0.42 + note_index * 0.42))
        add_signal(start, tone(midi(root), beat * 1.65, 0.105 * intensity, "bass"), pan=0.0)
        add_signal(start + beat * 2, tone(midi(root + 7), beat * 1.45, 0.073 * intensity, "bass"), pan=0.03)
        start += bar
        bar_index += 1

    # Arpeggiated learning motif.
    arp_pattern = [0, 1, 2, 1, 0, 2, 1, 2]
    step = beat / 2.0
    index = 0
    t = 2.0
    while t < duration - 1.3:
        current_bar = int(t / bar)
        _, chord = progression[current_bar % len(progression)]
        note = chord[arp_pattern[index % len(arp_pattern)]] + 12
        amp = 0.052 if t < 10 else 0.066
        pan = -0.30 if index % 2 == 0 else 0.30
        add_signal(t, tone(midi(note), step * 1.5, amp, "pluck"), pan=pan)
        index += 1
        t += step

    # Soft electronic drums—kept restrained so on-screen text remains the focus.
    beat_index = 0
    t = 5.5
    while t < duration - 1.2:
        # Kick.
        length = 0.24
        count = int(length * sample_rate)
        tt = np.arange(count, dtype=np.float32) / sample_rate
        phase = math.tau * (62.0 * tt + 48.0 * (1.0 - np.exp(-tt * 18.0)) / 18.0)
        kick = np.sin(phase) * np.exp(-tt * 15.0) * 0.23
        add_signal(t, kick.astype(np.float32), pan=0.0)

        # Snare on beats two and four.
        if beat_index % 4 in (1, 3):
            length_s = 0.18
            count_s = int(length_s * sample_rate)
            ts = np.arange(count_s, dtype=np.float32) / sample_rate
            noise = rng.normal(0.0, 1.0, count_s).astype(np.float32)
            snare = noise * np.exp(-ts * 24.0) * 0.055
            snare += np.sin(math.tau * 185 * ts) * np.exp(-ts * 28.0) * 0.035
            add_signal(t, snare.astype(np.float32), pan=0.06)

        # Gentle closed hat on the offbeat.
        hat_start = t + beat / 2.0
        count_h = int(0.055 * sample_rate)
        th = np.arange(count_h, dtype=np.float32) / sample_rate
        hat = rng.normal(0.0, 1.0, count_h).astype(np.float32) * np.exp(-th * 62.0) * 0.020
        add_signal(hat_start, hat, pan=0.34 if beat_index % 2 else -0.34)

        beat_index += 1
        t += beat

    # A simple pentatonic melody enters during the feature demonstrations.
    melody = [72, 74, 76, 79, 76, 74, 69, 72, 74, 76, 79, 81, 79, 76, 74, 72]
    melody_t = 10.2
    note_index = 0
    while melody_t < 39.2:
        note = melody[note_index % len(melody)]
        if note_index % 4 != 3:
            add_signal(melody_t, tone(midi(note), beat * 0.92, 0.043, "pluck"), pan=0.12)
        melody_t += beat
        note_index += 1

    # Tiny stereo delay for space.
    delay = int(0.19 * sample_rate)
    left[delay:] += right[:-delay] * 0.085
    right[delay:] += left[:-delay].copy() * 0.065

    # Master fade, soft saturation, and normalization.
    fade_in = int(1.0 * sample_rate)
    fade_out = int(1.8 * sample_rate)
    left[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    right[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    left[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    right[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    stereo = np.column_stack((np.tanh(left * 1.35), np.tanh(right * 1.35)))
    peak = float(np.max(np.abs(stereo)))
    if peak > 0:
        stereo *= 0.86 / peak
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767.0).astype("<i2")

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


# -----------------------------------------------------------------------------
# Asset and video output
# -----------------------------------------------------------------------------

def save_preview_assets() -> None:
    poster = frame_at(17.0).convert("RGB").resize((OUTPUT_W, OUTPUT_H), Image.Resampling.LANCZOS)
    poster.save(BASE_DIR / "poster.png", quality=95)

    timestamps = [2.6, 7.5, 17.0, 29.2, 37.0, 42.5]
    labels = ["Pembuka", "Nilai Produk", "Fitur Scan", "Fitur Belajar", "Dampak", "Penutup"]
    board = Image.new("RGB", (1320, 620), (244, 244, 245))
    draw = ImageDraw.Draw(board)
    text(draw, (38, 28), "STORYBOARD — SINAU BRAILLE", 26, INK, "Bold")
    text(draw, (1282, 37), "Durasi 00:45  •  16:9", 13, MUTED, "SemiBold", "ra")
    thumb_w, thumb_h = 400, 225
    for index, (timestamp, label) in enumerate(zip(timestamps, labels)):
        col, row = index % 3, index // 3
        x = 38 + col * 427
        y = 81 + row * 263
        frame = frame_at(timestamp).convert("RGB").resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        board.paste(frame, (x, y))
        draw.rounded_rectangle((x, y, x + thumb_w, y + thumb_h), radius=8, outline=(211, 216, 222), width=2)
        minutes = int(timestamp // 60)
        seconds = int(timestamp % 60)
        text(draw, (x + 4, y + thumb_h + 13), f"{minutes:02d}:{seconds:02d}  {label}", 13, INK, "SemiBold")
    board.save(BASE_DIR / "storyboard.png", quality=95)


def render_video(output_path: Path, audio_path: Path, fps: int = FPS) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    frame_count = int(DURATION * fps)
    log_path = BASE_DIR / "render.log"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{SOURCE_W}x{SOURCE_H}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-i",
        str(audio_path),
        "-filter_complex",
        f"[0:v]scale={OUTPUT_W}:{OUTPUT_H}:flags=lanczos,format=yuv420p[v]",
        "-map",
        "[v]",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-t",
        f"{DURATION:.3f}",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log)
        if process.stdin is None:
            raise RuntimeError("Could not open FFmpeg input pipe")
        try:
            last_percent = -1
            for frame_index in range(frame_count):
                timestamp = frame_index / fps
                frame = frame_at(timestamp).convert("RGB")
                process.stdin.write(frame.tobytes())
                percent = int((frame_index + 1) * 100 / frame_count)
                if percent // 10 != last_percent // 10:
                    print(f"Rendering: {percent}%", flush=True)
                    last_percent = percent
            process.stdin.close()
            return_code = process.wait()
        except Exception:
            process.kill()
            raise
    if return_code != 0:
        raise RuntimeError(f"FFmpeg failed with exit code {return_code}. See {log_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-only", action="store_true", help="Only generate poster and storyboard")
    parser.add_argument("--fps", type=int, default=FPS, help="Video frame rate (default: 30)")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "sinau-braille-promo.mp4")
    args = parser.parse_args()

    print("Creating preview assets...", flush=True)
    save_preview_assets()
    if args.preview_only:
        print("Preview assets are ready.")
        return

    music_path = BASE_DIR / "music-original.wav"
    print("Creating original instrumental music...", flush=True)
    create_music(music_path)
    print("Rendering final video...", flush=True)
    render_video(args.output.resolve(), music_path, args.fps)
    print(f"Done: {args.output.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        print("FFmpeg closed the render pipe unexpectedly. Check render.log.", file=sys.stderr)
        raise

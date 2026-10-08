#!/usr/bin/env python3
"""Placement-aware compositor. All brand, photo, framing, and copy come from config.

Coordinates are normalized to the destination canvas, never inherited from a
portrait screenshot triptych. The native text renderer supplies script-aware fonts.
"""
from __future__ import annotations

import math
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageOps


def rectangle(values: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y, width, height = values
    if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1 or y + height > 1:
        raise ValueError(f"Rectangle must lie inside the normalized canvas: {values}")
    return round(x * size[0]), round(y * size[1]), round(width * size[0]), round(height * size[1])


def backdrop(source: Path, size: tuple[int, int], style: dict, layout: dict) -> Image.Image:
    with Image.open(source) as image:
        canvas = ImageOps.fit(ImageOps.exif_transpose(image).convert("RGB"), size,
                              Image.Resampling.LANCZOS, centering=tuple(layout.get("photoCenter", [0.5, 0.5]))).convert("RGBA")
    if layout.get('preserveArtwork'):
        return canvas
    if layout.get('photoBlur'):
        canvas = canvas.filter(ImageFilter.GaussianBlur(size[1] * layout['photoBlur']))
    if 'photoOpacity' in layout:
        opacity = layout['photoOpacity']
        if not 0 <= opacity <= 1:
            raise ValueError('photoOpacity must be between zero and one')
        canvas = Image.blend(Image.new('RGBA', size, style.get('background', '#091A3A')), canvas, opacity)
    navy = style.get("background", "#091A3A")
    grade = Image.new("RGBA", size, navy)
    # Render gradient as one column, then expand: much faster than per-pixel Python.
    column = Image.new("L", (1, size[1]))
    column.putdata([round(145 - 95 * y / max(1, size[1] - 1)) for y in range(size[1])])
    grade.putalpha(column.resize(size))
    canvas.alpha_composite(grade)
    if layout.get('audioBars'):
        # Brand artwork, not a claim to be a measured waveform from this take.
        bars = Image.new('RGBA', size)
        draw = ImageDraw.Draw(bars)
        for i in range(117):
            x = round((i + .5) * size[0] / 117)
            envelope = .13 + .15 * (.5 + .5 * math.sin(i * .43)) * (.3 + .7 * abs(math.sin(i * .087)))
            h = round(size[1] * envelope)
            y = round(size[1] * .51)
            r = max(3, round(size[0] / 420))
            draw.rounded_rectangle((x-r, y-h, x+r, y+h), radius=r,
                                   fill=style.get('accent', '#FFAA1C')+'55')
        canvas.alpha_composite(bars.filter(ImageFilter.GaussianBlur(size[1] * .025)))
        canvas.alpha_composite(bars)
    if style.get("echoWave", True):
        wave = Image.new("RGBA", size)
        draw = ImageDraw.Draw(wave)
        baseline = layout.get("waveY", 0.68) * size[1]
        points = [(x, round(baseline + size[1] * 0.022 * math.sin(x / size[0] * 18) +
                            size[1] * 0.006 * math.sin(x / size[0] * 51)))
                  for x in range(0, size[0] + 4, 4)]
        draw.line(points, fill=style.get("accent", "#FFAA1C"), width=max(2, round(size[1] * .003)))
        canvas.alpha_composite(wave.filter(ImageFilter.GaussianBlur(size[1] * .005)))
        canvas.alpha_composite(wave)
    return canvas


def add_recording_badge(canvas: Image.Image, source: Path, layout: dict) -> None:
    """Isolate the real capture screen's microphone control, preserving its pixels."""
    x, y, w, h = rectangle(layout['recordingRect'], canvas.size)
    with Image.open(source) as image:
        cx, cy, cw, ch = rectangle(layout['recordingCrop'], image.size)
        control = ImageOps.fit(image.convert('RGBA').crop((cx, cy, cx+cw, cy+ch)), (w, h), Image.Resampling.LANCZOS)
    mask = Image.new('L', (w, h)); ImageDraw.Draw(mask).ellipse((0, 0, w-1, h-1), fill=255)
    control.putalpha(mask)
    glow = Image.new('RGBA', canvas.size)
    ImageDraw.Draw(glow).ellipse((x-w*.15, y-h*.15, x+w*1.15, y+h*1.15), fill='#F5A62366')
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(w*.22)))
    canvas.alpha_composite(control, (x, y))


def add_ui(canvas: Image.Image, source: Path, layout: dict) -> None:
    x, y, width, height = rectangle(layout["uiRect"], canvas.size)
    with Image.open(source) as image:
        ui = ImageOps.exif_transpose(image).convert("RGBA")
    crop = layout.get("uiCrop")
    if crop:
        cx, cy, cw, ch = rectangle(crop, ui.size)
        ui = ui.crop((cx, cy, cx + cw, cy + ch))
    # Put the native UI on a rounded, framed surface at output resolution.
    border = max(3, round(canvas.height * .004))
    ui = ImageOps.contain(ui, (width - 2 * border, height - 2 * border), Image.Resampling.LANCZOS)
    frame = Image.new("RGBA", (ui.width + 2 * border, ui.height + 2 * border))
    mask = Image.new("L", frame.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, frame.width - 1, frame.height - 1),
                                         radius=canvas.height * .028, fill=255)
    frame.paste("#080D18", (0, 0, frame.width, frame.height))
    frame.alpha_composite(ui, (border, border))
    frame.putalpha(mask)
    frame = frame.rotate(layout.get("uiAngle", 0), Image.Resampling.BICUBIC, expand=True)
    # Refitting after rotation keeps all four device edges inside the safe area.
    frame = ImageOps.contain(frame, (width, height), Image.Resampling.LANCZOS)
    position = (x + (width - frame.width) // 2, y + (height - frame.height) // 2)
    shadow = Image.new("RGBA", canvas.size)
    shape = Image.new("RGBA", frame.size, (0, 0, 0, 160))
    shape.putalpha(frame.getchannel("A").point(lambda a: round(a * .65)))
    shadow.alpha_composite(shape, (position[0] + border, position[1] + border * 3))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(canvas.height * .012)))
    canvas.alpha_composite(frame, position)


def compose(background: Path, ui: Path | None, text: list[str], size: tuple[int, int],
            style: dict, layout: dict, renderer: Path, output: Path) -> None:
    canvas = backdrop(background, size, style, layout)
    if ui:
        if 'recordingRect' in layout:
            add_recording_badge(canvas, ui, layout)
        else:
            add_ui(canvas, ui, layout)
    if layout.get('textLayers'):
        for layer in layout['textLayers']:
            x, y, width, height = rectangle(layer['rect'], size)
            if layout.get('artSafeAreaPixels'):
                left, top, right, bottom = layout['artSafeAreaPixels']
                if x < left or y < top or x + width > right or y + height > bottom:
                    raise ValueError('Essential header typography leaves the art safe area')
            with tempfile.TemporaryDirectory(prefix='creative-text-') as temp:
                overlay = Path(temp) / 'text.png'
                subprocess.run([str(renderer), '--text', '\n'.join(layer['text']), '--output', str(overlay),
                    '--width', str(width), '--height', str(height),
                    '--font-size', str(round(layer['fontScale'] * size[1])),
                    '--font', layer.get('font', 'Georgia-Bold'), '--color', layer.get('color', '#10223D'),
                    '--align', layer.get('align', 'center')], check=True)
                with Image.open(overlay) as rendered:
                    if rendered.size != (width, height):
                        raise ValueError('Unexpected creative text pixel dimensions')
                    bounds = rendered.getchannel('A').getbbox()
                    if not bounds or bounds[0] < 2 or bounds[1] < 2 or bounds[2] > width-2 or bounds[3] > height-2:
                        raise ValueError('Creative text touches or exceeds its canvas')
                    canvas.alpha_composite(rendered.convert('RGBA'), (x, y))
    elif text:
        x, y, width, height = rectangle(layout["textRect"], size)
        with tempfile.TemporaryDirectory(prefix="media-headline-") as temp:
            overlay = Path(temp) / "headline.png"
            subprocess.run([str(renderer), "--text", "\n".join(text), "--output", str(overlay),
                            "--width", str(width), "--height", str(height),
                            "--font-size", str(round(layout.get("fontScale", .1) * size[1]))], check=True)
            with Image.open(overlay) as rendered:
                if rendered.size != (width, height):
                    raise ValueError("Headline renderer returned unexpected pixel dimensions")
                canvas.alpha_composite(rendered.convert("RGBA"), (x, y))
    canvas.convert("RGB").save(output, format="PNG")

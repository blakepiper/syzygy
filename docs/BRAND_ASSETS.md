# Brand assets

Syzygy's logo and mascot ship inside the package
(`src/syzygy/resources/brand/`). The colour logo uses terminal half-block
pixels; the detailed monochrome mascot uses a 2×4-dot Braille renderer so its
wheel, face, and robe retain negative space at terminal sizes instead of
collapsing into an interpolated blob (`syzygy.tui.widgets.pixel_art`).

## Where they appear

Two assets, no more. M17 added *placements*, not artwork:

| Asset | Shown on | Notes |
|---|---|---|
| `logo.png` | the opening sequence (`tui/screens/startup.py`), the welcome screen | falls back to `brand.ASCII_WORDMARK` when the box is too small |
| `mascot.png` | the opening sequence, the welcome screen, and the home screen at `-wide`/`-tall` | rendered as monochrome Braille line art; falls back to nothing at all |

On startup and welcome, both assets belong to one centered 64-column lockup.
The logo, mascot, and welcome copy share an axis and explicit spacing; do not
position them as unrelated full-width regions.

The home companion has three states (`brand.MascotState`: waiting,
drawing, complete), and each is a CSS treatment of the same PNG rather
than a separate image — see the `Mascot.-mascot-*` rules in
`syzygy.tcss`. Adding a state costs a rule; it must not cost an asset. If
you ever do add an asset, add a row above and a regeneration recipe below,
in the same commit.

## Why PNGs and not the SVGs

A terminal cannot display SVG, and rasterizing at runtime would mean a
rendering dependency (cairosvg, or a system librsvg) for two images that
never change between releases. The SVGs at the repository root stay the
editable source; the PNGs are generated from them at author time and
committed.

`logo.svg` carries an explicit black background rect. The TUI uses
`logo-dark.svg`, which is the same artwork with no background, rasterized
with `-b none` — fully transparent pixels render as blank cells with no
background colour, so the terminal's own background shows through instead
of a near-black rectangle.

## Regenerating

Needs `rsvg-convert` (`librsvg`) and Pillow. Neither is a runtime
dependency; both are only used here.

```bash
# The wordmark: transparent background, 1200px wide (4:1).
rsvg-convert -w 1200 -b none logo-dark.svg -o src/syzygy/resources/brand/logo.png
```

The mascot starts as `mascot.png` at the repository root, which has an
opaque black background baked in. Two things are done to it: the black is
keyed out to transparency, and it is downscaled — the source is
839×1348, but `pixel_art.MAX_COLUMNS` means a terminal can never ask for
more than about 40×64 pixels of it, and the full-resolution file was
740 KB in every wheel.

```python
from PIL import Image

source = Image.open("mascot.png").convert("RGBA")
pixels = source.load()
width, height = source.size
for y in range(height):
    for x in range(width):
        red, green, blue, _ = pixels[x, y]
        if red + green + blue < 60:  # near-black: the background field
            pixels[x, y] = (0, 0, 0, 0)
source.resize((420, 675), Image.LANCZOS).save(
    "src/syzygy/resources/brand/mascot.png", optimize=True
)
```

The luminance threshold is safe because the source is monochrome pixel
art: 96% of its pixels are within a few units of pure black or pure
white.

## The theme and result-ready cue (`resources/audio/`)

Not a derived asset: the MP3 in the package *is* the master, so there is
nothing to regenerate and no source file at the repository root. It is the
project author's own work, so there is no third-party licensing to clear
for AGPL redistribution.

It is 3.5 MB, which is most of the wheel. Playback through `syzygy.audio`
ships in the main install and degrades to silence if no audio device is
available. The same directory carries `notification.wav`, a short bundled
one-shot cue played when a daily or Oracle interpretation becomes ready. It
uses its own playback stream, so it does not restart the theme; mute and
`--no-audio` silence both.

## Sizes

Keep the committed PNGs modest. `pixel_art` caps portrait rendering at
`MAX_COLUMNS` (40) and `brand.MAX_LOGO_COLUMNS` (64) for the wide wordmark.
The mascot samples two source pixels across and four down per terminal cell;
the logo and card illustrations retain the half-cell colour path.

# Brand assets

Syzygy's logo and mascot ship inside the package
(`src/syzygy/resources/brand/`) and are rendered into terminal half-block
pixels by `syzygy.tui.widgets.brand`, the same way card art is
(`syzygy.tui.widgets.pixel_art`).

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

## The theme (`resources/audio/theme.mp3`)

Not a derived asset: the MP3 in the package *is* the master, so there is
nothing to regenerate and no source file at the repository root. It is the
project author's own work, so there is no third-party licensing to clear
for AGPL redistribution.

It is 3.5 MB, which is most of the wheel. Playback through `syzygy.audio`
ships in the main install and degrades to silence if no audio device is
available.

## Sizes

Keep the committed PNGs modest. `pixel_art` caps rendering at
`MAX_COLUMNS` (40) for portrait images and `brand.MAX_LOGO_COLUMNS` (64)
for the wide wordmark, so resolution beyond a few hundred pixels is
weight in the wheel that nothing can display.

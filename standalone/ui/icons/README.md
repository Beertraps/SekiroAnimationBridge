# Animation Bridge icons

Original vector artwork for this project, under the repository's GPL-3.0-or-later license.
The bridge arc connects two endpoints, with an animation keyframe at its crown.
Cream, apricot and sage on forest green match the workspace's warm neutral palette.

- `bridge.svg`: master artwork, also used in the app's navigation rail.
- `favicon.svg`: simplified artwork for small browser and Windows icons.
- `bridge.ico`: transparent Windows icon with 16, 20, 24, 32, 40, 48, 64, 128 and 256 px frames.
- `bridge-192.png`, `bridge-512.png`: transparent raster exports for launchers and other uses.
- `apple-touch-icon.png`: 180 px touch icon.
- `favicon-32.png`: 32 px raster export of the small artwork.

The interface symbols live in `../index.html`: 24 px grids, rounded strokes and corners,
with color inherited from the UI for both themes. Animation uses a keyframe diamond;
the donor action uses a transfer symbol. Keep labels and accessible names on controls.

To regenerate the raster files and ICO, run from the repository root in PowerShell:

```powershell
npm install --prefix work/icon-tools --no-audit --no-fund @resvg/resvg-js@2.6.2
$env:NODE_PATH = "$PWD/work/icon-tools/node_modules"
node tools/build_icons.js
```

These are optional design tools; running the app does not require Node or extra packages.
`Create Desktop Shortcut.cmd` installs or refreshes the desktop shortcut for this checkout.
After moving the extracted app folder, run it again so the launcher and icon paths follow it.

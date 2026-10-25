/* Optional maintainer tool; the app uses the checked-in assets without Node.
 * npm install --prefix work/icon-tools --no-audit --no-fund @resvg/resvg-js@2.6.2
 * PowerShell: $env:NODE_PATH="$PWD/work/icon-tools/node_modules"; node tools/build_icons.js
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { Resvg } = require('@resvg/resvg-js');
const directory = path.join(__dirname, '../standalone/ui/icons');
const full = fs.readFileSync(path.join(directory, 'bridge.svg'), 'utf8');
const small = fs.readFileSync(path.join(directory, 'favicon.svg'), 'utf8');
const render = (svg, size) => new Resvg(svg, { fitTo: { mode: 'width', value: size } }).render().asPng();
for (const size of [192, 512]) fs.writeFileSync(path.join(directory, `bridge-${size}.png`), render(full, size));
fs.writeFileSync(path.join(directory, 'apple-touch-icon.png'), render(full, 180));
fs.writeFileSync(path.join(directory, 'favicon-32.png'), render(small, 32));

// Windows Vista and later support PNG frames in ICO files, including alpha.
const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
const frames = sizes.map(size => render(size <= 32 ? small : full, size));
const header = Buffer.alloc(6 + sizes.length * 16);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(sizes.length, 4);
let offset = header.length;
sizes.forEach((size, index) => {
  const entry = 6 + index * 16;
  header[entry] = header[entry + 1] = size === 256 ? 0 : size;
  header.writeUInt16LE(1, entry + 4);
  header.writeUInt16LE(32, entry + 6);
  header.writeUInt32LE(frames[index].length, entry + 8);
  header.writeUInt32LE(offset, entry + 12);
  offset += frames[index].length;
});
fs.writeFileSync(path.join(directory, 'bridge.ico'), Buffer.concat([header, ...frames]));
console.log('Built four PNGs and a nine-size Windows icon from the two SVG masters.');

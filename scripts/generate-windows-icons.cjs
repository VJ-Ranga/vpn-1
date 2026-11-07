const fs = require("node:fs");
const path = require("node:path");
const { Resvg } = require("@resvg/resvg-js");

const assets = path.join(__dirname, "..", "assets");
const svg = fs.readFileSync(path.join(assets, "northstar-vpn.svg"));
const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
const images = sizes.map((size) => new Resvg(svg, { fitTo: { mode: "width", value: size } }).render().asPng());
fs.writeFileSync(path.join(assets, "northstar-vpn.png"), images[images.length - 1]);

// Vista+ ICO supports PNG-compressed images. Include small sizes for Explorer,
// shortcuts and title bars, as well as 256px for high-DPI displays.
const header = Buffer.alloc(6 + sizes.length * 16);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(sizes.length, 4);
let offset = header.length;
images.forEach((image, index) => {
  const entry = 6 + index * 16;
  header[entry] = sizes[index] === 256 ? 0 : sizes[index];
  header[entry + 1] = header[entry];
  header.writeUInt16LE(1, entry + 4);
  header.writeUInt16LE(32, entry + 6);
  header.writeUInt32LE(image.length, entry + 8);
  header.writeUInt32LE(offset, entry + 12);
  offset += image.length;
});
fs.writeFileSync(path.join(assets, "northstar-vpn.ico"), Buffer.concat([header, ...images]));
console.log("Generated Northstar PNG and multi-size Windows ICO from the SVG logo.");

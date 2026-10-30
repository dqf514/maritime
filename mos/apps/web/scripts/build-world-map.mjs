/**
 * 生成世界地图底图数据 —— apps/web/lib/world-map.ts
 *
 * 航次「航线图」此前只有一张空白网格，看不出航点在地球上的位置。
 * 这里从 Natural Earth 110m 国界（world-atlas，TopoJSON）生成一份**预投影**的
 * SVG path 常量：坐标系与 workspace 页的 proj() 完全一致（等距圆柱投影），
 * 因此前端只需把 path 画出来，不必再引入 d3-geo 之类的依赖，也不必在运行时
 * 请求外部地图服务。
 *
 * 用法：
 *   node scripts/build-world-map.mjs            # 下载并生成
 *   node scripts/build-world-map.mjs --local <topojson>   # 用本地文件（离线）
 *
 * 数据源：https://unpkg.com/world-atlas@2/countries-110m.json (Natural Earth, public domain)
 */

import { writeFileSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../lib/world-map.ts");

const SRC_URL = "https://unpkg.com/world-atlas@2.0.2/countries-110m.json";

// —— 与 workspace/page.tsx 的 proj() 保持一致 ——
const MAP_W = 960;
const MAP_H = 420;
const proj = (lon, lat) => [((lon + 180) / 360) * MAP_W, ((90 - lat) / 180) * MAP_H];

// —— TopoJSON 解码 ——
function decodeArcs(topology) {
  const { scale, translate } = topology.transform ?? { scale: [1, 1], translate: [0, 0] };
  return topology.arcs.map((arc) => {
    let x = 0;
    let y = 0;
    return arc.map(([dx, dy]) => {
      x += dx;
      y += dy;
      return [x * scale[0] + translate[0], y * scale[1] + translate[1]];
    });
  });
}

function arcPoints(index, arcs) {
  if (index < 0) {
    const idx = ~index;
    const arc = arcs[idx];
    return arc.slice().reverse();
  }
  return arcs[index];
}

function ringCoords(arcIndexes, arcs) {
  const pts = [];
  for (const idx of arcIndexes) {
    const seg = arcPoints(idx, arcs);
    for (let i = pts.length ? 1 : 0; i < seg.length; i++) pts.push(seg[i]);
  }
  return pts;
}

function geometryPolygons(geom, arcs) {
  const out = [];
  if (geom.type === "Polygon") {
    out.push(geom.arcs.map((r) => ringCoords(r, arcs)));
  } else if (geom.type === "MultiPolygon") {
    for (const poly of geom.arcs) out.push(poly.map((r) => ringCoords(r, arcs)));
  }
  return out;
}

// —— Douglas–Peucker 简化（在像素空间做，直接决定文件大小）——
function simplify(points, epsilon) {
  if (points.length < 3) return points;
  const keep = new Uint8Array(points.length);
  keep[0] = 1;
  keep[points.length - 1] = 1;
  const stack = [[0, points.length - 1]];
  while (stack.length) {
    const [s, e] = stack.pop();
    let maxDist = 0;
    let index = -1;
    const [ax, ay] = points[s];
    const [bx, by] = points[e];
    const dx = bx - ax;
    const dy = by - ay;
    const denom = dx * dx + dy * dy;
    for (let i = s + 1; i < e; i++) {
      const [px, py] = points[i];
      let d;
      if (denom === 0) {
        d = Math.hypot(px - ax, py - ay);
      } else {
        let t = ((px - ax) * dx + (py - ay) * dy) / denom;
        t = Math.max(0, Math.min(1, t));
        d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
      }
      if (d > maxDist) {
        maxDist = d;
        index = i;
      }
    }
    if (maxDist > epsilon && index > 0) {
      keep[index] = 1;
      stack.push([s, index], [index, e]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

function ringToPath(ring) {
  if (ring.length < 3) return "";
  const pts = simplify(ring, 0.7).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`);
  if (pts.length < 3) return "";
  return `M${pts[0]}L${pts.slice(1).join("L")}Z`;
}

/**
 * 跨 ±180° 的环（俄罗斯楚科奇、斐济等）在 TopoJSON 里经度被量化到
 * [-180,180]，直接投影会在图上拉出一条横贯全图的斜线。这里把环的经度
 * **解卷绕**（相邻点保持连续），投影后若超出画布右边界，再补一份平移
 * -360° 的副本贴到左边缘 —— 这就是世界地图上跨日界陆地的常规画法。
 */
function unwrapRing(ring) {
  const out = [ring[0]];
  for (let i = 1; i < ring.length; i++) {
    const prev = out[i - 1][0];
    let lon = ring[i][0];
    while (lon - prev > 180) lon -= 360;
    while (prev - lon > 180) lon += 360;
    out.push([lon, ring[i][1]]);
  }
  return out;
}

// —— 主流程 ——
const localArg = process.argv.indexOf("--local");
let topology;
if (localArg > -1) {
  const file = process.argv[localArg + 1];
  topology = JSON.parse(readFileSync(file, "utf8"));
  console.log(`读取本地 TopoJSON：${file}`);
} else {
  const res = await fetch(SRC_URL);
  if (!res.ok) throw new Error(`下载失败：${res.status}`);
  topology = await res.json();
  console.log(`已下载 ${SRC_URL}`);
}

const arcs = decodeArcs(topology);
const countries = topology.objects?.countries?.geometries ?? [];

const paths = [];
for (const geom of countries) {
  for (const poly of geometryPolygons(geom, arcs)) {
    for (const ring of poly) {
      const projected = unwrapRing(ring).map(([lon, lat]) => proj(lon, lat));
      const xs = projected.map((p) => p[0]);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const d = ringToPath(projected);
      if (!d) continue;
      paths.push(d);
      // 越过画布右边界的部分再画一份到左边（跨日界的陆地两侧都能看到）
      if (maxX > MAP_W) paths.push(ringToPath(projected.map(([x, y]) => [x - MAP_W, y])));
      if (minX < 0) paths.push(ringToPath(projected.map(([x, y]) => [x + MAP_W, y])));
    }
  }
}

const body = paths.join("");
const header = `// 自动生成 —— 请勿手工编辑。
// 运行 \`node scripts/build-world-map.mjs\` 重新生成。
// 数据源：Natural Earth 110m 国界（world-atlas，public domain）。
// 坐标系：等距圆柱投影，与 workspace 页 proj() 一致（960×420）。

/** 世界陆地轮廓（预投影 SVG path，逐环一条；外环与内环同列，用 evenodd 挖湖）。 */
export const WORLD_LAND_PATHS: string[] = [
${paths.map((p) => `  "${p}",`).join("\n")}
];

/** 地图画布尺寸（viewBox），与投影常量一致。 */
export const WORLD_MAP_W = ${MAP_W};
export const WORLD_MAP_H = ${MAP_H};
`;
console.log(`路径数据 ${(body.length / 1024).toFixed(1)} KB`);

writeFileSync(OUT, header, "utf8");
console.log(`已写出 ${OUT}：${paths.length} 个环，${(body.length / 1024).toFixed(1)} KB`);

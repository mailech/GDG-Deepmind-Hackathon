import type { El, Rect, Step, TreeNode } from './types';

/**
 * Board layout. Pure geometry, so the renderer, Nova's highlights and the
 * student's hit-testing all agree on where everything is.
 *
 * Steps flow into columns like a real whiteboard: each new step goes into the
 * shortest column. Text widths are estimated from character counts — exact
 * measurement would need a render pass per element, and a few pixels of slack
 * is invisible on a hand-drawn board.
 */

// Plain family names only: SVG presentation attributes cannot read CSS
// variables. The live board gets the real next/font faces from the
// `.nova-board` rules in globals.css; these attributes are what survives into
// the JPEG snapshot sent to Nova, where page CSS does not apply.
export const HAND = '"Kalam", "Comic Sans MS", cursive';
export const MONO = 'Consolas, ui-monospace, monospace';

const HAND_W = 0.5; // average glyph width / font size, handwriting face
const MONO_W = 0.6;

export const TITLE_FS = 27;
const TITLE_H = 50;
const EL_GAP = 20;
const STEP_PAD_BOTTOM = 34;
const LABEL_H = 26;

export type TextGeom = { lines: string[]; fs: number; lh: number };
export type CodeGeom = { fs: number; lh: number; pad: number; labelH: number };
export type CellGeom = { cellW: number; cellH: number; labelH: number; top: number };
export type ChainGeom = {
  boxes: Rect[];
  vertical: boolean;
  arrows: boolean;
  labelH: number;
  fs: number;
};
export type TreeGeom = {
  nodes: { node: TreeNode; x: number; y: number; w: number; h: number }[];
  edges: { from: string; to: string }[];
  labelH: number;
  fs: number;
};
export type TableGeom = {
  colW: number[];
  rowH: number;
  labelH: number;
  fs: number;
  headers: boolean;
};

export type PlacedEl = {
  el: El;
  step: number; // 1-based step index, 0 for loose improvisation
  order: number; // position within its step, for the write-in stagger
  x: number;
  y: number;
  w: number;
  h: number;
  /** Sub-target rects keyed by the part after '#', in board coordinates. */
  parts: Record<string, Rect>;
  geom:
    | TextGeom
    | CodeGeom
    | CellGeom
    | ChainGeom
    | TreeGeom
    | TableGeom
    | ListGeom
    | MediaGeom
    | DiagramGeom;
};

export type PlacedStep = {
  index: number;
  step: Step;
  x: number;
  y: number;
  w: number;
  h: number;
};

export type BoardLayout = {
  width: number;
  height: number;
  colW: number;
  steps: PlacedStep[];
  els: PlacedEl[];
};

// ---------------------------------------------------------------------------

function wrap(text: string, maxChars: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = '';
  for (const w of words) {
    if (!cur) cur = w;
    else if ((cur + ' ' + w).length <= maxChars) cur += ' ' + w;
    else {
      lines.push(cur);
      cur = w;
    }
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [''];
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const longest = (xs: string[]) => xs.reduce((m, s) => Math.max(m, s.length), 0);

type Sized = { w: number; h: number; parts: Record<string, Rect>; geom: PlacedEl['geom'] };

function sizeText(text: string, colW: number, fs: number): Sized {
  const lh = Math.round(fs * 1.4);
  const maxChars = Math.max(8, Math.floor(colW / (fs * HAND_W)));
  const lines = wrap(text, maxChars);
  const w = Math.min(colW, longest(lines) * fs * HAND_W + 8);
  return { w, h: lines.length * lh, parts: {}, geom: { lines, fs, lh } };
}

function sizeCode(lines: string[], label: string | undefined, colW: number): Sized {
  const pad = 14;
  let fs = 15;
  const need = longest(lines) * fs * MONO_W + pad * 2;
  if (need > colW) fs = clamp((colW - pad * 2) / Math.max(1, longest(lines)) / MONO_W, 10, 15);
  const lh = Math.round(fs * 1.6);
  const labelH = label ? LABEL_H : 0;
  const w = Math.min(colW, Math.max(180, longest(lines) * fs * MONO_W + pad * 2));
  const parts: Record<string, Rect> = {};
  lines.forEach((_, i) => {
    parts[String(i)] = { x: 6, y: labelH + pad + i * lh - 2, w: w - 12, h: lh };
  });
  return { w, h: labelH + pad * 2 + lines.length * lh, parts, geom: { fs, lh, pad, labelH } };
}

function sizeArray(
  values: string[],
  hasPointers: boolean,
  label: string | undefined,
  colW: number
): Sized {
  const labelH = label ? LABEL_H : 0;
  let cellW = clamp(longest(values) * 13 + 24, 48, 96);
  if (values.length * cellW > colW) cellW = colW / Math.max(1, values.length);
  const cellH = 50;
  const parts: Record<string, Rect> = {};
  values.forEach((_, i) => {
    parts[String(i)] = { x: i * cellW, y: labelH, w: cellW, h: cellH };
  });
  const h = labelH + cellH + 20 + (hasPointers ? 40 : 0);
  return { w: values.length * cellW, h, parts, geom: { cellW, cellH, labelH, top: labelH } };
}

function sizeChain(
  values: string[],
  vertical: boolean,
  arrows: boolean,
  label: string | undefined,
  colW: number
): Sized {
  const labelH = label ? LABEL_H : 0;
  const fs = 19;
  const boxes: Rect[] = [];
  if (vertical) {
    const w = clamp(longest(values) * fs * HAND_W + 36, 96, colW);
    const bh = 44;
    const gap = arrows ? 22 : 6;
    values.forEach((_, i) => boxes.push({ x: 0, y: labelH + i * (bh + gap), w, h: bh }));
  } else {
    const widths = values.map((v) => clamp(v.length * fs * HAND_W + 30, 58, 150));
    const gap = arrows ? 38 : 10;
    const total = widths.reduce((a, b) => a + b, 0) + gap * Math.max(0, values.length - 1);
    const k = total > colW ? colW / total : 1;
    let x = 0;
    widths.forEach((bw) => {
      boxes.push({ x, y: labelH, w: bw * k, h: 46 });
      x += (bw + gap) * k;
    });
  }
  const parts: Record<string, Rect> = {};
  boxes.forEach((b, i) => (parts[String(i)] = b));
  const w = boxes.reduce((m, b) => Math.max(m, b.x + b.w), 0);
  const h = boxes.reduce((m, b) => Math.max(m, b.y + b.h), labelH) + 4;
  return { w, h, parts, geom: { boxes, vertical, arrows, labelH, fs } };
}

function sizeTree(nodes: TreeNode[], label: string | undefined, colW: number): Sized {
  const labelH = label ? LABEL_H : 0;
  const fs = 17;
  const ids = new Set(nodes.map((n) => n.id));
  const kids = new Map<string, string[]>();
  const roots: string[] = [];
  for (const n of nodes) {
    if (n.parent && ids.has(n.parent) && n.parent !== n.id) {
      kids.set(n.parent, [...(kids.get(n.parent) ?? []), n.id]);
    } else roots.push(n.id);
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const nodeW = (n: TreeNode) => clamp(n.label.length * fs * 0.55 + 26, 44, 150);
  const slot = Math.max(...nodes.map(nodeW)) + 14;

  // Leaves take successive slots; a parent sits over the middle of its children.
  const pos = new Map<string, { col: number; depth: number }>();
  let leaf = 0;
  let maxDepth = 0;
  const seen = new Set<string>();
  const place = (id: string, depth: number): number => {
    if (seen.has(id)) return pos.get(id)?.col ?? 0; // guard against cycles
    seen.add(id);
    maxDepth = Math.max(maxDepth, depth);
    const ch = kids.get(id) ?? [];
    let col: number;
    if (!ch.length) col = leaf++;
    else {
      const cols = ch.map((c) => place(c, depth + 1));
      col = (Math.min(...cols) + Math.max(...cols)) / 2;
    }
    pos.set(id, { col, depth });
    return col;
  };
  roots.forEach((r) => place(r, 0));

  const naturalW = Math.max(1, leaf) * slot;
  const k = naturalW > colW ? colW / naturalW : 1;
  const levelH = 70;
  const nh = 36;
  const placed = nodes
    .filter((n) => pos.has(n.id))
    .map((n) => {
      const p = pos.get(n.id)!;
      const w = nodeW(n) * Math.min(1, k * 1.1);
      const cx = (p.col + 0.5) * slot * k;
      return { node: n, x: cx - w / 2, y: labelH + p.depth * levelH, w, h: nh };
    });
  const edges = nodes
    .filter((n) => n.parent && byId.has(n.parent) && pos.has(n.id))
    .map((n) => ({ from: n.parent!, to: n.id }));
  const parts: Record<string, Rect> = {};
  placed.forEach((p) => (parts[p.node.id] = { x: p.x, y: p.y, w: p.w, h: p.h }));
  return {
    w: naturalW * k,
    h: labelH + maxDepth * levelH + nh + 6,
    parts,
    geom: { nodes: placed, edges, labelH, fs },
  };
}

function sizeTable(
  headers: string[] | undefined,
  rows: string[][],
  label: string | undefined,
  colW: number
): Sized {
  const labelH = label ? LABEL_H : 0;
  let fs = 16;
  const ncol = Math.max(headers?.length ?? 0, ...rows.map((r) => r.length));
  const widths = Array.from({ length: ncol }, (_, c) =>
    clamp(
      Math.max((headers?.[c] ?? '').length, ...rows.map((r) => (r[c] ?? '').length)) * fs * 0.52 +
        24,
      44,
      260
    )
  );
  const total = widths.reduce((a, b) => a + b, 0);
  const k = total > colW ? colW / total : 1;
  if (k < 1) fs = Math.max(12, fs * k);
  const colWs = widths.map((w) => w * k);
  const rowH = 36;
  const hasHead = !!headers?.length;
  const parts: Record<string, Rect> = {};
  rows.forEach((r, ri) => {
    let x = 0;
    colWs.forEach((cw, ci) => {
      parts[`${ri}.${ci}`] = { x, y: labelH + (hasHead ? rowH : 0) + ri * rowH, w: cw, h: rowH };
      x += cw;
    });
  });
  return {
    w: total * k,
    h: labelH + (rows.length + (hasHead ? 1 : 0)) * rowH + 4,
    parts,
    geom: { colW: colWs, rowH, labelH, fs, headers: hasHead },
  };
}

function sizeEl(el: El, colW: number): Sized {
  switch (el.kind) {
    case 'text':
      return sizeText(el.text, colW, 23);
    case 'note': {
      const s = sizeText(el.text, colW - 30, 21);
      return { ...s, w: s.w + 30 };
    }
    case 'code':
      return sizeCode(el.lines, el.label, colW);
    case 'array':
      return sizeArray(el.values, !!el.pointers?.length, el.label, colW);
    case 'chain':
      return sizeChain(el.values, !!el.vertical, el.arrows !== false, el.label, colW);
    case 'tree':
      return sizeTree(el.nodes, el.label, colW);
    case 'table':
      return sizeTable(el.headers, el.rows, el.label, colW);
    case 'diagram':
      return sizeDiagram(el, colW);
    case 'list':
      return sizeList(el.items, el.label, colW);
    case 'media': {
      const labelH = el.caption ? LABEL_H + 4 : 0;
      // Images are generated 16:9 like clips, so both fill the column exactly.
      const w = colW;
      const h = (w * 9) / 16;
      return { w, h: h + labelH, parts: {}, geom: { labelH, mediaW: w, mediaH: h } };
    }
  }
}

export type ListGeom = {
  labelH: number;
  fs: number;
  lh: number;
  items: { lines: string[]; y: number }[];
};
export type MediaGeom = { labelH: number; mediaW: number; mediaH: number };

function sizeList(items: string[], label: string | undefined, colW: number): Sized {
  const labelH = label ? LABEL_H : 0;
  const fs = 21;
  const lh = Math.round(fs * 1.35);
  const maxChars = Math.max(10, Math.floor((colW - 28) / (fs * HAND_W)));
  let y = labelH;
  const parts: Record<string, Rect> = {};
  const laid = items.map((it, i) => {
    const lines = wrap(it, maxChars);
    const row = { lines, y };
    parts[String(i)] = { x: 0, y, w: colW, h: lines.length * lh };
    y += lines.length * lh + 8;
    return row;
  });
  return { w: colW, h: y, parts, geom: { labelH, fs, lh, items: laid } };
}

export type DiagramGeom = {
  labelH: number;
  fs: number;
  layout: 'flow' | 'cycle' | 'hub' | 'timeline' | 'layers' | 'compare';
  boxes: Record<string, Rect>;
  center?: { x: number; y: number };
  axisY?: number;
  headers?: { text: string; x: number; y: number; w: number }[];
};

type DNode = Extract<El, { kind: 'diagram' }>['nodes'][number];

function nodeSize(n: DNode, fs: number) {
  const text = n.label.length + (n.icon ? 3 : 0);
  const noteLen = (n.note ?? '').length * 0.72;
  const w = clamp(Math.max(text, noteLen) * fs * 0.52 + 34, 96, 230);
  return { w, h: n.note ? 60 : 46 };
}

function sizeDiagram(el: Extract<El, { kind: 'diagram' }>, colW: number): Sized {
  const labelH = el.label ? LABEL_H + 6 : 0;
  const fs = 17;
  const boxes: Record<string, Rect> = {};
  const nodes = el.nodes;
  const layout = el.layout ?? 'flow';
  const done = (h: number, extra: Partial<DiagramGeom> = {}): Sized => ({
    w: colW,
    h,
    parts: boxes,
    geom: { labelH, fs, layout, boxes, ...extra },
  });

  if (layout === 'layers') {
    // Stacked bands, full width — the OSI model, the atmosphere, a software stack.
    let y = labelH;
    nodes.forEach((n) => {
      const h = n.note ? 54 : 46;
      boxes[n.id] = { x: 0, y, w: colW, h };
      y += h + 8;
    });
    return done(y);
  }

  if (layout === 'compare') {
    const groups = Array.from(new Set(nodes.map((n) => n.group || 'A'))).slice(0, 2);
    const half = (colW - 56) / 2;
    const headers = groups.map((g, i) => ({ text: g, x: i * (half + 56), y: labelH, w: half }));
    const ys = [labelH + 44, labelH + 44];
    nodes.forEach((n) => {
      const gi = Math.max(0, groups.indexOf(n.group || 'A'));
      const col = gi > 1 ? 1 : gi;
      const h = n.note ? 58 : 44;
      boxes[n.id] = { x: col * (half + 56), y: ys[col], w: half, h };
      ys[col] += h + 10;
    });
    return done(Math.max(...ys), { headers, center: { x: colW / 2, y: labelH + 18 } });
  }

  if (layout === 'timeline') {
    const axisY = labelH + 26;
    const step = colW / Math.max(1, nodes.length);
    let bottom = axisY;
    nodes.forEach((n, i) => {
      const sz = nodeSize(n, fs);
      const w = Math.min(sz.w, step * 1.85);
      const cx = step * (i + 0.5);
      const y = axisY + 22 + (i % 2) * (sz.h + 14); // alternate rows so neighbours never collide
      boxes[n.id] = { x: clamp(cx - w / 2, 0, colW - w), y, w, h: sz.h };
      bottom = Math.max(bottom, y + sz.h);
    });
    return done(bottom + 6, { axisY });
  }

  if (layout === 'hub' && nodes.length > 2) {
    // Centre in the middle, spokes out to a row above and a row below. A ring
    // was tried first: side nodes collided with a wide centre box.
    const ring = nodes.slice(1);
    const topRow = ring.slice(0, Math.ceil(ring.length / 2));
    const botRow = ring.slice(topRow.length);
    const placeRow = (row: DNode[], y: number) => {
      const sizes = row.map((n) => nodeSize(n, fs));
      const gap = 22;
      const total = sizes.reduce((a, s) => a + s.w, 0) + gap * (row.length - 1);
      const k = total > colW ? colW / total : 1;
      let x = (colW - total * k) / 2;
      row.forEach((n, i) => {
        boxes[n.id] = { x, y, w: sizes[i].w * k, h: sizes[i].h };
        x += (sizes[i].w + gap) * k;
      });
      return Math.max(...sizes.map((s) => s.h));
    };
    const topH = placeRow(topRow, labelH);
    const c = nodeSize(nodes[0], fs + 2);
    const cy = labelH + topH + 62;
    boxes[nodes[0].id] = { x: colW / 2 - c.w / 2 - 8, y: cy, w: c.w + 16, h: c.h + 8 };
    const botY = cy + c.h + 8 + 62;
    const botH = botRow.length ? placeRow(botRow, botY) : 0;
    return done(botRow.length ? botY + botH + 6 : cy + c.h + 14, {
      center: { x: colW / 2, y: cy + c.h / 2 },
    });
  }

  if (layout === 'cycle' && nodes.length > 2) {
    const ring = nodes;
    const sizes = ring.map((n) => nodeSize(n, fs));
    const maxW = Math.max(...sizes.map((s) => s.w));
    const maxH = Math.max(...sizes.map((s) => s.h));
    const rx = Math.max(90, Math.min(colW / 2 - maxW / 2 - 4, 240));
    const ry = Math.min(165, 78 + ring.length * 15);
    const cx = colW / 2;
    const cy = labelH + ry + maxH / 2 + 4;
    ring.forEach((n, i) => {
      const a = -Math.PI / 2 + (i / ring.length) * Math.PI * 2;
      const s = sizes[i];
      boxes[n.id] = {
        x: cx + Math.cos(a) * rx - s.w / 2,
        y: cy + Math.sin(a) * ry - s.h / 2,
        w: s.w,
        h: s.h,
      };
    });
    return done(cy + ry + maxH / 2 + 8, { center: { x: cx, y: cy } });
  }

  // flow: layered top-to-bottom; a node sits one layer below the deepest node
  // pointing at it. Nodes with no edges at all get their own final row rather
  // than crowding the top.
  const linked = new Set(el.edges.flatMap((e) => [e.from, e.to]));
  const layer: Record<string, number> = {};
  nodes.forEach((n) => (layer[n.id] = 0));
  for (let pass = 0; pass < nodes.length; pass++) {
    let moved = false;
    for (const e of el.edges) {
      if (layer[e.from] === undefined || layer[e.to] === undefined) continue;
      if (layer[e.to] < layer[e.from] + 1 && layer[e.from] + 1 < nodes.length) {
        layer[e.to] = layer[e.from] + 1;
        moved = true;
      }
    }
    if (!moved) break;
  }
  const rows: DNode[][] = [];
  nodes.filter((n) => linked.has(n.id)).forEach((n) => (rows[layer[n.id]] ??= []).push(n));
  const compact = rows.filter(Boolean);
  const loose = nodes.filter((n) => !linked.has(n.id));
  if (loose.length) compact.push(loose);
  let y = labelH;
  compact.forEach((row) => {
    const sizes = row.map((n) => nodeSize(n, fs));
    const gap = 28;
    const total = sizes.reduce((a, s) => a + s.w, 0) + gap * (row.length - 1);
    const k = total > colW ? colW / total : 1;
    let x = (colW - total * k) / 2;
    const rh = Math.max(...sizes.map((s) => s.h));
    row.forEach((n, i) => {
      boxes[n.id] = { x, y, w: sizes[i].w * k, h: sizes[i].h };
      x += (sizes[i].w + gap) * k;
    });
    y += rh + 58; // room between rows for arrow labels
  });
  return done(y - 52);
}

// ---------------------------------------------------------------------------

export function layoutBoard(steps: Step[], revealed: number, columns: number): BoardLayout {
  const margin = 36;
  const gutter = 56;
  const width = columns === 1 ? 1000 : 1240;
  const colW = (width - margin * 2 - gutter * (columns - 1)) / columns;
  const colH = Array.from({ length: columns }, () => margin);
  const placedSteps: PlacedStep[] = [];
  const els: PlacedEl[] = [];

  steps.slice(0, revealed).forEach((step, si) => {
    const col = colH.indexOf(Math.min(...colH));
    const x = margin + col * (colW + gutter);
    const y0 = colH[col];
    let y = y0 + TITLE_H;
    step.elements.forEach((el, order) => {
      const s = sizeEl(el, colW);
      const indent = el.kind === 'note' ? 0 : 0;
      els.push({
        el,
        step: si + 1,
        order,
        x: x + indent,
        y,
        w: s.w,
        h: s.h,
        parts: s.parts,
        geom: s.geom,
      });
      y += s.h + EL_GAP;
    });
    const h = y - y0 + STEP_PAD_BOTTOM - EL_GAP;
    placedSteps.push({ index: si + 1, step, x, y: y0, w: colW, h });
    colH[col] = y0 + h + 24;
  });

  return {
    width,
    height: Math.max(...colH) + margin,
    colW,
    steps: placedSteps,
    els,
  };
}

/** Board-space rect for a target address, or undefined if it is not drawn. */
export function targetRect(layout: BoardLayout, target: string): Rect | undefined {
  const [id, sub] = target.split('#');
  const pe = layout.els.find((e) => e.el.id === id);
  if (!pe) return undefined;
  if (sub !== undefined && pe.parts[sub]) {
    const p = pe.parts[sub];
    return { x: pe.x + p.x, y: pe.y + p.y, w: p.w, h: p.h };
  }
  return { x: pe.x, y: pe.y, w: pe.w, h: pe.h };
}

/** A few words for what a target shows — the fallback when the agent has no record of it. */
export function targetText(layout: BoardLayout, target: string): string {
  const [id, sub] = target.split('#');
  const pe = layout.els.find((e) => e.el.id === id);
  if (!pe) return target;
  const el = pe.el;
  if (sub === undefined) {
    if (el.kind === 'text' || el.kind === 'note') return el.text;
    if (el.kind === 'code') return el.lines.slice(0, 2).join(' / ');
    if (el.kind === 'array' || el.kind === 'chain') return el.values.join(', ');
    if (el.kind === 'tree') return el.nodes.map((n) => n.label).join(', ');
    if (el.kind === 'diagram') return el.nodes.map((n) => n.label).join(' -> ');
    if (el.kind === 'list') return el.items.join('; ');
    if (el.kind === 'media') return el.caption ?? el.media;
    return el.label ?? el.kind;
  }
  if (el.kind === 'code') return el.lines[+sub]?.trim() ?? '';
  if (el.kind === 'array' || el.kind === 'chain') return el.values[+sub] ?? '';
  if (el.kind === 'tree') return el.nodes.find((n) => n.id === sub)?.label ?? '';
  if (el.kind === 'diagram') return el.nodes.find((n) => n.id === sub)?.label ?? '';
  if (el.kind === 'list') return el.items[+sub] ?? '';
  if (el.kind === 'table') {
    const [r, c] = sub.split('.').map(Number);
    return el.rows[r]?.[c] ?? '';
  }
  return '';
}

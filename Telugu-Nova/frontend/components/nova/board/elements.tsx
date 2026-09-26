'use client';

import { createContext, useContext } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import type {
  CellGeom,
  ChainGeom,
  CodeGeom,
  DiagramGeom,
  ListGeom,
  MediaGeom,
  PlacedEl,
  PlacedStep,
  TableGeom,
  TextGeom,
  TreeGeom,
} from './layout';
import { HAND, MONO, TITLE_FS } from './layout';
import { arrowHead, sketchLine, sketchPill, sketchRect } from './sketch';

/** Marker colours. Navy for the lesson, clay for Nova's live annotations. */
export const INK = {
  board: '#FBFAF6',
  grid: '#EFEBE2',
  ink: '#2B3A55',
  soft: '#8A8F9C',
  faint: '#C9C6BD',
  teacher: '#C4704F',
  highlight: '#F6D55C',
  student: '#2F7FD1',
  studentHi: '#7ED957',
};

const WRITE_STAGGER = 0.55; // seconds between elements of one step

/** Reveal an element left-to-right, like a marker writing it. Mount-only. */
function WriteIn({
  id,
  w,
  h,
  delay,
  children,
}: {
  id: string;
  w: number;
  h: number;
  delay: number;
  children: React.ReactNode;
}) {
  const dur = Math.min(1.5, 0.35 + w / 900);
  return (
    <>
      <defs>
        <clipPath id={`wr-${id}`}>
          <motion.rect
            x={-20}
            y={-40}
            height={h + 80}
            initial={{ width: 0 }}
            animate={{ width: w + 60 }}
            transition={{ duration: dur, delay, ease: 'easeInOut' }}
          />
        </clipPath>
      </defs>
      <g clipPath={`url(#wr-${id})`}>{children}</g>
    </>
  );
}

function Label({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <text x={0} y={17} fontFamily={HAND} fontSize={17} fill={INK.soft}>
      {text}
    </text>
  );
}

// ---------------------------------------------------------------------------

function TextEl({ pe, color = INK.ink }: { pe: PlacedEl; color?: string }) {
  const g = pe.geom as TextGeom;
  return (
    <>
      {g.lines.map((ln, i) => (
        <text key={i} x={0} y={i * g.lh + g.fs} fontFamily={HAND} fontSize={g.fs} fill={color}>
          {ln}
        </text>
      ))}
    </>
  );
}

function NoteEl({ pe }: { pe: PlacedEl }) {
  const g = pe.geom as TextGeom;
  return (
    <>
      <path
        d={`M6,-10 Q4,${g.lh * 0.55} 20,${g.lh * 0.55}`}
        fill="none"
        stroke={INK.teacher}
        strokeWidth={2}
        strokeLinecap="round"
      />
      <path
        d={arrowHead(6, -12, -Math.PI / 2, 8)}
        fill="none"
        stroke={INK.teacher}
        strokeWidth={2}
        strokeLinecap="round"
      />
      <g transform="translate(30,0)">
        {g.lines.map((ln, i) => (
          <text
            key={i}
            x={0}
            y={i * g.lh + g.fs}
            fontFamily={HAND}
            fontSize={g.fs}
            fill={INK.teacher}
          >
            {ln}
          </text>
        ))}
      </g>
    </>
  );
}

function CodeEl({ pe }: { pe: PlacedEl }) {
  const el = pe.el as Extract<PlacedEl['el'], { kind: 'code' }>;
  const g = pe.geom as CodeGeom;
  const bodyH = pe.h - g.labelH;
  return (
    <>
      <Label text={el.label} />
      <rect x={0} y={g.labelH} width={pe.w} height={bodyH} rx={8} fill="#F3F1EA" />
      <path
        d={sketchRect(0, g.labelH, pe.w, bodyH, pe.el.id)}
        fill="none"
        stroke={INK.faint}
        strokeWidth={1.5}
      />
      {el.lines.map((ln, i) => (
        <g key={i}>
          <text
            x={g.pad - 4}
            y={g.labelH + g.pad + i * g.lh + g.fs}
            fontFamily={MONO}
            className="mono"
            fontSize={g.fs * 0.78}
            fill={INK.faint}
            textAnchor="end"
          >
            {i + 1}
          </text>
          <text
            x={g.pad + 6}
            y={g.labelH + g.pad + i * g.lh + g.fs}
            fontFamily={MONO}
            className="mono"
            fontSize={g.fs}
            fill={INK.ink}
            style={{ whiteSpace: 'pre' }}
          >
            {ln}
          </text>
        </g>
      ))}
    </>
  );
}

function ArrayEl({ pe }: { pe: PlacedEl }) {
  const el = pe.el as Extract<PlacedEl['el'], { kind: 'array' }>;
  const g = pe.geom as CellGeom;
  const fs = Math.min(21, g.cellW * 0.42);
  return (
    <>
      <Label text={el.label} />
      {el.values.map((v, i) => (
        <g key={i}>
          <path
            d={sketchRect(i * g.cellW, g.top, g.cellW, g.cellH, `${pe.el.id}-${i}`)}
            fill="none"
            stroke={INK.ink}
            strokeWidth={2}
            strokeLinecap="round"
          />
          <AnimatePresence mode="popLayout">
            <motion.text
              key={`${i}-${v}`}
              x={i * g.cellW + g.cellW / 2}
              y={g.top + g.cellH / 2 + fs * 0.36}
              textAnchor="middle"
              fontFamily={HAND}
              fontSize={fs}
              fill={INK.ink}
              initial={{ opacity: 0, y: g.top + g.cellH / 2 + fs * 0.36 - 10 }}
              animate={{ opacity: 1, y: g.top + g.cellH / 2 + fs * 0.36 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              {v}
            </motion.text>
          </AnimatePresence>
          <text
            x={i * g.cellW + g.cellW / 2}
            y={g.top + g.cellH + 15}
            textAnchor="middle"
            fontFamily={MONO}
            className="mono"
            fontSize={11}
            fill={INK.soft}
          >
            {i}
          </text>
        </g>
      ))}
      {(el.pointers ?? []).map((p, k) => {
        // Pointers on the same cell stack so both names stay readable.
        const same = (el.pointers ?? []).slice(0, k).filter((q) => q.index === p.index).length;
        const cx = p.index * g.cellW + g.cellW / 2;
        const top = g.top + g.cellH + 20;
        return (
          <motion.g
            key={p.name}
            initial={false}
            animate={{ x: cx }}
            transition={{ type: 'spring', stiffness: 170, damping: 20 }}
          >
            <path d={`M0,${top + 18} L0,${top + 2}`} stroke={INK.teacher} strokeWidth={2} />
            <path
              d={arrowHead(0, top, -Math.PI / 2, 7)}
              fill="none"
              stroke={INK.teacher}
              strokeWidth={2}
            />
            <text
              x={same * 16}
              y={top + 34}
              textAnchor="middle"
              fontFamily={HAND}
              fontSize={17}
              fill={INK.teacher}
            >
              {p.name}
            </text>
          </motion.g>
        );
      })}
    </>
  );
}

function ChainEl({ pe }: { pe: PlacedEl }) {
  const el = pe.el as Extract<PlacedEl['el'], { kind: 'chain' }>;
  const g = pe.geom as ChainGeom;
  return (
    <>
      <Label text={el.label} />
      {g.boxes.map((b, i) => (
        <g key={i}>
          <path
            d={sketchRect(b.x, b.y, b.w, b.h, `${pe.el.id}-${i}`)}
            fill="none"
            stroke={INK.ink}
            strokeWidth={2}
            strokeLinecap="round"
          />
          <text
            x={b.x + b.w / 2}
            y={b.y + b.h / 2 + g.fs * 0.36}
            textAnchor="middle"
            fontFamily={HAND}
            fontSize={g.fs}
            fill={INK.ink}
          >
            {el.values[i]}
          </text>
          {g.arrows && i < g.boxes.length - 1 && (
            <ChainArrow a={b} b={g.boxes[i + 1]} vertical={g.vertical} seed={`${pe.el.id}-a${i}`} />
          )}
        </g>
      ))}
    </>
  );
}

function ChainArrow({
  a,
  b,
  vertical,
  seed,
}: {
  a: { x: number; y: number; w: number; h: number };
  b: { x: number; y: number; w: number; h: number };
  vertical: boolean;
  seed: string;
}) {
  const [x1, y1, x2, y2] = vertical
    ? [a.x + a.w / 2, a.y + a.h + 2, b.x + b.w / 2, b.y - 3]
    : [a.x + a.w + 3, a.y + a.h / 2, b.x - 4, b.y + b.h / 2];
  return (
    <>
      <path
        d={sketchLine(x1, y1, x2, y2, seed, 0.8)}
        fill="none"
        stroke={INK.ink}
        strokeWidth={1.8}
      />
      <path
        d={arrowHead(x2, y2, Math.atan2(y2 - y1, x2 - x1), 8)}
        fill="none"
        stroke={INK.ink}
        strokeWidth={1.8}
        strokeLinecap="round"
      />
    </>
  );
}

function TreeEl({ pe }: { pe: PlacedEl }) {
  const el = pe.el as Extract<PlacedEl['el'], { kind: 'tree' }>;
  const g = pe.geom as TreeGeom;
  const at = new Map(g.nodes.map((n) => [n.node.id, n]));
  return (
    <>
      <Label text={el.label} />
      {g.edges.map((e) => {
        const a = at.get(e.from);
        const b = at.get(e.to);
        if (!a || !b) return null;
        return (
          <path
            key={`${e.from}-${e.to}`}
            d={sketchLine(a.x + a.w / 2, a.y + a.h, b.x + b.w / 2, b.y, `${pe.el.id}-${e.to}`, 0.8)}
            fill="none"
            stroke={INK.ink}
            strokeWidth={1.8}
          />
        );
      })}
      {g.nodes.map((n) => (
        <g key={n.node.id}>
          <path
            d={sketchPill(n.x, n.y, n.w, n.h, `${pe.el.id}-${n.node.id}`)}
            fill={INK.board}
            stroke={INK.ink}
            strokeWidth={2}
          />
          <text
            x={n.x + n.w / 2}
            y={n.y + n.h / 2 + g.fs * 0.36}
            textAnchor="middle"
            fontFamily={HAND}
            fontSize={g.fs}
            fill={INK.ink}
          >
            {n.node.label}
          </text>
        </g>
      ))}
    </>
  );
}

function TableEl({ pe }: { pe: PlacedEl }) {
  const el = pe.el as Extract<PlacedEl['el'], { kind: 'table' }>;
  const g = pe.geom as TableGeom;
  const top = g.labelH;
  const nrows = el.rows.length + (g.headers ? 1 : 0);
  const xs = g.colW.reduce<number[]>((acc, w) => [...acc, acc[acc.length - 1] + w], [0]);
  const width = xs[xs.length - 1];
  const cell = (text: string, ci: number, ri: number, bold: boolean) => (
    <text
      key={`${ri}-${ci}`}
      x={xs[ci] + 10}
      y={top + ri * g.rowH + g.rowH / 2 + g.fs * 0.36}
      fontFamily={HAND}
      fontSize={g.fs}
      fontWeight={bold ? 700 : 400}
      fill={bold ? INK.teacher : INK.ink}
    >
      {text}
    </text>
  );
  return (
    <>
      <Label text={el.label} />
      {Array.from({ length: nrows + 1 }, (_, r) => (
        <path
          key={`h${r}`}
          d={sketchLine(0, top + r * g.rowH, width, top + r * g.rowH, `${pe.el.id}-h${r}`, 0.9)}
          fill="none"
          stroke={r === 1 && g.headers ? INK.ink : INK.faint}
          strokeWidth={r === 1 && g.headers ? 1.8 : 1.3}
        />
      ))}
      {xs.map((x, c) => (
        <path
          key={`v${c}`}
          d={sketchLine(x, top, x, top + nrows * g.rowH, `${pe.el.id}-v${c}`, 0.9)}
          fill="none"
          stroke={INK.faint}
          strokeWidth={1.3}
        />
      ))}
      {g.headers && (el.headers ?? []).map((h, c) => cell(h, c, 0, true))}
      {el.rows.map((row, r) => row.map((t, c) => cell(t, c, r + (g.headers ? 1 : 0), false)))}
    </>
  );
}

// ---------------------------------------------------------------------------
// General-subject visuals: diagrams, cycles, lists, generated media
// ---------------------------------------------------------------------------

/** Generated media bytes by element id: a blob URL, or 'failed'. */
export const MediaContext = createContext<Record<string, { url: string; mime: string } | 'failed'>>(
  {}
);

function edgePoint(r: { x: number; y: number; w: number; h: number }, tx: number, ty: number) {
  const cx = r.x + r.w / 2;
  const cy = r.y + r.h / 2;
  const dx = tx - cx;
  const dy = ty - cy;
  const t = Math.min(
    Math.abs(dx) > 0.01 ? r.w / 2 / Math.abs(dx) : Infinity,
    Math.abs(dy) > 0.01 ? r.h / 2 / Math.abs(dy) : Infinity
  );
  return { x: cx + dx * Math.min(1, t + 0.05), y: cy + dy * Math.min(1, t + 0.05) };
}

const PALETTE: Record<string, { fill: string; stroke: string }> = {
  blue: { fill: '#DCEBFA', stroke: '#4F7DB3' },
  green: { fill: '#DDF3E4', stroke: '#4E9A6A' },
  orange: { fill: '#FCE3D2', stroke: '#C4704F' },
  pink: { fill: '#F9DDE8', stroke: '#B85B82' },
  purple: { fill: '#E8E0F8', stroke: '#7A62B8' },
  yellow: { fill: '#FBF1C9', stroke: '#B8952E' },
  gray: { fill: '#ECEBE7', stroke: '#7C7A73' },
};
const paint = (c?: string) => PALETTE[c ?? ''] ?? { fill: '#FFFFFF', stroke: INK.ink };

/** A short label on an arrow, on a white chip so crossing lines never hide it. */
function EdgeLabel({ x, y, text }: { x: number; y: number; text: string }) {
  const w = text.length * 7.6 + 12;
  return (
    <g>
      <rect
        x={x - w / 2}
        y={y - 11}
        width={w}
        height={20}
        rx={10}
        fill="#FFFFFF"
        stroke={INK.grid}
      />
      <text x={x} y={y + 4} textAnchor="middle" fontFamily={HAND} fontSize={14} fill={INK.teacher}>
        {text}
      </text>
    </g>
  );
}

function DiagramNode({
  n,
  r,
  seed,
  fs,
  band,
}: {
  n: { id: string; label: string; icon?: string; note?: string; color?: string };
  r: { x: number; y: number; w: number; h: number };
  seed: string;
  fs: number;
  band?: boolean;
}) {
  const p = paint(n.color);
  const text = `${n.icon ? n.icon + ' ' : ''}${n.label}`;
  const size = Math.min(fs, (r.w - 18) / Math.max(1, text.length * 0.52));
  const labelY = n.note && !band ? r.y + r.h / 2 - 2 : r.y + r.h / 2 + size * 0.36;
  return (
    <g>
      <path
        d={band ? sketchRect(r.x, r.y, r.w, r.h, seed) : sketchPill(r.x, r.y, r.w, r.h, seed)}
        fill={p.fill}
        stroke={p.stroke}
        strokeWidth={2}
      />
      <text
        x={band ? r.x + 16 : r.x + r.w / 2}
        y={labelY}
        textAnchor={band ? 'start' : 'middle'}
        fontFamily={HAND}
        fontSize={size}
        fontWeight={700}
        fill={INK.ink}
      >
        {text}
      </text>
      {n.note && (
        <text
          x={band ? r.x + r.w - 14 : r.x + r.w / 2}
          y={band ? r.y + r.h / 2 + 5 : r.y + r.h / 2 + 16}
          textAnchor={band ? 'end' : 'middle'}
          fontFamily={HAND}
          fontSize={13}
          fill={INK.soft}
        >
          {n.note}
        </text>
      )}
    </g>
  );
}

function DiagramEl({ pe }: { pe: PlacedEl }) {
  const el = pe.el as Extract<PlacedEl['el'], { kind: 'diagram' }>;
  const g = pe.geom as DiagramGeom;
  const hub = g.layout === 'hub' ? el.nodes[0] : undefined;
  // A hub always has spokes; other layouts draw exactly the edges given.
  const edges =
    hub && el.edges.length === 0
      ? el.nodes.slice(1).map((n) => ({ from: hub.id, to: n.id, label: '' }))
      : g.layout === 'layers' || g.layout === 'compare' || g.layout === 'timeline'
        ? []
        : el.edges;
  return (
    <>
      {el.label && (
        <text x={0} y={19} fontFamily={HAND} fontSize={20} fontWeight={700} fill={INK.ink}>
          {el.label}
        </text>
      )}

      {g.layout === 'timeline' && g.axisY !== undefined && (
        <>
          <path
            d={sketchLine(0, g.axisY, pe.w, g.axisY, `${pe.el.id}-axis`, 1)}
            stroke={INK.ink}
            strokeWidth={2.4}
            fill="none"
          />
          <path
            d={arrowHead(pe.w, g.axisY, 0, 10)}
            stroke={INK.ink}
            strokeWidth={2.4}
            fill="none"
          />
          {el.nodes.map((n) => {
            const r = g.boxes[n.id];
            if (!r) return null;
            const cx = r.x + r.w / 2;
            return (
              <g key={`t-${n.id}`}>
                <line
                  x1={cx}
                  y1={g.axisY}
                  x2={cx}
                  y2={r.y}
                  stroke={INK.faint}
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                />
                <circle cx={cx} cy={g.axisY} r={6} fill={paint(n.color).stroke} />
              </g>
            );
          })}
        </>
      )}

      {g.layout === 'compare' && g.headers && (
        <>
          {g.headers.map((h, i) => (
            <g key={h.text}>
              <rect
                x={h.x}
                y={h.y}
                width={h.w}
                height={34}
                rx={10}
                fill={i === 0 ? '#DCEBFA' : '#FCE3D2'}
              />
              <text
                x={h.x + h.w / 2}
                y={h.y + 23}
                textAnchor="middle"
                fontFamily={HAND}
                fontSize={19}
                fontWeight={700}
                fill={INK.ink}
              >
                {h.text}
              </text>
            </g>
          ))}
          {g.center && (
            <g>
              <circle cx={g.center.x} cy={g.center.y} r={20} fill={INK.teacher} />
              <text
                x={g.center.x}
                y={g.center.y + 5}
                textAnchor="middle"
                fontFamily={HAND}
                fontSize={15}
                fontWeight={700}
                fill="#FFFFFF"
              >
                vs
              </text>
            </g>
          )}
        </>
      )}

      {edges.map((e, i) => {
        const a = g.boxes[e.from];
        const b = g.boxes[e.to];
        if (!a || !b) return null;
        const p1 = edgePoint(a, b.x + b.w / 2, b.y + b.h / 2);
        const p2 = edgePoint(b, a.x + a.w / 2, a.y + a.h / 2);
        let mx = (p1.x + p2.x) / 2;
        let my = (p1.y + p2.y) / 2;
        if (g.layout === 'cycle' && g.center) {
          // Bow outward so the loop reads as a loop.
          const ox = mx - g.center.x;
          const oy = my - g.center.y;
          const len = Math.hypot(ox, oy) || 1;
          mx += (ox / len) * 28;
          my += (oy / len) * 28;
        }
        const ang = Math.atan2(p2.y - my, p2.x - mx);
        // Label at the true midpoint of the curve.
        const lx = (p1.x + 2 * mx + p2.x) / 4;
        const ly = (p1.y + 2 * my + p2.y) / 4;
        return (
          <g key={i}>
            <path
              d={`M${p1.x},${p1.y} Q${mx},${my} ${p2.x},${p2.y}`}
              fill="none"
              stroke={INK.ink}
              strokeWidth={1.9}
              strokeLinecap="round"
            />
            <path
              d={arrowHead(p2.x, p2.y, ang, 9)}
              fill="none"
              stroke={INK.ink}
              strokeWidth={1.9}
              strokeLinecap="round"
            />
            {e.label && <EdgeLabel x={lx} y={ly} text={e.label} />}
          </g>
        );
      })}

      {el.nodes.map((n) => {
        const r = g.boxes[n.id];
        if (!r) return null;
        return (
          <DiagramNode
            key={n.id}
            n={n}
            r={r}
            seed={`${pe.el.id}-${n.id}`}
            fs={hub && n.id === hub.id ? g.fs + 2 : g.fs}
            band={g.layout === 'layers'}
          />
        );
      })}
    </>
  );
}

function ListEl({ pe }: { pe: PlacedEl }) {
  const el = pe.el as Extract<PlacedEl['el'], { kind: 'list' }>;
  const g = pe.geom as ListGeom;
  return (
    <>
      <Label text={el.label} />
      {g.items.map((it, i) => (
        <g key={i}>
          <circle cx={8} cy={it.y + g.lh / 2} r={4} fill={INK.teacher} />
          {it.lines.map((ln, j) => (
            <text
              key={j}
              x={24}
              y={it.y + j * g.lh + g.fs}
              fontFamily={HAND}
              fontSize={g.fs}
              fill={INK.ink}
            >
              {ln}
            </text>
          ))}
        </g>
      ))}
    </>
  );
}

function MediaEl({ pe }: { pe: PlacedEl }) {
  const el = pe.el as Extract<PlacedEl['el'], { kind: 'media' }>;
  const g = pe.geom as MediaGeom;
  const media = useContext(MediaContext)[el.id];
  const top = g.labelH;
  const ready = media && media !== 'failed' ? media : null;
  return (
    <>
      {el.caption && (
        <text x={0} y={18} fontFamily={HAND} fontSize={19} fontWeight={700} fill={INK.teacher}>
          {el.caption}
        </text>
      )}
      <rect x={0} y={top} width={g.mediaW} height={g.mediaH} rx={10} fill="#F1EEE6" />
      {ready ? (
        ready.mime.startsWith('video') ? (
          <foreignObject x={0} y={top} width={g.mediaW} height={g.mediaH}>
            <video
              src={ready.url}
              autoPlay
              loop
              muted
              playsInline
              controls
              style={{ width: '100%', height: '100%', borderRadius: 10, objectFit: 'cover' }}
            />
          </foreignObject>
        ) : (
          <image
            href={ready.url}
            x={0}
            y={top}
            width={g.mediaW}
            height={g.mediaH}
            preserveAspectRatio="xMidYMid meet"
          />
        )
      ) : (
        <motion.text
          x={g.mediaW / 2}
          y={top + g.mediaH / 2}
          textAnchor="middle"
          fontFamily={HAND}
          fontSize={20}
          fill={INK.soft}
          animate={media === 'failed' ? { opacity: 1 } : { opacity: [0.35, 1, 0.35] }}
          transition={media === 'failed' ? {} : { duration: 1.4, repeat: Infinity }}
        >
          {media === 'failed'
            ? 'could not generate this one'
            : el.media === 'video'
              ? 'making a short clip… (about a minute)'
              : 'drawing an infographic…'}
        </motion.text>
      )}
      {ready && (
        <g data-snapshot-skip>
          <rect
            x={g.mediaW - 196}
            y={top + g.mediaH - 30}
            width={188}
            height={22}
            rx={11}
            fill="#FFFFFF"
            opacity={0.9}
          />
          <text
            x={g.mediaW - 102}
            y={top + g.mediaH - 15}
            textAnchor="middle"
            fontFamily={MONO}
            className="mono"
            fontSize={11}
            fill={INK.teacher}
          >
            {el.media === 'video' ? 'AI-generated · Veo' : 'AI-generated · Nano Banana'}
          </text>
        </g>
      )}
      <path
        d={sketchRect(0, top, g.mediaW, g.mediaH, pe.el.id)}
        fill="none"
        stroke={INK.faint}
        strokeWidth={1.5}
      />
    </>
  );
}

// ---------------------------------------------------------------------------

export function BoardElement({ pe }: { pe: PlacedEl }) {
  let body: React.ReactNode;
  switch (pe.el.kind) {
    case 'text':
      body = <TextEl pe={pe} />;
      break;
    case 'note':
      body = <NoteEl pe={pe} />;
      break;
    case 'code':
      body = <CodeEl pe={pe} />;
      break;
    case 'array':
      body = <ArrayEl pe={pe} />;
      break;
    case 'chain':
      body = <ChainEl pe={pe} />;
      break;
    case 'tree':
      body = <TreeEl pe={pe} />;
      break;
    case 'table':
      body = <TableEl pe={pe} />;
      break;
    case 'diagram':
      body = <DiagramEl pe={pe} />;
      break;
    case 'list':
      body = <ListEl pe={pe} />;
      break;
    case 'media':
      body = <MediaEl pe={pe} />;
      break;
  }
  return (
    <motion.g
      data-el={pe.el.id}
      initial={{ x: pe.x, y: pe.y }}
      animate={{ x: pe.x, y: pe.y }}
      transition={{ type: 'spring', stiffness: 140, damping: 22 }}
    >
      <WriteIn id={pe.el.id} w={pe.w} h={pe.h} delay={0.45 + pe.order * WRITE_STAGGER}>
        {body}
      </WriteIn>
    </motion.g>
  );
}

export function StepTitle({ ps }: { ps: PlacedStep }) {
  const title = ps.step.title;
  const w = Math.min(ps.w, title.length * TITLE_FS * 0.5 + 44);
  return (
    <motion.g
      initial={{ x: ps.x, y: ps.y }}
      animate={{ x: ps.x, y: ps.y }}
      transition={{ type: 'spring', stiffness: 140, damping: 22 }}
    >
      <WriteIn id={`title-${ps.step.id}`} w={w} h={44} delay={0}>
        {title && (
          <>
            <circle cx={13} cy={17} r={13} fill="none" stroke={INK.teacher} strokeWidth={2} />
            <text
              x={13}
              y={23}
              textAnchor="middle"
              fontFamily={HAND}
              fontSize={17}
              fill={INK.teacher}
            >
              {ps.index}
            </text>
            <text
              x={36}
              y={26}
              fontFamily={HAND}
              fontSize={TITLE_FS}
              fontWeight={700}
              fill={INK.ink}
            >
              {title}
            </text>
            <path
              d={sketchLine(36, 37, w, 38, `ul-${ps.step.id}`, 1)}
              fill="none"
              stroke={INK.teacher}
              strokeWidth={2.2}
              strokeLinecap="round"
            />
          </>
        )}
      </WriteIn>
    </motion.g>
  );
}

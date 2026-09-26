'use client';

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useDataChannel, useSessionContext } from '@livekit/components-react';
import { useT } from '../i18n';
import { loadBoard, loadMedia, saveBoard, saveMedia } from './archive';
import { BoardElement, INK, MediaContext, StepTitle } from './elements';
import { type BoardLayout, HAND, layoutBoard, targetRect, targetText } from './layout';
import { type Pt, bboxOf, hitTest, shapeOf, snapshotRegion } from './marks';
import {
  type ResearchItem,
  type ResearchOp,
  ResearchPanel,
  reduceResearch,
} from './research-panel';
import { arrowHead, sketchCircle, smoothPath } from './sketch';
import type { BoardOp, El, Rect, Step, StudentMark } from './types';

/**
 * The shared whiteboard.
 *
 * Nova draws here while it talks: a lesson arrives as steps, each revealed as
 * Nova reaches it, plus live highlights, arrows and notes when a doubt comes
 * up. The student draws here too — circling or underlining anything turns
 * into a precise question ("line 3 of the code") that Nova hears instantly.
 *
 * Agent -> browser: data channel "nova-board" (small JSON ops).
 * Browser -> agent: text stream "nova-board-student" (marks, with a JPEG of
 * the marked region, which can be far larger than a data packet allows).
 */

export const BOARD_TOPIC = 'nova-board';
export const STUDENT_TOPIC = 'nova-board-student';

// ---------------------------------------------------------------------------
// Board state
// ---------------------------------------------------------------------------

type Annot =
  | { kind: 'hl'; id: number; target: string; color: string }
  | { kind: 'arrow'; id: number; from: string; to: string; label?: string };

type State = {
  title: string;
  steps: Step[];
  revealed: number;
  planning: string | null;
  annots: Annot[];
  pointAt: string | null;
  pointSeq: number;
  seq: number;
};

const EMPTY: State = {
  title: '',
  steps: [],
  revealed: 0,
  planning: null,
  annots: [],
  pointAt: null,
  pointSeq: 0,
  seq: 0,
};

const HL_COLORS: Record<string, string> = {
  yellow: INK.highlight,
  green: '#9BE08A',
  pink: '#F7A8C4',
  blue: '#A9D2F7',
  orange: '#F9C58D',
};

function withElement(steps: Step[], id: string, fn: (el: El) => El): Step[] {
  return steps.map((s) => ({
    ...s,
    elements: s.elements.map((e) => (e.id === id ? fn(e) : e)),
  }));
}

function reduce(state: State, op: BoardOp): State {
  const seq = state.seq + 1;
  switch (op.op) {
    case 'planning':
      return { ...state, planning: op.topic, seq };
    case 'lesson':
      return {
        ...EMPTY,
        title: op.lesson.title,
        steps: op.lesson.steps.map((s) => ({ ...s, elements: [...s.elements] })),
        seq,
      };
    case 'reveal':
      return {
        ...state,
        planning: null,
        revealed: Math.min(state.steps.length, Math.max(state.revealed, op.step)),
        pointAt: null,
        seq,
      };
    case 'add': {
      const steps = state.steps.map((s) => ({ ...s, elements: [...s.elements] }));
      let revealed = state.revealed;
      // After the element it explains, else at the end of the latest step.
      const afterId = op.after?.split('#')[0];
      let si = afterId
        ? steps.slice(0, revealed).findIndex((s) => s.elements.some((e) => e.id === afterId))
        : -1;
      if (si >= 0) {
        const at = steps[si].elements.findIndex((e) => e.id === afterId);
        steps[si].elements.splice(at + 1, 0, op.element);
      } else {
        if (revealed === 0) {
          steps.splice(0, 0, { id: `free${seq}`, title: '', elements: [] });
          revealed = 1;
        }
        si = revealed - 1;
        steps[si].elements.push(op.element);
      }
      return {
        ...state,
        steps,
        revealed,
        planning: null,
        pointAt: op.element.id,
        pointSeq: seq,
        seq,
      };
    }
    case 'array':
      return {
        ...state,
        steps: withElement(state.steps, op.id, (e) =>
          e.kind === 'array'
            ? { ...e, values: op.values ?? e.values, pointers: op.pointers ?? e.pointers }
            : e
        ),
        pointAt: op.id,
        pointSeq: seq,
        seq,
      };
    case 'highlight': {
      // Keep the board readable: only the latest few highlights stay.
      const annots = [
        ...state.annots.filter((a) => !(a.kind === 'hl' && a.target === op.target)),
        {
          kind: 'hl' as const,
          id: seq,
          target: op.target,
          color: HL_COLORS[op.color ?? ''] ?? INK.highlight,
        },
      ];
      const hls = annots.filter((a) => a.kind === 'hl');
      const drop = new Set(hls.slice(0, Math.max(0, hls.length - 4)).map((a) => a.id));
      return {
        ...state,
        annots: annots.filter((a) => !drop.has(a.id)),
        pointAt: op.target,
        pointSeq: seq,
        seq,
      };
    }
    case 'arrow':
      return {
        ...state,
        annots: [
          ...state.annots,
          { kind: 'arrow' as const, id: seq, from: op.from, to: op.to, label: op.label },
        ].slice(-4),
        pointAt: op.to,
        pointSeq: seq,
        seq,
      };
    case 'point':
      return { ...state, pointAt: op.target, pointSeq: seq, seq };
    case 'unmark':
      return { ...state, annots: [], pointAt: null, seq };
    case 'clear':
      return { ...EMPTY, title: state.title, seq };
    case 'board_new':
    case 'board_open':
    case 'media_fail':
      return state; // handled by reduceBook / the media store
  }
}

// ---------------------------------------------------------------------------
// Several boards, like tabs. A new topic opens a new page; old pages stay.
// ---------------------------------------------------------------------------

type Book = { pages: Record<string, State>; order: string[]; active: string };
type BookOp =
  | (BoardOp & { board?: string })
  | { op: 'local_open'; board: string }
  | { op: 'local_new'; board: string; title: string }
  | { op: 'restore'; book: Book };

const FIRST_BOOK: Book = {
  pages: { b1: { ...EMPTY, title: 'Board 1' } },
  order: ['b1'],
  active: 'b1',
};

function withPage(book: Book, id: string, title?: string): Book {
  if (book.pages[id]) return book;
  return {
    ...book,
    pages: { ...book.pages, [id]: { ...EMPTY, title: title || `Board ${book.order.length + 1}` } },
    order: [...book.order, id],
  };
}

function reduceBook(book: Book, op: BookOp): Book {
  if (op.op === 'restore') return op.book;
  if (op.op === 'local_open') return { ...withPage(book, op.board), active: op.board };
  if (op.op === 'local_new') return { ...withPage(book, op.board, op.title), active: op.board };
  const id = op.board ?? book.active;
  let next = withPage(book, id, op.op === 'board_new' ? op.title : undefined);
  if (op.op === 'board_new' && op.title) {
    next = { ...next, pages: { ...next.pages, [id]: { ...next.pages[id], title: op.title } } };
  }
  const page = reduce(next.pages[id], op);
  // Wherever the teacher draws is where the student should be looking.
  return { ...next, pages: { ...next.pages, [id]: page }, active: id };
}

// ---------------------------------------------------------------------------
// Student ink
// ---------------------------------------------------------------------------

type Tool = 'pen' | 'highlighter' | 'hand';
type Stroke = { id: number; pts: Pt[]; tool: Tool; mark: number | null; page: string };
type Mark = {
  id: number;
  page: string;
  box: Rect;
  shape: StudentMark['shape'];
  targets: { target: string; text: string }[];
  status: 'open' | 'asked';
  image?: string;
};

const GROUP_MS = 850; // strokes closer together than this are one mark
const AUTO_ASK_S = 2; // seconds before a circle asks on its own

// ---------------------------------------------------------------------------

/**
 * `chatId` names the archive this board is saved under. With `replay`, the
 * board is read-only: it loads a finished class from the archive instead of
 * listening to a live one.
 */
export function Board({
  fallback,
  chatId,
  replay = false,
  restore = false,
}: {
  fallback?: React.ReactNode;
  chatId?: string;
  replay?: boolean;
  /** Live, but continuing a saved chat: load its board first. */
  restore?: boolean;
}) {
  const [book, dispatch] = useReducer(reduceBook, FIRST_BOOK);
  const [research, dispatchResearch] = useReducer(reduceResearch, []);
  const [media, setMedia] = useState<
    Record<string, { url: string; mime: string; source?: string } | 'failed'>
  >({});
  const state = book.pages[book.active] ?? EMPTY;
  const session = useSessionContext();
  const room = replay ? undefined : session.room;

  // --- archive: save the live board as it changes; load it when replaying
  const chatRef = useRef(chatId);
  chatRef.current = chatId;
  // Until a continued chat's board is loaded, do not save the empty one over it.
  const restoredRef = useRef(!restore);
  useEffect(() => {
    if (replay || !chatId || !restoredRef.current) return;
    const snapshot = { book, research };
    const t = setTimeout(() => void saveBoard(chatId, snapshot), 600);
    return () => {
      clearTimeout(t);
      // Also on unmount: ending the class must not drop the last change.
      void saveBoard(chatId, snapshot);
    };
  }, [book, research, chatId, replay]);
  useEffect(() => {
    if (!(replay || restore) || !chatId) return;
    let alive = true;
    void (async () => {
      const saved = await loadBoard<{ book: Book; research: ResearchItem[] }>(chatId);
      const blobs = await loadMedia(chatId);
      if (!alive) return;
      if (saved?.book) dispatch({ op: 'restore', book: saved.book });
      if (saved?.research) dispatchResearch({ op: 'restore', items: saved.research });
      restoredRef.current = true;
      setMedia((live) => ({
        ...Object.fromEntries(
          Object.entries(blobs).map(([id, m]) => [
            id,
            { url: URL.createObjectURL(m.blob), mime: m.mime, source: m.source },
          ])
        ),
        ...live,
      }));
    })();
    return () => {
      alive = false;
    };
  }, [replay, restore, chatId]);

  useDataChannel(BOARD_TOPIC, (msg) => {
    if (replay) return;
    try {
      const op = JSON.parse(new TextDecoder().decode(msg.payload)) as BookOp | ResearchOp;
      if (op.op.startsWith('research')) dispatchResearch(op as ResearchOp);
      else if (op.op === 'media_fail')
        setMedia((m) => ({ ...m, [(op as { id: string }).id]: 'failed' }));
      else dispatch(op as BookOp);
    } catch {
      /* ignore malformed frames */
    }
  });

  // Tell the teachers which page the student is looking at, so "ఇది" and
  // "this board" mean the right thing.
  const tellAgent = useCallback(
    (msg: Record<string, unknown>) => {
      room?.localParticipant
        .sendText(JSON.stringify(msg), { topic: STUDENT_TOPIC })
        .catch((err) => console.warn('board message not sent', err));
    },
    [room]
  );
  const openPage = (id: string) => {
    if (id === book.active) return;
    dispatch({ op: 'local_open', board: id });
    tellAgent({ type: 'board_open', board: id });
  };
  const newPage = () => {
    const id = `s${Date.now().toString(36)}`;
    const title = `Board ${book.order.length + 1}`;
    dispatch({ op: 'local_new', board: id, title });
    tellAgent({ type: 'board_new', board: id, title });
  };

  // Generated images and clips arrive as byte streams, keyed by element id.
  useEffect(() => {
    if (!room) return;
    const topic = 'nova-media';
    try {
      room.registerByteStreamHandler(topic, async (reader) => {
        const chunks = await reader.readAll();
        const mime = reader.info.mimeType || 'image/jpeg';
        const blob = new Blob(chunks as BlobPart[], { type: mime });
        const url = URL.createObjectURL(blob);
        const id = reader.info.attributes?.id ?? reader.info.id;
        const source = reader.info.attributes?.source || undefined;
        setMedia((m) => ({ ...m, [id]: { url, mime, source } }));
        if (chatRef.current) void saveMedia(chatRef.current, id, { blob, mime, source });
      });
    } catch {
      /* already registered by a previous mount */
    }
    return () => {
      try {
        room.unregisterByteStreamHandler(topic);
      } catch {
        /* ignore */
      }
    };
  }, [room]);

  // --- responsive columns
  const scrollRef = useRef<HTMLDivElement>(null);
  const [viewW, setViewW] = useState(900);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setViewW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // One wide column, so diagrams and pictures use the whole board; a second
  // column only on very wide screens.
  const columns = viewW >= 1700 ? 2 : 1;

  const layout: BoardLayout = useMemo(
    () => layoutBoard(state.steps, state.revealed, columns),
    [state.steps, state.revealed, columns]
  );
  const scale = viewW / layout.width;
  const boardH = Math.max(layout.height, (scrollRef.current?.clientHeight ?? 600) / scale);

  // --- follow Nova: keep whatever it just drew or pointed at in view
  const followRect = useMemo<Rect | undefined>(() => {
    if (state.pointAt) return targetRect(layout, state.pointAt);
    const last = layout.steps[layout.steps.length - 1];
    return last ? { x: last.x, y: last.y, w: last.w, h: last.h } : undefined;
  }, [layout, state.pointAt]);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !followRect) return;
    const top = followRect.y * scale;
    const bottom = (followRect.y + Math.min(followRect.h, 420)) * scale;
    if (top < el.scrollTop + 20 || bottom > el.scrollTop + el.clientHeight - 20) {
      el.scrollTo({ top: Math.max(0, top - 70), behavior: 'smooth' });
    }
    // Only re-run when the thing to follow changes, not on every layout tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.revealed, state.pointSeq]);

  // --- Nova's marker: shows where it is pointing, then fades
  const [pointerOn, setPointerOn] = useState(false);
  useEffect(() => {
    if (!state.pointAt) return;
    setPointerOn(true);
    const t = setTimeout(() => setPointerOn(false), 3500);
    return () => clearTimeout(t);
  }, [state.pointSeq, state.pointAt]);
  const pointerRect = state.pointAt ? targetRect(layout, state.pointAt) : undefined;

  // --- student ink
  const svgRef = useRef<SVGSVGElement>(null);
  const [tool, setTool] = useState<Tool>('pen');
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [marks, setMarks] = useState<Mark[]>([]);
  const drawing = useRef<Stroke | null>(null);
  const groupTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingStrokes = useRef<number[]>([]);
  const strokePts = useRef(new Map<number, Pt[]>()); // read synchronously when a mark closes
  const nextId = useRef(1);

  const toBoard = useCallback((e: React.PointerEvent): Pt => {
    const svg = svgRef.current!;
    const m = svg.getScreenCTM();
    if (!m) return [0, 0];
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return [p.x, p.y];
  }, []);

  const sendMark = useCallback(
    async (mark: Mark, ask: boolean) => {
      if (!room) return;
      const payload: StudentMark = {
        type: 'mark',
        id: String(mark.id),
        board: mark.page,
        ask,
        shape: mark.shape,
        targets: mark.targets,
        image: mark.image,
      };
      try {
        await room.localParticipant.sendText(JSON.stringify(payload), { topic: STUDENT_TOPIC });
      } catch (err) {
        console.warn('could not send mark', err);
      }
    },
    [room]
  );

  const finishMark = useCallback(async () => {
    if (replay) {
      pendingStrokes.current = []; // a finished class has no teacher to ask
      return;
    }
    const ids = pendingStrokes.current;
    pendingStrokes.current = [];
    if (!ids.length) return;
    const markId = nextId.current++;
    const mine = ids.map((id) => strokePts.current.get(id) ?? []);
    const pts = mine.flat();
    const firstPts = mine[0] ?? [];
    setStrokes((prev) => prev.map((s) => (ids.includes(s.id) ? { ...s, mark: markId } : s)));
    if (!pts.length) return;
    const box = bboxOf(pts);
    const shape = ids.length === 1 ? shapeOf(firstPts, box) : 'scribble';
    const targets = hitTest(layout, box, shape).map((t) => {
      const pe = layout.els.find((e) => e.el.id === t.split('#')[0]);
      let text = targetText(layout, t);
      // On a picture, say WHERE on it — "the image" alone tells the teacher nothing.
      if (pe?.el.kind === 'media') {
        const g = pe.geom as { labelH: number; mediaW: number; mediaH: number };
        const fx = Math.round(((box.x + box.w / 2 - pe.x) / g.mediaW) * 100);
        const fy = Math.round(((box.y + box.h / 2 - pe.y - g.labelH) / g.mediaH) * 100);
        text += ` — the mark is around ${Math.max(0, Math.min(100, fx))}% from the left and ${Math.max(0, Math.min(100, fy))}% from the top of the picture`;
      }
      return { target: t, text };
    });

    // Snapshot the mark plus whatever it points at, with some context around.
    const region = [
      box,
      ...targets.map((t) => targetRect(layout, t.target)).filter(Boolean),
    ] as Rect[];
    const x0 = Math.max(0, Math.min(...region.map((r) => r.x)) - 60);
    const y0 = Math.max(0, Math.min(...region.map((r) => r.y)) - 60);
    const x1 = Math.min(layout.width, Math.max(...region.map((r) => r.x + r.w)) + 60);
    const y1 = Math.max(...region.map((r) => r.y + r.h)) + 60;
    const image = svgRef.current
      ? await snapshotRegion(svgRef.current, {
          x: x0,
          y: y0,
          w: Math.max(200, x1 - x0),
          h: Math.max(120, y1 - y0),
        })
      : undefined;

    const mark: Mark = {
      id: markId,
      page: book.active,
      box,
      shape,
      targets,
      status: 'open',
      image,
    };
    setMarks((prev) => [...prev.filter((m) => m.status === 'asked').slice(-3), mark]);
    // Context only: if the student now just SAYS "idhi enti?", Nova knows what "idhi" is.
    void sendMark(mark, false);
  }, [layout, sendMark, book.active, replay]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (tool === 'hand' || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    if (groupTimer.current) clearTimeout(groupTimer.current);
    const s: Stroke = {
      id: nextId.current++,
      pts: [toBoard(e)],
      tool,
      mark: null,
      page: book.active,
    };
    drawing.current = s;
    strokePts.current.set(s.id, s.pts);
    setStrokes((prev) => [...prev, s]);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const s = drawing.current;
    if (!s) return;
    const p = toBoard(e);
    const last = s.pts[s.pts.length - 1];
    if (Math.hypot(p[0] - last[0], p[1] - last[1]) < 2) return;
    s.pts = [...s.pts, p];
    strokePts.current.set(s.id, s.pts);
    setStrokes((prev) => prev.map((x) => (x.id === s.id ? { ...s } : x)));
  };
  const onPointerUp = () => {
    const s = drawing.current;
    drawing.current = null;
    if (!s) return;
    pendingStrokes.current.push(s.id);
    if (groupTimer.current) clearTimeout(groupTimer.current);
    groupTimer.current = setTimeout(() => void finishMark(), GROUP_MS);
  };

  const ask = (mark: Mark) => {
    setMarks((prev) => prev.map((m) => (m.id === mark.id ? { ...m, status: 'asked' } : m)));
    void sendMark(mark, true);
  };
  const dismiss = (mark: Mark) => {
    setMarks((prev) => prev.filter((m) => m.id !== mark.id));
    setStrokes((prev) => prev.filter((s) => s.mark !== mark.id));
  };
  const eraseAll = () => {
    // This page's ink only; other boards keep theirs.
    setStrokes((prev) => prev.filter((s) => s.page !== book.active));
    setMarks((prev) => prev.filter((m) => m.page !== book.active));
    pendingStrokes.current = [];
  };

  const pageStrokes = strokes.filter((s) => s.page === book.active);
  const pageMarks = marks.filter((m) => m.page === book.active);
  const empty = state.revealed === 0 && !state.planning;
  if (empty && fallback && strokes.length === 0 && book.order.length === 1 && research.length === 0)
    return <>{fallback}</>;

  return (
    <div className="flex h-full w-full flex-col xl:flex-row">
      <div
        className="relative flex min-h-0 min-w-0 flex-1 flex-col"
        style={{ background: INK.board }}
      >
        {/* header: lesson title + tools */}
        <div
          className="flex items-center gap-3 px-5 py-3"
          style={{ borderBottom: `1px solid ${INK.grid}` }}
        >
          <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto">
            {book.order.map((id, i) => {
              const pg = book.pages[id];
              const on = id === book.active;
              return (
                <button
                  key={id}
                  onClick={() => openPage(id)}
                  title={pg.title}
                  className="max-w-[180px] shrink-0 truncate rounded-xl px-3 py-1.5 text-[15px] transition"
                  style={{
                    fontFamily: 'var(--font-hand)',
                    fontWeight: on ? 700 : 400,
                    color: on ? INK.ink : INK.soft,
                    background: on ? '#FFFFFF' : 'transparent',
                    border: `1px solid ${on ? INK.faint : 'transparent'}`,
                  }}
                >
                  <span style={{ color: INK.teacher }}>{i + 1}</span>{' '}
                  {pg.planning && pg.revealed === 0 ? pg.planning : pg.title}
                </button>
              );
            })}
            <button
              onClick={newPage}
              title="New board — the old ones stay"
              aria-label="New board"
              className="flex size-8 shrink-0 items-center justify-center rounded-xl text-[18px] transition hover:brightness-95"
              style={{ color: INK.soft, border: `1px dashed ${INK.faint}` }}
            >
              +
            </button>
          </div>
          <Tools
            tool={tool}
            setTool={setTool}
            onErase={eraseAll}
            canErase={pageStrokes.length > 0}
          />
        </div>

        <div
          ref={scrollRef}
          className="relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
          style={{ touchAction: tool === 'hand' ? 'auto' : 'none' }}
        >
          <div className="relative" style={{ height: boardH * scale }}>
            <svg
              ref={svgRef}
              className="nova-board absolute inset-0 select-none"
              viewBox={`0 0 ${layout.width} ${boardH}`}
              width={viewW}
              height={boardH * scale}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              style={{ cursor: tool === 'hand' ? 'grab' : 'crosshair' }}
            >
              <GridPaper w={layout.width} h={boardH} />

              {/* Nova's highlights sit under the ink so text stays crisp */}
              <g>
                <AnimatePresence>
                  {state.annots
                    .filter((a) => a.kind === 'hl')
                    .map((a) => {
                      const r = a.kind === 'hl' ? targetRect(layout, a.target) : undefined;
                      if (!r || a.kind !== 'hl') return null;
                      return (
                        <motion.rect
                          key={a.id}
                          x={r.x - 6}
                          y={r.y - 3}
                          height={r.h + 6}
                          rx={6}
                          fill={a.color}
                          opacity={0.55}
                          initial={{ width: 0 }}
                          animate={{ width: r.w + 12 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.45, ease: 'easeOut' }}
                        />
                      );
                    })}
                </AnimatePresence>
              </g>

              {layout.steps.map((ps) => (
                <StepTitle key={ps.step.id} ps={ps} />
              ))}
              <MediaContext.Provider value={media}>
                {layout.els.map((pe) => (
                  <BoardElement key={pe.el.id} pe={pe} />
                ))}
              </MediaContext.Provider>

              {/* Nova's arrows */}
              {state.annots.map((a) =>
                a.kind === 'arrow' ? <TeacherArrow key={a.id} layout={layout} a={a} /> : null
              )}

              {/* student ink */}
              <g>
                {pageStrokes.map((s) => (
                  <path
                    key={s.id}
                    d={smoothPath(s.pts)}
                    fill="none"
                    stroke={s.tool === 'highlighter' ? INK.studentHi : INK.student}
                    strokeWidth={s.tool === 'highlighter' ? 18 : 3.4}
                    strokeOpacity={s.tool === 'highlighter' ? 0.4 : 0.95}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ))}
              </g>

              {/* Nova's marker pointing at what it is talking about */}
              <AnimatePresence>
                {pointerOn && pointerRect && (
                  <motion.g
                    data-snapshot-skip
                    key="pointer"
                    initial={{
                      opacity: 0,
                      x: pointerRect.x + pointerRect.w + 6,
                      y: pointerRect.y + pointerRect.h / 2,
                    }}
                    animate={{
                      opacity: 1,
                      x: pointerRect.x + pointerRect.w + 6,
                      y: pointerRect.y + pointerRect.h / 2,
                    }}
                    exit={{ opacity: 0 }}
                    transition={{ type: 'spring', stiffness: 120, damping: 18 }}
                  >
                    <g transform="rotate(-35)">
                      <rect x={4} y={-6} width={46} height={12} rx={4} fill={INK.teacher} />
                      <path d="M4,-6 L-8,0 L4,6 Z" fill={INK.teacher} />
                    </g>
                  </motion.g>
                )}
              </AnimatePresence>

              {state.planning && state.revealed === 0 && (
                <Planning w={layout.width} topic={state.planning} />
              )}
            </svg>

            {/* mark chips, in screen space over the board */}
            <AnimatePresence>
              {pageMarks.map((m) => (
                <MarkChip
                  key={m.id}
                  mark={m}
                  scale={scale}
                  maxX={viewW}
                  onAsk={() => ask(m)}
                  onDismiss={() => dismiss(m)}
                />
              ))}
            </AnimatePresence>
          </div>

          {empty && pageStrokes.length === 0 && <EmptyBoard />}
        </div>
      </div>
      {research.length > 0 && (
        <div className="h-72 shrink-0 xl:h-full xl:w-[330px]">
          <ResearchPanel items={research} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function GridPaper({ w, h }: { w: number; h: number }) {
  return (
    <>
      <defs>
        <pattern id="nova-grid" width={32} height={32} patternUnits="userSpaceOnUse">
          <path d="M32,0 L0,0 0,32" fill="none" stroke={INK.grid} strokeWidth={1} />
        </pattern>
      </defs>
      <rect x={0} y={0} width={w} height={h} fill={INK.board} />
      <rect x={0} y={0} width={w} height={h} fill="url(#nova-grid)" />
    </>
  );
}

function TeacherArrow({
  layout,
  a,
}: {
  layout: BoardLayout;
  a: Extract<Annot, { kind: 'arrow' }>;
}) {
  const r1 = targetRect(layout, a.from);
  const r2 = targetRect(layout, a.to);
  if (!r1 || !r2) return null;
  const c1 = { x: r1.x + r1.w / 2, y: r1.y + r1.h / 2 };
  const c2 = { x: r2.x + r2.w / 2, y: r2.y + r2.h / 2 };
  // Leave from / arrive at the rect edges rather than the centres.
  const edge = (r: Rect, from: { x: number; y: number }, to: { x: number; y: number }) => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const t = Math.min(
      Math.abs(dx) > 0.01 ? r.w / 2 / Math.abs(dx) : Infinity,
      Math.abs(dy) > 0.01 ? r.h / 2 / Math.abs(dy) : Infinity
    );
    return { x: from.x + dx * Math.min(1, t + 0.04), y: from.y + dy * Math.min(1, t + 0.04) };
  };
  const p1 = edge(r1, c1, c2);
  const p2 = edge(r2, c2, c1);
  const mx = (p1.x + p2.x) / 2 + (p2.y - p1.y) * 0.18;
  const my = (p1.y + p2.y) / 2 - (p2.x - p1.x) * 0.18;
  const ang = Math.atan2(p2.y - my, p2.x - mx);
  return (
    <g>
      <motion.path
        d={`M${p1.x},${p1.y} Q${mx},${my} ${p2.x},${p2.y}`}
        fill="none"
        stroke={INK.teacher}
        strokeWidth={2.6}
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6 }}
      />
      <motion.path
        d={arrowHead(p2.x, p2.y, ang, 12)}
        fill="none"
        stroke={INK.teacher}
        strokeWidth={2.6}
        strokeLinecap="round"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.55 }}
      />
      {a.label && (
        <motion.text
          x={mx}
          y={my - 8}
          textAnchor="middle"
          fontFamily={HAND}
          fontSize={19}
          fill={INK.teacher}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
        >
          {a.label}
        </motion.text>
      )}
    </g>
  );
}

function Planning({ w, topic }: { w: number; topic: string }) {
  const t = useT();
  return (
    <g data-snapshot-skip>
      <motion.path
        d={sketchCircle(w / 2, 150, 44, 44, topic)}
        fill="none"
        stroke={INK.teacher}
        strokeWidth={3}
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: [0, 1, 1], opacity: [1, 1, 0] }}
        transition={{ duration: 1.8, repeat: Infinity }}
      />
      <text x={w / 2} y={240} textAnchor="middle" fontFamily={HAND} fontSize={24} fill={INK.soft}>
        {t.preparing} {topic}
      </text>
    </g>
  );
}

function MarkChip({
  mark,
  scale,
  maxX,
  onAsk,
  onDismiss,
}: {
  mark: Mark;
  scale: number;
  maxX: number;
  onAsk: () => void;
  onDismiss: () => void;
}) {
  const t = useT();
  // Circling IS asking: after a short countdown the question goes by itself.
  // The student can ask straight away, or cancel with the cross.
  const [left_s, setLeftS] = useState(AUTO_ASK_S);
  const askRef = useRef(onAsk);
  askRef.current = onAsk;
  useEffect(() => {
    if (mark.status !== 'open') return;
    if (left_s <= 0) {
      askRef.current();
      return;
    }
    const id = setTimeout(() => setLeftS((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [left_s, mark.status]);
  const left = Math.min((mark.box.x + mark.box.w) * scale + 10, maxX - 250);
  const top = Math.max(4, mark.box.y * scale - 8);
  const what = mark.targets
    .map((t) => t.text)
    .filter(Boolean)
    .slice(0, 2)
    .join(' · ');
  return (
    <motion.div
      initial={{ opacity: 0, y: 6, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      className="absolute z-10 w-[240px] rounded-2xl px-3 py-2.5 shadow-lg"
      style={{ left, top, background: '#FFFFFF', border: `1px solid ${INK.grid}` }}
    >
      {mark.status === 'asked' ? (
        <div className="flex items-center gap-2">
          <motion.span
            className="size-2 rounded-full"
            style={{ background: INK.teacher }}
            animate={{ opacity: [1, 0.2, 1] }}
            transition={{ duration: 1.1, repeat: Infinity }}
          />
          <span className="text-[13px] font-semibold" style={{ color: INK.teacher }}>
            {t.looking}
          </span>
        </div>
      ) : (
        <>
          {what && (
            <p className="mb-2 truncate font-mono text-[11px]" style={{ color: INK.soft }}>
              {what}
            </p>
          )}
          <div className="flex gap-2">
            <button
              onClick={onAsk}
              className="flex-1 rounded-xl py-2 text-[13px] font-semibold text-white transition hover:brightness-105 active:scale-[0.98]"
              style={{ background: INK.teacher }}
            >
              {t.dontGet}
              {left_s > 0 ? ` (${left_s})` : ''}
            </button>
            <button
              onClick={onDismiss}
              aria-label="Remove mark"
              className="rounded-xl px-3 py-2 text-[13px] transition hover:brightness-95"
              style={{ background: INK.board, color: INK.soft, border: `1px solid ${INK.grid}` }}
            >
              ✕
            </button>
          </div>
        </>
      )}
    </motion.div>
  );
}

function Tools({
  tool,
  setTool,
  onErase,
  canErase,
}: {
  tool: Tool;
  setTool: (t: Tool) => void;
  onErase: () => void;
  canErase: boolean;
}) {
  const btn = (t: Tool, label: string, icon: React.ReactNode) => (
    <button
      key={t}
      onClick={() => setTool(t)}
      title={label}
      aria-label={label}
      aria-pressed={tool === t}
      className="flex size-9 items-center justify-center rounded-xl transition"
      style={{
        background: tool === t ? `${INK.student}1F` : 'transparent',
        color: tool === t ? INK.student : INK.soft,
        border: `1px solid ${tool === t ? `${INK.student}55` : INK.grid}`,
      }}
    >
      {icon}
    </button>
  );
  return (
    <div className="flex items-center gap-1.5">
      {btn(
        'pen',
        'Pen — circle or underline anything to ask about it',
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M4 20l4-1 11-11-3-3L5 16l-1 4z" strokeLinejoin="round" />
        </svg>
      )}
      {btn(
        'highlighter',
        'Highlighter',
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M9 15l-4 5h6l2-2M9 15l7-11 4 3-7 11-4-3z" strokeLinejoin="round" />
        </svg>
      )}
      {btn(
        'hand',
        'Scroll the board',
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path
            d="M8 13V5a1.5 1.5 0 013 0v6m0-1V4a1.5 1.5 0 013 0v7m0-5a1.5 1.5 0 013 0v7m0-4a1.5 1.5 0 013 0v5a7 7 0 01-7 7h-1a7 7 0 01-6-3l-3-5a1.5 1.5 0 012.5-1.6L8 15"
            strokeLinecap="round"
          />
        </svg>
      )}
      <button
        onClick={onErase}
        disabled={!canErase}
        title="Erase my marks"
        aria-label="Erase my marks"
        className="flex size-9 items-center justify-center rounded-xl transition disabled:opacity-35"
        style={{ color: INK.soft, border: `1px solid ${INK.grid}` }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M16 3l5 5-10 10H6l-3-3L16 3zM6 18h14" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );
}

function EmptyBoard() {
  const t = useT();
  return (
    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-8 text-center">
      <p className="text-[26px]" style={{ color: INK.ink, fontFamily: 'var(--font-hand)' }}>
        {t.boardEmptyTitle}
      </p>
      <p className="mt-2 max-w-[24rem] text-[14px] leading-relaxed" style={{ color: INK.soft }}>
        {t.boardEmptyBody}
      </p>
    </div>
  );
}

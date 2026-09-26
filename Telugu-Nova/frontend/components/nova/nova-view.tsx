'use client';

import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { ConnectionState, Track } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import {
  useAgent,
  useDataChannel,
  useMaybeRoomContext,
  useSessionContext,
  useSessionMessages,
  useTrackToggle,
  useTrackTranscription,
} from '@livekit/components-react';
import { Board } from '@/components/nova/board/board';
import { Canvas, type CanvasPayload } from '@/components/nova/canvas';
import {
  LANGS,
  type Lang,
  LangContext,
  readLangCookie,
  useT,
  writeLangCookie,
} from '@/components/nova/i18n';

/**
 * Day 3 frontend for Nova — a Computer Science companion for Telugu-speaking
 * students.
 *
 * Five screens, one per required state:
 *
 *   ready       -> one obvious button, nothing else competing with it
 *   connecting  -> explicit "wait", because the agent takes a moment to join
 *   live        -> who is speaking, right now, unmissable
 *   ended       -> what happened + an obvious way back in
 *   mic-error   -> what went wrong and exactly how to fix it
 *
 * Visual language: warm paper background, one soft card, muted earth tones.
 * A student uses this late at night when something is already going wrong, so
 * the interface stays quiet — no hard contrast, no glow, nothing shouting.
 */

type Screen = 'ready' | 'connecting' | 'live' | 'ended' | 'mic-error';

// Comfort palette — muted, warm, low-contrast.
const C = {
  paper: '#F6F1E9',
  card: '#FFFDFA',
  ink: '#4A4038',
  inkSoft: '#8C8177',
  line: '#E8DFD2',
  clay: '#C4704F', // primary action
  sage: '#6F9E82', // listening
  sky: '#5B7FA6', // speaking
  amber: '#C89B4A', // thinking
  rose: '#B5695F', // end / error
};

/**
 * Day 9: each agent gets its own skin, not just its own accent colour.
 *
 * The paper, the card, the panel edge and the bar colours all shift together,
 * so a handoff is unmistakable even with the sound off. Every palette stays
 * inside the same warm, low-contrast family — this should feel like the same
 * product handing you to a colleague, not four different apps.
 */
type AgentTheme = {
  paper: string;
  card: string;
  edge: string;
  accent: string;
  bubble: string;
};

const THEMES: Record<string, AgentTheme> = {
  // Nova — warm terracotta on cream. The home state.
  nova: {
    paper: '#F6F1E9',
    card: '#FFFDFA',
    edge: '#E8DFD2',
    accent: '#C4704F',
    bubble: '#EFE7DA',
  },
  // Algo — cooler, bluer paper. Sharper, more technical.
  algo: {
    paper: '#EEF2F6',
    card: '#FBFDFF',
    edge: '#D8E2EC',
    accent: '#5B7FA6',
    bubble: '#DFE8F1',
  },
  // Keerthi — green, softest of the four. You are already stressed.
  keerthi: {
    paper: '#EEF4EF',
    card: '#FBFDFB',
    edge: '#D7E5DB',
    accent: '#6F9E82',
    bubble: '#DEEBE2',
  },
  // Vikram — amber, a shade more formal. Interview room.
  vikram: {
    paper: '#F7F2E6',
    card: '#FFFDF7',
    edge: '#EADFC6',
    accent: '#B98A32',
    bubble: '#F0E5CE',
  },
};

const themeFor = (id: string) => THEMES[id] ?? THEMES.nova;

const AGENT_NAME: Record<string, string> = {
  nova: 'Nova',
  algo: 'Algo',
  keerthi: 'Keerthi',
  vikram: 'Vikram',
};

// ---------------------------------------------------------------------------
// Microphone permission
// ---------------------------------------------------------------------------

type MicError = 'denied' | 'notfound' | 'other';

/** Ask for the mic BEFORE connecting, so a refusal is a clean screen and not a
 *  half-joined call the student has to figure out. */
async function requestMic(): Promise<MicError | null> {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices) return 'other';
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop()); // LiveKit opens its own track
    return null;
  } catch (err) {
    const name = (err as DOMException)?.name;
    if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied';
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'notfound';
    return 'other';
  }
}

// ---------------------------------------------------------------------------
// Shared chrome
// ---------------------------------------------------------------------------

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex min-h-svh w-full items-center justify-center px-5 py-10"
      style={{ background: C.paper }}
    >
      <div
        className="w-full max-w-md rounded-3xl px-9 py-12"
        style={{
          background: C.card,
          border: `1px solid ${C.line}`,
          boxShadow: '0 1px 2px rgba(74,64,56,0.04), 0 12px 32px rgba(74,64,56,0.07)',
        }}
      >
        <div className="flex flex-col items-center">{children}</div>
      </div>
    </div>
  );
}

function Mark({ tint = C.clay, pulse = false }: { tint?: string; pulse?: boolean }) {
  return (
    <div className="relative mb-6 flex size-16 items-center justify-center">
      {pulse && (
        <motion.span
          className="absolute inset-0 rounded-full"
          style={{ background: tint, opacity: 0.16 }}
          animate={{ scale: [1, 1.35, 1], opacity: [0.18, 0.04, 0.18] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}
      <div
        className="relative flex size-16 items-center justify-center rounded-full font-mono text-xl font-semibold"
        style={{ background: `${tint}1A`, color: tint }}
      >
        AA
      </div>
    </div>
  );
}

/** Soft rounded bars. Calm when idle, lively when the agent speaks. */
function Bars({ tint, active }: { tint: string; active: boolean }) {
  const heights = [16, 30, 42, 30, 16];
  return (
    <div className="flex h-14 items-center justify-center gap-2">
      {heights.map((h, i) => (
        <motion.span
          key={i}
          className="w-2.5 rounded-full"
          style={{ background: tint, opacity: active ? 0.9 : 0.28 }}
          animate={
            active ? { height: [h * 0.45, h, h * 0.55, h * 0.9, h * 0.45] } : { height: h * 0.4 }
          }
          transition={
            active
              ? { duration: 1.1, repeat: Infinity, delay: i * 0.09, ease: 'easeInOut' }
              : { duration: 0.4 }
          }
        />
      ))}
    </div>
  );
}

function PrimaryButton({
  children,
  onClick,
  tint = C.clay,
}: {
  children: React.ReactNode;
  onClick: () => void;
  tint?: string;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full rounded-2xl py-4 text-[17px] font-semibold text-white transition hover:brightness-[1.06] active:scale-[0.985]"
      style={{ background: tint, boxShadow: `0 6px 16px ${tint}33` }}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// 1. READY
// ---------------------------------------------------------------------------

function ReadyScreen({ onStart }: { onStart: () => void }) {
  const t = useT();
  return (
    <Shell>
      <Mark />
      <p className="font-mono text-[10px] tracking-[0.22em] uppercase" style={{ color: C.inkSoft }}>
        {t.tagline}
      </p>
      <h1 className="mt-2.5 text-[32px] font-bold" style={{ color: C.ink }}>
        Agent Acharya
      </h1>
      <p
        className="mt-3 mb-9 max-w-[18rem] text-center text-[15px] leading-relaxed"
        style={{ color: C.inkSoft }}
      >
        {t.readyBody}
      </p>

      <div className="mb-4 w-full">
        <LanguagePicker />
      </div>
      <PrimaryButton onClick={onStart}>{t.start}</PrimaryButton>

      <p className="mt-4 text-[12px]" style={{ color: C.inkSoft }}>
        {t.micNote}
      </p>
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// 2. CONNECTING
// ---------------------------------------------------------------------------

function ConnectingScreen() {
  const t = useT();
  return (
    <Shell>
      <Mark pulse />
      <h2 className="text-[22px] font-bold" style={{ color: C.ink }}>
        {t.connecting}
      </h2>
      <p className="mt-2 text-center text-[15px]" style={{ color: C.inkSoft }}>
        {t.connectingBody}
      </p>
      <div className="mt-7 flex gap-2" aria-hidden>
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="size-2 rounded-full"
            style={{ background: C.clay }}
            animate={{ opacity: [0.2, 1, 0.2] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
          />
        ))}
      </div>
      <p
        className="mt-7 font-mono text-[10px] tracking-[0.22em] uppercase"
        style={{ color: C.inkSoft }}
      >
        connecting
      </p>
    </Shell>
  );
}

type Line = { id: string; mine: boolean; text: string; at: number };

// ---------------------------------------------------------------------------
// Chat history — kept in this browser across classes
// ---------------------------------------------------------------------------

type Saved = Line & { who: string };
const HISTORY_KEY = 'aa_chat_history';

function loadHistory(): Saved[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as Saved[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(items: Saved[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(-400)));
  } catch {
    /* storage full or blocked: history is a convenience, not a requirement */
  }
}

function HistoryLine({ line, dim }: { line: Saved; dim?: boolean }) {
  return (
    <div className={line.mine ? 'text-right' : 'text-left'} style={{ opacity: dim ? 0.6 : 1 }}>
      <span
        className="mb-1 block font-mono text-[9px] tracking-[0.14em] uppercase"
        style={{ color: C.inkSoft }}
      >
        {line.who}
      </span>
      <span
        className="inline-block max-w-[88%] rounded-xl px-3 py-1.5 text-[14px] leading-relaxed"
        style={{ background: line.mine ? C.line : `${C.clay}1A`, color: C.ink }}
      >
        {line.text}
      </span>
    </div>
  );
}

/** Collapse repeats of the same speaker saying the same thing.
 *  Interim and final segments can arrive under different ids. */
function dedupe(lines: Line[]): Line[] {
  const seen = new Set<string>();
  const out: Line[] = [];
  for (const line of lines) {
    const key = `${line.mine}:${line.text.trim()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(line);
  }
  return out;
}

// ---------------------------------------------------------------------------
// 3. LIVE — listening / thinking / speaking
// ---------------------------------------------------------------------------

const STATUS: Record<
  string,
  { key: 'listening' | 'thinking' | 'speaking'; en: string; tint: string }
> = {
  listening: { key: 'listening', en: 'listening to you', tint: C.sage },
  thinking: { key: 'thinking', en: 'thinking', tint: C.amber },
  speaking: { key: 'speaking', en: 'agent is speaking', tint: C.sky },
};

function LiveScreen({
  onEnd,
  canvas,
  agent: who,
  handoffs,
}: {
  onEnd: () => void;
  canvas: CanvasPayload[];
  agent: { id: string; name: string; role: string; tint: string; lang: string };
  handoffs: { id: string; from: string; to: string; reason: string; at: number }[];
}) {
  const agent = useAgent();
  const session = useSessionContext();
  const tr = useT();

  // Transcripts come straight off the audio tracks. useSessionMessages only
  // carries typed chat, so on a voice-only call it stays empty — reading the
  // tracks is what actually produces a live transcript.
  const agentTrack = agent.isConnected ? agent.microphoneTrack : undefined;
  const localTrack = session.isConnected ? session.local.microphoneTrack : undefined;
  const { segments: agentSegments } = useTrackTranscription(agentTrack);
  const { segments: userSegments } = useTrackTranscription(localTrack);

  // Track segments are the only source. Session messages are NOT merged in:
  // with text_output enabled the agent publishes each utterance as a message
  // as well, so including both prints every line twice.
  const lines = dedupe(
    [
      ...userSegments.map((sg) => ({
        id: `u-${sg.id}`,
        mine: true,
        text: sg.text,
        at: sg.firstReceivedTime,
      })),
      ...agentSegments.map((sg) => ({
        id: `a-${sg.id}`,
        mine: false,
        text: sg.text,
        at: sg.firstReceivedTime,
      })),
    ]
      .filter((l) => l.text?.trim())
      .sort((a, b) => a.at - b.at)
  );
  // Earlier classes, loaded once; this class is appended as it happens.
  const [earlier] = useState<Saved[]>(() => loadHistory());
  useEffect(() => {
    if (!lines.length) return;
    saveHistory([...earlier, ...lines.map((l) => ({ ...l, who: l.mine ? tr.you : who.name }))]);
  }, [lines, earlier, tr.you, who.name]);

  const { toggle: toggleMic, enabled: micOn } = useTrackToggle({
    source: Track.Source.Microphone,
  });

  const state = agent.state === 'connecting' ? 'thinking' : agent.state;
  const status = STATUS[state] ?? STATUS.thinking;

  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [lines.length]);

  const t = themeFor(who.id);

  // Handoffs sit inside the transcript, in sequence, so the student can see
  // exactly where the conversation changed hands and why.
  const feed = [
    ...lines.map((l) => ({ kind: 'line' as const, at: l.at, line: l })),
    ...handoffs.map((h) => ({ kind: 'handoff' as const, at: h.at, handoff: h })),
  ].sort((a, b) => a.at - b.at);

  return (
    <motion.div
      className="flex h-svh w-full flex-col lg:flex-row"
      animate={{ backgroundColor: t.paper }}
      transition={{ duration: 0.5 }}
    >
      {/* LEFT — the conversation */}
      <motion.aside
        className="flex w-full shrink-0 flex-col px-6 py-6 lg:h-svh lg:w-[380px]"
        animate={{ backgroundColor: t.card, borderRightColor: t.edge }}
        transition={{ duration: 0.5 }}
        style={{ borderRightWidth: 1, borderRightStyle: 'solid' }}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={who.id}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 10 }}
            transition={{ duration: 0.25 }}
            className="flex items-center gap-3"
          >
            <div
              className="flex size-10 items-center justify-center rounded-xl font-mono text-sm font-semibold"
              style={{ background: `${who.tint}1F`, color: who.tint }}
            >
              AA
            </div>
            <div className="flex-1">
              <p className="text-[16px] font-bold" style={{ color: C.ink }}>
                {who.name}
              </p>
              <p
                className="font-mono text-[10px] tracking-[0.16em] uppercase"
                style={{ color: who.tint }}
              >
                {who.role}
              </p>
            </div>
            {who.id !== 'nova' && (
              <span
                className="rounded-full px-2.5 py-1 text-[11px] font-semibold"
                style={{ background: `${who.tint}1F`, color: who.tint }}
              >
                {who.lang}
              </span>
            )}
          </motion.div>
        </AnimatePresence>

        <div className="mt-4">
          <LanguagePicker />
        </div>

        {/* who is speaking */}
        <div className="mt-6 flex flex-col items-center">
          <div
            className="flex items-center gap-2.5 rounded-full px-4 py-2"
            style={{ background: `${status.tint}18` }}
          >
            <motion.span
              className="size-2 rounded-full"
              style={{ background: status.tint }}
              animate={{ opacity: [1, 0.25, 1] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            />
            <span className="text-[14px] font-semibold" style={{ color: status.tint }}>
              {tr[status.key]}
            </span>
          </div>
          <p
            className="mt-2 font-mono text-[10px] tracking-[0.18em] uppercase"
            style={{ color: C.inkSoft }}
          >
            {status.en}
          </p>
          <div className="mt-3">
            <Bars
              tint={state === 'thinking' ? t.accent : status.tint}
              active={state === 'speaking' || state === 'listening'}
            />
          </div>
        </div>

        {/* live transcript */}
        <div
          ref={scrollRef}
          className="mt-4 min-h-0 flex-1 overflow-y-auto rounded-2xl p-3.5"
          style={{ background: t.paper, border: `1px solid ${t.edge}` }}
        >
          {earlier.length > 0 && (
            <div className="mb-3 flex flex-col gap-2.5">
              <p
                className="text-center font-mono text-[10px] tracking-[0.18em] uppercase"
                style={{ color: C.inkSoft }}
              >
                {tr.earlier}
              </p>
              {earlier.slice(-60).map((l) => (
                <HistoryLine key={`h-${l.id}-${l.at}`} line={l} dim />
              ))}
              <p
                className="mt-1 text-center font-mono text-[10px] tracking-[0.18em] uppercase"
                style={{ color: C.inkSoft }}
              >
                {tr.thisClass}
              </p>
            </div>
          )}
          {feed.length === 0 ? (
            <p className="pt-10 text-center text-[13px]" style={{ color: C.inkSoft }}>
              {tr.transcriptEmpty}
            </p>
          ) : (
            <div className="flex flex-col gap-2.5">
              {lines.map((line) => {
                const mine = line.mine;
                return (
                  <div key={line.id} className={mine ? 'text-right' : 'text-left'}>
                    <span
                      className="mb-1 block font-mono text-[9px] tracking-[0.14em] uppercase"
                      style={{ color: C.inkSoft }}
                    >
                      {mine ? tr.you : who.name}
                    </span>
                    <span
                      className="inline-block max-w-[88%] rounded-xl px-3 py-1.5 text-[14px] leading-relaxed"
                      style={
                        mine
                          ? { background: t.bubble, color: C.ink }
                          : { background: `${t.accent}1F`, color: C.ink }
                      }
                    >
                      {line.text}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="mt-4 flex w-full gap-3">
          <button
            onClick={() => toggleMic()}
            className="flex-1 rounded-2xl py-3.5 text-[14px] font-semibold transition hover:brightness-[0.98]"
            style={{ background: t.paper, border: `1px solid ${t.edge}`, color: C.ink }}
          >
            {micOn ? tr.micOff : tr.micOn}
          </button>
          <button
            onClick={onEnd}
            className="flex-1 rounded-2xl py-3.5 text-[14px] font-semibold text-white transition hover:brightness-[1.06]"
            style={{ background: C.rose }}
          >
            {tr.endCall}
          </button>
        </div>
      </motion.aside>

      {/* RIGHT — the shared whiteboard. The older card canvas only shows when
          the cascade pipeline pushed cards and nothing has been drawn. */}
      <section className="min-h-[60svh] flex-1 lg:min-h-0">
        <Board fallback={canvas.length ? <Canvas items={canvas} /> : undefined} />
      </section>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// 4. CALL ENDED
// ---------------------------------------------------------------------------

function EndedScreen({ turns, onRestart }: { turns: number; onRestart: () => void }) {
  const t = useT();
  const [history, setHistory] = useState<Saved[]>([]);
  useEffect(() => setHistory(loadHistory()), []);
  return (
    <Shell>
      <Mark tint={C.sage} />
      <h2 className="text-[22px] font-bold" style={{ color: C.ink }}>
        {t.ended}
      </h2>
      <p className="mt-2 mb-8 text-center text-[15px]" style={{ color: C.inkSoft }}>
        {turns > 0 ? t.endedTurns(turns) : t.endedNone}
      </p>
      <PrimaryButton onClick={onRestart}>{t.again}</PrimaryButton>
      {history.length > 0 && (
        <div className="mt-6 w-full">
          <div className="mb-2 flex items-center justify-between">
            <p
              className="font-mono text-[10px] tracking-[0.18em] uppercase"
              style={{ color: C.inkSoft }}
            >
              {t.history}
            </p>
            <button
              onClick={() => {
                saveHistory([]);
                setHistory([]);
              }}
              className="text-[12px] underline"
              style={{ color: C.inkSoft }}
            >
              {t.clearHistory}
            </button>
          </div>
          <div
            className="flex max-h-72 flex-col gap-2.5 overflow-y-auto rounded-2xl p-3"
            style={{ background: C.paper, border: `1px solid ${C.line}` }}
          >
            {history.slice(-80).map((l) => (
              <HistoryLine key={`e-${l.id}-${l.at}`} line={l} />
            ))}
          </div>
        </div>
      )}
      <p
        className="mt-6 font-mono text-[10px] tracking-[0.22em] uppercase"
        style={{ color: C.inkSoft }}
      >
        call ended
      </p>
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// 5. MIC PERMISSION ERROR
// ---------------------------------------------------------------------------

const MIC_COPY: Record<MicError, { title: string; body: string; how: string[] }> = {
  denied: {
    title: 'Microphone is blocked',
    body: 'The browser is not allowing the microphone. Nova needs it to hear you.',
    how: ['Click the lock icon in the address bar', 'Set Microphone to Allow', 'Reload this page'],
  },
  notfound: {
    title: 'No microphone found',
    body: 'This device does not seem to have a microphone.',
    how: ['Connect a headset or mic', 'Check the input device in system settings', 'Reload'],
  },
  other: {
    title: 'Could not open the microphone',
    body: 'Another app may be using it.',
    how: ['Close Meet / Zoom and similar apps', 'Reload the browser', 'Try again'],
  },
};

function MicErrorScreen({ kind, onRetry }: { kind: MicError; onRetry: () => void }) {
  const copy = MIC_COPY[kind];
  return (
    <Shell>
      <div
        className="mb-5 flex size-14 items-center justify-center rounded-full text-2xl"
        style={{ background: `${C.rose}1A` }}
      >
        🎤
      </div>
      <h2 className="text-center text-[21px] font-bold" style={{ color: C.rose }}>
        {copy.title}
      </h2>
      <p
        className="mt-2 max-w-[16rem] text-center text-[14px] leading-relaxed"
        style={{ color: C.inkSoft }}
      >
        {copy.body}
      </p>

      <div
        className="mt-6 w-full rounded-2xl p-4"
        style={{ background: C.paper, border: `1px solid ${C.line}` }}
      >
        <p
          className="mb-3 font-mono text-[10px] tracking-[0.18em] uppercase"
          style={{ color: C.inkSoft }}
        >
          How to fix
        </p>
        <ol className="flex flex-col gap-2.5">
          {copy.how.map((step, i) => (
            <li key={i} className="flex gap-3 text-[14px]" style={{ color: C.ink }}>
              <span
                className="flex size-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px] font-bold text-white"
                style={{ background: C.clay }}
              >
                {i + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
      </div>

      <div className="mt-6 w-full">
        <PrimaryButton onClick={onRetry}>Try again</PrimaryButton>
      </div>
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

const FADE = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
  transition: { duration: 0.26 },
};

/** Language dropdown. Changing it re-labels the UI and tells the teacher to switch. */
function LanguagePicker() {
  const { lang, setLang } = useContext(LangContext);
  const t = useT();
  return (
    <label className="flex w-full items-center gap-2 text-[12px]" style={{ color: C.inkSoft }}>
      <span className="font-mono tracking-[0.14em] uppercase">{t.language}</span>
      <select
        value={lang}
        onChange={(e) => setLang(e.target.value as Lang)}
        className="flex-1 rounded-xl px-3 py-2 text-[14px] font-semibold outline-none"
        style={{ background: C.paper, border: `1px solid ${C.line}`, color: C.ink }}
      >
        {LANGS.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function NovaView() {
  const [lang, setLangState] = useState<Lang>('en');
  const room = useMaybeRoomContext();
  useEffect(() => setLangState(readLangCookie()), []);
  const setLang = useCallback(
    (l: Lang) => {
      setLangState(l);
      writeLangCookie(l);
      // Mid-class switch: tell whoever is teaching to change language now.
      room?.localParticipant
        .sendText(JSON.stringify({ type: 'language', lang: l }), { topic: 'nova-board-student' })
        .catch(() => {});
    },
    [room]
  );
  return (
    <LangContext.Provider value={{ lang, setLang }}>
      <NovaViewInner />
    </LangContext.Provider>
  );
}

function NovaViewInner() {
  const session = useSessionContext();
  const { connectionState, isConnected, start, end } = session;
  const { messages } = useSessionMessages(session);

  const [micError, setMicError] = useState<MicError | null>(null);
  const [hasEnded, setHasEnded] = useState(false);
  const [turns, setTurns] = useState(0);
  const [canvas, setCanvas] = useState<CanvasPayload[]>([]);
  // Day 9: which agent currently holds the conversation. The backend pushes an
  // 'agent' frame on every handoff, so the UI changes with the voice.
  const [handoffs, setHandoffs] = useState<
    { id: string; from: string; to: string; reason: string; at: number }[]
  >([]);
  const [agentId, setAgentId] = useState<{
    id: string;
    name: string;
    role: string;
    tint: string;
    lang: string;
  }>({ id: 'nova', name: 'Acharya', role: 'Teacher', tint: C.clay, lang: 'English' });
  const wasConnected = useRef(false);

  // The agent pushes code and flowcharts here over the data channel while it
  // talks. Anything unparseable is dropped rather than crashing the view.
  useDataChannel('nova-canvas', (msg) => {
    try {
      const payload = JSON.parse(new TextDecoder().decode(msg.payload)) as CanvasPayload;
      if (payload.kind === 'agent') {
        // Record why the conversation moved, so the student can see it rather
        // than wondering why a different voice is suddenly talking.
        if (payload.from && payload.from !== payload.id) {
          setHandoffs((prev) => [
            ...prev,
            {
              id: `${payload.from}-${payload.id}-${prev.length}`,
              from: payload.from!,
              to: payload.id,
              reason: payload.reason ?? '',
              at: Date.now(),
            },
          ]);
        }
        setAgentId({
          id: payload.id,
          name: payload.name,
          role: payload.role,
          tint: payload.tint,
          lang: payload.lang,
        });
        return;
      }
      // Cards accumulate so a flowchart and its code stay on screen together.
      setCanvas((prev) => (payload.kind === 'clear' ? [] : [...prev, payload]));
    } catch {
      /* ignore malformed frames */
    }
  });

  // Remember the transcript length before teardown — messages are cleared on
  // disconnect, so the ended screen would otherwise always read zero.
  useEffect(() => {
    if (isConnected) {
      wasConnected.current = true;
      setTurns(messages.length);
    } else if (wasConnected.current) {
      wasConnected.current = false;
      setHasEnded(true);
    }
  }, [isConnected, messages.length]);

  const handleStart = useCallback(async () => {
    setMicError(null);
    const err = await requestMic();
    if (err) {
      setMicError(err);
      return;
    }
    setHasEnded(false);
    setCanvas([]);
    setHandoffs([]);
    setAgentId({
      id: 'nova',
      name: 'Acharya',
      role: 'Teacher',
      tint: C.clay,
      lang: 'English',
    });
    await start();
  }, [start]);

  const handleEnd = useCallback(async () => {
    await end();
  }, [end]);

  let screen: Screen = 'ready';
  if (micError) screen = 'mic-error';
  else if (isConnected) screen = 'live';
  else if (connectionState === ConnectionState.Connecting) screen = 'connecting';
  else if (hasEnded) screen = 'ended';

  return (
    <AnimatePresence mode="wait">
      <motion.div key={screen} {...FADE}>
        {screen === 'ready' && <ReadyScreen onStart={handleStart} />}
        {screen === 'connecting' && <ConnectingScreen />}
        {screen === 'live' && (
          <LiveScreen onEnd={handleEnd} canvas={canvas} agent={agentId} handoffs={handoffs} />
        )}
        {screen === 'ended' && <EndedScreen turns={turns} onRestart={handleStart} />}
        {screen === 'mic-error' && <MicErrorScreen kind={micError!} onRetry={handleStart} />}
      </motion.div>
    </AnimatePresence>
  );
}

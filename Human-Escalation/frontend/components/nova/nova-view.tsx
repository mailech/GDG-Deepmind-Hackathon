'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ConnectionState, Track } from 'livekit-client';
import { AnimatePresence, motion } from 'motion/react';
import {
  useAgent,
  useDataChannel,
  useSessionContext,
  useSessionMessages,
  useTrackToggle,
  useTrackTranscription,
} from '@livekit/components-react';
import { Canvas, type CanvasPayload } from '@/components/nova/canvas';

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
        {'{ }'}
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
  return (
    <Shell>
      <Mark />
      <p className="font-mono text-[10px] tracking-[0.22em] uppercase" style={{ color: C.inkSoft }}>
        Computer Science
      </p>
      <h1 className="mt-2.5 text-[32px] font-bold" style={{ color: C.ink }}>
        నోవా
      </h1>
      <p
        className="mt-3 mb-9 max-w-[15rem] text-center text-[15px] leading-relaxed"
        style={{ color: C.inkSoft }}
      >
        కోడ్ దగ్గర ఆగిపోయినవా? అడుగు — coding, DSA, OS, ఏదైనా.
      </p>

      <PrimaryButton onClick={onStart}>మాట్లాడదాం</PrimaryButton>

      <p className="mt-4 text-[12px]" style={{ color: C.inkSoft }}>
        మైక్ అనుమతి అడుగుతుంది
      </p>
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// 2. CONNECTING
// ---------------------------------------------------------------------------

function ConnectingScreen() {
  return (
    <Shell>
      <Mark pulse />
      <h2 className="text-[22px] font-bold" style={{ color: C.ink }}>
        కలుపుతున్నా…
      </h2>
      <p className="mt-2 text-center text-[15px]" style={{ color: C.inkSoft }}>
        ఒక్క సెకను ఆగు రా. నోవా వస్తుంది.
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

const STATUS: Record<string, { te: string; en: string; tint: string }> = {
  listening: { te: 'నేను వింటున్నా', en: 'listening to you', tint: C.sage },
  thinking: { te: 'ఆలోచిస్తున్నా…', en: 'thinking', tint: C.amber },
  speaking: { te: 'నోవా మాట్లాడుతుంది', en: 'agent is speaking', tint: C.sky },
};

function LiveScreen({ onEnd, canvas }: { onEnd: () => void; canvas: CanvasPayload[] }) {
  const agent = useAgent();
  const session = useSessionContext();

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
  const { toggle: toggleMic, enabled: micOn } = useTrackToggle({
    source: Track.Source.Microphone,
  });

  const state = agent.state === 'connecting' ? 'thinking' : agent.state;
  const status = STATUS[state] ?? STATUS.thinking;

  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [lines.length]);

  return (
    <div className="flex h-svh w-full flex-col lg:flex-row" style={{ background: C.paper }}>
      {/* LEFT — the conversation */}
      <aside
        className="flex w-full shrink-0 flex-col px-6 py-6 lg:h-svh lg:w-[380px]"
        style={{ borderRight: `1px solid ${C.line}`, background: C.card }}
      >
        <div className="flex items-center gap-3">
          <div
            className="flex size-10 items-center justify-center rounded-xl font-mono text-sm font-semibold"
            style={{ background: `${C.clay}1A`, color: C.clay }}
          >
            {'{ }'}
          </div>
          <div>
            <p className="text-[16px] font-bold" style={{ color: C.ink }}>
              నోవా
            </p>
            <p
              className="font-mono text-[10px] tracking-[0.16em] uppercase"
              style={{ color: C.inkSoft }}
            >
              Computer Science
            </p>
          </div>
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
              {status.te}
            </span>
          </div>
          <p
            className="mt-2 font-mono text-[10px] tracking-[0.18em] uppercase"
            style={{ color: C.inkSoft }}
          >
            {status.en}
          </p>
          <div className="mt-3">
            <Bars tint={status.tint} active={state === 'speaking' || state === 'listening'} />
          </div>
        </div>

        {/* live transcript */}
        <div
          ref={scrollRef}
          className="mt-4 min-h-0 flex-1 overflow-y-auto rounded-2xl p-3.5"
          style={{ background: C.paper, border: `1px solid ${C.line}` }}
        >
          {lines.length === 0 ? (
            <p className="pt-10 text-center text-[13px]" style={{ color: C.inkSoft }}>
              మాట్లాడు — ఇక్కడ కనిపిస్తుంది
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
                      {mine ? 'నువ్వు' : 'నోవా'}
                    </span>
                    <span
                      className="inline-block max-w-[88%] rounded-xl px-3 py-1.5 text-[14px] leading-relaxed"
                      style={
                        mine
                          ? { background: '#EFE7DA', color: C.ink }
                          : { background: `${C.sky}1A`, color: C.ink }
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
            style={{ background: C.paper, border: `1px solid ${C.line}`, color: C.ink }}
          >
            {micOn ? 'మైక్ ఆఫ్' : 'మైక్ ఆన్'}
          </button>
          <button
            onClick={onEnd}
            className="flex-1 rounded-2xl py-3.5 text-[14px] font-semibold text-white transition hover:brightness-[1.06]"
            style={{ background: C.rose }}
          >
            కాల్ ఆపు
          </button>
        </div>
      </aside>

      {/* RIGHT — code + flowcharts */}
      <section className="min-h-0 flex-1">
        <Canvas items={canvas} />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 4. CALL ENDED
// ---------------------------------------------------------------------------

function EndedScreen({ turns, onRestart }: { turns: number; onRestart: () => void }) {
  return (
    <Shell>
      <Mark tint={C.sage} />
      <h2 className="text-[22px] font-bold" style={{ color: C.ink }}>
        కాల్ అయిపోయింది
      </h2>
      <p className="mt-2 mb-8 text-center text-[15px]" style={{ color: C.inkSoft }}>
        {turns > 0 ? `${turns} సార్లు మాట్లాడుకున్నాం. మళ్ళీ రా!` : 'మళ్ళీ ఎప్పుడైనా రా రా.'}
      </p>
      <PrimaryButton onClick={onRestart}>మళ్ళీ మాట్లాడదాం</PrimaryButton>
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
    title: 'మైక్ ఆఫ్‌లో ఉంది',
    body: 'బ్రౌజర్ మైక్ వాడనివ్వట్లేదు. నోవా నిన్ను వినాలంటే మైక్ కావాలి.',
    how: [
      'Address bar లో ఎడమవైపు lock icon నొక్కు',
      'Microphone → Allow అని పెట్టు',
      'ఈ page ని reload చెయ్యి',
    ],
  },
  notfound: {
    title: 'మైక్ దొరకలేదు',
    body: 'ఈ device లో microphone కనిపించట్లేదు.',
    how: [
      'Headset లేదా mic connect చెయ్యి',
      'System settings లో input device చూడు',
      'Reload చెయ్యి',
    ],
  },
  other: {
    title: 'మైక్ ఓపెన్ కాలేదు',
    body: 'మైక్ వాడటానికి కుదర్లేదు. వేరే app వాడుతుందేమో చూడు.',
    how: ['Meet / Zoom లాంటివి close చెయ్యి', 'Browser reload చెయ్యి', 'మళ్ళీ try చెయ్యి'],
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
          ఇలా సరిచెయ్యి
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
        <PrimaryButton onClick={onRetry}>మళ్ళీ try చెయ్యి</PrimaryButton>
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

export function NovaView() {
  const session = useSessionContext();
  const { connectionState, isConnected, start, end } = session;
  const { messages } = useSessionMessages(session);

  const [micError, setMicError] = useState<MicError | null>(null);
  const [hasEnded, setHasEnded] = useState(false);
  const [turns, setTurns] = useState(0);
  const [canvas, setCanvas] = useState<CanvasPayload[]>([]);
  const wasConnected = useRef(false);

  // The agent pushes code and flowcharts here over the data channel while it
  // talks. Anything unparseable is dropped rather than crashing the view.
  useDataChannel('nova-canvas', (msg) => {
    try {
      const payload = JSON.parse(new TextDecoder().decode(msg.payload)) as CanvasPayload;
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
        {screen === 'live' && <LiveScreen onEnd={handleEnd} canvas={canvas} />}
        {screen === 'ended' && <EndedScreen turns={turns} onRestart={handleStart} />}
        {screen === 'mic-error' && <MicErrorScreen kind={micError!} onRetry={handleStart} />}
      </motion.div>
    </AnimatePresence>
  );
}

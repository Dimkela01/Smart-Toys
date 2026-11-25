'use client';

/**
 * The voice loop as one hook (ARCHITECTURE.md §6.1, F-05, UC-11, UC-22).
 *
 * Press the paw -> microphone frames go up the socket. Release -> the server answers
 * with sentences of audio, which play in order while the character speaks. Press again
 * while it is talking and the answer stops within a frame or two (barge-in, §6.1): the
 * client silences playback itself rather than waiting for the server to confirm, because
 * the child's own voice is the only thing that should be heard after they press.
 *
 * Nothing here can put text on the screen. A failure arrives as a code and is answered
 * with one of Bruno's recorded lines (NFR-09).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { CharacterState } from '@/components/Character';
import { Microphone, isRecordingPossible, type Frame } from '@/lib/audio/capture';
import { FallbackVoice } from '@/lib/audio/fallback';
import { Player } from '@/lib/audio/player';
import { TurnSocket, type ServerState } from '@/lib/audio/turnSocket';

/** §6.1: one press may not run longer than this. */
const MAX_PRESS_MS = 15_000;

/** UI.md §3.3 state names; the server sends a subset. */
const FROM_SERVER: Record<ServerState, CharacterState> = {
  listening: 'listening',
  thinking: 'thinking',
  speaking: 'speaking',
  idle: 'idle',
  sleeping: 'sleeping',
};

export type Voice = {
  /** What the character should be doing. */
  state: CharacterState;
  /** Microphone RMS while held, for the ring around the paw. */
  inputLevel: number;
  /** Output RMS while speaking, for the mouth. */
  mouth: number;
  /** False when the microphone cannot work here at all (no secure context). */
  possible: boolean;
  connected: boolean;
  pressDown: () => void;
  pressUp: () => void;
};

export function useVoice(token: string | null, language: string): Voice {
  const [state, setState] = useState<CharacterState>('sleeping');
  const [inputLevel, setInputLevel] = useState(0);
  const [mouth, setMouth] = useState(0);
  const [connected, setConnected] = useState(false);

  const mic = useRef<Microphone | null>(null);
  const player = useRef<Player>(new Player());
  const socket = useRef<TurnSocket | null>(null);
  const voice = useRef<FallbackVoice | null>(null);
  const turnId = useRef(0);
  const holding = useRef(false);
  const capTimer = useRef<number | null>(null);
  const possible = useRef(isRecordingPossible());

  const clearCap = useCallback(() => {
    if (capTimer.current !== null) {
      window.clearTimeout(capTimer.current);
      capTimer.current = null;
    }
  }, []);

  useEffect(() => {
    if (token === null) return;
    // held in locals, because the cleanup below runs after a render that may already
    // have replaced what the refs point at
    const playback = player.current;
    const connection = new TurnSocket({
      onState: (incoming) => setState(FROM_SERVER[incoming] ?? 'idle'),
      onAudio: (_turn, _seq, wav) => void player.current.enqueue(wav),
      onDone: () => undefined,
      onError: (code) => {
        // the character settles back; the voice says what happened (UC-22)
        setState('idle');
        void voice.current?.play(code);
      },
      onClosed: () => {
        setConnected(false);
        setState('sleeping');
      },
    });
    socket.current = connection;
    connection
      .connect(token)
      .then(() => {
        setConnected(true);
        setState('idle');
      })
      .catch(() => {
        setConnected(false);
        setState('sleeping');
      });

    return () => {
      clearCap();
      playback.stop();
      connection.close();
      socket.current = null;
      const microphone = mic.current;
      mic.current = null;
      microphone?.close();
    };
  }, [token, clearCap]);

  const release = useCallback((): void => {
    if (!holding.current) return;
    holding.current = false;
    clearCap();
    setInputLevel(0);
    mic.current?.stop();
    const connection = socket.current;
    if (connection === null) return;
    connection.endTurn(`t${turnId.current}`);
    setState('thinking');
  }, [clearCap]);

  const press = useCallback(async (): Promise<void> => {
    if (!possible.current || holding.current) return;
    const connection = socket.current;
    if (connection === null || !connection.open) return;

    // barge-in first: stop talking before anything that might await (§6.1)
    player.current.stop();
    setMouth(0);
    holding.current = true;

    if (mic.current === null) mic.current = new Microphone();
    const microphone = mic.current;
    try {
      // inside the gesture, which is the only time iOS will resume a context
      await microphone.open();
    } catch {
      holding.current = false;
      possible.current = false;
      setState('idle');
      return;
    }
    if (!holding.current) return; // released while the permission dialog was up

    const context = microphone.audioContext;
    if (context !== null) {
      player.current.attach(context);
      player.current.watch(setMouth, () => {
        setMouth(0);
        setState('idle');
      });
      if (voice.current === null) {
        voice.current = new FallbackVoice(context, language);
        void voice.current.warm();
      }
    }

    turnId.current += 1;
    const label = `t${turnId.current}`;
    setState('listening');
    connection.startTurn(label);
    microphone.start((frame: Frame) => {
      setInputLevel(frame.rms);
      connection.sendAudio(frame.pcm);
    });

    clearCap();
    capTimer.current = window.setTimeout(() => {
      // §6.1: a press cannot run past the cap; treat it as a release
      capTimer.current = null;
      if (holding.current) release();
    }, MAX_PRESS_MS);
  }, [clearCap, language, release]);

  return {
    state,
    inputLevel,
    mouth,
    possible: possible.current,
    connected,
    pressDown: () => void press(),
    pressUp: release,
  };
}

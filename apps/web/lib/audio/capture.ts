/**
 * Microphone capture for the paw (ARCHITECTURE.md §6.1, F-21).
 *
 * Two things here are not optional on a phone:
 *
 * * **A secure context.** `getUserMedia` does not exist over plain http, which is why
 *   `make https` exists. `isRecordingPossible()` lets the screen find out before the
 *   child presses anything.
 * * **`resume()` inside the press.** iOS starts every AudioContext suspended and only
 *   lets a user gesture start it. The gesture is the paw going down, so resume happens
 *   there and nowhere else.
 *
 * The microphone track is kept open between turns on purpose: asking for it again per
 * turn costs hundreds of milliseconds and, on iOS, can show the indicator repeatedly.
 */

const WORKLET_URL = '/worklets/capture.js';

export type Frame = { pcm: ArrayBuffer; rms: number };

export function isRecordingPossible(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    typeof navigator !== 'undefined' &&
    navigator.mediaDevices !== undefined &&
    typeof navigator.mediaDevices.getUserMedia === 'function'
  );
}

export class Microphone {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private sink: GainNode | null = null;
  private listening = false;
  private onFrame: ((frame: Frame) => void) | null = null;

  /** True once the microphone has been granted and the worklet is loaded. */
  get ready(): boolean {
    return this.node !== null;
  }

  /**
   * The context, so playback can share it. Phones allow very few AudioContexts, and one
   * that the press already resumed is also one that is allowed to make sound.
   */
  get audioContext(): AudioContext | null {
    return this.context;
  }

  /**
   * Must be called from inside the press handler, so the gesture is still "live".
   * Safe to call again: the second press reuses everything.
   */
  async open(): Promise<void> {
    if (this.context === null) {
      this.context = new AudioContext();
    }
    if (this.context.state === 'suspended') {
      await this.context.resume();
    }
    if (this.stream === null) {
      // Every constraint here is `ideal`, never exact. A bare `channelCount: 1` is a
      // hard requirement: a device that cannot capture single-channel then fails the
      // whole call rather than handing over stereo we could use perfectly well. Mono is
      // enforced downstream anyway - the worklet reads channel 0 and ignores the rest -
      // so none of these four is worth losing the microphone over.
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: { ideal: 1 },
          echoCancellation: { ideal: true },
          noiseSuppression: { ideal: true },
          autoGainControl: { ideal: true },
        },
      });
    }
    if (this.node === null) {
      await this.context.audioWorklet.addModule(WORKLET_URL);
      this.node = new AudioWorkletNode(this.context, 'bruno-capture', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        channelCount: 1,
      });
      this.node.port.onmessage = (event: MessageEvent<Frame>) => {
        if (this.listening) this.onFrame?.(event.data);
      };
      this.source = this.context.createMediaStreamSource(this.stream);
      this.source.connect(this.node);
      // a silent sink: some browsers do not pull audio through a worklet whose output
      // goes nowhere, and then `process` is never called
      this.sink = this.context.createGain();
      this.sink.gain.value = 0;
      this.node.connect(this.sink);
      this.sink.connect(this.context.destination);
    }
  }

  /** Frames only flow between start() and stop(), so nothing is captured at rest. */
  start(onFrame: (frame: Frame) => void): void {
    this.onFrame = onFrame;
    this.listening = true;
  }

  stop(): void {
    this.listening = false;
    this.onFrame = null;
  }

  /** Release the microphone; the indicator on the phone goes out. */
  close(): void {
    this.stop();
    this.node?.port.postMessage('stop');
    this.node?.disconnect();
    this.source?.disconnect();
    this.sink?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    void this.context?.close();
    this.node = null;
    this.source = null;
    this.sink = null;
    this.stream = null;
    this.context = null;
  }
}

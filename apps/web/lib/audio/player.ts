/**
 * Ordered playback of the sentences Bruno says (ARCHITECTURE.md §6.1).
 *
 * The server sends one WAV per sentence, numbered. They have to play in order and with
 * no gap between them, while later ones are still arriving - so each buffer is scheduled
 * on the AudioContext clock rather than started when the previous `ended` event fires,
 * which would leave an audible seam.
 *
 * The output RMS drives the character's mouth (UI.md §3.3), so the mouth moves with the
 * actual waveform instead of a timer.
 *
 * `stop()` must be immediate: barge-in has to silence Bruno within 150 ms (§6.1).
 */

export type Level = (rms: number) => void;

export class Player {
  private context: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private gain: GainNode | null = null;
  private playing: AudioBufferSourceNode[] = [];
  private nextStart = 0;
  private frame: number | null = null;
  // typed as Float32Array<ArrayBuffer>, which is what getFloatTimeDomainData wants: the
  // plain alias also admits a SharedArrayBuffer, which that call does not accept
  private samples = new Float32Array(new ArrayBuffer(0));
  private onLevel: Level | null = null;
  private onIdle: (() => void) | null = null;

  /** Share the capture context if there is one: phones allow few AudioContexts. */
  attach(context: AudioContext): void {
    if (this.context === context) return;
    this.context = context;
    this.gain = context.createGain();
    this.analyser = context.createAnalyser();
    this.analyser.fftSize = 512;
    this.samples = new Float32Array(new ArrayBuffer(this.analyser.fftSize * 4));
    this.gain.connect(this.analyser);
    this.analyser.connect(context.destination);
  }

  watch(onLevel: Level, onIdle: () => void): void {
    this.onLevel = onLevel;
    this.onIdle = onIdle;
  }

  /** Queue one sentence. `wav` is what the server sent, header and all. */
  async enqueue(wav: ArrayBuffer): Promise<void> {
    const context = this.context;
    const gain = this.gain;
    if (context === null || gain === null) return;
    const buffer = await context.decodeAudioData(wav);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(gain);

    // a small lead on the first sentence, so scheduling never lands in the past
    const now = context.currentTime;
    const start = Math.max(this.nextStart, now + 0.02);
    source.start(start);
    this.nextStart = start + buffer.duration;
    this.playing.push(source);
    source.onended = () => {
      this.playing = this.playing.filter((item) => item !== source);
      if (this.playing.length === 0) {
        this.nextStart = 0;
        this.stopWatching();
        this.onIdle?.();
      }
    };
    this.startWatching();
  }

  /** Silence immediately and forget what was queued (barge-in). */
  stop(): void {
    for (const source of this.playing) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // already finished; nothing to stop
      }
    }
    this.playing = [];
    this.nextStart = 0;
    this.stopWatching();
    this.onLevel?.(0);
  }

  get speaking(): boolean {
    return this.playing.length > 0;
  }

  private startWatching(): void {
    if (this.frame !== null || this.analyser === null) return;
    const tick = (): void => {
      const analyser = this.analyser;
      if (analyser === null) return;
      analyser.getFloatTimeDomainData(this.samples);
      let sum = 0;
      for (const sample of this.samples) sum += sample * sample;
      this.onLevel?.(Math.sqrt(sum / this.samples.length));
      this.frame = window.requestAnimationFrame(tick);
    };
    this.frame = window.requestAnimationFrame(tick);
  }

  private stopWatching(): void {
    if (this.frame !== null) {
      window.cancelAnimationFrame(this.frame);
      this.frame = null;
    }
  }
}

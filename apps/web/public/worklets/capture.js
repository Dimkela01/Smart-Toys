/**
 * Microphone capture worklet (ARCHITECTURE.md §6.1).
 *
 * Takes the AudioContext's own rate (usually 48 kHz on a phone), resamples to the
 * 16 kHz mono PCM16 the speech-to-text service expects, and posts one 20 ms frame at a
 * time so the connection carries a steady trickle instead of one lump at release.
 *
 * It runs on the audio thread, so it must not allocate much or block: everything here is
 * arithmetic over small typed arrays. The RMS travels with each frame, which is what the
 * level ring around the paw is drawn from.
 *
 * Served from public/ rather than bundled: addModule() takes a URL, and the worklet
 * scope has no imports, no window and no DOM.
 */

const TARGET_RATE = 16000;
const FRAME_MS = 20;
const FRAME_SAMPLES = (TARGET_RATE * FRAME_MS) / 1000; // 320

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // sampleRate is a global in the worklet scope: the context's real rate
    this.step = sampleRate / TARGET_RATE;
    this.pending = new Float32Array(0);
    // read position inside `pending`, in input samples, kept across blocks so the
    // resampling does not click at every block boundary
    this.position = 0;
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.filled = 0;
    this.stopped = false;
    this.port.onmessage = (event) => {
      if (event.data === 'stop') this.stopped = true;
    };
  }

  process(inputs) {
    if (this.stopped) return false;
    const channel = inputs[0] && inputs[0][0];
    if (!channel || channel.length === 0) return true;

    let sum = 0;
    for (let i = 0; i < channel.length; i += 1) sum += channel[i] * channel[i];
    const rms = Math.sqrt(sum / channel.length);

    const merged = new Float32Array(this.pending.length + channel.length);
    merged.set(this.pending);
    merged.set(channel, this.pending.length);
    this.pending = merged;

    while (this.position + 1 < this.pending.length) {
      const index = Math.floor(this.position);
      const fraction = this.position - index;
      const left = this.pending[index];
      const value = left + (this.pending[index + 1] - left) * fraction;
      const clamped = value < -1 ? -1 : value > 1 ? 1 : value;
      this.frame[this.filled] = Math.round(clamped * 32767);
      this.filled += 1;
      if (this.filled === FRAME_SAMPLES) {
        // a copy, because the frame buffer is reused for the next 20 ms
        const out = this.frame.slice();
        this.port.postMessage({ pcm: out.buffer, rms }, [out.buffer]);
        this.filled = 0;
      }
      this.position += this.step;
    }

    const consumed = Math.floor(this.position);
    if (consumed > 0) {
      this.pending = this.pending.slice(consumed);
      this.position -= consumed;
    }
    return true;
  }
}

registerProcessor('bruno-capture', CaptureProcessor);

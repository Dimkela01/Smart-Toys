/**
 * The client half of /ws/turns (ARCHITECTURE.md §7.2).
 *
 * The token travels as a WebSocket subprotocol, because a browser cannot set an
 * Authorization header on a WebSocket and a token in the query string would end up in
 * logs and history.
 *
 * Binary frames carry a small JSON header, so a client can drop audio belonging to a
 * turn it has already abandoned:
 *
 *     to the server     [4-byte big-endian sequence][PCM16 16 kHz mono]
 *     from the server   [4-byte big-endian header length][JSON header][WAV]
 *
 * Nothing that arrives here is text for the child: an `error` carries a code, and the
 * screen answers it with one of its own recorded lines (NFR-09).
 */

export type ServerState = 'listening' | 'thinking' | 'speaking' | 'idle' | 'sleeping';

export type TurnEvents = {
  onState?: (state: ServerState) => void;
  onAudio?: (turnId: string, seq: number, wav: ArrayBuffer) => void;
  onDone?: (turnId: string) => void;
  onError?: (code: string) => void;
  onClosed?: (clean: boolean) => void;
};

function socketUrl(): string {
  const { protocol, host } = window.location;
  const scheme = protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${host}/api/v1/ws/turns`;
}

export class TurnSocket {
  private socket: WebSocket | null = null;
  private sequence = 0;

  constructor(private readonly events: TurnEvents) {}

  get open(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  connect(token: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(socketUrl(), ['bearer', token]);
      socket.binaryType = 'arraybuffer';
      this.socket = socket;

      socket.onopen = () => resolve();
      socket.onerror = () => reject(new Error('turn socket failed'));
      socket.onclose = (event) => {
        this.socket = null;
        this.events.onClosed?.(event.code === 1000 || event.code === 1001);
      };
      socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
        if (typeof event.data !== 'string') {
          const view = new DataView(event.data);
          const size = view.getUint32(0);
          const header = new TextDecoder().decode(new Uint8Array(event.data, 4, size));
          const parsed = JSON.parse(header) as { turn_id: string; seq: number };
          this.events.onAudio?.(parsed.turn_id, parsed.seq, event.data.slice(4 + size));
          return;
        }
        const message = JSON.parse(event.data) as { type: string; [key: string]: unknown };
        if (message.type === 'state') this.events.onState?.(message.state as ServerState);
        else if (message.type === 'error') this.events.onError?.(String(message.code));
        else if (message.type === 'turn.done') this.events.onDone?.(String(message.turn_id));
      };
    });
  }

  private send(payload: Record<string, unknown>): void {
    if (this.open) this.socket?.send(JSON.stringify(payload));
  }

  startTurn(turnIdClient: string): void {
    this.sequence = 0;
    this.send({ type: 'turn.start', turn_id_client: turnIdClient });
  }

  /** One 20 ms frame. The sequence number lets the server notice a gap. */
  sendAudio(pcm: ArrayBuffer): void {
    if (!this.open) return;
    this.sequence += 1;
    const framed = new Uint8Array(4 + pcm.byteLength);
    new DataView(framed.buffer).setUint32(0, this.sequence);
    framed.set(new Uint8Array(pcm), 4);
    this.socket?.send(framed);
  }

  endTurn(turnIdClient: string): void {
    this.send({ type: 'turn.end', turn_id_client: turnIdClient });
  }

  cancel(): void {
    this.send({ type: 'turn.cancel' });
  }

  close(): void {
    this.socket?.close(1000);
    this.socket = null;
  }
}

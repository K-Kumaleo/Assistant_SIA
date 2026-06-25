// ws.ts — WebSocket client with auto-reconnect

export type WsMessage = {
  type: string;
  [key: string]: unknown;
};

type MessageHandler = (msg: WsMessage) => void;

export class SiaWebSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: MessageHandler[] = [];
  private reconnectDelay = 1000;
  private maxDelay = 10000;
  private _connected = false;
  private intentionallyClosed = false;

  constructor(url: string) {
    this.url = url;
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    this.intentionallyClosed = false;

    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      console.error("WS connect error:", e);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.log("[SIA WS] Connected");
      this._connected = true;
      this.reconnectDelay = 1000;
      this.emit({ type: "status_change", connected: true });
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WsMessage;
        this.handlers.forEach((h) => h(msg));
      } catch (e) {
        console.error("[SIA WS] Parse error:", e);
      }
    };

    this.ws.onclose = () => {
      this._connected = false;
      this.emit({ type: "status_change", connected: false });
      if (!this.intentionallyClosed) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (err) => {
      console.error("[SIA WS] Error:", err);
    };
  }

  private scheduleReconnect() {
    setTimeout(() => {
      console.log(`[SIA WS] Reconnecting in ${this.reconnectDelay}ms…`);
      this.connect();
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxDelay);
    }, this.reconnectDelay);
  }

  send(msg: WsMessage) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  on(handler: MessageHandler) {
    this.handlers.push(handler);
  }

  private emit(msg: WsMessage) {
    this.handlers.forEach((h) => h(msg));
  }

  get connected() {
    return this._connected;
  }

  close() {
    this.intentionallyClosed = true;
    this.ws?.close();
  }

  ping() {
    this.send({ type: "ping" });
  }
}

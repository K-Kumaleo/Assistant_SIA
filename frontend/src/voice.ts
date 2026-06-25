// voice.ts — Web Speech API recognition + Web Audio playback queue

export type TranscriptCallback = (text: string, isFinal: boolean) => void;

// ── Speech Recognition ────────────────────────────────────────────────────────
export class SpeechRecognizer {
  private recognition: SpeechRecognition | null = null;
  private _active = false;
  private onTranscript: TranscriptCallback;
  private onError: (err: string) => void;

  constructor(onTranscript: TranscriptCallback, onError: (err: string) => void) {
    this.onTranscript = onTranscript;
    this.onError = onError;
  }

  init(): boolean {
    const SR = window.SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      this.onError("Speech recognition not supported. Use Google Chrome.");
      return false;
    }

    this.recognition = new SR();
    this.recognition.continuous = true;
    this.recognition.interimResults = true;
    this.recognition.lang = "en-GB";
    this.recognition.maxAlternatives = 1;

    this.recognition.onresult = (event: SpeechRecognitionEvent) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0].transcript.trim();
        const isFinal = result.isFinal;
        if (text) {
          this.onTranscript(text, isFinal);
        }
      }
    };

    this.recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      this.onError(`Speech error: ${event.error}`);
    };

    this.recognition.onend = () => {
      // Auto-restart if still active
      if (this._active) {
        try {
          this.recognition?.start();
        } catch (e) {
          // already started
        }
      }
    };

    return true;
  }

  start() {
    this._active = true;
    try {
      this.recognition?.start();
    } catch (e) {
      // already running
    }
  }

  stop() {
    this._active = false;
    try {
      this.recognition?.stop();
    } catch (e) {}
  }

  get active() {
    return this._active;
  }
}


// ── Audio Playback Queue ──────────────────────────────────────────────────────
export class AudioPlayer {
  private ctx: AudioContext | null = null;
  private queue: ArrayBuffer[] = [];
  private playing = false;
  public onPlayStart: (() => void) | null = null;
  public onPlayEnd: (() => void) | null = null;

  init() {
    this.ctx = new AudioContext();
  }

  /** Resume AudioContext (needed after user gesture) */
  async resume() {
    if (this.ctx?.state === "suspended") {
      await this.ctx.resume();
    }
  }

  async enqueue(base64Audio: string) {
    const binary = atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    this.queue.push(bytes.buffer);
    this.playNext();
  }

  private async playNext() {
    if (this.playing || this.queue.length === 0 || !this.ctx) return;
    this.playing = true;
    this.onPlayStart?.();

    const buf = this.queue.shift()!;
    try {
      const decoded = await this.ctx.decodeAudioData(buf);
      const source = this.ctx.createBufferSource();
      source.buffer = decoded;
      source.connect(this.ctx.destination);
      source.onended = () => {
        this.playing = false;
        if (this.queue.length > 0) {
          this.playNext();
        } else {
          this.onPlayEnd?.();
        }
      };
      source.start();
    } catch (e) {
      console.error("Audio decode error:", e);
      this.playing = false;
      this.onPlayEnd?.();
    }
  }

  get isPlaying() {
    return this.playing;
  }
}

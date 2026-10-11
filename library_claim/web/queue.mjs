/** Bounded FIFO evidence queue. Failed entries retain their bytes and IDs. */
export class EvidenceQueue {
  constructor(send, {maxCount = 4, maxBytes = 24 * 1024 * 1024, changed = () => {}} = {}) {
    this.send = send; this.maxCount = maxCount; this.maxBytes = maxBytes; this.changed = changed;
    this.items = []; this.bytes = 0; this.running = false; this.paused = false; this.error = null;
    this.waiters = [];
  }
  push(item) {
    if (this.items.length >= this.maxCount || this.bytes + item.blob.size > this.maxBytes) return false;
    this.items.push(item); this.bytes += item.blob.size; this.changed(this);
    void this.pump(); return true;
  }
  async pump() {
    if (this.running || this.paused) return;
    this.running = true;
    try {
      while (this.items.length && !this.paused) {
        const item = this.items[0];
        try { await this.send(item); }
        catch (error) { this.paused = true; this.error = error; break; }
        this.items.shift(); this.bytes -= item.blob.size; this.changed(this);
      }
    } finally {
      this.running = false; this.changed(this);
      const waiters = this.waiters.splice(0);
      for (const {resolve, reject} of waiters) {
        if (!this.items.length) resolve();
        else reject(this.error || new Error("Uploads remain pending"));
      }
    }
  }
  resume() { this.paused = false; this.error = null; void this.pump(); }
  drain() {
    if (!this.items.length) return Promise.resolve();
    if (this.paused) return Promise.reject(this.error || new Error("Uploads paused"));
    return new Promise((resolve, reject) => this.waiters.push({resolve, reject}));
  }
  discard() {
    if (this.running) throw new Error("Wait for the current upload before discarding");
    const removed = this.items.splice(0); this.bytes = 0; this.paused = false; this.error = null;
    this.changed(this); return removed;
  }
}

/** Latest preview replaces old preview; it never enters the evidence FIFO. */
export class LatestPreview {
  constructor() { this.value = null; this.generation = 0; }
  begin() { this.value = null; return ++this.generation; }
  put(value, generation) { if (generation !== this.generation) return false; this.value = value; return true; }
  clear() { this.value = null; ++this.generation; }
}

/** Permissions may remain pending; always release a late or cancelled stream. */
export async function acquireCamera(getMedia, constraints, {isCurrent, timeoutMs=20000}) {
  let abandoned=false, timer;
  const request=getMedia(constraints).then(stream=>{
    if(abandoned||!isCurrent()) { stream.getTracks().forEach(track=>track.stop()); throw new Error('Camera request cancelled'); }
    return stream;
  });
  try {
    return await Promise.race([request, new Promise((_,reject)=>{
      timer=setTimeout(()=>reject(new Error('Camera permission or device response is still pending. Allow camera access, then retry.')),timeoutMs);
    })]);
  } finally { abandoned=true; clearTimeout(timer); }
}

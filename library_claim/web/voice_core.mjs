// Reference-derived PCM conversion/playback, with bounded queue and generation guards.
export function pcm16(input, rate) {
  if (!(rate >= 16000) || !input.length) throw new Error('Invalid microphone sample rate');
  const output = new ArrayBuffer(Math.floor(input.length * 16000 / rate) * 2), view = new DataView(output);
  for (let i=0;i<output.byteLength/2;i++) {
    const position=i*rate/16000, before=Math.floor(position), weight=position-before;
    const sample=Math.max(-1,Math.min(1,input[before]*(1-weight)+input[Math.min(before+1,input.length-1)]*weight));
    view.setInt16(i*2,sample<0?sample*32768:sample*32767,true);
  }
  return output;
}
export function encode(buffer) { let raw='';for(const b of new Uint8Array(buffer)) raw+=String.fromCharCode(b);return btoa(raw); }
export class Playback {
  constructor(context) { this.context=context;this.sources=new Set();this.next=0; }
  clear() { for(const source of this.sources) {try {source.stop();}catch{}}this.sources.clear();this.next=0; }
  play(encoded) {
    const raw=atob(encoded);if(!raw.length||raw.length%2) throw new Error('Invalid audio');
    const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0)), view=new DataView(bytes.buffer);
    const start=Math.max(this.context.currentTime,this.next);
    if(start-this.context.currentTime>5) {this.clear();throw new Error('Voice playback fell behind; reconnect.');}
    const buffer=this.context.createBuffer(1,bytes.length/2,24000), channel=buffer.getChannelData(0);
    for(let i=0;i<channel.length;i++) channel[i]=view.getInt16(i*2,true)/32768;
    const source=this.context.createBufferSource();source.buffer=buffer;source.connect(this.context.destination);
    this.sources.add(source);source.onended=()=>this.sources.delete(source);source.start(start);this.next=start+buffer.duration;
  }
}
export class ConnectionGeneration {
  constructor() {this.value=0;this.epoch=null;}
  next() {this.epoch=null;return ++this.value;}
  accepts(generation,event) {
    if(generation!==this.value) return false;
    if(event.type==='ready') this.epoch=event.epoch;
    return this.epoch!==null && event.epoch===this.epoch;
  }
}

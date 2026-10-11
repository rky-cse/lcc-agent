class CapturePCM extends AudioWorkletProcessor {
  constructor() {super();this.data=[];this.block=Math.ceil(sampleRate/10);}
  process(inputs) {
    const channel=inputs[0]?.[0];if(channel) this.data.push(...channel);
    if(this.data.length>=this.block) {const block=Float32Array.from(this.data.splice(0,this.block));this.port.postMessage(block,[block.buffer]);}
    return true;
  }
}
registerProcessor('capture-pcm',CapturePCM);

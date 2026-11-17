/* recorder：本地录音 → 16kHz PCM WAV → base64。只服务会话输入框。
   不做识别、不做发送：拿到 base64 后由动作层调需求、回填输入框。 */
const VoiceRecorder = (() => {
  let ctx = null, stream = null, node = null, src = null, gain = null;
  let chunks = [];
  let recording = false;
  let sourceRate = 0;

  async function start() {
    if (recording) return;
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    sourceRate = ctx.sampleRate;
    chunks = [];
    src = ctx.createMediaStreamSource(stream);
    node = ctx.createScriptProcessor(4096, 1, 1);
    node.onaudioprocess = (e) => {
      chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    gain = ctx.createGain();
    gain.gain.value = 0;                 // 回调要节点链通，但不外放监听声
    src.connect(node);
    node.connect(gain);
    gain.connect(ctx.destination);
    recording = true;
  }

  function stop() {
    recording = false;
    const flat = concat(chunks);
    try { node && node.disconnect(); src && src.disconnect(); gain && gain.disconnect(); } catch (e) {}
    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (ctx) ctx.close().catch(() => {});
    const pcm = resample(flat, sourceRate, 16000);
    const wav = encodeWav(pcm, 16000);
    const b64 = toBase64(wav);
    ctx = stream = node = src = gain = null;
    chunks = [];
    return Promise.resolve({ b64, mime: "audio/wav" });
  }

  function concat(parts) {
    const len = parts.reduce((s, p) => s + p.length, 0);
    const out = new Float32Array(len);
    let off = 0;
    for (const p of parts) { out.set(p, off); off += p.length; }
    return out;
  }

  function resample(input, inRate, outRate) {
    if (!inRate || inRate === outRate) return input;
    const ratio = inRate / outRate;
    const outLen = Math.floor(input.length / ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const pos = i * ratio;
      const i0 = Math.floor(pos);
      const f = pos - i0;
      const a = input[i0] || 0;
      const b = input[i0 + 1] || 0;
      out[i] = a + (b - a) * f;
    }
    return out;
  }

  function encodeWav(samples, rate) {
    const n = samples.length;
    const buf = new ArrayBuffer(44 + n * 2);
    const v = new DataView(buf);
    const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
    writeStr(0, "RIFF");
    v.setUint32(4, 36 + n * 2, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    v.setUint32(16, 16, true);
    v.setUint16(20, 1, true);            // PCM
    v.setUint16(22, 1, true);            // 单声道
    v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true);
    v.setUint16(32, 2, true);
    v.setUint16(34, 16, true);
    writeStr(36, "data");
    v.setUint32(40, n * 2, true);
    let off = 44;
    for (let i = 0; i < n; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      off += 2;
    }
    return buf;
  }

  function toBase64(buf) {
    const bytes = new Uint8Array(buf);
    let bin = "";
    const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    }
    return btoa(bin);
  }

  return {
    start,
    stop,
    get recording() { return recording; }
  };
})();

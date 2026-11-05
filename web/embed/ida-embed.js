/*!
 * Interactive Demo Assets (IDA) - embeddable audio analysis widget.
 *
 * Zero dependencies. Drop one <script> tag and one element per clip:
 *
 *   <script src="ida-embed.js" defer></script>
 *   <div data-ida-src="data/mix.json" data-ida-audio="audio/mix.wav"></div>
 *
 * Two layers, deliberately:
 *   1. Precomputed (librosa, offline): waveform, RMS, spectral centroid,
 *      mel spectrogram, beats, onsets, tempo curve, key and metrics. These come
 *      from the JSON written by `python -m ida_dsp analyze`.
 *   2. Live (Web Audio AnalyserNode): spectrum, peak/RMS meter and centroid,
 *      measured on the audio that is playing right now in the visitor's browser.
 *
 * Cross-origin audio needs CORS headers (Access-Control-Allow-Origin) for the
 * live layer; otherwise the browser silences the analyser and the widget falls
 * back to showing only the precomputed layer.
 */
(function (global) {
  "use strict";

  const SCHEMA = "ida.analysis.v1";
  const STYLE_ID = "ida-embed-style";
  const INFERNO = [
    [0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99],
    [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164],
  ];

  const CSS = `
.ida-root{font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#e7e9ee;
  background:#0d1117;border:1px solid #232a36;border-radius:12px;padding:16px;max-width:100%;box-sizing:border-box}
.ida-root *{box-sizing:border-box}
.ida-head{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between;margin-bottom:10px}
.ida-title{font-size:16px;font-weight:600;margin:0}
.ida-sub{color:#8b93a3;font-size:12px}
.ida-chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 14px}
.ida-chip{background:#161c26;border:1px solid #232a36;border-radius:999px;padding:3px 10px;font-size:12px;color:#b9c0cc}
.ida-chip b{color:#fff;font-weight:600;font-variant-numeric:tabular-nums}
.ida-canvas{display:block;width:100%;border-radius:8px;background:#090c11;cursor:pointer;margin-bottom:10px}
.ida-canvas.ida-wave,.ida-canvas.ida-live-canvas{height:120px}
.ida-canvas.ida-spec{height:180px}
.ida-label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#7a8394;margin:6px 0 4px}
.ida-live{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:#b9c0cc;margin:4px 0 6px;font-variant-numeric:tabular-nums}
.ida-live b{color:#fff}
.ida-audio{width:100%;margin-top:8px}
.ida-error{color:#ffb4a8;font-size:13px}
.ida-foot{font-size:11px;color:#6b7383;margin-top:8px}
`;

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function h(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const k of Object.keys(attrs || {})) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "class") node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    }
    (children || []).forEach((c) => node.appendChild(c));
    return node;
  }

  function decodeSpectrogram(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function palette() {
    const lut = new Uint8ClampedArray(256 * 3);
    for (let i = 0; i < 256; i++) {
      const p = (i / 255) * (INFERNO.length - 1);
      const a = Math.floor(p), b = Math.min(a + 1, INFERNO.length - 1), f = p - a;
      for (let c = 0; c < 3; c++) lut[i * 3 + c] = INFERNO[a][c] + (INFERNO[b][c] - INFERNO[a][c]) * f;
    }
    return lut;
  }
  const LUT = palette();

  const hzToMel = (hz) => 2595 * Math.log10(1 + hz / 700);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const dbfs = (lin) => 20 * Math.log10(Math.max(lin, 1e-10));

  function fitCanvas(canvas) {
    const dpr = global.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(canvas.clientWidth));
    const h = Math.round(canvas.clientHeight);
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
  }

  function buildSpectrogramImage(spec) {
    const frames = spec.frames, mels = spec.n_mels;
    const q = decodeSpectrogram(spec.data);
    const off = document.createElement("canvas");
    off.width = frames;
    off.height = mels;
    const octx = off.getContext("2d");
    const img = octx.createImageData(frames, mels);
    for (let m = 0; m < mels; m++) {
      const row = mels - 1 - m; // low frequencies at the bottom
      for (let f = 0; f < frames; f++) {
        const v = q[m * frames + f];
        const o = (row * frames + f) * 4;
        img.data[o] = LUT[v * 3];
        img.data[o + 1] = LUT[v * 3 + 1];
        img.data[o + 2] = LUT[v * 3 + 2];
        img.data[o + 3] = 255;
      }
    }
    octx.putImageData(img, 0, 0);
    return off;
  }

  function createWidget(root, data, opts) {
    const m = data.metrics, mu = data.musical, dur = m.duration_s;
    const series = data.series, spec = data.spectrogram;
    const maxHz = spec.freqs_hz[spec.freqs_hz.length - 1];
    const specImage = buildSpectrogramImage(spec);
    const sampleRate = m.sample_rate || 22050;

    root.classList.add("ida-root");
    root.setAttribute("role", "region");
    root.setAttribute("aria-label", `${data.title} audio analysis`);
    root.innerHTML = "";

    const chipDefs = [
      ["Peak", `${m.peak_dbfs} dBFS`, "Largest absolute sample"],
      ["RMS", `${m.rms_dbfs} dBFS`, "Root-mean-square level over the whole clip"],
      ["Crest", `${m.crest_factor_db} dB`, "Peak minus RMS"],
      ["Dyn. range", `~${m.dynamic_range_db_approx} dB`, "Approximate: 95th minus 10th percentile of frame RMS above -60 dB. Not LUFS/PLR."],
      ["Tempo", `${mu.tempo_bpm} BPM`, "librosa beat tracker at 5.8 ms frames"],
      ["Key", mu.key, `Krumhansl-Schmuckler profile, r = ${mu.key_correlation}`],
      ["Onsets", `${m.onset_rate_per_s}/s`, "Detected onset events per second"],
      ["Clipped", `${m.clipped_samples}`, "Samples at or above 0.999 full scale"],
    ];
    if (m.stereo_correlation !== null && m.stereo_correlation !== undefined) {
      chipDefs.push(["L/R corr.", `${m.stereo_correlation}`, "Pearson correlation of left and right channels"]);
    }

    const head = h("div", { class: "ida-head" }, [
      h("div", {}, [
        h("h3", { class: "ida-title", text: data.title }),
      ]),
      h("div", { class: "ida-sub", text: `${dur.toFixed(2)} s · ${m.channels === 2 ? "stereo" : "mono"} · ${sampleRate / 1000} kHz · measured with librosa ${data.generated_by ? data.generated_by.librosa : ""}` }),
    ]);
    const chips = h("div", { class: "ida-chips" }, chipDefs.map(([k, v, tip]) =>
      h("span", { class: "ida-chip", title: tip }, [h("span", { text: k + " " }), h("b", { text: v })])));

    // CSS fixes each canvas height so fitCanvas() never feeds back into its own layout.
    const waveCanvas = h("canvas", { class: "ida-canvas ida-wave", "aria-label": "Waveform. Click to seek.", role: "img" });
    const specCanvas = h("canvas", { class: "ida-canvas ida-spec", "aria-label": "Mel spectrogram with spectral centroid. Click to seek.", role: "img" });
    const liveCanvas = h("canvas", { class: "ida-canvas ida-live-canvas", "aria-label": "Live spectrum analyser", role: "img" });
    const liveReadout = h("div", { class: "ida-live" });
    const audioSrc = root.getAttribute("data-ida-audio");
    const audio = h("audio", { class: "ida-audio", controls: "", preload: "metadata" });
    if (audioSrc) {
      audio.crossOrigin = "anonymous";
      audio.src = audioSrc;
    }

    root.appendChild(head);
    root.appendChild(chips);
    root.appendChild(h("div", { class: "ida-label", text: "Waveform · RMS (blue) · beats (grey) · onsets (dots)" }));
    root.appendChild(waveCanvas);
    root.appendChild(h("div", { class: "ida-label", text: "Mel spectrogram · spectral centroid (white)" }));
    root.appendChild(specCanvas);
    root.appendChild(h("div", { class: "ida-label", text: "Live analyser (measured while playing)" }));
    root.appendChild(liveReadout);
    root.appendChild(liveCanvas);
    if (audioSrc) root.appendChild(audio);
    else root.appendChild(h("div", { class: "ida-error", text: "No data-ida-audio set: showing analysis only." }));
    root.appendChild(h("div", { class: "ida-foot", text: "Every number above is computed from the source audio; nothing is hand-entered." }));

    // ---- live analyser (created on first play, needs a user gesture) ----
    let ctx = null, analyser = null, freqDb = null, timeBuf = null, binHz = 0;
    let liveFrame = 0, liveOk = false, liveFailed = false;

    function ensureGraph() {
      if (ctx) return;
      if (!global.AudioContext && !global.webkitAudioContext) return;
      try {
        const AC = global.AudioContext || global.webkitAudioContext;
        ctx = new AC();
        const srcNode = ctx.createMediaElementSource(audio);
        analyser = ctx.createAnalyser();
        analyser.fftSize = 2048;
        analyser.smoothingTimeConstant = 0.6;
        freqDb = new Float32Array(analyser.frequencyBinCount);
        timeBuf = new Float32Array(analyser.fftSize);
        binHz = ctx.sampleRate / analyser.fftSize;
        srcNode.connect(analyser);
        analyser.connect(ctx.destination);
        liveOk = true;
      } catch (err) {
        liveOk = false;
        liveFailed = true;
      }
    }

    audio.addEventListener("play", () => {
      ensureGraph();
      if (ctx && ctx.state === "suspended") ctx.resume();
    });

    // ---- drawing -------------------------------------------------------
    function playheadFrac() {
      return dur > 0 ? clamp(audio.currentTime / dur, 0, 1) : 0;
    }

    function drawWave() {
      const { ctx: g, w, h: H } = fitCanvas(waveCanvas);
      g.clearRect(0, 0, w, H);
      const wf = data.waveform.min_max, N = wf.length;
      const mid = H / 2, amp = H * 0.45;
      g.fillStyle = "#3a4558";
      for (let i = 0; i < N; i++) {
        const x = (i / N) * w, cw = Math.max(1, w / N);
        const top = mid - wf[i][1] * amp, bot = mid - wf[i][0] * amp;
        g.fillRect(x, top, cw, Math.max(1, bot - top));
      }
      // beats
      g.strokeStyle = "rgba(200,205,215,0.28)";
      g.lineWidth = 1;
      g.beginPath();
      (mu.beats_s || []).forEach((b) => { const x = (b / dur) * w; g.moveTo(x, 0); g.lineTo(x, H); });
      g.stroke();
      // RMS curve (bottom band, -60..0 dBFS)
      const t = series.t, rms = series.rms_db;
      g.strokeStyle = "#4da3ff";
      g.lineWidth = 1.5;
      g.beginPath();
      for (let i = 0; i < t.length; i++) {
        const x = (t[i] / dur) * w;
        const v = clamp((rms[i] + 60) / 60, 0, 1);
        const y = H - v * H * 0.4;
        i === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
      }
      g.stroke();
      // onsets
      g.fillStyle = "#ffb454";
      (mu.onsets_s || []).forEach((o) => g.fillRect((o / dur) * w - 1, H - 5, 2, 4));
      drawPlayhead(g, w, H);
    }

    function drawSpec() {
      const { ctx: g, w, h: H } = fitCanvas(specCanvas);
      g.clearRect(0, 0, w, H);
      g.imageSmoothingEnabled = true;
      g.drawImage(specImage, 0, 0, w, H);
      const melMax = hzToMel(maxHz);
      g.strokeStyle = "rgba(255,255,255,0.85)";
      g.lineWidth = 1.5;
      g.beginPath();
      const t = series.t, c = series.centroid_hz;
      for (let i = 0; i < t.length; i++) {
        const x = (t[i] / dur) * w;
        const y = H * (1 - clamp(hzToMel(c[i]) / melMax, 0, 1));
        i === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
      }
      g.stroke();
      drawPlayhead(g, w, H);
    }

    function drawPlayhead(g, w, H) {
      const x = playheadFrac() * w;
      g.strokeStyle = "#ff5c7a";
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(x, 0);
      g.lineTo(x, H);
      g.stroke();
    }

    function drawLive() {
      const { ctx: g, w, h: H } = fitCanvas(liveCanvas);
      g.clearRect(0, 0, w, H);
      if (!liveOk || audio.paused) {
        g.fillStyle = "#5b6475";
        g.font = "13px system-ui, sans-serif";
        const msg = liveFailed
          ? "Live analyser unavailable in this browser or for this audio source"
          : "Press play to see the live spectrum";
        g.fillText(msg, 12, H / 2);
        return;
      }
      analyser.getFloatFrequencyData(freqDb);
      analyser.getFloatTimeDomainData(timeBuf);

      // log-spaced bars from 30 Hz to Nyquist
      const bars = 72, fLo = 30, fHi = sampleRate / 2;
      const bw = w / bars;
      for (let b = 0; b < bars; b++) {
        const f0 = fLo * Math.pow(fHi / fLo, b / bars);
        const f1 = fLo * Math.pow(fHi / fLo, (b + 1) / bars);
        const i0 = Math.max(1, Math.floor(f0 / binHz)), i1 = Math.max(i0 + 1, Math.ceil(f1 / binHz));
        let peak = -200;
        for (let i = i0; i < Math.min(i1, freqDb.length); i++) peak = Math.max(peak, freqDb[i]);
        const v = clamp((peak + 100) / 80, 0, 1);
        const bh = v * H;
        g.fillStyle = `hsl(${200 - 160 * v}, 85%, ${45 + 15 * v}%)`;
        g.fillRect(b * bw + 1, H - bh, Math.max(1, bw - 2), bh);
      }

      // live numbers (throttled text update)
      if (liveFrame++ % 6 === 0) {
        let peak = 0, sumSq = 0;
        for (let i = 0; i < timeBuf.length; i++) {
          const a = Math.abs(timeBuf[i]);
          if (a > peak) peak = a;
          sumSq += timeBuf[i] * timeBuf[i];
        }
        const rms = Math.sqrt(sumSq / timeBuf.length);
        let num = 0, den = 0;
        for (let i = 1; i < freqDb.length; i++) {
          const mag = Math.pow(10, freqDb[i] / 20);
          num += i * binHz * mag;
          den += mag;
        }
        const centroid = den > 0 ? num / den : 0;
        liveReadout.innerHTML = "";
        [
          ["Live peak", `${dbfs(peak).toFixed(1)} dBFS`],
          ["Live RMS", `${dbfs(rms).toFixed(1)} dBFS`],
          ["Live centroid", `${Math.round(centroid)} Hz`],
        ].forEach(([k, v]) => liveReadout.appendChild(h("span", {}, [h("span", { text: k + " " }), h("b", { text: v })])));
      }
    }

    function frame() {
      drawWave();
      drawSpec();
      drawLive();
      raf = global.requestAnimationFrame(frame);
    }

    // ---- interaction ---------------------------------------------------
    function seekFrom(evt, canvas) {
      const rect = canvas.getBoundingClientRect();
      const frac = clamp((evt.clientX - rect.left) / rect.width, 0, 1);
      audio.currentTime = frac * dur;
    }
    waveCanvas.addEventListener("pointerdown", (e) => seekFrom(e, waveCanvas));
    specCanvas.addEventListener("pointerdown", (e) => seekFrom(e, specCanvas));

    let raf = 0;
    raf = global.requestAnimationFrame(frame);

    if (global.ResizeObserver) {
      new ResizeObserver(() => { drawWave(); drawSpec(); }).observe(root);
    }

    return {
      destroy() {
        global.cancelAnimationFrame(raf);
        audio.pause();
      },
    };
  }

  function errorBox(root, message) {
    root.classList.add("ida-root");
    root.innerHTML = "";
    root.appendChild(h("div", { class: "ida-error", text: message }));
  }

  function mount(root) {
    injectStyle();
    const src = root.getAttribute("data-ida-src");
    if (!src) { errorBox(root, "IDA: missing data-ida-src."); return Promise.resolve(null); }
    if (root.__idaWidget) return Promise.resolve(root.__idaWidget);
    return fetch(src)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} for ${src}`);
        return r.json();
      })
      .then((data) => {
        if (data.schema !== SCHEMA) throw new Error(`Unsupported schema ${data.schema}`);
        root.__idaWidget = createWidget(root, data);
        return root.__idaWidget;
      })
      .catch((err) => {
        errorBox(root, `IDA: could not load analysis (${err.message}). Run "python -m ida_dsp demo" or check the path.`);
        return null;
      });
  }

  function mountAll(scope) {
    const nodes = (scope || document).querySelectorAll("[data-ida-src]");
    return Promise.all(Array.prototype.map.call(nodes, mount));
  }

  global.IDA = { mount, mountAll, schema: SCHEMA, version: "0.1.0" };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mountAll());
  } else {
    mountAll();
  }
})(window);

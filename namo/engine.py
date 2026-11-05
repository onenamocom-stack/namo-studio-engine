#!/usr/bin/env python3
"""
namo/engine.py - the one door into NAMO's production engine.

This file implements SPEC.md section by section. Every rule below names its section.

    python namo/engine.py probe              prove runtimes; exit 1 if any is missing
    python namo/engine.py runtimes           list candidates, no probing
    python namo/engine.py render <job.json>  validate, render, verify
    python namo/engine.py pipeline <yaml>    refuse a pipeline whose skills are missing
    python namo/engine.py checkjob <json>    validate only
    python namo/engine.py fitbeats <beats.json> [voice] [rate]
                                             retime an rd beats file so its narration fits

Design rule taken from the spec, section 6: a runtime that cannot honour the brief must
refuse the job. A film that silently ignores the brief is worse than no film, because it
looks like success.
"""
import base64, json, math, os, re, shutil, subprocess, sys, tempfile, urllib.error, urllib.request, wave
from pathlib import Path

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent
SCENES = NAMO / "mg" / "scenes"
SKILLS = ROOT / "skills"

SCHEMA = "namo.job/1"

# SPEC §2 - every required key, and the enums that go with them
REQUIRED = ("schema", "kind", "runtime", "scene", "seconds", "fps",
            "ratio", "style", "emotion", "voice", "name")
ENUMS = {
    "kind": {"webshow", "explainer", "customer", "shot-test"},
    "runtime": {"mg", "rd"},
    "ratio": {"16:9", "9:16", "1:1"},
    "emotion": {"calm", "energetic", "dramatic", "deadpan"},
}

# SPEC §4 - output acceptance
MIN_BYTES = 20481          # "> 20480", so 20481 is the first acceptable size
DURATION_TOLERANCE = 0.02  # 2 %
DURATION_FLOOR = 0.5       # seconds
BLANK_STDDEV = 1.0         # luma stddev below this is a blank frame

# SPEC §1: a ratio is a real frame size, not a label
SIZE_FOR_RATIO = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1":  (1080, 1080),
}
BLANK_RATIO = 0.0          # SPEC §4: blank frames <= 0 %
SILENT_MEAN_DB = -50.0     # SPEC §4: an audio track whose mean volume is below this is silence

# voice: a job names its engine and id (SPEC §2). piper models live in VOICES (factory.yml caches
# it); chirp3 is Google Cloud TTS Chirp3-HD, authenticated by `gcloud auth print-access-token`
# (laptop: user login; Actions: keyless WIF as the TTS-only service account). A line may be sped
# up to fit its slot by at most ATEMPO_MAX; beyond that the job fails - never overlap, never truncate.
VOICES = ROOT / ".voices"
DEFAULT_VOICE = {"engine": "chirp3", "id": "hi-IN-Chirp3-HD-Kore"}   # fitbeats default
ATEMPO_MAX = 1.15
VOICE_ID = {
    "piper": re.compile(r"[a-z]{2,3}_[A-Z]{2}-\w+-\w+"),           # <lang>_<REGION>-<name>-<quality>
    "chirp3": re.compile(r"[a-z]{2,3}-[A-Z]{2}-Chirp3-HD-[A-Z][a-z]+"),  # <lang>-<REGION>-Chirp3-HD-<Name>
}
TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
TTS_PROJECT = "project-5e5df107-b8f8-4649-9d1"     # quota project, as namo-studio namo_audio.py
SR = 48000
# TTS pads both ends with silence; strip it so a line's length is its speech (namo_audio.fit)
EDGE_STRIP = ("silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
              "silenceremove=start_periods=1:start_threshold=-50dB,areverse")

# mastering (compose stage, every runtime): voice chain, optional ducked bed, then gain + a 4x
# oversampled limiter (not loudnorm: over its LRA/TP limits it drops to dynamic mode and misses I).
# The gain is set on the voice alone: in a speech-sparse film (gita-ep01, ~13 % speech) the bed in
# the pauses passes the R128 relative gate and pulls the film's integrated loudness ~5 LU under the
# speech; chasing -16 on the whole film then cost ~8 dB of limiting on the voice. With dense narration
# (explainers) film and speech loudness are the same. AAC overshoots the PCM peak, so the encoded film
# is measured and re-limited once.
LUFS = -16.0            # speech loudness (R128 integrated of the mastered voice), mobile-first
LUFS_TOL = 1.0          # LU: compose and verify_video reject speech outside LUFS +/- LUFS_TOL
TP_MAX = -1.5           # dBTP, measured on the encoded film
TP_CEIL = -2.5          # limiter ceiling before AAC (namo_studio measured +1.2 dB AAC overshoot)
VOICE_CHAIN = ("highpass=f=80,"
               "deesser=i=0.3:m=0.5:f=0.5,"
               "acompressor=threshold=-21dB:ratio=2.5:attack=8:release=150:knee=3,"
               "equalizer=f=3000:t=q:w=1:g=2")
BEDS = NAMO / "audio"   # <name>.flac seamless loops; job.bed names one
BED_UNDER_VOICE_DB = 22  # bed level under speech, after ducking
BED_DUCK_DB = 6          # how far the bed drops while the voice speaks (it swells back in the pauses)


def which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return ""


def chromium():
    return os.environ.get("PLAYWRIGHT_CHROME") or which(
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")


def sanitise_name(raw):
    """SPEC §2: collapse anything outside [A-Za-z0-9._-] to '-', and never allow . or .."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw)).strip("-")
    s = s.strip(".")
    return s[:80]


# ------------------------------------------------------------------ §2 job gate

def validate_job(job):
    """SPEC §2. Returns (ok, reason). Refuses before any renderer is called."""
    if not isinstance(job, dict):
        return False, "job must be a JSON object"
    missing = [k for k in REQUIRED if k not in job or job[k] in (None, "")]
    if missing:
        return False, "job is missing required key(s): %s" % ", ".join(missing)

    if job["schema"] != SCHEMA:
        return False, "job.schema must be %r, got %r" % (SCHEMA, job["schema"])

    for key, allowed in ENUMS.items():
        if not isinstance(job[key], str) or job[key] not in allowed:
            return False, "job.%s must be one of %s, got %r" % (
                key, ", ".join(sorted(allowed)), job[key])

    secs = job["seconds"]
    # NaN passes `<= 0` and `> max` both as False, which silently disabled the duration gate.
    if isinstance(secs, bool) or not isinstance(secs, (int, float)) or not math.isfinite(secs) or secs <= 0:
        return False, "job.seconds must be a finite number > 0, got %r" % (secs,)

    fps = job["fps"]
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or not (1 <= fps <= 120):
        return False, "job.fps must be between 1 and 120, got %r" % (fps,)

    workers = job.get("workers", 4)
    if not isinstance(workers, int) or isinstance(workers, bool) or not (1 <= workers <= 32):
        return False, "job.workers must be an integer 1-32, got %r" % (workers,)

    scene = str(job["scene"])
    if "/" in scene or "\\" in scene or scene in (".", "..") or scene.startswith("."):
        return False, "job.scene must be a plain name (namo/mg/scenes/<scene>/ or namo/rd/beats/<scene>.json)"

    voice = job["voice"]
    if not isinstance(voice, dict) or not voice.get("engine") or not voice.get("id"):
        return False, "job.voice must be an object with engine and id"
    if voice["engine"] not in VOICE_ID or not isinstance(voice["id"], str) \
            or not VOICE_ID[voice["engine"]].fullmatch(voice["id"]):
        return False, "job.voice %r: engine must be one of %s, with an id of that engine" % (voice, ", ".join(VOICE_ID))

    bed = job.get("bed")
    if bed is not None and not (isinstance(bed, str) and re.fullmatch(r"[\w-]+", bed) and (BEDS / (bed + ".flac")).exists()):
        return False, "job.bed must name a namo/audio/<bed>.flac, got %r (have: %s)" % (
            bed, ", ".join(sorted(p.stem for p in BEDS.glob("*.flac"))) or "none")

    # SPEC §2: name is sanitised, not rejected. The caller keeps its own copy in the job.
    name = sanitise_name(job["name"])
    if not name:
        return False, "job.name becomes empty after sanitising"

    rt = CANDIDATES.get(job["runtime"])
    if rt is None:
        return False, "unknown runtime %r" % (job["runtime"],)
    if secs > rt.max_seconds:
        return False, "job.seconds %s exceeds %s.max_seconds %s" % (secs, rt.name, rt.max_seconds)
    return True, "ok"


# ------------------------------------------------------------------ voice (compose stage)

# Read window.DUR / window.VO the way lemo core/render/events.mjs reads DUR / EV, with the
# render's own --q and --size, so VO arrives in output seconds.
PAGE_VO_JS = (
    "import { openDemo, closeServer } from './core/render/page.mjs';"
    "const [dir, q, w, h] = process.argv.slice(-4);"
    "const { browser, page } = await openDemo(dir, { w: +w, h: +h, q });"
    "const r = await page.evaluate(() => ({ dur: window.DUR, vo: window.VO }));"
    "console.log('NAMO_VO ' + JSON.stringify(r));"
    "await browser.close(); closeServer();")


def _num(x):
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)


def page_vo(d, film, qs, ratio):
    """(dur, vo, err). vo is None when the page exposes no window.VO."""
    w, h = SIZE_FOR_RATIO[ratio]
    r = subprocess.run(["node", "--input-type=module", "-e", PAGE_VO_JS, film, qs, str(w), str(h)],
                       cwd=str(d), env={**os.environ, "PLAYWRIGHT_CHROME": chromium()},
                       capture_output=True, encoding="utf-8", errors="replace", timeout=300)
    line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("NAMO_VO ")), None)
    if r.returncode != 0 or line is None:
        return None, None, "could not read window.VO from the page: exited %d; %s" % (
            r.returncode, ((r.stderr or "") + r.stdout).strip()[-300:] or "no output")
    got = json.loads(line[len("NAMO_VO "):])
    if not _num(got.get("dur")) or got["dur"] <= 0:
        return None, None, "the page exposes no usable window.DUR (%r)" % (got.get("dur"),)
    return float(got["dur"]), got.get("vo"), None


def voice_model(vid):
    """(model path, err). Fetches the piper model into VOICES when it is not there yet."""
    model = VOICES / (vid + ".onnx")
    if not (model.exists() and Path(str(model) + ".json").exists()):
        r = subprocess.run([sys.executable, "-m", "piper.download_voices", "--data-dir", str(VOICES), vid],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not model.exists():
            return None, "piper voice %s unavailable: %s" % (vid, ((r.stderr or "") + r.stdout).strip()[-200:])
    return model, None


def _piper(model, text, wav, rate):
    cfg = json.loads(Path(str(model) + ".json").read_text(encoding="utf-8"))
    scale = cfg.get("inference", {}).get("length_scale", 1.0) / rate
    src = Path(str(wav) + ".txt")
    src.write_text(text, encoding="utf-8")        # piper reads -i as utf-8; stdin would use the locale
    r = subprocess.run([sys.executable, "-m", "piper", "-m", str(model), "-i", str(src), "-f", str(wav),
                        "--length-scale", "%.4f" % scale], capture_output=True, text=True, timeout=300)
    src.unlink()
    if r.returncode != 0 or not Path(wav).exists():
        return "piper exited %d: %s" % (r.returncode, ((r.stderr or "") + r.stdout).strip()[-200:])
    return None


def _chirp3(vid, text, wav, rate, token):
    """namo-studio namo_audio._tts, minus its API-enabling retry: a failure fails the job, with the reason."""
    body = {"input": {"text": text}, "voice": {"languageCode": "-".join(vid.split("-")[:2]), "name": vid},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SR, "speakingRate": rate}}
    req = urllib.request.Request(TTS_URL, json.dumps(body).encode(), {
        "Authorization": "Bearer " + token, "x-goog-user-project": TTS_PROJECT, "Content-Type": "application/json"})
    try:
        audio = base64.b64decode(json.load(urllib.request.urlopen(req, timeout=120))["audioContent"])
    except urllib.error.HTTPError as e:
        return "chirp3 %s: TTS HTTP %d: %s" % (vid, e.code, e.read().decode("utf-8", "replace")[:300])
    except Exception as e:
        return "chirp3 %s: %s: %s" % (vid, type(e).__name__, str(e)[:200])
    Path(wav).write_bytes(audio)                  # LINEAR16 comes as a whole WAV file
    return None


def speaker(voice):
    """
    (say, err) for a job voice {engine, id}. say(text, wav, rate) -> (seconds, err) writes the
    line as a 48 kHz mono wav with the TTS edge silence stripped. No fallback to another voice.
    """
    eng, vid = voice.get("engine"), voice.get("id")
    if eng not in VOICE_ID:
        return None, "voice engine %r is not one of %s" % (eng, ", ".join(VOICE_ID))
    if not isinstance(vid, str) or not VOICE_ID[eng].fullmatch(vid):
        return None, "voice id %r is not a %s id (%s)" % (vid, eng, VOICE_ID[eng].pattern)
    if eng == "piper":
        model, err = voice_model(vid)
        if err:
            return None, err
        synth = lambda text, raw, rate: _piper(model, text, raw, rate)
    else:
        gcloud = which("gcloud")
        if not gcloud:
            return None, "chirp3 voice %s needs gcloud for an access token; gcloud is not installed" % vid
        r = subprocess.run([gcloud, "auth", "print-access-token"], capture_output=True, text=True, timeout=120)
        token = r.stdout.strip()                  # never printed or logged
        if r.returncode != 0 or not token:
            return None, "chirp3 voice %s: gcloud auth print-access-token exited %d: %s" % (
                vid, r.returncode, (r.stderr or "").strip()[-200:])
        synth = lambda text, raw, rate: _chirp3(vid, text, raw, rate, token)

    def say(text, wav, rate=1.0):
        raw = Path(str(wav) + ".raw.wav")
        err = synth(text, raw, rate)
        if err:
            return None, err
        r = subprocess.run([which("ffmpeg"), "-y", "-v", "error", "-i", str(raw), "-af", EDGE_STRIP,
                            "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(wav)], capture_output=True, text=True)
        raw.unlink()
        if r.returncode != 0:
            return None, "%s: edge-silence strip failed: %s" % (vid, (r.stderr or "").strip()[-200:])
        with wave.open(str(wav)) as w:
            secs = w.getnframes() / float(w.getframerate())
        if secs <= 0:
            return None, "%s spoke an empty clip" % vid
        return secs, None
    return say, None


def build_voice(job, vo, dur, work):
    """
    Compose stage. One TTS clip per window.VO line, placed at its t on a dur-second timeline.
    A line's slot ends at its `end`, the next line's t, or dur, whichever is first. A clip longer
    than its slot is sped up by at most ATEMPO_MAX; past that the job fails, naming the line.
    Returns (mix.wav, per-line report, err).
    """
    v = job["voice"]
    if not isinstance(vo, list) or not vo:
        return None, [], ("scene %r exposes no window.VO narration, but the job asks for voice %s: "
                          "refusing to make a silent film" % (job["scene"], v.get("id")))
    rate = v.get("rate", 1.0)
    if not _num(rate) or not 0.5 <= rate <= 2.0:
        return None, [], "job.voice.rate must be a number in 0.5..2.0, got %r" % (rate,)
    say, err = speaker(v)
    if err:
        return None, [], err
    vlang = re.split(r"[-_]", v["id"])[0]
    speaks = {vlang, "sa"} if vlang == "hi" else {vlang}      # Sanskrit is spoken by the Hindi voice
    for l in vo:
        if not (isinstance(l, dict) and isinstance(l.get("id"), str) and _num(l.get("t"))
                and isinstance(l.get("text"), str) and l["text"].strip()
                and isinstance(l.get("lang"), str) and ("end" not in l or _num(l["end"]))):
            return None, [], "window.VO line %r is not {id, t, end, text, lang}" % (l,)
        if l["lang"] not in speaks:
            return None, [], "VO line %s is lang %r; voice %s speaks %s" % (
                l["id"], l["lang"], v["id"], "/".join(sorted(speaks)))

    lines = sorted(vo, key=lambda l: l["t"])
    report, ins, fl = [], [], []
    for i, l in enumerate(lines):
        nxt = lines[i + 1]["t"] if i + 1 < len(lines) else dur
        slot = min(l.get("end", nxt), nxt, dur) - l["t"]
        if l["t"] < 0 or slot <= 0:
            return None, report, "VO line %s at %.2fs has no room on a %.2fs timeline" % (l["id"], l["t"], dur)
        clip = work / ("vo%02d.wav" % i)
        secs, err = say(l["text"], clip, rate)
        if err:
            return None, report, "VO line %s: %s" % (l["id"], err)
        tempo = max(1.0, secs / slot)
        if tempo > ATEMPO_MAX:
            return None, report, ("VO line %s speaks %.2fs but its slot is %.2fs (from %.2fs): needs %.2fx, "
                                  "more than %.2fx. Shorten the line or widen its slot."
                                  % (l["id"], secs, slot, l["t"], tempo, ATEMPO_MAX))
        report.append({"id": l["id"], "t": l["t"], "slot": round(slot, 2), "spoken": round(secs, 2),
                       "tempo": round(tempo, 3), "placed": round(secs / tempo, 2)})
        ins += ["-i", str(clip)]
        fl.append("[%d:a]aresample=48000%s,adelay=%d:all=1[a%d]"
                  % (i, ",atempo=%.5f" % tempo if tempo > 1 else "", round(l["t"] * 1000), i))
    mix = work / "mix.wav"
    # length by -t, not atrim: after atempo+adelay, atrim cut a 10 s timeline to 9 s
    fl.append("%samix=inputs=%d:normalize=0,apad=whole_dur=%.3f[m]"
              % ("".join("[a%d]" % i for i in range(len(lines))), len(lines), dur))
    r = subprocess.run([which("ffmpeg"), "-y", "-v", "error", *ins, "-filter_complex", ";".join(fl),
                        "-map", "[m]", "-t", "%.3f" % dur, "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le",
                        str(mix)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not mix.exists():
        return None, report, "voice mix failed: %s" % (r.stderr or "").strip()[-200:]
    return mix, report, None


def voice_for(vid):
    """A voice id names its engine: {engine, id}, or None when no engine owns the id."""
    eng = next((e for e, p in VOICE_ID.items() if isinstance(vid, str) and p.fullmatch(vid)), None)
    return {"engine": eng, "id": vid} if eng else None


def fit_beats(path, voice=DEFAULT_VOICE, rate=1.0, pad=0.4):
    """
    Retime an rd beats file so every beat's `vo` line fits its beat when spoken by `voice` at
    `rate` (+ `pad` s breath), keeping the total length. Beats that overrun take time from
    beats with room, in proportion to that room. Rewrites the file. (rows, err)
    """
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    beats = doc["beats"]
    total = sum(b["dur"] for b in beats)
    say, err = speaker(voice)
    if err:
        return [], err
    tmp = Path(tempfile.mkdtemp(prefix="namo-fit-"))
    try:
        spoken = []
        for b in beats:
            secs, err = say(b["vo"], tmp / (b["id"] + ".wav"), rate) if b.get("vo") else (0.0, None)
            if err:
                return [], "beat %s: %s" % (b["id"], err)
            spoken.append(secs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    need = [s + pad if s else 0.0 for s in spoken]
    if sum(need) > total:
        return [], "narration needs %.1fs (incl. %.1fs pad per line) but the film is %.1fs: shorten lines" % (
            sum(need), pad, total)
    room = [max(0.0, b["dur"] - n) for b, n in zip(beats, need)]
    short = sum(max(0.0, n - b["dur"]) for b, n in zip(beats, need))
    keep = 1 - short / sum(room) if short else 1.0
    durs = [round(max(n, b["dur"]) if r == 0 else n + r * keep, 2) for b, n, r in zip(beats, need, room)]
    durs[-1] = round(total - sum(durs[:-1]), 2)
    rows, t = [], 0.0
    for b, d, s in zip(beats, durs, spoken):
        rows.append({"id": b["id"], "was": b["dur"], "dur": d, "spoken": round(s, 2), "fill": round(s / d, 2)})
        b["t"], b["dur"] = round(t, 2), d
        t += d
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rows, None


def ebur128(path, pre=""):
    """(I LUFS, LRA LU, true peak dBTP) of the first audio stream, or None if ffmpeg cannot measure it.
    `pre` is a filter chain run before the meter (ending in a comma)."""
    r = subprocess.run([which("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                        "-af", pre + "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    s = (r.stderr or "")[(r.stderr or "").rfind("Summary:"):]
    got = [re.search(k + r":\s+(-?[\d.]+|-inf)", s) for k in ("I", "LRA", "Peak")]
    if r.returncode != 0 or not all(got):
        return None
    return tuple(float(m.group(1).replace("-inf", "-120")) for m in got)


def speech_lufs(path, lines):
    """R128 integrated loudness of `path` gated to the spoken VO windows (build_voice report:
    t .. t+placed), or None. The bed sits BED_UNDER_VOICE_DB under the speech there, so this is
    the speech loudness the listener hears, whatever the bed adds in the pauses."""
    sel = "+".join("between(t,%.3f,%.3f)" % (l["t"], l["t"] + l["placed"]) for l in lines)
    return ebur128(path, "aselect='%s'," % sel)


def compose(silent, mix, out, fps, bed, work):
    """
    Compose stage, every runtime. The voice mix goes through VOICE_CHAIN; an optional bed (job.bed)
    loops under it, sidechain-ducked to BED_UNDER_VOICE_DB below the speech. The gain that brings the
    voice alone to LUFS through a 4x-oversampled limiter at TP_CEIL is applied to the sum, so speech
    sits at LUFS in every film whatever the bed adds in the pauses; then it is muxed under the picture
    (fps, AAC). If AAC pushed the film's true peak over TP_MAX, the master is re-limited lower by the
    overshoot and the audio re-muxed once (picture copied).
    Speech that misses LUFS by more than LUFS_TOL after the last limiter pass fails the job.
    Returns ({I, LRA, TP of the film, speech: LUFS of the mastered voice}, err).
    """
    ff = which("ffmpeg")

    def run(*a):
        r = subprocess.run([ff, "-y", "-v", "error", *map(str, a)], capture_output=True, text=True)
        return None if r.returncode == 0 else "ffmpeg exited %d: %s" % (r.returncode, (r.stderr or "").strip()[-300:])

    voice = pre = work / "voice.wav"
    err = run("-i", mix, "-af", VOICE_CHAIN, "-c:a", "pcm_f32le", voice)
    lv = None if err else ebur128(voice)
    if not lv or lv[0] < -70:
        return None, "voice master: %s" % (err or "the voice mix is silent or unmeasurable (%r)" % (lv,))
    if bed:
        src = BEDS / (bed + ".flac")
        lb = ebur128(src)
        if not lb:
            return None, "bed %s cannot be measured" % src.name
        # sidechain reduction ~ (speech - threshold) * (1 - 1/ratio) = BED_DUCK_DB (namo_studio mix_audio)
        thr = lv[0] - BED_DUCK_DB / (1 - 1 / 20.0)
        gain = lv[0] - BED_UNDER_VOICE_DB + BED_DUCK_DB - lb[0]
        pre = work / "pre.wav"
        err = run("-i", voice, "-stream_loop", "-1", "-i", src, "-filter_complex",
                  "[0:a]asplit=2[v][key];[1:a]aformat=sample_rates=%d:channel_layouts=stereo,volume=%.2fdB[b];"
                  "[b][key]sidechaincompress=threshold=%.5f:ratio=20:attack=20:release=400:knee=2[d];"
                  "[v][d]amix=inputs=2:normalize=0:duration=first[m]" % (SR, gain, 10 ** (thr / 20)),
                  "-map", "[m]", "-c:a", "pcm_f32le", pre)
        if err:
            return None, "bed mix: " + err

    def master(ceil):
        """(master.wav, speech LUFS, err). The LUFS returned is measured after the last gain change."""
        dst = work / "master.wav"
        limit = lambda src, g: run("-i", src, "-af", "volume=%.3fdB,aresample=%d,alimiter=limit=%.5f:level=false:"
                                   "attack=1:release=60,aresample=%d" % (g, SR * 4, 10 ** (ceil / 20), SR),
                                   "-c:a", "pcm_f32le", dst)
        gain = LUFS - lv[0]
        for n in range(4):        # the limiter takes a little loudness; correct what it took
            err = limit(voice, gain)
            got = None if err else ebur128(dst)
            if not got:
                return None, None, "master: " + (err or "the limited voice cannot be measured")
            i = got[0]
            if abs(i - LUFS) < 0.1 or n == 3:
                break
            gain += LUFS - i
        if abs(i - LUFS) > LUFS_TOL:
            return None, i, ("master: speech is %.1f LUFS after 4 limiter passes, outside %.0f +/- %.0f: its crest "
                             "is too high for a %.1f dBTP ceiling" % (i, LUFS, LUFS_TOL, ceil))
        err = limit(pre, gain) if pre != voice else None
        return dst, i, ("master: " + err) if err else None

    aac = ["-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-shortest"]
    m, speech, err = master(TP_CEIL)
    if err:
        return None, err
    err = run("-i", silent, "-i", m, "-map", "0:v", "-map", "1:a", "-vf", "fps=%d,format=yuv420p" % fps,
              "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-r", fps, *aac, out)
    lf = None if err else ebur128(out)
    if lf and lf[2] > TP_MAX:
        m, speech, err = master(TP_CEIL - (lf[2] - TP_MAX) - 0.3)
        if err:
            return None, err
        redo = work / "redo.mp4"
        err = run("-i", out, "-i", m, "-map", "0:v", "-map", "1:a", "-c:v", "copy", *aac, redo)
        if not err:
            os.replace(redo, out)
            lf = ebur128(out)
    if err or not lf:
        return None, "mux: %s" % (err or "the film's audio cannot be measured")
    if lf[2] > TP_MAX:
        return None, "the film's true peak is %.2f dBTP, over %.1f, after one re-limit" % (lf[2], TP_MAX)
    return {"I": lf[0], "LRA": lf[1], "TP": lf[2], "speech": speech}, None


# ------------------------------------------------------------------ §3 runtimes

class Runtime:
    name = ""
    kind = "cpu"
    produces = "film"
    cost_per_sec_usd = 0.0
    max_seconds = 600

    def probe(self):
        """(ok, why). ok means: this can make a film now, not that its files exist."""
        return False, "not implemented"

    def render(self, job, outdir):
        raise NotImplementedError


class MgRuntime(Runtime):
    """SPEC §3. Vector motion graphics through the vendored lemo engine. CPU, free."""
    name = "mg"
    kind = "cpu"
    produces = "film"
    cost_per_sec_usd = 0.0

    def engine_dir(self):
        for d in (ROOT / "lemo", ROOT / "ftm" / "lemo", ROOT / "ftm"):
            if (d / "core" / "render" / "video.mjs").exists():
                return d
        return None

    def scenes(self):
        if not SCENES.is_dir():
            return []
        return sorted(p.name for p in SCENES.iterdir()
                      if p.is_dir() and (p / "scene.json").exists())

    def probe(self):
        d = self.engine_dir()
        if not d:
            return False, "lemo core/render/video.mjs not found (run namo/bootstrap.sh)"
        if not which("node"):
            return False, "node missing"
        if not chromium():
            return False, "no chrome/chromium and PLAYWRIGHT_CHROME unset"
        for b in ("ffmpeg", "ffprobe"):
            if not which(b):
                return False, b + " missing (needed to compose and verify, SPEC §4)"
        scenes = self.scenes()
        if not scenes:
            return False, "no scene with a scene.json under namo/mg/scenes"
        # execute the binaries once: `which` says a file exists, not that it runs
        for cmd in (["node", "--version"], ["ffmpeg", "-version"], ["ffprobe", "-version"]):
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=20)
            except Exception as e:
                return False, "%s did not run: %s" % (cmd[0], str(e)[:80])
            if r.returncode != 0:
                return False, "%s exited %d" % (cmd[0], r.returncode)
        try:
            r = subprocess.run([chromium(), "--version"], capture_output=True, timeout=25)
            if r.returncode != 0:
                return False, "chrome exited %d" % r.returncode
        except Exception as e:
            return False, "chrome did not run: %s" % str(e)[:80]
        # Invariant R1: prove it renders. One still, from the smallest scene, thrown away.
        # A version check says the tool exists; this says it works.
        if os.environ.get("NAMO_PROBE_RENDER", "1") == "1":
            try:
                scene = scenes[0]
                tag = "probe-%s" % os.getpid()
                work = d / "films" / tag          # lemo resolves films/<x> from its own cwd
                try:
                    if work.exists():
                        shutil.rmtree(work, ignore_errors=True)
                    work.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(SCENES / scene, work)
                    css = NAMO / "mg" / "fonts.css"
                    if css.exists():
                        shutil.copy(css, work / "fonts.css")
                    outdir = Path(tempfile.mkdtemp(prefix="namo-probe-out-"))
                    env = {**os.environ, "PLAYWRIGHT_CHROME": chromium()}
                    pr = subprocess.run(
                        ["node", "core/render/still.mjs", "films/" + tag, "1.0",
                         "--out", str(outdir), "--prefix", "still_"],
                        cwd=str(d), env=env, capture_output=True, text=True, timeout=180)
                    made = sorted(outdir.glob("still_*.jpg"))
                    if pr.returncode != 0 or not made:
                        return False, ("render probe failed: exited %d, %d still(s)%s"
                                       % (pr.returncode, len(made),
                                          "; " + ((pr.stderr or pr.stdout or "").strip()[-260:] or "no output")))
                    if made[0].stat().st_size < 1000:
                        return False, "render probe produced a %d-byte still" % made[0].stat().st_size
                finally:
                    shutil.rmtree(work, ignore_errors=True)
                    shutil.rmtree(locals().get("outdir", Path("/nonexistent")), ignore_errors=True)
            except Exception as e:
                return False, "render probe error: %s: %s" % (type(e).__name__, str(e)[:120])
        # the voice is not probed here: a job names its own voice and build_voice() checks that
        # backend first thing at render time, so a missing one fails the job, not the runtime
        return True, "engine=%s scenes=%d, chrome ok, one still rendered" % (d.name, len(scenes))

    def scene_meta(self, scene):
        """Read and validate the scene's own declaration. Fail closed on anything unclear."""
        src = SCENES / scene
        if not src.is_dir():
            return None, "scene %r is not on disk" % scene
        meta = src / "scene.json"
        if not meta.exists():
            return None, "scene %r has no scene.json; cannot tell what it honours" % scene
        try:
            m = json.loads(meta.read_text())
        except Exception as e:
            return None, "scene %r scene.json unreadable: %s" % (scene, e)
        if "kind" not in m:
            return None, "scene %r does not declare its kind" % scene
        return m, None

    def honours(self, scene, job):
        """
        SPEC §6. This is ADVISORY, not a veto. The plan is delivered to the page through
        `--q`/`--size`; the scene applies it at render time. What we refuse here is only a
        scene that is structurally unable to apply it: no scene.json, unreadable, or a kind
        that belongs to a different film. Everything else is applied, and §4 then judges the
        result. Refusing every mismatch would mean the renderer never sees a new value, which
        is exactly the hole goldfish round 7 named.
        """
        m, err = self.scene_meta(scene)
        if err:
            return err
        if m["kind"] != job["kind"]:
            return "scene %r is for kind %r, the brief asks for %r" % (scene, m["kind"], job["kind"])
        # An authored scene cannot follow the plan. Accept it only when the brief already
        # matches what it was authored as; otherwise the result would not match the brief.
        if not m.get("applicable", False):
            mismatch = []
            for k in ("ratio", "seconds", "style", "emotion"):
                if k in m and m[k] != job.get(k):
                    mismatch.append("%s %r vs %r" % (k, m[k], job.get(k)))
            if mismatch:
                return ("scene %r is authored (%s) and cannot be changed by a plan; "
                        "brief asks for %s. Re-author the scene, or change the brief."
                        % (scene, ", ".join(mismatch), job.get("kind")))
        return None

    def render(self, job, outdir):
        ok, why = validate_job(job)
        if not ok:
            return {"ok": False, "error": why}
        problem = self.honours(job["scene"], job)
        if problem:
            return {"ok": False, "error": problem}

        d = self.engine_dir()
        outdir = Path(outdir).resolve()
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / (sanitise_name(job["name"]) + ".mp4")
        if out.exists():
            out.unlink()            # SPEC §4 / O3: a stale file never satisfies a run

        # lemo resolves `films/<scene>` relative to its own cwd, so the scene has to live
        # inside the engine dir. Use a unique name so parallel jobs cannot collide (D11),
        # and remove it afterwards.
        tag = "%s-%s" % (sanitise_name(job["name"]), os.getpid())
        film = d / "films" / tag
        work = film
        try:
            if film.exists():
                shutil.rmtree(film, ignore_errors=True)
            film.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SCENES / job["scene"], film)
            css = NAMO / "mg" / "fonts.css"
            if css.exists():
                shutil.copy(css, film / "fonts.css")

            # D6: the decision reaches the page through lemo's own channel. `--q k=v` becomes
            # ?k=v on the scene URL (core/render/page.mjs), and `--size` sets the frame. The
            # scene reads location.search, so seconds/ratio/style are inputs, not a wish.
            (film / "render.json").write_text(json.dumps({
                "schema": SCHEMA, "kind": job["kind"], "seconds": job["seconds"],
                "fps": job["fps"], "ratio": job["ratio"], "style": job["style"],
                "emotion": job["emotion"], "voice": job["voice"], "name": job["name"],
            }, indent=1))

            authored = (json.loads((SCENES / job["scene"] / "scene.json").read_text())
                        if (SCENES / job["scene"] / "scene.json").exists() else {})
            qs = "&".join([
                "authoredSeconds=%s" % authored.get("seconds", ""),
                "authoredRatio=%s" % authored.get("ratio", ""),
                "seconds=%s" % job["seconds"],
                "ratio=%s" % job["ratio"],
                "style=%s" % job["style"],
                "emotion=%s" % job["emotion"],
                "kind=%s" % job["kind"],
                "renderjson=1",
            ])
            # Voice before pictures: the narration is cheap to check and a scene that cannot
            # be voiced should fail in seconds, not after a full render.
            dur, vo, err = page_vo(d, "films/" + tag, qs, job["ratio"])
            if err:
                return {"ok": False, "error": err}
            mix, lines, err = build_voice(job, vo, dur, film)
            if err:
                return {"ok": False, "error": err, "voice": lines}

            silent = film / "silent.mp4"
            env = {**os.environ, "PLAYWRIGHT_CHROME": chromium(),
                   "NAMO_JOB": json.dumps(job)}
            cmd = ["node", "core/render/video.mjs", "films/" + tag,
                   "--fps", str(int(job["fps"])),
                   "--workers", str(int(job.get("workers", 4))),
                   "--q", qs,
                   "--size", "%dx%d" % SIZE_FOR_RATIO[job["ratio"]],
                   "--out", str(silent)]
            try:
                r = subprocess.run(cmd, cwd=str(d), env=env, capture_output=True, text=True)
            except FileNotFoundError as e:
                return {"ok": False, "error": "node not found: %s" % e,
                        "cmd": " ".join(cmd), "cwd": str(d)}
            except Exception as e:
                return {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                        "cmd": " ".join(cmd), "cwd": str(d)}
            log = ((r.stdout or "") + (r.stderr or "")).strip()
            if r.returncode != 0:
                return {"ok": False, "error": "lemo exited %d" % r.returncode,
                        "cmd": " ".join(cmd), "cwd": str(d),
                        "log": log[-3000:] or "(both stdout and stderr were empty)",
                        "video_mjs": str(d / "core/render/video.mjs") if d else ""}
            if not silent.exists():
                return {"ok": False, "error": "lemo reported success but wrote no file", "log": log}
            # compose: master the voice (+ bed) and mux it under the picture
            audio, err = compose(silent, mix, out, int(job["fps"]), job.get("bed"), film)
            if err:
                return {"ok": False, "error": err, "log": log[-3000:], "voice": lines}
            log += "\naudio: speech %(speech).1f LUFS; film I %(I).1f LUFS, LRA %(LRA).1f LU, TP %(TP).1f dBTP" % audio
            # SPEC §4 / O1: success is not "a file appeared". Verify here, so a caller using
            # REGISTRY directly gets the same guarantee as the CLI.
            good, msg = verify_video(out, job["seconds"], job["voice"], lines)
            if not good:
                return {"ok": False, "out": str(out), "error": "rejected: " + msg, "log": log, "voice": lines}
            return {"ok": True, "out": str(out), "produces": "film", "verified": msg, "log": log,
                    "voice": lines, "audio": audio}
        finally:
            shutil.rmtree(work, ignore_errors=True)


class RdRuntime(Runtime):
    """
    rendiv (React + TypeScript) motion-design explainers, namo/rd. CPU, free.
    The scene is a beats file, namo/rd/beats/<scene>.json; its `vo` lines are the narration.
    Voice and compose are the mg ones: build_voice() and compose().
    """
    name = "rd"
    kind = "cpu"
    produces = "film"
    cost_per_sec_usd = 0.0

    def __init__(self):
        self.dir = NAMO / "rd"

    def beats(self):
        return sorted(p.stem for p in (self.dir / "beats").glob("*.json"))

    def node(self, args, timeout=None):
        return subprocess.run(["node", "render.mjs", *args], cwd=str(self.dir), capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout)

    def probe(self):
        for b in ("node", "ffmpeg", "ffprobe"):
            if not which(b):
                return False, b + " missing"
        if not (self.dir / "node_modules" / "@rendiv" / "renderer").is_dir():
            return False, "namo/rd deps missing (cd namo/rd && npm ci && npx playwright install chromium)"
        beats = self.beats()
        if not beats:
            return False, "no beats file under namo/rd/beats"
        # R1: prove it renders - one second of the first beats file at 320x180, thrown away
        if os.environ.get("NAMO_PROBE_RENDER", "1") == "1":
            tmp = Path(tempfile.mkdtemp(prefix="namo-rd-probe-"))
            try:
                film = tmp / "probe.mp4"
                r = self.node(["--beats", str(self.dir / "beats" / (beats[0] + ".json")), "--seconds", "1",
                               "--size", "320x180", "--fps", "10", "--concurrency", "1", "--out", str(film)],
                              timeout=300)
                if r.returncode != 0 or not film.exists() or film.stat().st_size < 1000:
                    return False, "render probe failed: exited %d; %s" % (
                        r.returncode, ((r.stderr or "") + (r.stdout or "")).strip()[-260:] or "no output")
            except Exception as e:
                return False, "render probe error: %s: %s" % (type(e).__name__, str(e)[:120])
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return True, "beats=%d, 1 s film rendered" % len(beats)

    def render(self, job, outdir):
        ok, why = validate_job(job)
        if not ok:
            return {"ok": False, "error": why}
        src = self.dir / "beats" / (job["scene"] + ".json")
        if not src.exists():
            return {"ok": False, "error": "beats file namo/rd/beats/%s.json is not on disk (have: %s)"
                    % (job["scene"], ", ".join(self.beats()) or "none")}
        try:
            declared = json.loads(src.read_text(encoding="utf-8")).get("kind")
        except Exception as e:
            return {"ok": False, "error": "beats file %s unreadable: %s" % (src.name, e)}
        if declared != job["kind"]:      # SPEC §6: never render another kind's film
            return {"ok": False, "error": "beats %r is for kind %r, the brief asks for %r"
                    % (job["scene"], declared, job["kind"])}

        outdir = Path(outdir).resolve()
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / (sanitise_name(job["name"]) + ".mp4")
        if out.exists():
            out.unlink()            # SPEC §4 / O3
        work = Path(tempfile.mkdtemp(prefix="namo-rd-"))
        try:
            silent = work / "silent.mp4"
            base = ["--beats", str(src), "--seconds", str(job["seconds"]), "--ratio", job["ratio"],
                    "--fps", str(int(job["fps"])), "--out", str(silent)]
            # voice before pictures: the narration is cheap to check, the render is not
            r = self.node(base + ["--vo-only", "1"], timeout=120)
            vo_file = work / "silent.vo.json"
            if r.returncode != 0 or not vo_file.exists():
                return {"ok": False, "error": "render.mjs --vo-only exited %d" % r.returncode,
                        "log": ((r.stderr or "") + (r.stdout or ""))[-1500:]}
            mix, lines, err = build_voice(job, json.loads(vo_file.read_text(encoding="utf-8")),
                                          float(job["seconds"]), work)
            if err:
                return {"ok": False, "error": err, "voice": lines}

            r = self.node(base + ["--concurrency", str(int(job.get("workers", 4)))])
            log = ((r.stdout or "") + (r.stderr or "")).strip()
            if r.returncode != 0 or not silent.exists():
                return {"ok": False, "error": "rendiv exited %d" % r.returncode, "log": log[-3000:], "voice": lines}
            audio, err = compose(silent, mix, out, int(job["fps"]), job.get("bed"), work)
            if err:
                return {"ok": False, "error": err, "log": log[-3000:], "voice": lines}
            log += "\naudio: speech %(speech).1f LUFS; film I %(I).1f LUFS, LRA %(LRA).1f LU, TP %(TP).1f dBTP" % audio
            good, msg = verify_video(out, job["seconds"], job["voice"], lines)
            if not good:
                return {"ok": False, "out": str(out), "error": "rejected: " + msg, "log": log, "voice": lines}
            return {"ok": True, "out": str(out), "produces": "film", "verified": msg, "log": log, "voice": lines,
                    "audio": audio}
        finally:
            shutil.rmtree(work, ignore_errors=True)


CANDIDATES = {rt.name: rt for rt in (MgRuntime(), RdRuntime())}
REGISTRY = {}


def register_proven():
    """SPEC §3 / R1. Only proven runtimes enter REGISTRY. Fail closed."""
    report = {}
    REGISTRY.clear()
    for name, rt in CANDIDATES.items():
        ok, why = rt.probe()
        report[name] = (ok, why)
        if ok:
            REGISTRY[name] = rt
    return report


# ------------------------------------------------------------------ §4 verify

def verify_video(path, seconds, voice=None, lines=None):
    """
    SPEC §4 / O1-O3. Returns (ok, reason).
    A failure to run a check is a failure: no bare except that returns True.
    With a voice, the film must also carry an audio stream of the same length that is not silent,
    and its speech - gated to the VO windows in `lines` (the build_voice report) - must sit at
    LUFS +/- LUFS_TOL. A voiced film without its lines cannot be checked, so it is rejected.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) \
            or not math.isfinite(seconds) or seconds <= 0:
        return False, "refusing to verify without a target duration (seconds must be a number > 0)"

    p = Path(path)
    if not p.exists():
        return False, "missing %s" % p
    size = p.stat().st_size
    if size < MIN_BYTES:
        return False, "size %d bytes is not more than %d" % (size, MIN_BYTES - 1)

    ffprobe = which("ffprobe")
    if not ffprobe:
        return False, "ffprobe missing: cannot verify (SPEC §4 O2 says reject, not pass)"
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        return False, "undecodable: %s" % (r.stderr or "").strip()[:140]
    try:
        dur = float(r.stdout.strip())
    except ValueError:
        return False, "ffprobe returned no duration"

    tol = max(DURATION_FLOOR, DURATION_TOLERANCE * float(seconds))
    if abs(dur - float(seconds)) > tol:
        return False, "duration %.2fs is outside %.2fs +/- %.2fs" % (dur, seconds, tol)

    ffmpeg = which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg missing: cannot sample pixels (SPEC §4 O2 says reject, not pass)"
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(p), "-an",
                           "-vf", "fps=1,scale=64:36", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                          capture_output=True)
    if proc.returncode != 0:
        return False, "frame sampling failed: %s" % (proc.stderr or b"").decode("utf8", "ignore")[:140]
    raw = proc.stdout
    frame_bytes = 64 * 36
    n = len(raw) // frame_bytes
    if n == 0:
        return False, "could not decode a single frame"
    if len(raw) % frame_bytes != 0:
        return False, "frame sampler returned a partial frame (%d bytes)" % (len(raw) % frame_bytes)

    flat = 0
    for i in range(n):
        chunk = raw[i * frame_bytes:(i + 1) * frame_bytes]
        mean = sum(chunk) / float(frame_bytes)
        var = sum((b - mean) ** 2 for b in chunk) / float(frame_bytes)
        if var ** 0.5 < BLANK_STDDEV:
            flat += 1
    ratio = flat / float(n)
    if ratio > BLANK_RATIO:
        return False, "%d of %d sampled frames are blank (%.0f%%)" % (flat, n, ratio * 100)
    if not voice:
        return True, "%.1fs, %d frames sampled, 0 blank" % (dur, n)

    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return False, "the job has voice %s but the film has no audio stream" % voice.get("id")
    try:
        adur = float(r.stdout.split()[0])
    except ValueError:
        return False, "ffprobe returned no audio duration (%r)" % r.stdout.strip()[:40]
    if abs(adur - float(seconds)) > tol:
        return False, "audio %.2fs is outside %.2fs +/- %.2fs" % (adur, seconds, tol)
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(p), "-map", "0:a:0",
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    mean = re.search(r"mean_volume:\s*(-?inf|-?[\d.]+) dB", r.stderr or "")
    peak = re.search(r"max_volume:\s*(-?inf|-?[\d.]+) dB", r.stderr or "")
    if r.returncode != 0 or not mean or not peak:
        return False, "could not measure the audio level: %s" % (r.stderr or "").strip()[-140:]
    mean, peak = float(mean.group(1)), float(peak.group(1))
    if mean < SILENT_MEAN_DB:
        return False, "audio is silent: mean %.1f dB, max %.1f dB (silence is below %.0f dB mean)" % (
            mean, peak, SILENT_MEAN_DB)
    if not lines:
        return False, "the job has voice %s but no VO line timings were given: cannot check speech loudness" % (
            voice.get("id"))
    sl = speech_lufs(p, lines)
    if not sl:
        return False, "could not measure the speech loudness over %d VO line(s)" % len(lines)
    if abs(sl[0] - LUFS) > LUFS_TOL:
        return False, "speech is %.1f LUFS over its %d VO line(s), outside %.0f +/- %.0f" % (
            sl[0], len(lines), LUFS, LUFS_TOL)
    return True, "%.1fs, %d frames sampled, 0 blank; audio %.1fs, mean %.1f dB, max %.1f dB; speech %.1f LUFS" % (
        dur, n, adur, mean, peak, sl[0])


# ------------------------------------------------------------------ §5 pipelines

def check_pipeline(path):
    """
    SPEC §5 / P1. Returns (ok, reason). Skill names are matched whether quoted or bare,
    in `skill: x` form and in YAML list form; comments are ignored.
    """
    p = Path(path)
    if not p.exists():
        return False, [], "missing %s" % p
    raw = p.read_text(errors="ignore")
    lines = []
    for line in raw.splitlines():
        out, quote = [], None
        for ch in line:
            if quote:
                if ch == quote:
                    quote = None
                out.append(ch)
                continue
            if ch in "\"'":
                quote = ch
                out.append(ch)
                continue
            if ch == "#":
                break                     # a real comment: outside quotes only
            out.append(ch)
        cleaned = "".join(out).rstrip()
        if cleaned.strip():
            lines.append(cleaned)
    text = "\n".join(lines)

    named = set()
    for m in re.finditer(r"skill:\s*[\"']?([\w/.-]+)[\"']?", text):
        named.add(m.group(1))
    for m in re.finditer(r"^[\s-]+[\"']?((?:pipelines|meta|creative|core)/[\w/.-]+)[\"']?\s*$", text, re.M):
        named.add(m.group(1))
    for m in re.finditer(r"\[([^\]]*)\]", text):        # flow lists
        for item in m.group(1).split(","):
            item = item.strip().strip("\"'")
            if re.fullmatch(r"(?:pipelines|meta|creative|core)/[\w/.-]+", item):
                named.add(item)


    # list-form skills with no known prefix: a bare item that is not a path, not a number,
    # not a boolean and contains a '/', a '-' or a known pipeline word is treated as a skill.
    for m in re.finditer(r"^\s*-\s*[\"']?([A-Za-z][\w/.-]*)[\"']?\s*$", text, re.M):
        tok = m.group(1)
        if tok.lower() in ("true", "false", "null", "none"):
            continue
        if re.fullmatch(r"[\w-]+", tok) and not any(
                k in tok.lower() for k in ("director", "producer", "reviewer", "skill", "protocol")):
            continue          # plain word: a mode or a flag, not a skill
        named.add(tok)

    if not named:
        return False, [], "no skills named: not a pipeline"
    missing = sorted(s for s in named if not (SKILLS / (s + ".md")).exists())
    if missing:
        return False, missing, "%d of %d skill(s) have no file: %s" % (
            len(missing), len(named), ", ".join(missing[:8]))
    return True, [], "%d skills present" % len(named)


# ------------------------------------------------------------------ cli

def _usage():
    print(__doc__)
    return 1


def main(argv):
    if not argv:
        return _usage()
    cmd = argv[0]

    if cmd == "runtimes":
        for n, rt in CANDIDATES.items():
            print("%-4s %-4s %-6s cost=%s max=%ss" % (n, rt.kind, rt.produces,
                                                      rt.cost_per_sec_usd, rt.max_seconds))
        return 0

    if cmd == "probe":
        report = register_proven()
        bad = 0
        for n, (ok, why) in report.items():
            print("%-4s %s %s" % (n, "OK  " if ok else "FAIL", why))
            if not ok:
                bad += 1
        print("REGISTRY: %s" % (", ".join(sorted(REGISTRY)) or "empty"))
        return 1 if bad else 0

    if cmd == "checkjob":
        ok, why = validate_job(json.loads(Path(argv[1]).read_text()))
        print(("PASS " if ok else "REFUSE ") + why)
        return 0 if ok else 1

    if cmd == "fitbeats":
        voice = voice_for(argv[2]) if len(argv) > 2 else DEFAULT_VOICE
        if not voice:
            print("FAIL voice id %r belongs to no engine (%s)" % (argv[2], ", ".join(VOICE_ID)))
            return 1
        rows, err = fit_beats(argv[1], voice, *[float(x) for x in argv[3:4]])
        for r in rows:
            print("%-5s dur %5.2fs -> %5.2fs  spoken %5.2fs  fill %.2f" % (r["id"], r["was"], r["dur"], r["spoken"], r["fill"]))
        print(("FAIL " + err) if err else "fitted %s" % argv[1])
        return 1 if err else 0

    if cmd == "pipeline":
        ok, missing, why = check_pipeline(argv[1])
        print(("PASS " if ok else "REFUSE ") + why)
        for m in missing:
            print("   missing: skills/%s.md" % m)
        return 0 if ok else 1

    if cmd == "render":
        job = json.loads(Path(argv[1]).read_text())
        outdir = Path(argv[2]) if len(argv) > 2 else Path("out")

        ok, why = validate_job(job)
        if not ok:
            print("REFUSED: " + why)
            return 2

        rt = REGISTRY.get(job["runtime"])      # the job decides the runtime, not the CLI
        if rt is None:
            report = register_proven()
            rt = REGISTRY.get(job["runtime"])
            if rt is None:
                print("%s is not proven: %s" % (job["runtime"], report.get(job["runtime"], (False, "unknown"))[1]))
                return 2

        res = rt.render(job, outdir)
        if res.get("log"):
            print(res["log"][-1500:])
        for l in res.get("voice", []):
            print("voice %-6s t=%6.2fs slot %5.2fs spoken %5.2fs tempo %.3f placed %5.2fs"
                  % (l["id"], l["t"], l["slot"], l["spoken"], l["tempo"], l["placed"]))
        if not res.get("ok"):
            print("RENDER FAILED: %s" % res.get("error"))
            return 1
        good, msg = verify_video(res["out"], job["seconds"], job["voice"], res.get("voice"))
        print(("PASS " if good else "REJECT ") + msg)
        return 0 if good else 1

    return _usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
else:
    register_proven()      # SPEC §3 / R2: importers see the same REGISTRY

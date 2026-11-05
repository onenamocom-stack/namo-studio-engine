#!/usr/bin/env python3
"""
namo/engine.py - the one door into NAMO's production engine.

This file implements SPEC.md section by section. Every rule below names its section.

    python namo/engine.py probe              prove runtimes; exit 1 if any is missing
    python namo/engine.py runtimes           list candidates, no probing
    python namo/engine.py render <job.json>  validate, render, verify
    python namo/engine.py pipeline <yaml>    refuse a pipeline whose skills are missing
    python namo/engine.py checkjob <json>    validate only

Design rule taken from the spec, section 6: a runtime that cannot honour the brief must
refuse the job. A film that silently ignores the brief is worse than no film, because it
looks like success.
"""
import json, math, os, re, shutil, subprocess, sys, tempfile, wave
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
    "runtime": {"mg", "h3"},
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

# voice: piper models live here (factory.yml caches it); a line may be sped up to fit its
# slot by at most ATEMPO_MAX, beyond that the job fails - never overlap, never truncate
VOICES = ROOT / ".voices"
DEFAULT_VOICE = "hi_IN-pratham-medium"
ATEMPO_MAX = 1.15
VOICE_ID = re.compile(r"[a-z]{2,3}_[A-Z]{2}-\w+-\w+")      # piper's <lang>_<REGION>-<name>-<quality>


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
    if "/" in scene or scene in (".", "..") or scene.startswith("."):
        return False, "job.scene must be a plain directory name inside namo/mg/scenes"

    voice = job["voice"]
    if not isinstance(voice, dict) or not voice.get("engine") or not voice.get("id"):
        return False, "job.voice must be an object with engine and id"

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
    if not isinstance(vid, str) or not VOICE_ID.fullmatch(vid):
        return None, "voice id %r is not a piper voice (<lang>_<REGION>-<name>-<quality>)" % (vid,)
    model = VOICES / (vid + ".onnx")
    if not (model.exists() and Path(str(model) + ".json").exists()):
        r = subprocess.run([sys.executable, "-m", "piper.download_voices", "--data-dir", str(VOICES), vid],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not model.exists():
            return None, "piper voice %s unavailable: %s" % (vid, ((r.stderr or "") + r.stdout).strip()[-200:])
    return model, None


def speak(model, text, wav, rate=1.0):
    """Synthesise one line with piper into wav. (seconds, err)."""
    cfg = json.loads(Path(str(model) + ".json").read_text(encoding="utf-8"))
    scale = cfg.get("inference", {}).get("length_scale", 1.0) / rate
    src = Path(str(wav) + ".txt")
    src.write_text(text, encoding="utf-8")        # piper reads -i as utf-8; stdin would use the locale
    r = subprocess.run([sys.executable, "-m", "piper", "-m", str(model), "-i", str(src), "-f", str(wav),
                        "--length-scale", "%.4f" % scale], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not Path(wav).exists():
        return None, "piper exited %d: %s" % (r.returncode, ((r.stderr or "") + r.stdout).strip()[-200:])
    with wave.open(str(wav)) as w:
        secs = w.getnframes() / float(w.getframerate())
    if secs <= 0:
        return None, "piper wrote an empty clip"
    return secs, None


def build_voice(job, vo, dur, work):
    """
    Compose stage. One piper clip per window.VO line, placed at its t on a dur-second timeline.
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
    model, err = voice_model(v["id"])
    if err:
        return None, [], err
    vlang = v["id"].split("_")[0]
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
        secs, err = speak(model, l["text"], clip, rate)
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
        for b in ("ffmpeg", "ffprobe", "sh"):
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
        # every job carries a voice (SPEC §2), so a runtime that cannot speak cannot make a film
        model, err = voice_model(DEFAULT_VOICE)
        if err:
            return False, "voice: " + err
        tmp = Path(tempfile.mkdtemp(prefix="namo-probe-voice-"))
        try:
            secs, err = speak(model, "नमो", tmp / "probe.wav")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if err:
            return False, "voice %s: %s" % (DEFAULT_VOICE, err)
        return True, "engine=%s scenes=%d, chrome ok, one still rendered, voice %s spoke %.2fs" % (
            d.name, len(scenes), DEFAULT_VOICE, secs)

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
            # compose: lemo's mux (two-pass loudnorm); grain 0, every mg style is vector
            m = subprocess.run([which("sh"), "core/render/mux.sh", silent.as_posix(), mix.as_posix(),
                                out.as_posix(), str(int(job["fps"])), "0"],
                               cwd=str(d), capture_output=True, text=True)
            log += "\n" + ((m.stdout or "") + (m.stderr or "")).strip()
            if m.returncode != 0 or not out.exists():
                return {"ok": False, "error": "mux exited %d" % m.returncode, "log": log[-3000:], "voice": lines}
            # SPEC §4 / O1: success is not "a file appeared". Verify here, so a caller using
            # REGISTRY directly gets the same guarantee as the CLI.
            good, msg = verify_video(out, job["seconds"], job["voice"])
            if not good:
                return {"ok": False, "out": str(out), "error": "rejected: " + msg, "log": log, "voice": lines}
            return {"ok": True, "out": str(out), "produces": "film", "verified": msg, "log": log,
                    "voice": lines}
        finally:
            shutil.rmtree(work, ignore_errors=True)


class H3Runtime(Runtime):
    """SPEC §3. MiniMax H3 on outsourced GPU. Produces raw stems, never a finished film."""
    name = "h3"
    kind = "gpu"
    produces = "stems"
    cost_per_sec_usd = 0.00039
    max_seconds = 120

    def __init__(self):
        self.script = NAMO / "namo_gpu.py"

    def probe(self):
        key = os.environ.get("RUNPOD_KEY")
        if not key:
            return False, "RUNPOD_KEY unset"
        if not self.script.exists():
            return False, "namo/namo_gpu.py missing"
        try:
            import urllib.request
            req = urllib.request.Request("https://rest.runpod.io/v1/pods",
                                         headers={"Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=20) as f:
                if f.status != 200:
                    return False, "provider replied %s" % f.status
        except Exception as e:
            return False, "provider unreachable: %s" % str(e)[:100]
        return True, "provider reachable, dispatcher present"

    def render(self, job, outdir):
        ok, why = validate_job(job)
        if not ok:
            return {"ok": False, "kind": "stems", "produces": "stems", "error": why}
        ok, why = self.probe()          # exactly one probe call per render
        if not ok:
            return {"ok": False, "kind": "stems", "produces": "stems", "error": why}

        stem_dir = Path(outdir).resolve() / "stems" / sanitise_name(job["name"])
        if stem_dir.exists():
            shutil.rmtree(stem_dir, ignore_errors=True)   # SPEC §4 / O3
        stem_dir.mkdir(parents=True, exist_ok=True)

        r = subprocess.run([sys.executable, str(self.script),
                            "--job", json.dumps(job), "--out", str(stem_dir)],
                           capture_output=True, text=True)
        log = ((r.stdout or "") + (r.stderr or ""))[-4000:]
        stems = sorted(str(p) for p in stem_dir.glob("*.mp4"))
        manifest = stem_dir / "stems.json"
        manifest.write_text(json.dumps({"job": job, "stems": stems, "exit": r.returncode}, indent=1))
        if r.returncode != 0:
            return {"ok": False, "kind": "stems", "produces": "stems", "error": "dispatcher exited %d" % r.returncode, "log": log}
        if not stems:
            return {"ok": False, "kind": "stems", "produces": "stems", "error": "dispatcher produced no stems", "log": log}
        return {"ok": True, "kind": "stems", "produces": "stems", "stems": stems,
                "manifest": str(manifest), "log": log}


CANDIDATES = {rt.name: rt for rt in (MgRuntime(), H3Runtime())}
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

def verify_video(path, seconds, voice=None):
    """
    SPEC §4 / O1-O3. Returns (ok, reason).
    A failure to run a check is a failure: no bare except that returns True.
    With a voice, the film must also carry an audio stream of the same length that is not silent.
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
    return True, "%.1fs, %d frames sampled, 0 blank; audio %.1fs, mean %.1f dB, max %.1f dB" % (
        dur, n, adur, mean, peak)


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
        if res.get("produces", res.get("kind")) != "film":
            print("STEMS OK (%s): %d file(s) in %s — a film still has to be composed"
                  % (res.get("produces"), len(res.get("stems", [])),
                     Path(res.get("manifest", "")).parent))
            return 0
        good, msg = verify_video(res["out"], job["seconds"], job["voice"])
        print(("PASS " if good else "REJECT ") + msg)
        return 0 if good else 1

    return _usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
else:
    register_proven()      # SPEC §3 / R2: importers see the same REGISTRY

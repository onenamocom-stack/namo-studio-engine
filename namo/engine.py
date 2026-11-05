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
import json, math, os, re, shutil, subprocess, sys, tempfile
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
                return False, b + " missing (needed by SPEC §4)"
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
        return True, "engine=%s scenes=%d, node/ffmpeg/ffprobe/chrome all run" % (d.name, len(scenes))

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
        if not m.get("applicable", True):
            return "scene %r declares it cannot apply a plan; re-author it" % scene
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

        work = Path(tempfile.mkdtemp(prefix="namo-mg-"))
        try:
            film = work / "films" / job["scene"]
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
            env = {**os.environ, "PLAYWRIGHT_CHROME": chromium(),
                   "NAMO_JOB": json.dumps(job)}
            cmd = ["node", "core/render/video.mjs", "films/" + job["scene"],
                   "--fps", str(int(job["fps"])),
                   "--workers", str(int(job.get("workers", 4))),
                   "--q", qs,
                   "--size", "%dx%d" % SIZE_FOR_RATIO[job["ratio"]],
                   "--out", str(out)]
            r = subprocess.run(cmd, cwd=str(d), env=env, capture_output=True, text=True)
            log = ((r.stdout or "") + (r.stderr or ""))[-4000:]
            if r.returncode != 0:
                return {"ok": False, "error": "lemo exited %d" % r.returncode, "log": log}
            if not out.exists():
                return {"ok": False, "error": "lemo reported success but wrote no file", "log": log}
            # SPEC §4 / O1: success is not "a file appeared". Verify here, so a caller using
            # REGISTRY directly gets the same guarantee as the CLI.
            good, msg = verify_video(out, job["seconds"])
            if not good:
                return {"ok": False, "out": str(out), "error": "rejected: " + msg, "log": log}
            return {"ok": True, "out": str(out), "produces": "film", "verified": msg, "log": log}
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

def verify_video(path, seconds):
    """
    SPEC §4 / O1-O3. Returns (ok, reason).
    A failure to run a check is a failure: no bare except that returns True.
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
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(p),
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
    return True, "%.1fs, %d frames sampled, 0 blank" % (dur, n)


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
        if not res.get("ok"):
            print("RENDER FAILED: %s" % res.get("error"))
            return 1
        if res.get("produces", res.get("kind")) != "film":
            print("STEMS OK (%s): %d file(s) in %s — a film still has to be composed"
                  % (res.get("produces"), len(res.get("stems", [])),
                     Path(res.get("manifest", "")).parent))
            return 0
        good, msg = verify_video(res["out"], job["seconds"])
        print(("PASS " if good else "REJECT ") + msg)
        return 0 if good else 1

    return _usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
else:
    register_proven()      # SPEC §3 / R2: importers see the same REGISTRY

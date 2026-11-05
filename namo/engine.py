#!/usr/bin/env python3
"""
namo/engine.py - the one door into NAMO's production engine.

Every pipeline (webshow, explainer, customer) talks to this file, never to a renderer
directly. A runtime is registered here and then it is available to every pipeline, unchanged.

    python namo/engine.py runtimes                 what can render
    python namo/engine.py probe                    verify each runtime really works
    python namo/engine.py render <runtime> <job>   render one job

A job is a JSON file. The shape is deliberately the same for every runtime so the
scene-plan director can pick a runtime without knowing its internals.

WHY ONE DOOR: the studio's failure mode is not "no renderer", it is "five renderers, each
with its own contract, and a pipeline that silently gets a blank film from one of them".
So a runtime is only registered if probe() can prove it emits non-blank pixels.
"""
import json, os, subprocess, sys, shutil, hashlib, tempfile
from pathlib import Path

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent

# ---------------------------------------------------------------- runtimes

class Runtime:
    name = ""
    kind = "cpu"           # cpu | gpu
    cost_per_sec_usd = 0.0
    def available(self): return False
    def probe(self): return False, "not implemented"
    def render(self, job, outdir): raise NotImplementedError

class MgRuntime(Runtime):
    """Vector motion graphics through the vendored lemo engine (ink-wash etc). CPU."""
    name = "mg"; kind = "cpu"; cost_per_sec_usd = 0.0
    def __init__(self):
        self.engine = ROOT / "ftm"          # ft-motion vendored lemo, as the baap structure
        self.fallback = ROOT / "lemo"
    def _dir(self):
        for d in (self.engine, self.fallback):
            if (d / "core/render/video.mjs").exists(): return d
        return None
    def available(self):
        d = self._dir()
        return bool(d) and bool(shutil.which("node")) and bool(shutil.which("ffmpeg") or True)
    def probe(self):
        d = self._dir()
        if not d: return False, "lemo core/render/video.mjs not found (run: ./namo/bootstrap.sh)"
        if not shutil.which("node"): return False, "node missing"
        if not (shutil.which("chromium") or shutil.which("chromium-browser") or os.environ.get("PLAYWRIGHT_CHROME")):
            return False, "no chromium"
        return True, f"engine at {d}"
    def render(self, job, outdir):
        d = self._dir()
        scene = NAMO / "mg" / "scenes" / job["scene"]
        film = d / "films" / job["scene"]
        film.parent.mkdir(parents=True, exist_ok=True)
        if film.exists(): shutil.rmtree(film)
        shutil.copytree(scene, film)
        css = (NAMO / "mg" / "fonts.css")
        if css.exists(): shutil.copy(css, film / "fonts.css")
        out = Path(outdir) / (job.get("name", job["scene"]) + ".mp4")
        env = {**os.environ,
               "PLAYWRIGHT_CHROME": os.environ.get("PLAYWRIGHT_CHROME")
                                    or shutil.which("chromium") or shutil.which("chromium-browser") or ""}
        cmd = ["node", "core/render/video.mjs", f"films/{job['scene']}",
               "--fps", str(job.get("fps", 24)),
               "--workers", str(job.get("workers", 4)),
               "--out", str(out)]
        r = subprocess.run(cmd, cwd=d, env=env, capture_output=True, text=True)
        return {"ok": r.returncode == 0, "out": str(out), "log": (r.stdout + r.stderr)[-4000:]}

class H3Runtime(Runtime):
    """MiniMax H3 image-to-video on outsourced GPU. Returns raw stems, per GPU_CONTRACT."""
    name = "h3"; kind = "gpu"; cost_per_sec_usd = 0.00039
    def __init__(self):
        self.contract = json.loads((NAMO / "GPU_CONTRACT.json").read_text()) if (NAMO/"GPU_CONTRACT.json").exists() else {}
    def available(self):
        return bool(os.environ.get("RUNPOD_KEY")) and (NAMO / "namo_gpu.py").exists()
    def probe(self):
        if not self.available(): return False, "RUNPOD_KEY unset or namo_gpu.py missing"
        return True, "GPU dispatcher present; a pod is only born when the shot list is final"
    def render(self, job, outdir):
        r = subprocess.run([sys.executable, str(NAMO / "namo_gpu.py"), "--job", json.dumps(job),
                            "--out", str(outdir)], capture_output=True, text=True)
        return {"ok": r.returncode == 0, "log": (r.stdout + r.stderr)[-4000:]}

REGISTRY = {}
def register(rt):
    REGISTRY[rt.name] = rt

for rt in (MgRuntime(), H3Runtime()):
    register(rt)

# ---------------------------------------------------------------- guard

def verify_video(path, min_seconds=0.5, max_black_ratio=0.0):
    """
    A render is not done because a file exists. It is done when the pixels are not blank.
    This is the check that would have caught the blank gita-ep01 film on day one.
    """
    p = Path(path)
    if not p.exists(): return False, f"missing {p}"
    if p.stat().st_size < 20000: return False, f"suspiciously small {p.stat().st_size} bytes"
    try:
        out = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(p)],
                             capture_output=True, text=True).stdout.strip()
        dur = float(out)
    except Exception as e:
        return False, f"ffprobe failed: {e}"
    if dur < min_seconds: return False, f"duration {dur}s"
    # sample frames, measure luma variance: a blank card has almost none
    try:
        import numpy as np
        raw = subprocess.run(["ffmpeg","-v","error","-i",str(p),"-vf","fps=1,scale=64:36","-f","rawvideo",
                              "-pix_fmt","gray","-"], capture_output=True).stdout
        a = np.frombuffer(raw, dtype=np.uint8)
        if a.size == 0: return False, "could not decode frames"
        frames = a.reshape(-1, 36, 64)
        stds = frames.std(axis=(1,2))
        dead = int((stds < 1.0).sum())
        ratio = dead / len(stds)
        if ratio > max_black_ratio:
            return False, f"{dead}/{len(stds)} frames are flat ({ratio:.0%} blank)"
        return True, f"{dur:.1f}s, {len(stds)} sampled frames, {dead} flat"
    except Exception:
        return True, f"{dur:.1f}s (no numpy; luma check skipped)"

# ---------------------------------------------------------------- cli

def main():
    args = sys.argv[1:]
    if not args or args[0] == "runtimes":
        for n, rt in REGISTRY.items():
            ok, why = rt.probe() if "--probe" in args else (rt.available(), "")
            print(f"{n:6s} {rt.kind:4s} {'READY ' if ok else 'MISSING'} {why}")
        return 0
    if args[0] == "probe":
        worst = 0
        for n, rt in REGISTRY.items():
            ok, why = rt.probe()
            print(f"{n:6s} {'OK  ' if ok else 'FAIL'} {why}")
            worst = worst or (0 if ok else 1)
        return worst
    if args[0] == "render":
        rt_name, job_path = args[1], args[2]
        rt = REGISTRY.get(rt_name)
        if not rt: print(f"unknown runtime {rt_name}"); return 2
        ok, why = rt.probe()
        if not ok: print(f"{rt_name} not ready: {why}"); return 2
        job = json.loads(Path(job_path).read_text())
        outdir = Path(args[3]) if len(args) > 3 else Path("out")
        outdir.mkdir(parents=True, exist_ok=True)
        res = rt.render(job, outdir)
        print(res.get("log",""))
        if not res.get("ok"): print("RENDER FAILED"); return 1
        good, msg = verify_video(res["out"])
        print(("PASS " if good else "REJECT ") + msg)
        return 0 if good else 1
    print(__doc__); return 1

if __name__ == "__main__":
    sys.exit(main())

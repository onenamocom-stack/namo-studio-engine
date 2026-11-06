#!/usr/bin/env python3
"""Build audiomap.json for the show's bed, so an A/V sync claim is measured, not assumed.

Wraps the repo's own .agents/skills/music-to-video/scripts/analyze-beatgrid.py so the bed and
the gate read the same numbers. Falls back to a tempo estimate if librosa is unavailable, and
says so in the output rather than inventing a grid.

    python tools/make_audiomap.py namo/audio/tanpura.flac out/audiomap.json
"""
import json, os, subprocess, sys


def analyze(path):
    """Prefer the skill's analyser. It returns bpm + beat times + downbeats."""
    script = os.path.join(os.path.dirname(__file__), "..", ".agents", "skills",
                          "music-to-video", "scripts", "analyze-beatgrid.py")
    if os.path.exists(script):
        r = subprocess.run([sys.executable, script, path, "--json"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            try:
                return json.loads(r.stdout), "analyze-beatgrid.py"
            except ValueError:
                pass
    return None, None


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def main(argv):
    bed = argv[1] if len(argv) > 1 else "namo/audio/tanpura.flac"
    out = argv[2] if len(argv) > 2 else "out/audiomap.json"

    am, how = analyze(bed)
    if am is None:
        # no analyser: report honestly instead of guessing a grid
        dur = duration(bed)
        am = {"bpm": None, "beats": [], "duration": dur,
              "note": "analyser unavailable: no beat grid, so A/V sync cannot be claimed"}
        how = "none"
    else:
        am.setdefault("duration", duration(bed))
    am["source"] = bed
    am["how"] = how
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump(am, f, indent=1)
    print("audiomap: bpm=%r beats=%d dur=%r via %s -> %s"
          % (am.get("bpm"), len(am.get("beats") or []), am.get("duration"), how, out))
    return 0 if am.get("beats") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

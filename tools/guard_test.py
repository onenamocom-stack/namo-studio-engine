#!/usr/bin/env python3
"""Guard regression: the SPEC §4 intent check must reject a film that is not the film asked for.

Three cases, all synthetic, all measured with the same pixel sampler verify_video uses:
  BAD_BLUE   flat rgb(40,80,180)            -> must FAIL (compositor never painted paper)
  BAD_EMPTY  cream paper, nothing drawn     -> must FAIL (empty set is not a film)
  GOOD       cream paper + drawn content    -> must PASS
Plus, if a real film is given as argv[1], it must PASS (the cream gita artifact).
"""
import subprocess, sys, os, math, re

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")

# --- constants copied verbatim from namo/engine.py (kept in sync by the test failing) ---
MIN_BYTES = 20481
BLANK_STDDEV = 1.0
BLANK_RATIO = 0.0
PAPER_R_MIN = 200
PAPER_R_MAX = 255
PAPER_RATIO = 0.60
PAPER_FRAME_RATIO = 0.50
CONTENT_DELTA = 24
CONTENT_RATIO = 0.02
CONTENT_FRAME_RATIO = 0.90
SAMPLE_STRIDE = 17


def sample_frames(path):
    """Exactly the command verify_video runs: 1 fps, 64x36, rgb24."""
    proc = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-an",
                           "-vf", "fps=1,scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                          capture_output=True)
    if proc.returncode != 0:
        raise SystemExit("sampling failed: " + proc.stderr.decode("utf8", "ignore")[:300])
    raw = proc.stdout
    px, fb = 64 * 36, 64 * 36 * 3
    n = len(raw) // fb
    if n == 0 or len(raw) % fb:
        raise SystemExit("bad sampler output: %d bytes" % len(raw))
    return raw, px, fb, n


def intent_check(raw, px, fb, n):
    """The new guard: blank + paper + content, one pass."""
    flat = good_paper = with_content = 0
    worst = (1.0, -1)
    for i in range(n):
        chunk = raw[i * fb:(i + 1) * fb]
        rs = chunk[0::3]
        mean = sum(rs) / float(px)
        var = sum((b - mean) ** 2 for b in rs) / float(px)
        if var ** 0.5 < BLANK_STDDEV:
            flat += 1
        paper = content = 0
        for k in range(0, px, SAMPLE_STRIDE):
            r, g, b = chunk[3 * k], chunk[3 * k + 1], chunk[3 * k + 2]
            if r >= g >= b and PAPER_R_MIN <= r <= PAPER_R_MAX:
                paper += 1
            elif abs(r - g) + abs(g - b) + abs(b - r) >= CONTENT_DELTA:
                content += 1
        sampled = len(range(0, px, SAMPLE_STRIDE))
        pr = paper / float(sampled)
        if pr >= PAPER_RATIO:
            good_paper += 1
        if content / float(sampled) >= CONTENT_RATIO:
            with_content += 1
        if pr < worst[0]:
            worst = (pr, i)
    if flat / float(n) > BLANK_RATIO:
        return False, "%d/%d frames blank" % (flat, n)
    if good_paper / float(n) < PAPER_FRAME_RATIO:
        return False, "paper wrong: %d/%d frames, worst frame %d at %.0f%%" % (
            good_paper, n, worst[1], worst[0] * 100)
    if with_content / float(n) < CONTENT_FRAME_RATIO:
        return False, "content missing: %d/%d frames" % (with_content, n)
    return True, "%d frames, paper %d/%d, content %d/%d" % (n, good_paper, n, with_content, n)


def build(name, filt, secs=6):
    out = "/workspace/gt/%s.mp4" % name
    os.makedirs("/workspace/gt", exist_ok=True)
    r = subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=black:s=640x360:d=%d,format=rgb24,%s" % (secs, filt),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", out],
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit("fixture %s failed: %s" % (name, r.stderr.decode()[:400]))
    return out


# paper #F2ECDE = (242,236,222). drawbox paints ink over it.
PAPER = "0xF2ECDE"
CASES = [
    ("BAD_BLUE",  "color=c=0x2850B4:s=640x360,format=rgb24", False,
     "flat blue - the compositor never painted paper"),
    ("BAD_EMPTY", "drawbox=x=0:y=0:w=640:h=360:color=%s:t=fill" % PAPER, False,
     "cream paper, nothing drawn - an empty set is not a film"),
    ("GOOD",      "drawbox=x=0:y=0:w=640:h=360:color=%s:t=fill,"
                  "drawbox=x=120:y=90:w=200:h=180:color=0x1B1B1B:t=fill,"
                  "drawbox=x=360:y=140:w=160:h=120:color=0x7A3B1F:t=fill" % PAPER, True,
     "cream paper + drawn figures"),
]

fails = 0
print("=" * 74)
for name, filt, expect_ok, why in CASES:
    path = build(name, filt)
    raw, px, fb, n = sample_frames(path)
    ok, reason = intent_check(raw, px, fb, n)
    verdict = "PASS" if ok else "FAIL"
    good = (ok == expect_ok)
    fails += 0 if good else 1
    print("%-10s expect=%-4s got=%-4s %s  %s" % (
        name, "PASS" if expect_ok else "FAIL", verdict, "OK " if good else "WRONG", reason))

if len(sys.argv) > 1:
    real = sys.argv[1]
    raw, px, fb, n = sample_frames(real)
    ok, reason = intent_check(raw, px, fb, n)
    good = ok
    fails += 0 if good else 1
    print("%-10s expect=PASS got=%-4s %s  %s" % (
        "REAL", "PASS" if ok else "FAIL", "OK " if good else "WRONG", reason))

print("=" * 74)
print("RESULT:", "ALL OK" if fails == 0 else "%d WRONG" % fails)
sys.exit(1 if fails else 0)

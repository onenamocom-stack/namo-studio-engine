#!/usr/bin/env python3
"""Why did the paper gate pass a film with no ink drawn on it?

Rebuilds the exact ffmpeg pipeline paper_check uses (fps=1, scale=160:90, rgb24) and reports,
per frame, how many of the 105 samples are paper / ink / neither. Prints the verdict paper_check
would reach and compares it with what the factory actually recorded.
"""
import subprocess, sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "namo"))
import engine

path = sys.argv[1]
paper = engine.PAPER
print("paper", paper, "TOL", engine.PAPER_TOL,
      "PAPER_SHARE", engine.PAPER_SHARE, "CONTENT_SHARE", engine.CONTENT_SHARE)

# 1) the real guard, on the real file
ok, why = engine.paper_check(path, paper)
print("paper_check ->", "PASS" if ok else "REJECT", "|", why)

# 2) the same command, verbose
r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-an",
                    "-vf", "fps=1,scale=160:90", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                   capture_output=True)
raw = r.stdout
w, h, fsz = 160, 90, 160 * 90 * 3
n = len(raw) // fsz
print("frames", n, "bytes", len(raw), "remainder", len(raw) % fsz)
for i in range(min(4, n)):
    fr = raw[i * fsz:(i + 1) * fsz]
    paper_n = ink_n = tot = 0
    darkest = 999
    for y in range(h // 8, h, h // 8):
        for x in range(w // 16, w, w // 16):
            o = (y * w + x) * 3
            px = (fr[o], fr[o + 1], fr[o + 2])
            tot += 1
            if all(abs(px[c] - paper[c]) <= engine.PAPER_TOL for c in range(3)):
                paper_n += 1
            elif sum(px) < sum(paper) * 0.72:
                ink_n += 1
            darkest = min(darkest, sum(px))
    print("frame %2d  n=%3d  paper %5.1f%%  ink %4.1f%%  darkest_sum %d (paper_sum %d, ink_cut %.0f)"
          % (i, tot, paper_n / tot * 100, ink_n / tot * 100, darkest,
             sum(paper), sum(paper) * 0.72))

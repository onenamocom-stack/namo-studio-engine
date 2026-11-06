"""SPEC §4 O5: a film must be the film the scene asked for. The old guard passed a blue frame and a
cream frame identically, because both are "not blank" once anything is drawn. These cases pin the
colour and coverage gates: blue fails, cream passes, empty paper fails, and a non-paper runtime
(paper=None) is exempt."""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "namo"))
import engine  # noqa: E402

PAPER = "0xF2ECDE"


def clip(tmp, name, colour, extra=""):
    p = os.path.join(tmp, name)
    vf = ["-vf", extra] if extra else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=%s:s=1920x1080:d=2:r=24" % colour,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", *vf,
                    "-c:v", "libx264", "-b:v", "3M", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", p], check=True)
    return p


def main():
    with tempfile.TemporaryDirectory() as tmp:
        figure = "drawbox=x=760:y=520:w=300:h=420:color=0x1a1410@1:t=fill,drawbox=x=250:y=120:w=60:h=900:color=0x8a7a60@1:t=fill"
        cream = clip(tmp, "cream.mp4", PAPER, figure)
        blue = clip(tmp, "blue.mp4", "0x2850B4", "drawbox=x=600:y=300:w=700:h=500:color=0xB0C0E0@1:t=fill")
        empty = clip(tmp, "empty.mp4", PAPER)
        ok_cream, why_cream = engine.verify_video(cream, 2)
        ok_blue, why_blue = engine.verify_video(blue, 2)
        ok_empty, why_empty = engine.verify_video(empty, 2)
        ok_rd, why_rd = engine.verify_video(blue, 2, paper=None)
    assert ok_cream, "cream paper with a figure must pass: %s" % why_cream
    assert not ok_blue, "an all-blue frame must be rejected"
    assert "paper" in why_blue, why_blue
    assert not ok_empty, "paper with nothing drawn must be rejected"
    assert ok_rd, "a non-paper runtime (paper=None) must be exempt: %s" % why_rd
    print("ok  cream=%s | blue rejected (%s) | empty rejected (%s)" % (why_cream, why_blue[:40], why_empty[:40]))


if __name__ == "__main__":
    main()

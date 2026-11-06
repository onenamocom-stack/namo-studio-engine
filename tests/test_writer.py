#!/usr/bin/env python3
"""The writer must refuse a film it cannot honestly fill, and must never pad one.

Every case here is a defect this file exists to prevent, measured on the last shipped film:
a 60 s render whose script carried 14 s of speech, so 46 s of the film was nothing.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "namo"))
import writer as W


def check(name, cond, why):
    global fails
    if not cond:
        fails += 1
    print("  %-46s %s  %s" % (name, "OK  " if cond else "FAIL", why))


fails = 0
print("== a line is measured, never assumed ==")
short = W.speak_seconds("\u0927\u0943\u0924\u0930\u093e\u0937\u094d\u091f\u094d\u0930 \u0909\u0935\u093e\u091a", "sa")
long_ = W.speak_seconds("\u0927\u0930\u094d\u092e\u0915\u094d\u0937\u0947\u0924\u094d\u0930\u0947 \u0915\u0941\u0930\u0941\u0915\u094d\u0937\u0947\u0924\u094d\u0930\u0947 \u0938\u092e\u0935\u0947\u0924\u093e \u092f\u0941\u092f\u0941\u0924\u094d\u0938\u0935\u0903", "sa")
check("a short shloka is shorter than a long one", short < long_, "%.2fs < %.2fs" % (short, long_))
check("empty text takes no time", W.speak_seconds("") == 0.0, "0.0s")

print("== the film is not padded ==")
beats, secs = W.fitting_length("gita 1.1", 60.0)
shots, rep = W.to_shots(beats, secs)
q = W.gate_beats(shots, secs)
check("asks 60 s, gets a shorter honest film", secs <= 60.0, "%.0fs" % secs)
check("every gate passes", all(q.values()), str([k for k, v in q.items() if not v]))

print("== the last shipped defect is refused ==")
# 4 s of speech stretched across a 60 s film: the exact shape of the weak render
thin = [dict(kind="hook", lang="hi", cast=["narrator"], picture="p1",
             text="\u0938\u0924\u094d\u0924\u0930\u0939 \u0926\u093f\u0928")]
x, rep2 = W.to_shots(W.fit(thin)[0], 60.0)
q2 = W.gate_beats(x, 60.0)
check("a 60 s film with one short line is refused", not q2["the_film_is_filled"],
      "filled=%s" % q2["the_film_is_filled"])
check("no shot drags past 60 % over its speech", not q2["no_shot_drags"] or rep2.get("unfilled", 0) > 30,
      "unfilled %.0fs" % rep2.get("unfilled", 0))

print("== the owner's Sanskrit rule ==")
bad = [dict(kind="shloka", lang="sa", cast=["dhritarashtra"], picture="a", text="x", need=2, speech=2),
       dict(kind="shloka", lang="sa", cast=["dhritarashtra"], picture="b", text="y", need=2, speech=2)]
check("two shlokas in a row is refused", not W.gate_beats(bad, 60)["sanskrit_rule"], "no explain between")

print("== a repeated picture is a duplicate, not a shot ==")
dup = [dict(kind="scene", lang="hi", cast=["narrator"], picture="same", text="a", need=2, speech=2),
       dict(kind="scene", lang="hi", cast=["narrator"], picture="same", text="b", need=2, speech=2)]
check("the same picture twice is refused", not W.gate_beats(dup, 60)["no_repeated_picture"], "dup")

print("\nRESULT:", "ALL OK" if fails == 0 else "%d WRONG" % fails)
sys.exit(1 if fails else 0)

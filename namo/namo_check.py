"""namo_check.py - run every guard. If this fails, do not generate and do not rent GPU."""
import json, os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

def run():
    fails = []
    B = json.load(open(os.path.join(ROOT, "SHOW_BIBLE.json"), encoding="utf-8"))
    R = json.load(open(os.path.join(ROOT, "FAILURE_REGISTRY.json"), encoding="utf-8"))
    # 1 builder refuses bad specs
    import namo_pd as pd
    for kw in [dict(who="x", framing="y", props=("lamp",), ground="brick"),
               dict(who="x", framing="y", props=(), ground="brick", fire="a lamp"),
               dict(who="x", framing="y", props=("lamp",), ground=None, fire="a lamp")]:
        try:
            pd.build(**kw); fails.append("builder accepted a bad spec")
        except ValueError:
            pass
    # 2 every banner is either evidenced or explicitly forbidden
    for cid, text in B["banners"]["evidence"].items():
        if not text: fails.append("banner missing for " + cid)
    if "lion" not in str(B["banners"].get("forbidden", {}).get("yudhishthira", [])):
        fails.append("yudhishthira lion not forbidden")
    # 3 cloth vocabulary must be corpus words
    for banned in ("cotton", "saree"):
        if banned in B["materials"]["fabric"].lower():
            fails.append("modern cloth word in bible: " + banned)
    # 4 homonym guard live
    import namo_text as nt
    cands = [os.path.join(ROOT, "..", "corpus", "mahabharatam.txt"),
              os.path.join(ROOT, "..", "..", "corpus", "mahabharatam.txt"),
              "/home/runner/work/namo-studio/namo-studio/corpus/mahabharatam.txt"]
    cpath = next((c for c in cands if os.path.exists(c)), None)
    if not cpath:
        fails.append("corpus not found for homonym check")
    else:
        t = nt.Text(cpath)
        if any("dark" in str(x["appearance"]).lower() for x in t.describe("karRa", limit=5)):
            fails.append("homonym guard not filtering kfzRa")
    # 5 registry present and complete
    if len(R.get("errors", [])) < 14:
        fails.append("failure registry incomplete")
    # 6 checklists present
    if not R.get("checklist_before_any_image") or not R.get("checklist_before_any_gpu"):
        fails.append("checklists missing")
    return fails

if __name__ == "__main__":
    f = run()
    print("NAMOTV_CHECK", "PASS" if not f else "FAIL")
    for x in f: print("  -", x)
    sys.exit(0 if not f else 1)

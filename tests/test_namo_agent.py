"""namo/agent.py routing: a named scene decides its kind; `key=value` selectors never classify.
Plus the goldfish-3 regressions: rd style gate, duration order, whole-word keywords, structured
fields win, the workflow's structured brief, the factory's stable job id."""
import json, os, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "namo"))
os.environ.setdefault("NAMO_PROBE_RENDER", "0")   # importing engine probes; no 1 s films in unit tests
import agent  # noqa: E402
import engine  # noqa: E402
import factory  # noqa: E402


def test_scene_selector_routes_explainer_beats_to_rd():
    for brief in ("30 second explainer scene=gita-1-1",
                  {"prompt": "30 second explainer", "scene": "gita-1-1"}):
        p = agent.plan(brief)
        assert (p["kind"], p["runtime"], p["scene"], p["seconds"]) == ("explainer", "rd", "gita-1-1", 30), p


def test_selector_text_does_not_vote():
    # without the scene's declaration, 'gita' inside the selector must still not add a webshow hit
    p = agent.plan("30 second explainer scene=gita-nonexistent")
    assert (p["kind"], p["scene"]) == ("explainer", "gita-nonexistent"), p


def test_webshow_scene_keeps_its_kind():
    p = agent.plan("explain this scene=gita-ep01")
    assert (p["kind"], p["runtime"]) == ("webshow", "mg"), p


def rd_job(**over):
    p = agent.plan({"prompt": "30 second explainer", "scene": "gita-1-1"})
    job = {"schema": "namo.job/1", "kind": p["kind"], "runtime": "rd", "scene": "gita-1-1",
           "seconds": p["seconds"], "fps": p["fps"], "ratio": p["ratio"], "style": p["style"],
           "emotion": p["emotion"], "voice": p["voice"], "name": "t"}
    return {**job, **over}


def no_node(*a, **k):
    raise AssertionError("rd rendered a job the gate should have refused")


def test_rd_refuses_styles_it_does_not_draw(tmp_path):
    rt = engine.RdRuntime()
    rt.node = no_node
    res = rt.render(rd_job(style="clean-professional"), tmp_path)
    assert not res["ok"] and "flat-motion-graphics" in res["error"], res
    plan = {**agent.plan({"prompt": "30 second explainer", "scene": "gita-1-1"}), "style": "clean-professional"}
    saved = dict(engine.REGISTRY)
    engine.REGISTRY["rd"] = rt
    try:
        ok, why = factory.feasible(plan)
    finally:
        engine.REGISTRY.clear(); engine.REGISTRY.update(saved)
    assert not ok and "flat-motion-graphics" in why, why


def test_first_duration_token_is_the_length_and_ratios_are_not_durations():
    cases = {"2 min intro then 30 second recap": 120, "30 second recap after a 2 min intro": 30,
             "9:16 vertical reel": 30, "16:9 film, 1:30 long": 90, "1:1 square 45s": 45}
    for text, want in cases.items():
        assert agent.read_seconds(text) == want, (text, agent.read_seconds(text))
    assert agent.plan("9:16 vertical reel")["ratio"] == "9:16"


def test_keywords_match_whole_words():
    assert agent.classify("show me the product")[0] == "customer"
    assert agent.classify("a short explainer")[0] == "explainer"
    assert agent.read_ratio("the history of the gita") == "16:9"      # 'story' inside 'history'
    assert agent.read_emotion("breakfast menu") is None                # 'fast' inside 'breakfast'


def test_structured_fields_win_and_zero_reaches_the_gate(tmp_path):
    p = agent.plan({"prompt": "gita chapter 2 episode 3, 60 seconds", "kind": "customer"})
    assert (p["kind"], p["runtime"], p["style"]) == ("customer", "mg", "clean-professional"), p
    p = agent.plan({"prompt": "30 seconds", "seconds": 0})
    assert p["seconds"] == 0, p
    rt = engine.RdRuntime()
    rt.node = no_node
    res = rt.render(rd_job(seconds=p["seconds"]), tmp_path)
    assert not res["ok"] and "seconds" in res["error"], res


def test_workflow_passes_overrides_as_structured_fields(tmp_path):
    wf = yaml.safe_load((ROOT / ".github/workflows/namo-agent.yml").read_text(encoding="utf-8"))
    steps = {s.get("name"): s for s in wf["jobs"]["make"]["steps"]}
    decide, make = steps["decide"]["run"], steps["make the video"]["run"]
    assert "--json brief.json" in decide and "--json brief.json" in make
    script = decide.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    default = wf[True]["workflow_dispatch"]["inputs"]["prompt"]["default"]   # yaml reads `on:` as True
    for P, S, R, want in ((default, "60", "", (60, "16:9")), ("40 sec vertical reel", "", "16:9", (40, "16:9"))):
        subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True, capture_output=True,
                       env={**os.environ, "P": P, "S": S, "R": R})
        p = agent.plan(json.loads((tmp_path / "brief.json").read_text()))
        assert (p["seconds"], p["ratio"]) == want, (P, S, R, p["seconds"], p["ratio"])


def test_factory_records_and_skips_an_id_less_job_under_one_id(tmp_path, monkeypatch):
    job = {"prompt": "30 second explainer  scene=gita-1-1"}
    (tmp_path / "q.json").write_text(json.dumps({"jobs": [job]}))
    monkeypatch.setattr(factory, "QUEUE", tmp_path / "q.json")
    monkeypatch.setattr(factory, "STATUS", tmp_path / "s.json")
    monkeypatch.setattr(factory, "feasible", lambda plan: (True, "ok"))
    renders = []
    monkeypatch.setattr(factory.router, "render",
                        lambda plan: renders.append(plan) or {"ok": True, "out": "x.mp4", "guard": "ok"})
    assert factory.once() == 0 and factory.once() == 0
    runs = json.loads((tmp_path / "s.json").read_text())["runs"]
    assert len(renders) == 1 and [r["state"] for r in runs] == ["DONE"], runs
    assert runs[0]["id"] == factory.job_id({"prompt": " 30 second explainer scene=gita-1-1 "})

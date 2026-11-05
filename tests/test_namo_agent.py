"""namo/agent.py routing: a named scene decides its kind; `key=value` selectors never classify."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "namo"))
import agent  # noqa: E402


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

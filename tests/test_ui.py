"""Static checks on the single-page UI: the served page, and that its script only touches elements that exist."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from cooksmart.api import create_app
from cooksmart.config import Settings
from cooksmart.db import DB

HTML = Path("cooksmart/static/index.html").read_text(encoding="utf-8")


def test_page_is_served_with_all_four_views():
    r = TestClient(create_app(Settings(":memory:", "", "m", "", "t"), DB(":memory:"))).get("/")
    assert r.status_code == 200
    for label in ("Simulator", "How it works", "Agent Studio", "Kitchen &amp; logs", "System prompt", "Knowledge base", "FAQs", "Household"):
        assert label in r.text, label


def test_every_element_id_the_script_uses_exists():
    """A mistyped id makes `$('#x').onclick = ...` throw and silently kills the whole page; catch it here."""
    script = re.search(r"<script>(.*)</script>", HTML, re.S).group(1)
    used = set(re.findall(r"\$\$?\('#([A-Za-z][\w\-]*)", script)) | set(re.findall(r"getElementById\('([\w\-]+)'", script))
    defined = set(re.findall(r'id=\\?"([\w\-]+)\\?"', HTML))
    assert used, "found no ids: the regex is wrong"
    used = {i for i in used if not i.endswith("-")}                      # 'view-' + x is built at runtime
    assert not (used - defined), f"script uses ids that the page never defines: {sorted(used - defined)}"


def test_no_leftover_clutter_from_the_old_layout():
    assert "scen button" not in HTML and "secure" not in HTML          # the 26-card grid and the banners are gone
    assert HTML.count('<details class="card"') == 0                     # nothing hides behind a pile of accordions


def test_every_studio_endpoint_the_script_calls_exists():
    """The UI calls the Studio API by string; make sure each (method, path) it uses is a real route."""
    app = create_app(Settings(":memory:", "", "m", "", "t"), DB(":memory:"))
    norm = lambda p: re.sub(r"\$?\{[^}]*\}", "{}", p)                      # {hid}, ${docSel}, {name} all become {}
    routes = {(m, norm(r.path)) for r in app.routes for m in getattr(r, "methods", [])}
    script = re.search(r"<script>(.*)</script>", HTML, re.S).group(1)
    calls = re.findall(r"req\('(GET|PUT|POST|DELETE)', HID \+ [`']/(studio[^`']*)[`']", script)
    assert len(calls) >= 12, "found too few calls: the regex is wrong"
    for method, path in calls:
        assert (method, "/api/{}/" + norm(path)) in routes, (method, path)


def test_every_scenario_can_be_picked_from_the_dropdown():
    from cooksmart import scenarios
    listed = set(re.findall(r"'([a-z_]+)'", re.search(r"const GROUPS = (.*?)\];\s*let scenarios", HTML, re.S).group(1)))
    missing = {s.id for s in scenarios.SCENARIOS} - listed
    assert not missing, f"scenarios the dropdown never shows: {sorted(missing)}"

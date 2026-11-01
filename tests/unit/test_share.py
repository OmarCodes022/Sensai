"""X3 public links: one section as an escaped snapshot, published only on a yes, removed for good."""
import threading
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from sensai.campaign import CampaignStore, apply, plan
from sensai.campaign.models import EntryEdit, PostEdit, Reply
from sensai.core.ports import ApprovalDecision
from sensai.guardrails import load_guardrail
from sensai.share import ShareError, Shares, handler, section_text
from sensai.cli.share_commands import share_command, unshare_command

BRAND = str(Path(__file__).parents[1] / "fixtures" / "brand.json")


@pytest.fixture
def guard():
    return load_guardrail(brand_file=BRAND, today=date(2026, 10, 28))


@pytest.fixture
def store(tmp_path, guard):
    store = CampaignStore(str(tmp_path / "campaigns"), today=lambda: date(2026, 10, 28))
    apply(store, plan(store.latest(), "posts", PostEdit(op="add", caption="Hydrates skin for up to 8 hours. <b>Glow</b>", claim_ids=["C01"]), guard.claims))
    apply(store, plan(store.latest(), "calendar", EntryEdit(op="add", date="2026-11-04", time="18:00", post_id="P1", theme="Launch"), guard.claims))
    return store


def test_only_the_chosen_section_is_shared_and_dm_replies_never(store):
    doc = store.latest()
    doc.sections.replies.items = [Reply(case_key="Q1", question="emma@x.com cure?", suggestion="Ask a dermatologist.")]
    text = section_text(doc, "calendar")
    assert "2026-11-04 18:00 · Instagram · P1 Launch" in text and "Hydrates" not in text and "emma" not in text
    with pytest.raises(ShareError, match="never shared"):
        section_text(doc, "replies")
    with pytest.raises(ShareError, match="empty"):
        section_text(doc, "report")


def test_a_refused_claim_shares_nothing(store, guard, tmp_path):
    bad = store.latest()
    bad.sections.posts.items[0].caption = "It cures eczema"
    with pytest.raises(ShareError, match="guardrails"):
        Shares(str(tmp_path / "shares"), "h").propose(guard, bad, "posts")


def test_a_published_page_is_served_escaped_and_removed_for_good(store, guard, tmp_path):
    shares = Shares(str(tmp_path / "shares"), "127.0.0.1", 0)
    token, url, text = shares.propose(guard, store.latest(), "posts")
    assert url.endswith(f"/s/{token}") and not (tmp_path / "shares").exists()  # Nothing written yet.
    shares.publish(token, text)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(str(tmp_path / "shares")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        body = urllib.request.urlopen(f"{base}/s/{token}").read().decode()
        assert "&lt;b&gt;Glow&lt;/b&gt;" in body and "<script" not in body
        for path in ("/", "/s/abc", f"/s/{token}/../x", "/shares"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + path)
            assert error.value.code == 404
        assert shares.remove(token) and not shares.remove(token)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{base}/s/{token}")
    finally:
        server.shutdown()


class Approval:
    def __init__(self, yes):
        self.yes, self.requests = yes, []

    def request(self, request):
        self.requests.append(request)
        return ApprovalDecision(self.yes)


def test_the_terminal_shows_content_and_url_then_publishes_only_on_yes(store, guard, tmp_path):
    shares, out = Shares(str(tmp_path / "shares"), "192.168.1.20"), []
    no = Approval(False)
    share_command(shares, store, guard, no, "calendar", out.append)
    assert out[-1] == "Nothing was shared." and shares.list() == []
    assert "Launch" in no.requests[0].content and no.requests[0].resource.startswith("http://192.168.1.20:8766/s/")
    share_command(shares, store, guard, Approval(True), "calendar", out.append)
    [token] = shares.list()
    assert out[-1].startswith(f"Shared: http://192.168.1.20:8766/s/{token}")
    share_command(shares, store, guard, Approval(True), "replies", out.append)
    assert out[-1].startswith("Not shared: DM replies are never shared")
    unshare_command(shares, token, out.append)
    assert "answers 404" in out[-1] and shares.list() == []


def test_the_link_uses_the_home_network_address_not_a_vpn_tunnel():
    from sensai.share import lan_host
    assert lan_host({"10.253.5.20", "100.72.45.7", "192.168.0.14"}) == "192.168.0.14"
    assert lan_host({"100.72.45.7", "172.20.1.4"}) == "172.20.1.4"
    assert lan_host({"127.0.0.1", "169.254.1.1"}) == lan_host(set()) == "127.0.0.1"

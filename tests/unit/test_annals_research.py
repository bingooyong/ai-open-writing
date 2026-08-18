from novel_agent.annals.research import NullResearchPort, WebResearchPort
from novel_agent.annals.skeleton import (
    CANONICAL_TITLE_RULE,
    build_skeleton,
    confirm_errors,
    fill_skeleton,
    patch_kernel_title_rule,
)
from novel_agent.domain.schemas.annals import SourceRef


def test_not_applicable_skeleton_is_confirmable() -> None:
    sk = build_skeleton(
        kernel_texts=["说书人"], time_locations=["临安城"], volume_texts=[], locked_drafts=[]
    )
    assert sk.cover.applicable is False
    assert sk.year_cards == []
    assert confirm_errors(sk) == []


def test_null_port_leaves_plot_hit_unconfirmable() -> None:
    sk = build_skeleton(
        kernel_texts=["2005穿回去"],
        time_locations=["2005秋 北影厂", "2006夏"],
        volume_texts=[],
        locked_drafts=[("v1c012", "柏林一种关注放映前夜")],
    )
    assert sk.cover.applicable is True
    assert sk.cover.span_start == 2005
    assert {card.year for card in sk.year_cards} == {2005, 2006}
    thick = {card.year for card in sk.year_cards if card.density == "thick"}
    assert thick == {2005, 2006}
    assert any("柏林一种关注" in d.issue for d in sk.debts)
    filled = fill_skeleton(sk, NullResearchPort())
    errors = confirm_errors(filled)
    assert errors  # plot-hit unsourced
    assert all(card.awards == [] for card in filled.year_cards)


def test_sourced_fill_confirms_and_human_widen() -> None:
    class FakePort:
        def lookup(self, query: str) -> list[SourceRef]:
            return [
                SourceRef(
                    url="https://example.invalid/x", excerpt=query, accessed="2026-08-18"
                )
            ]

    sk = build_skeleton(
        kernel_texts=["2005"],
        time_locations=["2005秋"],
        volume_texts=[],
        locked_drafts=[],
        span_start=2005,
        span_end=2025,
    )
    assert sk.cover.span_end == 2025
    thin = [card for card in sk.year_cards if card.density == "thin"]
    assert 2025 in {card.year for card in thin}
    filled = fill_skeleton(sk, FakePort())
    assert confirm_errors(filled) == []


def test_no_auto_widen_to_2025() -> None:
    sk = build_skeleton(
        kernel_texts=["2005"],
        time_locations=["2005秋", "2008初"],
        volume_texts=[],
        locked_drafts=[],
    )
    assert sk.cover.span_end == 2008


def test_patch_title_rule() -> None:
    out = patch_kernel_title_rule(["禁无代价全能", "严禁搬运真实片名", "真实片名不要写"])
    assert "严禁搬运真实片名" not in out
    assert all("真实片名" not in item or item == CANONICAL_TITLE_RULE for item in out)
    assert CANONICAL_TITLE_RULE in out
    assert "禁无代价全能" in out


def test_web_port_empty_http_returns_empty(monkeypatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    assert WebResearchPort(client).lookup("2006 金鸡 影后") == []

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app import news
from app.config import Feed
from app.news import NewsItem, clean_text, fetch_all, fetch_feed, merge_news, parse_feed
from tests.conftest import BROKEN_URL, CNBC_URL, MW_URL, fixture_bytes


def item(title, link, hour=None, source="X"):
    published = datetime(2026, 11, 18, hour, tzinfo=timezone.utc) if hour is not None else None
    return NewsItem(title=title, link=link, source=source, published=published)


class TestCleanText:
    def test_strips_tags_and_entities(self):
        assert clean_text("<p>S&amp;P <b>500</b></p>") == "S&P 500"

    def test_collapses_whitespace(self):
        assert clean_text("  a \n\n b\t c ") == "a b c"

    @pytest.mark.parametrize("value", [None, ""])
    def test_empty(self, value):
        assert clean_text(value) == ""

    def test_truncates_with_ellipsis(self):
        out = clean_text("x" * 50, max_len=10)
        assert len(out) == 10 and out.endswith("…")


class TestParseFeed:
    def test_parses_items_with_source_and_date(self):
        items = parse_feed(fixture_bytes("feed_cnbc.xml"), "CNBC")
        assert [i.title for i in items] == ["Fed holds rates steady, signals patience", "Oil prices slip as supply concerns ease"]
        assert all(i.source == "CNBC" for i in items)
        assert items[0].published == datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)

    def test_summary_html_is_cleaned(self):
        items = parse_feed(fixture_bytes("feed_cnbc.xml"), "CNBC")
        assert items[0].summary == "The Federal Reserve kept its benchmark rate unchanged ."

    def test_skips_entries_without_title(self):
        items = parse_feed(fixture_bytes("feed_cnbc.xml"), "CNBC")
        assert all(i.link != "https://www.cnbc.com/no-title" for i in items)

    def test_missing_date_is_none(self):
        items = parse_feed(fixture_bytes("feed_marketwatch.xml"), "MarketWatch")
        undated = [i for i in items if "bonds" in i.title]
        assert undated and undated[0].published is None

    def test_skips_non_http_links(self):
        xml = b"<rss><channel><item><title>Bad</title><link>javascript:alert(1)</link></item></channel></rss>"
        assert parse_feed(xml, "X") == []

    def test_garbage_input_returns_empty_list(self):
        assert parse_feed(b"this is not xml", "X") == []


class TestMergeNews:
    def test_sorts_newest_first_with_undated_last(self):
        merged = merge_news([[item("a", "https://a", 9), item("b", "https://b")], [item("c", "https://c", 12)]])
        assert [i.title for i in merged] == ["c", "a", "b"]

    def test_dedupes_by_link_ignoring_query_and_trailing_slash(self):
        merged = merge_news([[item("one", "https://x.com/story/", 1)], [item("two", "https://x.com/story?utm=feed", 2)]])
        assert len(merged) == 1

    def test_dedupes_by_title_ignoring_case_and_punctuation(self):
        merged = merge_news([[item("Fed holds rates steady", "https://a", 1)], [item("FED HOLDS RATES STEADY!", "https://b", 2)]])
        assert len(merged) == 1

    def test_first_feed_wins_on_duplicate(self):
        merged = merge_news([[item("Same", "https://a", 1, source="First")], [item("Same", "https://b", 2, source="Second")]])
        assert merged[0].source == "First"

    def test_limit(self):
        merged = merge_news([[item(str(n), f"https://{n}", n) for n in range(10)]], limit=3)
        assert [i.title for i in merged] == ["9", "8", "7"]

    def test_max_per_source_keeps_newest_from_each_source(self):
        busy = [item(f"busy {n}", f"https://busy/{n}", n, source="Busy") for n in range(10, 20)]
        quiet = [item(f"quiet {n}", f"https://quiet/{n}", n, source="Quiet") for n in range(0, 3)]
        merged = merge_news([busy, quiet], max_per_source=2)
        assert [i.title for i in merged] == ["busy 19", "busy 18", "quiet 2", "quiet 1"]

    def test_max_per_source_none_keeps_everything(self):
        busy = [item(f"busy {n}", f"https://busy/{n}", n, source="Busy") for n in range(5)]
        assert len(merge_news([busy])) == 5


class TestFetch:
    async def test_fetch_feed_returns_empty_on_server_error(self, mock_http):
        async with httpx.AsyncClient() as client:
            assert await fetch_feed(client, Feed("Broken", BROKEN_URL)) == []

    async def test_fetch_feed_returns_empty_on_network_error(self):
        with respx.mock() as router:
            router.get("https://feeds.test/down.xml").mock(side_effect=httpx.ConnectTimeout("timeout"))
            async with httpx.AsyncClient() as client:
                assert await fetch_feed(client, Feed("Down", "https://feeds.test/down.xml")) == []

    async def test_fetch_all_merges_feeds_and_survives_one_failure(self, mock_http):
        feeds = [Feed("CNBC", CNBC_URL), Feed("MarketWatch", MW_URL), Feed("Broken", BROKEN_URL)]
        async with httpx.AsyncClient() as client:
            items = await fetch_all(client, feeds)
        titles = [i.title for i in items]
        assert titles[0] == "Stocks rally to record as tech leads gains"
        assert sum("fed holds rates" in t.lower() for t in titles) == 1
        assert {i.source for i in items} == {"CNBC", "MarketWatch"}


class TestAboutCompany:
    @staticmethod
    def item(title, summary=""):
        return news.NewsItem(title=title, link=f"https://x.test/{abs(hash(title))}", source="Yahoo Finance",
                             published=None, summary=summary)

    def test_company_keywords_drop_legal_suffixes(self):
        assert news.company_keywords("Apple Inc.") == ["apple"]
        assert news.company_keywords("Meta Platforms, Inc.") == ["meta", "platforms"]
        assert news.company_keywords("ELI LILLY & Co") == ["eli", "lilly"]
        assert news.company_keywords(None) == []

    def test_matches_ticker_as_a_whole_word_only(self):
        assert news.mentions_company(self.item("AAPL hits a record"), "AAPL")
        assert news.mentions_company(self.item("Stocks (AAPL, MSFT) rally"), "MSFT")
        assert not news.mentions_company(self.item("AAPLX fund launches"), "AAPL")

    def test_matches_company_name_case_insensitively(self):
        assert news.mentions_company(self.item("Why apple is down"), "AAPL", "Apple Inc.")
        assert news.mentions_company(self.item("Markets", "Microsoft beat estimates"), "MSFT", "Microsoft Corp")
        assert not news.mentions_company(self.item("Pineapple prices jump"), "AAPL", "Apple Inc.")

    def test_relevant_first_then_topped_up_in_feed_order(self):
        items = [self.item("Snap falls"), self.item("Apple rises"), self.item("HP slips"), self.item("Ford gains")]
        picked = news.about_company(items, "AAPL", "Apple Inc.", 3)
        assert [i.title for i in picked] == ["Apple rises", "Snap falls", "HP slips"]

    def test_only_relevant_when_there_are_enough(self):
        items = [self.item("Snap falls"), self.item("Apple rises"), self.item("AAPL record"), self.item("Apple deal")]
        picked = news.about_company(items, "AAPL", "Apple Inc.", 3)
        assert [i.title for i in picked] == ["Apple rises", "AAPL record", "Apple deal"]

    def test_empty_feed(self):
        assert news.about_company([], "AAPL", "Apple Inc.", 3) == []

import tempfile
import unittest
from pathlib import Path

from newsbot.config import Config
from newsbot.generate import IG_CAPTION_LIMIT, _clean_hashtags, compose_caption
from newsbot.models import Article, PostContent
from newsbot.monitor import _looks_like_article_path, normalize_url, parse_feed
from newsbot.storage import Storage


class TestNormalizeUrl(unittest.TestCase):
    def test_strips_query_fragment_and_trailing_slash(self):
        self.assertEqual(
            normalize_url("https://WWW.Example.com/2026/07/some-story/?utm=x#top"),
            "https://www.example.com/2026/07/some-story",
        )

    def test_preserves_scheme_for_fetching(self):
        self.assertEqual(
            normalize_url("http://127.0.0.1:8765/story-x/"),
            "http://127.0.0.1:8765/story-x",
        )

    def test_same_article_dedupes(self):
        a = normalize_url("https://www.example.com/foo-bar/")
        b = normalize_url("https://www.example.com/foo-bar?fbclid=123")
        self.assertEqual(a, b)


class TestArticlePathHeuristic(unittest.TestCase):
    def test_accepts_wordpress_permalinks(self):
        self.assertTrue(_looks_like_article_path("/2026/07/new-restaurant-opens"))
        self.assertTrue(_looks_like_article_path("/new-bakery-opens-on-columbus"))

    def test_rejects_navigation(self):
        for path in ("/", "/about", "/category/food", "/tag/uws", "/page/2", "/feed"):
            self.assertFalse(_looks_like_article_path(path), path)


class TestParseFeed(unittest.TestCase):
    def test_rss2(self):
        xml = b"""<?xml version="1.0"?><rss version="2.0"><channel>
            <title>Site</title>
            <item><title>Story One</title>
                  <link>https://example.com/story-one/</link>
                  <pubDate>Mon, 20 Jul 2026 09:00:00 +0000</pubDate></item>
            <item><title>Story Two</title>
                  <link>https://example.com/story-two/</link></item>
        </channel></rss>"""
        stubs = parse_feed(xml)
        self.assertEqual(len(stubs), 2)
        self.assertEqual(stubs[0].url, "https://example.com/story-one")
        self.assertEqual(stubs[0].title, "Story One")
        self.assertIn("2026", stubs[0].published)

    def test_atom(self):
        xml = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>Atom Story</title>
            <link rel="alternate" href="https://example.com/atom-story"/>
            <updated>2026-07-20T09:00:00Z</updated></entry>
        </feed>"""
        stubs = parse_feed(xml)
        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].url, "https://example.com/atom-story")
        self.assertEqual(stubs[0].title, "Atom Story")

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_feed(b"<html>not a feed"), [])
        self.assertEqual(parse_feed(b"\x00binary"), [])


class TestCaption(unittest.TestCase):
    def _article(self):
        return Article(url="https://x.com/a-b", title="Title", body="Body text here.")

    def test_caption_includes_cta_credit_and_hashtags(self):
        cfg = Config()
        content = PostContent(summary="A summary.", caption="Big news! 🎉",
                              hashtags=["uws", "nyc"])
        caption = compose_caption(content, self._article(), cfg)
        self.assertIn("link in bio", caption)
        self.assertIn(cfg.source_name, caption)
        self.assertIn("#uws #nyc", caption)
        self.assertTrue(caption.startswith("Big news! 🎉"))

    def test_caption_never_exceeds_instagram_limit(self):
        cfg = Config()
        content = PostContent(summary="word " * 800, caption="Hook",
                              hashtags=[f"tag{i}" for i in range(25)])
        caption = compose_caption(content, self._article(), cfg)
        self.assertLessEqual(len(caption), IG_CAPTION_LIMIT)
        self.assertIn("link in bio", caption)

    def test_hashtags_cleaned_and_deduped(self):
        tags = _clean_hashtags(["#UWS", "uws", "upper west side!", "", "nyc"])
        self.assertEqual(tags, ["UWS", "upperwestside", "nyc"])


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.store = Storage(base / "db.sqlite", base / "log.jsonl")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_dedup(self):
        url = "https://x.com/story"
        self.assertTrue(self.store.is_empty())
        self.assertFalse(self.store.is_processed(url))
        self.store.mark(url, "posted", title="T", ig_post_id="123")
        self.assertTrue(self.store.is_processed(url))
        self.assertFalse(self.store.is_empty())

    def test_error_then_posted_updates_status(self):
        url = "https://x.com/story"
        self.store.mark(url, "error", error="boom")
        self.store.mark(url, "posted", ig_post_id="99")
        row = self.store.conn.execute(
            "SELECT status, ig_post_id, posted_at FROM processed WHERE url=?", (url,)
        ).fetchone()
        self.assertEqual(row[0], "posted")
        self.assertEqual(row[1], "99")
        self.assertIsNotNone(row[2])

    def test_events_logged(self):
        self.store.mark("https://x.com/a", "seeded", title="A")
        lines = self.store.log_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn('"event": "seeded"', lines[0])


if __name__ == "__main__":
    unittest.main()

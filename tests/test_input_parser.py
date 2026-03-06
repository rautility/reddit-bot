"""Tests for input file parsing."""

import json

from bot.utils.input_parser import parse_links_file, ActionEntry


class TestParsePipeDelimited:
    def test_basic(self, tmp_path):
        f = tmp_path / "links.txt"
        f.write_text("https://reddit.com/r/test/comments/abc|upvote\nhttps://reddit.com/r/test|join\n")
        entries = parse_links_file(str(f))
        assert len(entries) == 2
        assert entries[0].action == "upvote"
        assert entries[1].action == "join"

    def test_with_comment(self, tmp_path):
        f = tmp_path / "links.txt"
        f.write_text("https://reddit.com/r/test/comments/abc|comment|Hello world\n")
        entries = parse_links_file(str(f))
        assert entries[0].comment == "Hello world"

    def test_empty_file(self, tmp_path):
        f = tmp_path / "links.txt"
        f.write_text("")
        entries = parse_links_file(str(f))
        assert entries == []


class TestParseJson:
    def test_json_format(self, tmp_path):
        f = tmp_path / "links.json"
        data = [
            {"link": "https://reddit.com/r/test", "action": "join"},
            {"link": "https://reddit.com/r/test/comments/abc", "action": "comment", "comment": "Hi"},
        ]
        f.write_text(json.dumps(data))
        entries = parse_links_file(str(f))
        assert len(entries) == 2
        assert entries[1].comment == "Hi"


class TestParseCsv:
    def test_csv_format(self, tmp_path):
        f = tmp_path / "links.csv"
        f.write_text("link,action,comment\nhttps://reddit.com/r/test,join,\nhttps://reddit.com/r/test/comments/abc,comment,Hello\n")
        entries = parse_links_file(str(f))
        assert len(entries) == 2
        assert entries[1].comment == "Hello"

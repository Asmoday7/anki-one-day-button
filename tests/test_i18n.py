"""Language detection, formatting and safe delivery to the real webviews."""

import json
import sys
from string import Formatter
from types import SimpleNamespace

import pytest

from holdup import i18n


@pytest.mark.parametrize("code,expected", [("en", "en"), ("en_GB", "en"), ("ru", "ru"), ("ru_RU", "ru"), ("ru-RU", "ru"), ("ja_JP", "en"), (None, "en")])
def test_uses_anki_language_with_english_fallback(monkeypatch, code, expected):
    monkeypatch.setitem(sys.modules, "anki.lang", SimpleNamespace(current_lang=code))
    assert i18n.language() == expected
    assert i18n.tr("Done") == ("Готово" if expected == "ru" else "Done")
    assert i18n.tr("New source text") == "New source text"


def test_import_without_anki_uses_english(monkeypatch):
    monkeypatch.delitem(sys.modules, "anki.lang", raising=False)
    assert i18n.tr("Again in {interval}", interval="2 s") == "Again in 2 s"


def test_translated_placeholders_match_and_all_messages_format(monkeypatch):
    fields = lambda text: {field for _, field, _, _ in Formatter().parse(text) if field}
    for source, russian in i18n.RUSSIAN.items():
        assert fields(source) == fields(russian), source
        for language in ("en", "ru"):
            monkeypatch.setattr(i18n, "language", lambda: language)
            text = i18n.tr(source, **{name: 2 for name in fields(source)})
            assert "{" not in text and "}" not in text


@pytest.mark.parametrize("language", ["en", "ru"])
def test_script_catalogue_is_json_and_cannot_close_script_tag(monkeypatch, language):
    monkeypatch.setattr(i18n, "language", lambda: language)
    monkeypatch.setitem(i18n.RUSSIAN, '</script><b>"', '</script><b>"')
    script = i18n.localize_script("const strings = __HOLDUP_STRINGS__;")
    assert "__HOLDUP_STRINGS__" not in script and "</script>" not in script
    texts = json.loads(script.removeprefix("const strings = ").removesuffix(";"))
    assert texts["Done"] == ("Готово" if language == "ru" else "Done")

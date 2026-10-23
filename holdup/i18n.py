"""Small English/Russian catalogue; no dependencies outside desktop Anki.

English is the source language and fallback. Anki loads anki.lang before add-ons;
looking up that loaded module keeps non-GUI imports usable without Anki installed.
"""

import json
import sys


RUSSIAN = {
    "Study day": "Учебный день",
    "d": "д",
    "h": "ч",
    "min": "мин",
    "s": "с",
    "HoldUp: continue studying": "HoldUp: продолжить изучение",
    "HoldUp: interval…": "HoldUp: интервал…",
    "HoldUp: clear all practice": "HoldUp: убрать всю практику",
    "HoldUp: schedule practice": "HoldUp: назначить практику",
    "HoldUp: repeat practice": "HoldUp: перенести практику",
    "HoldUp: finish practice": "HoldUp: завершить практику",
    "HoldUp: resume paused practice cards": "HoldUp: возобновить карточки практики",
    "HoldUp: practice — ready {ready}, waiting {waiting}": "HoldUp: практика — готово {ready}, ожидают {waiting}",
    "HoldUp: practice — unable to read appointments": "HoldUp: практика — ошибка чтения",
    "HoldUp: the action could not be completed. It was not retried automatically.": "HoldUp: действие не выполнено. Ничего не повторялось автоматически.",
    "The open collection changed": "Открытая коллекция изменилась",
    "HoldUp — practice interval": "HoldUp — интервал практики",
    "When should the next extra appearance be scheduled?": "Когда назначать следующий дополнительный показ:",
    "After an interval from 1 second to 24 hours": "Через интервал от 1 секунды до 24 часов",
    "2 seconds": "2 секунды",
    "2 minutes": "2 минуты",
    "1 hour": "1 час",
    "1 day": "1 день",
    "Next Anki study day": "Следующий учебный день Anki",
    "The study day starts at the time set in Anki's preferences. “1 day” above means exactly 24 hours.": "Учебный день начнётся в час, выбранный в настройках Anki. «1 день» выше означает ровно 24 часа.",
    "HoldUp adds an extra appearance of this card without an FSRS rating. The original stays in Anki: choose a normal rating after scheduling practice. This setting applies to subsequent actions.": "HoldUp добавляет отдельный показ той же карточки без оценки FSRS. Оригинал остаётся в Anki: после назначения выберите обычную оценку. Настройка применяется к следующим нажатиям.",
    "HoldUp · practice without an FSRS rating": "HoldUp · практика без оценки FSRS",
    "Show Answer": "Показать ответ",
    "Next study day": "Следующий учебный день",
    "Again in {interval}": "Ещё через {interval}",
    "Done": "Готово",
    "Continue studying": "Продолжить изучение",
    "HoldUp: waiting {waiting} · ready {ready}": "HoldUp: ожидают {waiting} · к повторению {ready}",
    "HoldUp: waiting {count}": "HoldUp: ожидают {count}",
    "New": "Новые",
    "Learning": "Обучение",
    "Reviews: Anki {native}, HoldUp {ready}": "Повторение: Anki {native}, HoldUp {ready}",
    "Change the extra practice interval": "Изменить интервал отдельной практики",
    "Extra practice at the start of the next Anki study day.": "Дополнительный показ в начале следующего учебного дня Anki.",
    "Extra practice in {interval}.": "Отдельная практика через {interval}.",
    "No FSRS rating is recorded. The original stays in Anki: choose a normal rating separately.": "Оценка FSRS не записывается. Оригинал остаётся в Anki: выберите обычную оценку отдельно.",
    "Extra practice scheduled. Now choose a normal Anki rating.": "Дополнительный показ назначен. Теперь выберите обычную оценку Anki.",
    "HoldUp: ready {count} (including subdecks)": "HoldUp: к повторению {count} (включая подколоды)",
}


def language() -> str:
    code = getattr(sys.modules.get("anki.lang"), "current_lang", "en")
    return "ru" if isinstance(code, str) and code.lower().replace("-", "_").split("_")[0] == "ru" else "en"


def tr(source: str, **values) -> str:
    text = RUSSIAN.get(source, source) if language() == "ru" else source
    return text.format(**values)


def localize_script(script: str) -> str:
    """Insert static translations as JSON, never executable translated HTML."""
    texts = RUSSIAN if language() == "ru" else {source: source for source in RUSSIAN}
    encoded = json.dumps(texts, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return script.replace("__HOLDUP_STRINGS__", encoded)

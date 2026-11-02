"""Small, request-scoped UI catalog; product identifiers and license texts stay intact."""
import json
from pathlib import Path
from flask import request
from werkzeug.datastructures import LanguageAccept

LANGUAGES = (
    ('zh-CN', '简体中文'),
    ('zh-TW', '繁體中文'),
    ('en', 'English'),
    ('ja', '日本語'),
    ('fr', 'Français'),
)
SUPPORTED = frozenset(code for code, _ in LANGUAGES)
CATALOG = json.loads(Path(__file__).with_name('translations.json').read_text(encoding='utf-8'))


def current_language():
    for value in (request.args.get('lang'), request.cookies.get('kms_language')):
        if value in SUPPORTED:
            return value
    # Chinese is the fallback; keep Simplified and Traditional browser tags distinct.
    preferences = []
    for tag, quality in request.accept_languages:
        normalized = tag.lower()
        primary = normalized.split('-')[0]
        if normalized == 'zh-hant' or normalized.startswith(('zh-hant-', 'zh-tw', 'zh-hk', 'zh-mo')):
            language = 'zh-TW'
        elif primary == 'zh':
            language = 'zh-CN'
        else:
            language = primary
        preferences.append((language, quality))
    return LanguageAccept(preferences).best_match(tuple(code for code, _ in LANGUAGES)) or 'zh-CN'


def translate(message, **values):
    """Resolve one UI string for the current request language; product data is never translated."""
    return CATALOG.get(current_language(), {}).get(message, message).format(**values)


def register_i18n(app):
    @app.context_processor
    def translation_context():
        language = current_language()
        return dict(t=translate, language=language, languages=LANGUAGES, ui_messages=CATALOG.get(language, {}))

    @app.after_request
    def language_headers(response):
        response.headers['Content-Language'] = current_language()
        response.vary.add('Cookie')
        response.vary.add('Accept-Language')
        selected = request.args.get('lang')
        if selected in SUPPORTED and request.is_secure:
            response.set_cookie('kms_language', selected, max_age=31536000,
                                secure=True, httponly=True, samesite='Lax')
        return response

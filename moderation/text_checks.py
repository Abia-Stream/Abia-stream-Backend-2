"""
Cheap text signals for comments, video metadata and live chat.

Deliberately conservative: a hit on a comment or video only adds it to the
moderation queue (a human decides). Live chat, where nobody can review in
time, rejects the message instead.
"""
import re

from django.conf import settings

SPAM_LINKS = 'spam_links'
CONTACT_SPAM = 'contact_spam'
BANNED_TERM = 'banned_term'

URL_RE = re.compile(
    r'(?:https?://|www\.)\S+'
    r'|\b[a-z0-9-]+\.(?:com|net|org|io|ng|xyz|link|ly|me|co|info|biz|club|top|site|online)\b(?:/\S*)?',
    re.IGNORECASE,
)
SHORTENERS = ('bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'cutt.ly', 'rb.gy', 'is.gd',
              'wa.me', 't.me', 'shorturl.at', 'tiny.cc')
# Nigerian mobile numbers (0803..., +234 803...) and long international ones.
PHONE_RE = re.compile(r'(?:\+?234|\b0)[789][01]\d[\s-]?\d{3}[\s-]?\d{4}\b|\+\d[\d\s-]{9,15}\d')
CONTACT_WORDS = re.compile(r'\b(?:whats\s?app|telegram|dm me|inbox me|call me|text me)\b', re.IGNORECASE)


def banned_terms():
    return [t.strip().casefold() for t in getattr(settings, 'MODERATION_BANNED_TERMS', []) if t.strip()]


def check_text(text):
    """Returns a list of (signal, details) for `text`. Empty when clean."""
    text = text or ''
    hits = []

    links = URL_RE.findall(text)
    shortened = [link for link in links if any(s in link.lower() for s in SHORTENERS)]
    if shortened or len(links) >= 2:
        hits.append((SPAM_LINKS, {'links': links[:5]}))

    phones = PHONE_RE.findall(text)
    if phones or (CONTACT_WORDS.search(text) and links):
        hits.append((CONTACT_SPAM, {'phone_numbers': len(phones)}))

    folded = text.casefold()
    found = [t for t in banned_terms() if re.search(rf'\b{re.escape(t)}\b', folded)]
    if found:
        # Record how many, not which: the queue shows the text itself.
        hits.append((BANNED_TERM, {'count': len(found)}))

    return hits


def allowed_in_chat(text):
    """Chat is unreviewable in real time: no links, phone numbers or banned terms."""
    if URL_RE.search(text or '') or PHONE_RE.search(text or ''):
        return False
    return not any(signal == BANNED_TERM for signal, _ in check_text(text))

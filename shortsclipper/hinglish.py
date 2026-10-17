"""Hinglish romanization: Devanagari -> readable Latin script for captions.

Two passes per token:

1. English-loanword lexicon. Hindi speakers constantly write English words
   in Devanagari (टू, करियर, एडवाइज़र). A plain phonetic romanizer turns
   these into "tu", "kariyar", "edavaaijara" — faithful to the letters,
   unreadable as Hinglish. The lexicon maps common Devanagari spellings
   (and variants) back to the English spelling. Plurals written with a
   trailing स/स्/ज़ ("जॉब्स") fall back to the stem + "s".

2. Phonetic romanization of whatever remains, via indic-transliteration's
   IAST plus readability fixes (no diacritics, natural vowel spellings,
   trailing schwa drop). This is what Hinglish readers expect: "कैसे" ->
   "kaise", "बहुत" -> "bahut".

If indic-transliteration is not installed and a Hinglish render is
requested, we raise instead of silently shipping Devanagari captions the
user explicitly asked to be romanized (the v0.2.0 AppImage bug).
"""

import re

from .logutil import get_logger

log = get_logger("hinglish")

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_NUKTA = "़"


class HinglishUnavailableError(RuntimeError):
    """Raised when Hinglish captions are requested but the transliteration
    dependency is missing. Loud on purpose — see module docstring."""


def require_hinglish():
    """Import the transliteration dependency or raise a clear error."""
    try:
        from indic_transliteration import sanscript  # noqa: F401
        from indic_transliteration.sanscript import transliterate  # noqa: F401
    except Exception as e:
        raise HinglishUnavailableError(
            "Hinglish captions (--caption-script hinglish) need the "
            "'indic-transliteration' package, which is not installed in this "
            "environment. Install it with: pip install indic-transliteration "
            "(it is listed in requirements.txt — AppImages built from "
            "v0.2.1+ bundle it). Underlying import error: "
            f"{type(e).__name__}: {e}"
        ) from e


# ---- English-loanword lexicon -------------------------------------------
# Keyed by the exact Devanagari spelling; variants map to the same English.
# Keep entries lowercase English. Focus: function words + career/tech/money/
# media vocabulary that shows up in Hindi commentary videos.
_LOANWORDS = {
    # function words English speakers drop into Hindi sentences
    "टू": "to", "डू": "do", "डज़": "does", "डिड": "did", "इज़": "is", "इज": "is",
    "आर": "are", "वाज़": "was", "वाज": "was", "वर": "were", "वेर": "were",
    "विल": "will", "वुड": "would", "शुड": "should", "कुड": "could",
    "कैन": "can", "नॉट": "not", "नो": "no", "यस": "yes", "ओके": "ok",
    "ओक": "ok", "हाय": "hi", "है": "hey", "हे": "hey", "हेलो": "hello",
    "हैलो": "hello", "बाय": "bye", "सॉरी": "sorry", "थैंक": "thank",
    "थैंक्यू": "thank you", "प्लीज़": "please", "प्लीज": "please",
    "व्हाट": "what", "व्हेन": "when", "व्हेयर": "where", "व्हाय": "why",
    "हाउ": "how", "हु": "who", "व्हिच": "which", "दिस": "this", "दैट": "that",
    "दीज़": "these", "दोज़": "those", "हियर": "here", "हेयर": "here",
    "देयर": "there", "देर": "there", "माय": "my", "योर": "your", "हिज़": "his",
    "हर": "her", "आवर": "our", "अवर": "our", "देम": "them", "अस": "us",
    "मी": "me", "यू": "you", "आई": "i", "वी": "we", "दे": "they", "ही": "he",
    "शी": "she", "इट": "it", "एंड": "and", "ओर": "or", "बट": "but",
    "इफ": "if", "देन": "then", "सो": "so", "बिकॉज़": "because", "आल्सो": "also",
    "ओनली": "only", "जस्ट": "just", "लाइक": "like", "इवन": "even",
    "एवर": "ever", "नेवर": "never", "ऑलवेज़": "always", "समटाइम्स": "sometimes",
    "नाउ": "now", "टुडे": "today", "टुमॉरो": "tomorrow", "यस्टरडे": "yesterday",
    "टाइम": "time", "डे": "day", "नाइट": "night", "मॉर्निंग": "morning",
    "इवनिंग": "evening", "वीक": "week", "मंथ": "month", "ईयर": "year",
    "लाइफ": "life", "वर्ल्ड": "world", "पीपल": "people", "गाइज़": "guys",
    "गाईज़": "guys", "फ्रेंड": "friend", "फ्रेंड्स": "friends", "फैमिली": "family",
    "मोम": "mom", "डैड": "dad", "ब्रदर": "brother", "सिस्टर": "sister",
    # work / career / money
    "बॉस": "boss", "जॉब": "job", "जॉब्स": "jobs", "वर्क": "work",
    "करियर": "career", "कैरियर": "career", "एडवाइज़र": "advisor",
    "एडवाइजर": "advisor", "इंटरव्यू": "interview", "सैलरी": "salary",
    "कंपनी": "company", "मैनेजर": "manager", "ऑफिस": "office",
    "मीटिंग": "meeting", "प्रोजेक्ट": "project", "क्लाइंट": "client",
    "टीम": "team", "बिज़नेस": "business", "बिजनेस": "business",
    "मार्केटिंग": "marketing", "सेल्स": "sales", "प्रॉफिट": "profit",
    "लॉस": "loss", "मनी": "money", "बैंक": "bank", "अकाउंट": "account",
    "पेमेंट": "payment", "लोन": "loan", "टैक्स": "tax", "इनकम": "income",
    "अर्निंग": "earning", "स्टॉक": "stock", "शेयर": "share",
    "इन्वेस्टमेंट": "investment", "क्रिप्टो": "crypto", "ट्रेडिंग": "trading",
    "स्टार्टअप": "startup", "फाउंडर": "founder", "इंटर्नशिप": "internship",
    "रिज़्यूमे": "resume", "प्लेसमेंट": "placement", "पैकेज": "package",
    "एक्सपीरियंस": "experience", "फ्रेशर": "fresher", "ग्रोथ": "growth",
    "सक्सेस": "success", "टारगेट": "target", "गोल": "goal", "फोकस": "focus",
    "माइंडसेट": "mindset", "मोटिवेशन": "motivation", "हैबिट": "habit",
    "प्रोडक्टिविटी": "productivity", "स्किल": "skill", "स्किल्स": "skills",
    # education
    "डॉक्टर": "doctor", "टीचर": "teacher", "स्कूल": "school",
    "कॉलेज": "college", "यूनिवर्सिटी": "university", "एग्ज़ाम": "exam",
    "एग्जाम": "exam", "टेस्ट": "test", "मार्क्स": "marks", "रिज़ल्ट": "result",
    "रिजल्ट": "result", "कोर्स": "course", "क्लास": "class",
    "ट्रेनिंग": "training", "सर्टिफिकेट": "certificate", "डिग्री": "degree",
    "इंग्लिश": "english", "हिंदी": "hindi", "साइंस": "science",
    "मैथ्स": "maths", "हिस्ट्री": "history", "लैंग्वेज": "language",
    # tech / media
    "ईमेल": "email", "फोन": "phone", "मोबाइल": "mobile",
    "कंप्यूटर": "computer", "लैपटॉप": "laptop", "इंटरनेट": "internet",
    "वेबसाइट": "website", "ऐप": "app", "एप": "app", "ऐप्स": "apps",
    "एप्लीकेशन": "application", "वीडियो": "video", "वीडियोस": "videos",
    "ऑडियो": "audio", "कैमरा": "camera", "फोटो": "photo", "फाइल": "file",
    "फोल्डर": "folder", "डाउनलोड": "download", "अपलोड": "upload",
    "ऑनलाइन": "online", "ऑफलाइन": "offline", "डेटा": "data",
    "सर्वर": "server", "सॉफ्टवेयर": "software", "हार्डवेयर": "hardware",
    "कोडिंग": "coding", "प्रोग्राम": "program", "प्रोग्रामिंग": "programming",
    "डेवलपर": "developer", "इंजीनियर": "engineer", "इंजीनियरिंग": "engineering",
    "मशीन": "machine", "लर्निंग": "learning", "मॉडल": "model",
    "प्रॉम्प्ट": "prompt", "रोबोट": "robot", "टेक्नोलॉजी": "technology",
    "टेक्नोलोजी": "technology", "डिजिटल": "digital", "एआई": "ai",
    "ए आई": "ai", "चैटजीपीटी": "chatgpt", "जेमिनी": "gemini",
    "गूगल": "google", "यूट्यूब": "youtube", "इंस्टाग्राम": "instagram",
    "व्हाट्सऐप": "whatsapp", "व्हाट्सएप": "whatsapp", "टेलीग्राम": "telegram",
    "ट्विटर": "twitter", "फेसबुक": "facebook", "लिंक्डइन": "linkedin",
    "अमेज़ॉन": "amazon", "अमेजॉन": "amazon", "फ्लिपकार्ट": "flipkart",
    # news / stories / misc content words
    "न्यूज़": "news", "न्यूज": "news", "रिपोर्ट": "report", "स्टोरी": "story",
    "बुक": "book", "पेज": "page", "लाइन": "line", "वर्ड": "word",
    "प्रॉब्लम": "problem", "सलूशन": "solution", "सोल्यूशन": "solution",
    "क्वेश्चन": "question", "आंसर": "answer", "आइडिया": "idea",
    "प्लान": "plan", "स्टार्ट": "start", "स्टॉप": "stop", "फिनिश": "finish",
    "ओपन": "open", "क्लोज़": "close", "प्ले": "play", "गेम": "game",
    "प्लेयर": "player", "मैच": "match", "विन": "win", "लूज़": "lose",
    "स्कोर": "score", "फ्री": "free", "प्राइस": "price", "चीप": "cheap",
    "एक्सपेंसिव": "expensive", "डिस्काउंट": "discount", "ऑफर": "offer",
    "सेल": "sale", "पे": "pay", "कैश": "cash", "कार्ड": "card",
    "नंबर": "number", "नेम": "name", "एड्रेस": "address", "प्लेस": "place",
    "होम": "home", "रूम": "room", "गुड": "good", "बैड": "bad",
    "बेस्ट": "best", "बेटर": "better", "फास्ट": "fast", "स्लो": "slow",
    "ईज़ी": "easy", "इज़ी": "easy", "हार्ड": "hard", "सिंपल": "simple",
    "डिफिकल्ट": "difficult", "इंपॉर्टेंट": "important", "इम्पोर्टेन्ट": "important",
    "डिफरेंट": "different", "फर्स्ट": "first", "सेकंड": "second",
    "लास्ट": "last", "नेक्स्ट": "next", "बिग": "big", "स्मॉल": "small",
    "न्यू": "new", "ओल्ड": "old", "रियल": "real", "फेक": "fake",
    "ट्रू": "true", "फुल": "full", "हाफ": "half", "मच": "much",
    "मेनी": "many", "मोर": "more", "लेस": "less", "वेरी": "very",
}

# Plural suffixes Hindi writers tack onto English words.
_PLURAL_SUFFIXES = ("स्", "स", "ज़", "ज")


def _lookup_loanword(token):
    """Exact Devanagari spelling -> English, trying nukta-less and plural
    variants. Returns None when the token is not a known loanword."""
    hit = _LOANWORDS.get(token)
    if hit:
        return hit
    stripped = token.replace(_NUKTA, "")
    hit = _LOANWORDS.get(stripped)
    if hit:
        return hit
    for suf in _PLURAL_SUFFIXES:
        if token.endswith(suf) and len(token) > len(suf) + 1:
            stem = token[: -len(suf)]
            hit = _LOANWORDS.get(stem) or _LOANWORDS.get(stem.replace(_NUKTA, ""))
            if hit and not hit.endswith("s"):
                return hit + "s"
    return None


# ---- phonetic romanization ----------------------------------------------

_IAST_HINGLISH = [("ā", "aa"), ("ī", "i"), ("ū", "u"), ("ṃ", "n"), ("ṁ", "n"),
                  ("ṅ", "ng"), ("ñ", "ny"), ("ṇ", "n"), ("ṭh", "th"), ("ṭ", "t"),
                  ("ḍh", "dh"), ("ḍ", "d"), ("ṛ", "r"), ("ś", "sh"), ("ṣ", "sh"),
                  ("ḥ", ""), ("ē", "e"), ("ō", "o")]


def _romanize_phonetic(word):
    """IAST -> natural Hinglish spelling (no diacritics, schwa drop)."""
    require_hinglish()  # loud, wrapped error when the dep is missing
    from indic_transliteration import sanscript
    from indic_transliteration.sanscript import transliterate
    s = transliterate(word, sanscript.DEVANAGARI, sanscript.IAST)
    for a, b in _IAST_HINGLISH:
        s = s.replace(a, b)
    s = s.replace("~", "n")
    s = re.sub(r"[^\x00-\x7fA-Za-z']", "", s).lower()
    s = re.sub(r"([bcdfghjklmnpqrstvwxyz])a$", r"\1", s)
    return s


def to_hinglish(word):
    """Romanize a Devanagari word to readable Hinglish. Latin passes through.

    Known English loanwords return the English spelling ("करियर" -> "career");
    everything else gets a natural phonetic romanization ("बहुत" -> "bahut").
    Requires indic-transliteration — raises HinglishUnavailableError when it
    is missing so a requested Hinglish render can never silently no-op.
    """
    if not _DEVANAGARI.search(word):
        return word
    hit = _lookup_loanword(word.strip())
    if hit:
        return hit
    return _romanize_phonetic(word) or word

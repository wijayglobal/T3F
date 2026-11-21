"""Repairs for OCR'd Tamil (TVA glossaries). No Django imports.

The OCR read some Tamil letters as the Tamil digits they resemble (காற்றுச் ௪மிழ் for காற்றுச் சமிழ்),
wrote ர் as ா் (a legacy-font artefact: உட்கவா்தல்), and kept zero-width joiners. Digits are only
replaced inside a word that also has Tamil letters, so a real number like ௧௨ is left alone.
"""
import re
import unicodedata

TAMIL_LETTER = re.compile(r"[஀-௥]")  # letters and signs, not the digits ௦-௯
DIGIT_LOOKALIKES = {"௧": "க", "௨": "உ", "௪": "ச", "௫": "ரு", "௭": "எ", "௮": "அ"}
DIGIT = re.compile("[" + "".join(DIGIT_LOOKALIKES) + "]")
LATIN_OR_ASCII_DIGIT = re.compile(r"[A-Za-z0-9]")
EN_DIGIT_RUN = re.compile(r"\d")


def fix_tamil(s: str) -> str:
    s = unicodedata.normalize("NFC", s.replace("‌", "").replace("‍", "").replace("­", ""))
    s = s.replace("ா்", "ர்")
    words = [DIGIT.sub(lambda m: DIGIT_LOOKALIKES[m.group()], w) if TAMIL_LETTER.search(w) else w
             for w in s.split()]
    return " ".join(words)


def tamil_problem(s: str) -> str:
    """Why a repaired Tamil cell is still unusable, or "" if it is fine."""
    if not TAMIL_LETTER.search(s):
        return "no Tamil letters"
    if LATIN_OR_ASCII_DIGIT.search(s):
        return "Latin letters or digits in the Tamil"
    if re.search(r"[௦-௯]", s):
        return "Tamil digits left inside words"
    return ""


def english_problem(s: str) -> str:
    """Merged columns ("Acoustic filter 2 Alpha ray emission filter") and page noise ("Micrometer 081106")."""
    return "digits in the English headword (merged OCR columns)" if EN_DIGIT_RUN.search(s) else ""

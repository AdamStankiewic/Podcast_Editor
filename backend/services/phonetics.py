"""
Phonetics service for SSML pronunciation injection
Parses pronunciations.csv and injects <sub> and <phoneme> tags
"""
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass


@dataclass
class PronunciationRule:
    """Single pronunciation rule"""
    source: str  # Original word/phrase
    target: str  # Replacement or IPA notation
    mode: str  # "sub" or "phoneme_ipa"


class PhoneticsService:
    """Handles pronunciation rules and SSML injection"""

    def __init__(self, csv_path: str = "./pronunciations.csv"):
        self.csv_path = Path(csv_path)
        self.rules: List[PronunciationRule] = []
        self.load_rules()

    def load_rules(self):
        """Load pronunciation rules from CSV"""
        if not self.csv_path.exists():
            print(f"Warning: Pronunciations CSV not found: {self.csv_path}")
            return

        try:
            with self.csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    source = row.get("source", "").strip()
                    target = row.get("target", "").strip()
                    mode = row.get("mode", "").strip()

                    if not source or not target or not mode:
                        continue

                    if mode not in ["sub", "phoneme_ipa"]:
                        print(f"Warning: Invalid mode '{mode}' for rule '{source}', skipping")
                        continue

                    self.rules.append(PronunciationRule(
                        source=source,
                        target=target,
                        mode=mode
                    ))

            print(f"Loaded {len(self.rules)} pronunciation rules")

        except Exception as e:
            print(f"Error loading pronunciation rules: {e}")

    def inject_ssml_tags(self, text: str) -> str:
        """
        Inject SSML pronunciation tags into text
        - Case-insensitive matching
        - Only whole word/phrase matching
        - Preserves original text casing inside tags
        """
        if not self.rules:
            return text

        # Sort rules by length (longest first) to handle phrases before words
        sorted_rules = sorted(self.rules, key=lambda r: len(r.source), reverse=True)

        result = text

        for rule in sorted_rules:
            # Build regex pattern for whole word/phrase matching (case-insensitive)
            # Use word boundaries, but handle multi-word phrases
            pattern = r'\b(' + re.escape(rule.source) + r')\b'

            def replacer(match):
                """Replace function that preserves original casing"""
                original = match.group(1)

                if rule.mode == "sub":
                    # <sub alias="target">original</sub>
                    return f'<sub alias="{self._escape_xml(rule.target)}">{original}</sub>'
                elif rule.mode == "phoneme_ipa":
                    # <phoneme alphabet="ipa" ph="target">original</phoneme>
                    return f'<phoneme alphabet="ipa" ph="{self._escape_xml(rule.target)}">{original}</phoneme>'

                return original

            # Replace all occurrences (case-insensitive)
            result = re.sub(pattern, replacer, result, flags=re.IGNORECASE)

        return result

    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters for attributes"""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;"))

    def validate_ssml(self, text: str) -> Tuple[bool, str]:
        """
        Validate that SSML tags are properly formed
        Returns (is_valid, error_message)
        """
        # Check for unclosed tags
        sub_open = text.count("<sub ")
        sub_close = text.count("</sub>")

        phoneme_open = text.count("<phoneme ")
        phoneme_close = text.count("</phoneme>")

        errors = []

        if sub_open != sub_close:
            errors.append(f"Mismatched <sub> tags: {sub_open} open, {sub_close} close")

        if phoneme_open != phoneme_close:
            errors.append(f"Mismatched <phoneme> tags: {phoneme_open} open, {phoneme_close} close")

        # Check for nested tags (not allowed in SSML)
        if re.search(r'<(sub|phoneme)[^>]*>.*?<(sub|phoneme)', text):
            errors.append("Nested pronunciation tags detected (not allowed)")

        if errors:
            return False, "; ".join(errors)

        return True, ""

    def get_statistics(self, text: str) -> Dict[str, int]:
        """Get statistics about injected tags"""
        return {
            "sub_tags": text.count("<sub "),
            "phoneme_tags": text.count("<phoneme "),
            "total_rules_applied": text.count("<sub ") + text.count("<phoneme ")
        }

    # Roman numeral to Polish ordinal mapping (most common centuries/numbers)
    _ROMAN_TO_POLISH = {
        'I': 'pierwszego', 'II': 'drugiego', 'III': 'trzeciego',
        'IV': 'czwartego', 'V': 'piątego', 'VI': 'szóstego',
        'VII': 'siódmego', 'VIII': 'ósmego', 'IX': 'dziewiątego',
        'X': 'dziesiątego', 'XI': 'jedenastego', 'XII': 'dwunastego',
        'XIII': 'trzynastego', 'XIV': 'czternastego', 'XV': 'piętnastego',
        'XVI': 'szesnastego', 'XVII': 'siedemnastego', 'XVIII': 'osiemnastego',
        'XIX': 'dziewiętnastego', 'XX': 'dwudziestego', 'XXI': 'dwudziestego pierwszego',
    }

    def _expand_roman_numerals(self, text: str) -> Tuple[str, int]:
        """
        Replace Roman numerals (I-XXI) with Polish ordinal words.
        Only matches standalone Roman numerals (e.g. 'XIX wieku' but not 'I' as pronoun).
        """
        count = 0

        def replace_roman(match):
            nonlocal count
            roman = match.group(1)
            if roman in self._ROMAN_TO_POLISH:
                count += 1
                return self._ROMAN_TO_POLISH[roman]
            return roman

        # Match Roman numerals followed by Polish context words (wieku, wiek, stulecie, etc.)
        # or preceded by context like "w" (w XIX wieku)
        # Pattern: standalone Roman numeral (II-XXI) that looks like a numeral, not a word
        # We match Roman numerals that are:
        # 1. Followed by typical Polish words: wieku, wiek, wieka, stulecia, etc.
        # 2. Or multi-char Roman numerals (II+) standing alone
        result = re.sub(
            r'\b(XXI|XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II)\b'
            r'(?=\s+(?:wieku|wiek|wieka|wieków|stulecia|stuleciu|wieku))',
            replace_roman,
            text
        )

        # Also match standalone multi-char Roman numerals (III+) not near Polish "I" pronoun
        result = re.sub(
            r'\b(XXI|XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|IX|VIII|VII|VI|IV|III|II)\b',
            replace_roman,
            result
        )

        return result, count

    def apply_text_replacements(self, text: str) -> Tuple[str, int]:
        """
        Apply simple text replacements without SSML tags.

        For use with TTS providers that don't support SSML (like Chatterbox).
        Only applies 'sub' mode rules as direct text replacements.
        Also expands Roman numerals to Polish ordinal words.

        Args:
            text: Input text

        Returns:
            Tuple of (modified_text, number_of_replacements)
        """
        result = text
        total_replacements = 0

        # First expand Roman numerals
        result, roman_count = self._expand_roman_numerals(result)
        total_replacements += roman_count

        if not self.rules:
            return result, total_replacements

        # Sort rules by length (longest first)
        sorted_rules = sorted(self.rules, key=lambda r: len(r.source), reverse=True)

        for rule in sorted_rules:
            # Only apply 'sub' mode rules (direct text replacement)
            # Skip 'phoneme_ipa' as there's no way to represent IPA without SSML
            if rule.mode != "sub":
                continue

            # Build regex pattern for whole word matching
            pattern = r'\b' + re.escape(rule.source) + r'\b'

            # Count matches before replacement
            matches = len(re.findall(pattern, result, flags=re.IGNORECASE))

            if matches > 0:
                # Replace with target (preserving case of first letter if possible)
                def smart_replace(match):
                    original = match.group(0)
                    target = rule.target
                    # Preserve capitalization
                    if original[0].isupper() and target[0].islower():
                        target = target[0].upper() + target[1:]
                    elif original[0].islower() and target[0].isupper():
                        target = target[0].lower() + target[1:]
                    return target

                result = re.sub(pattern, smart_replace, result, flags=re.IGNORECASE)
                total_replacements += matches

        return result, total_replacements

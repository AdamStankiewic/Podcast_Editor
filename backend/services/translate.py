"""
Translation service using OpenAI GPT
Implements chunking with context preservation and length matching
"""
import os
import re
from typing import List, Tuple
from openai import OpenAI


class TranslationService:
    """Handles German to target language translation with context and length preservation"""

    # Language configurations: code -> (name, prompts)
    LANGUAGES = {
        "pl": {
            "name": "Polish",
            "native_name": "Polski",
            "role": "profesjonalnym lektorem podcastów historycznych. Tłumaczysz niemieckie nagrania na polski",
            "length_label": "znaków",
            "context_label": "KONTEKST GLOBALNY",
            "previous_label": "KONIEC POPRZEDNIEGO FRAGMENTU",
            "text_label": "TEKST DO TŁUMACZENIA",
            "response_label": "Odpowiedź (polskie tłumaczenie"
        },
        "fr": {
            "name": "French",
            "native_name": "Français",
            "role": "un narrateur professionnel de podcasts historiques. Tu traduis des enregistrements allemands en français",
            "length_label": "caractères",
            "context_label": "CONTEXTE GLOBAL",
            "previous_label": "FIN DU FRAGMENT PRÉCÉDENT",
            "text_label": "TEXTE À TRADUIRE",
            "response_label": "Réponse (traduction française"
        },
        "en": {
            "name": "English",
            "native_name": "English",
            "role": "a professional historical podcast narrator. You translate German recordings to English",
            "length_label": "characters",
            "context_label": "GLOBAL CONTEXT",
            "previous_label": "END OF PREVIOUS FRAGMENT",
            "text_label": "TEXT TO TRANSLATE",
            "response_label": "Response (English translation"
        }
    }

    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini", target_language: str = "pl"):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.target_language = target_language
        self.chunk_size = 3000  # Characters per chunk
        self.overlap_sentences = 2  # Sentences to overlap for context
        self.enable_ai_quality_check = True  # Always enabled for professional quality

        if target_language not in self.LANGUAGES:
            raise ValueError(f"Unsupported language: {target_language}. Supported: {list(self.LANGUAGES.keys())}")

    def translate(self, text: str, progress_callback=None) -> str:
        """
        Main translation method with chunking and context preservation

        Args:
            text: German text to translate
            progress_callback: Optional callback(current, total, message)

        Returns:
            Translated Polish text
        """
        # Step 1: Create global context summary
        if progress_callback:
            progress_callback(1, 4, "Creating global context summary...")

        global_context = self._create_global_context(text)

        # Step 2: Split into chunks
        if progress_callback:
            progress_callback(2, 4, "Splitting text into chunks...")

        chunks = self._split_into_chunks(text)

        # Step 3: Translate chunks with context
        if progress_callback:
            progress_callback(3, 4, f"Translating {len(chunks)} chunks...")

        translated_chunks = []
        previous_ending = ""

        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback(
                    3, 4,
                    f"Translating chunk {i+1}/{len(chunks)} ({len(chunk)} chars)..."
                )

            translated = self._translate_chunk(
                chunk,
                global_context,
                previous_ending,
                chunk_index=i,
                total_chunks=len(chunks)
            )

            translated_chunks.append(translated)

            # Extract last 2-3 sentences for next chunk context
            previous_ending = self._extract_ending_sentences(translated, count=2)

        # Step 4: Post-processing and editorial pass
        if progress_callback:
            progress_callback(4, 5, "Editorial pass: removing repetitions...")

        full_translation = "\n\n".join(translated_chunks)
        final_text = self._editorial_pass(full_translation)

        # Step 5: AI Quality Check (professional quality validation)
        if self.enable_ai_quality_check:
            if progress_callback:
                progress_callback(5, 5, "AI quality check: validating translation...")

            final_text = self._ai_quality_validator(final_text, text)

        return final_text

    def _create_global_context(self, text: str) -> str:
        """Create concise summary of the entire text (1-2k chars)"""
        prompt = f"""Jesteś ekspertem od podcastów historycznych. Przeczytaj poniższy niemiecki tekst i stwórz KRÓTKIE streszczenie (max 1500 znaków) zawierające:
- Główny temat/wydarzenie
- Kluczowe postacie/miejsca/daty
- Ogólny ton narracji

Tekst do streszczenia:
{text[:8000]}

Odpowiedź (TYLKO streszczenie, po polsku):"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Jesteś ekspertem od podcastów historycznych."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"Warning: Failed to create global context: {e}")
            return "Podcast historyczny."

    def _split_into_chunks(self, text: str) -> List[str]:
        """Split text into chunks of ~3000 chars, preserving paragraph boundaries"""
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            # If single paragraph is too long, split by sentences
            if len(para) > self.chunk_size:
                sentences = self._split_sentences(para)
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 2 <= self.chunk_size:
                        current_chunk += sent + " "
                    else:
                        if current_chunk.strip():
                            chunks.append(current_chunk.strip())
                        current_chunk = sent + " "
            else:
                # Try to add paragraph to current chunk
                if len(current_chunk) + len(para) + 2 <= self.chunk_size:
                    current_chunk += para + "\n\n"
                else:
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())
                    current_chunk = para + "\n\n"

        # Add remaining
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences"""
        # Simple sentence splitter for German and target languages
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _get_system_prompt(self, target_length: int, min_length: int, max_length: int) -> str:
        """Generate language-specific system prompt"""
        lang_cfg = self.LANGUAGES[self.target_language]

        if self.target_language == "pl":
            return f"""Jesteś {lang_cfg['role']}.

KRYTYCZNE WYMAGANIE - DŁUGOŚĆ TEKSTU:
- Oryginalny tekst: {target_length} {lang_cfg['length_label']}
- Twoje tłumaczenie MUSI mieć: {min_length}-{max_length} {lang_cfg['length_label']}
- Jeśli tłumaczenie jest za krótkie, rozwiń szczegóły, dodaj opisowe przymiotniki, rozbuduj narrację
- Jeśli jest za długie, skróć niepotrzebne słowa zachowując wszystkie fakty

ZACHOWAJ:
1. WSZYSTKIE fakty, daty, liczby, nazwy (bez zmyślania nowych!)
2. Spokojny, dokumentalny ton narracji
3. Płynność i naturalność polskiego języka
4. Chronologię i logikę wydarzeń

NAZWY WŁASNE I TERMINY HISTORYCZNE:
- Używaj USTALONYCH polskich terminów (NIE tłumacz dosłownie!):
  • "Fruchtbarer Halbmond" → "Żyzny Półksiężyc" (NIE "owocowy/frutkowy"!)
  • "Mesopotamien" → "Mezopotamia" (z polskim "ia")
  • "Seidenstraße" → "Jedwabny Szlak"
  • "Schwarzes Meer" → "Morze Czarne"
  • "Rotes Meer" → "Morze Czerwone"
  • "Mittelmeer" → "Morze Śródziemne"
  • "Persisches Reich" → "Imperium Perskie"
  • "Römisches Reich" → "Cesarstwo Rzymskie"
- Nazwiska osób zostaw w oryginale: "Napoleon Bonaparte" → "Napoleon Bonaparte"
- Jeśli nie znasz polskiego terminu, użyj transliteracji a nie dosłownego tłumaczenia

LICZBY I DATY - PISZ SŁOWNIE:
- Lata: "1945" → "tysiąc dziewięćset czterdzieści pięć" lub "rok tysiąc dziewięćset czterdzieści pięć"
- Liczby: "500 żołnierzy" → "pięćset żołnierzy"
- Daty: "15 maja 1945" → "piętnastego maja tysiąc dziewięćset czterdzieści pięć"
- Liczby rzymskie: "XVII wieku" → "siedemnastego wieku", "XX wieku" → "dwudziestego wieku", "II wojny" → "drugiej wojny"
- Wyjątki: Jeśli w oryginalnym tekście liczba jest cyfrą (np. w nazwie "Grupa 47"), zostaw cyfrę

TECHNIKA ROZSZERZANIA (gdy tekst za krótki):
- Dodaj opisowe przymiotniki (np. "bitwa" → "zaciętą bitwą", "król" → "wpływowy król")
- Rozwiń skróty myślowe (np. "wtedy" → "w tamtym burzliwym okresie")
- Użyj pełniejszych fraz (np. "w 1945" → "w pamiętnym roku 1945")
- Opisz kontekst bez dodawania faktów (np. "Hitler" → "niemiecki dyktator Hitler")

NIGDY NIE:
- Dodawaj faktów, których nie ma w oryginale
- Zmieniaj dat, liczb, nazwisk
- Twórz sztucznych powtórzeń"""

        elif self.target_language == "fr":
            return f"""Vous êtes {lang_cfg['role']}.

EXIGENCE CRITIQUE - LONGUEUR DU TEXTE:
- Texte original: {target_length} {lang_cfg['length_label']}
- Votre traduction DOIT avoir: {min_length}-{max_length} {lang_cfg['length_label']}
- Si la traduction est trop courte, développez les détails, ajoutez des adjectifs descriptifs, enrichissez la narration
- Si elle est trop longue, raccourcissez les mots inutiles en conservant tous les faits

CONSERVEZ:
1. TOUS les faits, dates, chiffres, noms (sans en inventer de nouveaux!)
2. Le ton calme et documentaire de la narration
3. La fluidité et le naturel de la langue française
4. La chronologie et la logique des événements

NOMS PROPRES ET TERMES HISTORIQUES:
- Utilisez les termes français ÉTABLIS (NE traduisez PAS littéralement!):
  • "Fruchtbarer Halbmond" → "Croissant fertile" (PAS "croissant fructueux/fruité"!)
  • "Mesopotamien" → "Mésopotamie"
  • "Seidenstraße" → "Route de la soie"
  • "Schwarzes Meer" → "Mer Noire"
  • "Rotes Meer" → "Mer Rouge"
  • "Mittelmeer" → "Méditerranée"
  • "Persisches Reich" → "Empire perse"
  • "Römisches Reich" → "Empire romain"
- Gardez les noms de personnes: "Napoleon Bonaparte" → "Napoléon Bonaparte"
- Si vous ne connaissez pas le terme français, utilisez la translittération et non une traduction littérale

CHIFFRES ET DATES - ÉCRIVEZ EN LETTRES:
- Années: "1945" → "mille neuf cent quarante-cinq" ou "l'année mille neuf cent quarante-cinq"
- Nombres: "500 soldats" → "cinq cents soldats"
- Dates: "15 mai 1945" → "le quinze mai mille neuf cent quarante-cinq"
- Chiffres romains: "XVIIe siècle" → "dix-septième siècle", "XXe siècle" → "vingtième siècle", "IIe guerre" → "Seconde Guerre"
- Exceptions: Si dans le texte original le nombre est un chiffre (par ex. dans "Groupe 47"), gardez le chiffre

TECHNIQUE D'EXPANSION (quand le texte est trop court):
- Ajoutez des adjectifs descriptifs (par ex. "bataille" → "bataille acharnée", "roi" → "roi influent")
- Développez les raccourcis de pensée (par ex. "alors" → "à cette période tumultueuse")
- Utilisez des phrases plus complètes (par ex. "en 1945" → "en cette année mémorable de 1945")
- Décrivez le contexte sans ajouter de faits (par ex. "Hitler" → "le dictateur allemand Hitler")

NE JAMAIS:
- Ajouter des faits qui ne sont pas dans l'original
- Changer les dates, chiffres, noms de famille
- Créer des répétitions artificielles"""

        else:  # en
            return f"""You are {lang_cfg['role']}.

CRITICAL REQUIREMENT - TEXT LENGTH:
- Original text: {target_length} {lang_cfg['length_label']}
- Your translation MUST be: {min_length}-{max_length} {lang_cfg['length_label']}
- If translation is too short, expand details, add descriptive adjectives, enrich narration
- If too long, trim unnecessary words while keeping all facts

PRESERVE:
1. ALL facts, dates, numbers, names (without inventing new ones!)
2. Calm, documentary narration tone
3. Fluidity and naturalness of English language
4. Chronology and logic of events

PROPER NOUNS AND HISTORICAL TERMS:
- Use ESTABLISHED English terms (DO NOT translate literally!):
  • "Fruchtbarer Halbmond" → "Fertile Crescent" (NOT "fruitful/fruity crescent"!)
  • "Mesopotamien" → "Mesopotamia"
  • "Seidenstraße" → "Silk Road"
  • "Schwarzes Meer" → "Black Sea"
  • "Rotes Meer" → "Red Sea"
  • "Mittelmeer" → "Mediterranean Sea"
  • "Persisches Reich" → "Persian Empire"
  • "Römisches Reich" → "Roman Empire"
- Keep person names: "Napoleon Bonaparte" → "Napoleon Bonaparte"
- If you don't know the English term, use transliteration not literal translation

NUMBERS AND DATES - SPELL OUT:
- Years: "1945" → "nineteen forty-five" or "the year nineteen forty-five"
- Numbers: "500 soldiers" → "five hundred soldiers"
- Dates: "May 15, 1945" → "the fifteenth of May, nineteen forty-five"
- Roman numerals: "XVII century" → "seventeenth century", "XX century" → "twentieth century", "WWII" → "Second World War"
- Exceptions: If in the original text the number is a digit (e.g. in "Group 47"), keep the digit

EXPANSION TECHNIQUE (when text is too short):
- Add descriptive adjectives (e.g. "battle" → "fierce battle", "king" → "influential king")
- Expand mental shortcuts (e.g. "then" → "in that turbulent period")
- Use fuller phrases (e.g. "in 1945" → "in the memorable year of 1945")
- Describe context without adding facts (e.g. "Hitler" → "German dictator Hitler")

NEVER:
- Add facts not in the original
- Change dates, numbers, surnames
- Create artificial repetitions"""

    def _translate_chunk(
        self,
        chunk: str,
        global_context: str,
        previous_ending: str,
        chunk_index: int,
        total_chunks: int
    ) -> str:
        """Translate a single chunk with context and strict length matching"""

        target_length = len(chunk)
        min_length = int(target_length * 0.85)
        max_length = int(target_length * 1.15)

        # Use language-specific system prompt
        system_prompt = self._get_system_prompt(target_length, min_length, max_length)

        # Build context with language-specific labels
        lang_cfg = self.LANGUAGES[self.target_language]
        context_parts = [f"{lang_cfg['context_label']}:\n{global_context}"]

        if previous_ending:
            context_parts.append(f"\n{lang_cfg['previous_label']}:\n{previous_ending}")

        context_parts.append(f"\n\nFragment {chunk_index + 1}/{total_chunks}.")
        context_parts.append(f"\n{lang_cfg['text_label']} ({len(chunk)} {lang_cfg['length_label']}, target: {min_length}-{max_length} {lang_cfg['length_label']}):\n{chunk}")

        user_prompt = "\n".join(context_parts)
        user_prompt += f"\n\n{lang_cfg['response_label']} {min_length}-{max_length} {lang_cfg['length_label']}, no comments):"

        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.5,  # Slightly higher for natural expansion
                    max_tokens=5000
                )

                translation = response.choices[0].message.content.strip()
                ratio = len(translation) / len(chunk)

                # If length is acceptable, return
                if min_length <= len(translation) <= max_length:
                    print(f"✓ Chunk {chunk_index+1} length: {len(translation)}/{target_length} chars (ratio: {ratio:.2f})")
                    return translation

                # If too short and we have retries left, ask GPT to expand
                if len(translation) < min_length and attempt < max_retries - 1:
                    print(f"⚠ Chunk {chunk_index+1} too short: {len(translation)}/{min_length} chars (ratio: {ratio:.2f}), expanding...")
                    translation = self._expand_translation(translation, chunk, min_length, max_length)

                    # Check again after expansion
                    ratio = len(translation) / len(chunk)
                    if min_length <= len(translation) <= max_length:
                        print(f"✓ After expansion: {len(translation)}/{target_length} chars (ratio: {ratio:.2f})")
                        return translation

                # Last attempt or within acceptable range - warn but accept
                print(f"⚠ Chunk {chunk_index+1} length ratio: {ratio:.2f} (original: {len(chunk)}, translated: {len(translation)})")
                return translation

            except Exception as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Translation failed for chunk {chunk_index+1}: {e}")
                print(f"Retry {attempt+1}/{max_retries} for chunk {chunk_index+1}: {e}")

    def _expand_translation(self, translation: str, original: str, min_length: int, max_length: int) -> str:
        """Expand translation to match target length without adding facts"""
        prompt = f"""Rozbuduj poniższe tłumaczenie, aby osiągnąć długość {min_length}-{max_length} znaków (obecnie: {len(translation)} znaków).

DOZWOLONE TECHNIKI:
- Opisowe przymiotniki (np. "król" → "potężny król")
- Pełniejsze frazy (np. "wtedy" → "w tamtym okresie")
- Kontekst bez faktów (np. "Hitler" → "niemiecki dyktator Hitler")
- Rozwinięcia skrótów myślowych

ZABRONIONE:
- Dodawanie nowych faktów, dat, nazwisk
- Zmiana treści merytorycznej
- Sztuczne powtórzenia

ORYGINALNY NIEMIECKI (dla kontekstu):
{original}

AKTUALNE TŁUMACZENIE:
{translation}

ROZSZERZONE TŁUMACZENIE ({min_length}-{max_length} znaków):"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Jesteś redaktorem rozszerzającym teksty bez dodawania faktów."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=5000
            )

            expanded = response.choices[0].message.content.strip()
            return expanded

        except Exception as e:
            print(f"Warning: Expansion failed: {e}, using original translation")
            return translation

    def _extract_ending_sentences(self, text: str, count: int = 2) -> str:
        """Extract last N sentences from text"""
        sentences = self._split_sentences(text)
        if len(sentences) <= count:
            return text

        return " ".join(sentences[-count:])

    def _validate_translation(self, text: str) -> str:
        """
        Validate translation for common errors (e.g., literal translations of historical terms)
        Returns corrected text with warnings
        """
        # Common translation errors to fix
        error_patterns = {
            "pl": {
                r'\b[Ff]rutkow(y|ego|ym|ych)\s+[Pp]ółksiężyc': 'Żyzny Półksiężyc',
                r'\b[Oo]wocow(y|ego|ym|ych)\s+[Pp]ółksiężyc': 'Żyzny Półksiężyc',
                r'\b[Pp]łodn(y|ego|ym|ych)\s+[Pp]ółksiężyc': 'Żyzny Półksiężyc',
                r'\bMesopotamia\b': 'Mezopotamia',
                r'\birański(m|ch|ego)\s+wyżyn': 'irańską wyżyn',  # Grammar fix
                r'\biranskim\s+wyżyną': 'irańską wyżyną',
            },
            "fr": {
                r'\b[Cc]roissant\s+fructueux': 'Croissant fertile',
                r'\b[Cc]roissant\s+fruité': 'Croissant fertile',
            },
            "en": {
                r'\b[Ff]ruitful\s+[Cc]rescent': 'Fertile Crescent',
                r'\b[Ff]ruity\s+[Cc]rescent': 'Fertile Crescent',
            }
        }

        patterns = error_patterns.get(self.target_language, {})
        corrected = text
        corrections_made = []

        for pattern, replacement in patterns.items():
            import re
            if re.search(pattern, corrected):
                corrected = re.sub(pattern, replacement, corrected)
                corrections_made.append(f"{pattern} → {replacement}")

        if corrections_made:
            print(f"⚠ Translation validation: Fixed {len(corrections_made)} common errors:")
            for correction in corrections_made:
                print(f"  - {correction}")

        return corrected

    def _editorial_pass(self, text: str) -> str:
        """
        Editorial pass to remove repetitions and improve flow
        WITHOUT changing facts

        Note: Skipped if text is too long (>40k chars) to avoid max_tokens limit
        """
        # Step 1: Validate and fix common translation errors
        text = self._validate_translation(text)

        # Skip editorial pass for very long texts (exceeds GPT-4o-mini 16k token limit)
        if len(text) > 40000:
            print(f"Info: Skipping editorial pass (text too long: {len(text)} chars)")
            return text

        prompt = f"""Jesteś redaktorem tekstów. Popraw poniższy tekst usuwając:
- Powtórzenia tych samych informacji
- Nienaturalne konstrukcje zdaniowe
- Zbędne słowa

WAŻNE:
- NIE zmieniaj żadnych faktów, dat, nazwisk, liczb
- NIE dodawaj nowych informacji
- Zachowaj długość tekstu (±5%)
- Popraw tylko płynność narracji

TEKST:
{text}

POPRAWIONY TEKST (bez komentarzy):"""

        try:
            # Calculate safe max_tokens (GPT-4o-mini limit: 16384)
            # Assume input uses ~len(text)/3 tokens, leave room for output
            estimated_input_tokens = len(text) // 3
            safe_max_tokens = min(16000, estimated_input_tokens + 2000)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Jesteś redaktorem podcastów historycznych."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=safe_max_tokens
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"Warning: Editorial pass failed: {e}, using original translation")
            return text

    def _ai_quality_validator(self, translated_text: str, original_german: str) -> str:
        """
        Professional AI quality check for translation
        Validates: natural language, historical accuracy, terminology consistency, audio suitability

        Args:
            translated_text: Translated text to validate
            original_german: Original German text (sample for context)

        Returns:
            Corrected translation with improved quality
        """
        # CRITICAL: Skip AI quality check for very long texts to avoid truncation and data loss
        # The prompt uses [:40000] truncation which causes partial text to be returned
        if len(translated_text) > 35000:
            print(f"ℹ️  Skipping AI quality check (text too long: {len(translated_text)} chars)")
            print(f"   Quality checks are limited to 35K chars to prevent data loss from truncation")
            return translated_text

        # For very long texts, use sample validation to avoid token limits
        original_sample = original_german[:5000] if len(original_german) > 5000 else original_german

        # Get language-specific quality check prompt
        prompt = self._get_quality_check_prompt(translated_text, original_sample)

        try:
            print(f"🔍 Running AI quality check for {self.target_language.upper()} ({len(translated_text)} chars)...")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"You are a professional quality checker for {self.LANGUAGES[self.target_language]['native_name']} podcast translations."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Low temperature for consistency
                max_tokens=16000  # Max for gpt-4o-mini
            )

            result_text = response.choices[0].message.content.strip()

            # Try to parse JSON response
            import json
            try:
                # Extract JSON from response (might have markdown code blocks)
                if "```json" in result_text:
                    json_start = result_text.find("```json") + 7
                    json_end = result_text.find("```", json_start)
                    result_text = result_text[json_start:json_end].strip()
                elif "```" in result_text:
                    json_start = result_text.find("```") + 3
                    json_end = result_text.find("```", json_start)
                    result_text = result_text[json_start:json_end].strip()

                result = json.loads(result_text)

                severity = result.get("severity", "none")
                issues = result.get("issues_found", [])
                corrected = result.get("corrected_text", translated_text)
                explanation = result.get("explanation", "")

                # Log results
                if severity != "none":
                    print(f"⚠ AI Quality Check - Severity: {severity.upper()}")
                    print(f"  Issues found ({len(issues)}):")
                    for issue in issues[:5]:  # Show first 5
                        print(f"    - {issue}")
                    if explanation:
                        print(f"  Explanation: {explanation[:200]}...")

                    # CRITICAL FIX: Check if corrected text was truncated
                    # If corrected text is significantly shorter, it means GPT only received a truncated version
                    # In that case, return the original to avoid data loss
                    if len(corrected) < len(translated_text) * 0.9:
                        print(f"⚠ WARNING: Corrected text is {len(corrected)} chars vs original {len(translated_text)} chars")
                        print(f"  This indicates truncation occurred. Keeping original text to prevent data loss.")
                        return translated_text

                    return corrected
                else:
                    print(f"✓ AI Quality Check passed - no major issues found")
                    return translated_text

            except json.JSONDecodeError:
                # If JSON parsing fails, use response as-is (might be corrected text)
                print(f"⚠ AI Quality Check: Could not parse JSON response, using GPT output directly")
                return result_text if len(result_text) > len(translated_text) * 0.8 else translated_text

        except Exception as e:
            print(f"Warning: AI quality check failed: {e}, using original translation")
            return translated_text

    def _get_quality_check_prompt(self, translated_text: str, original_sample: str) -> str:
        """Generate language-specific quality check prompt"""
        lang_cfg = self.LANGUAGES[self.target_language]
        text_length = len(translated_text)

        if self.target_language == "pl":
            return f"""Jesteś native Polish speaker i ekspertem od podcastów historycznych.

ZADANIE: Sprawdź jakość poniższego tłumaczenia i popraw błędy.

ORYGINALNY NIEMIECKI (fragment dla kontekstu):
{original_sample}

POLSKIE TŁUMACZENIE ({text_length} znaków):
{translated_text[:40000]}

SPRAWDŹ I POPRAW (4 kluczowe aspekty):

1. NATURALNOŚĆ JĘZYKA - czy brzmi jak native speaker?
   ❌ Germanizmy w składni (np. "został mianowany na stanowisko króla" zamiast "został królem")
   ❌ Sztuczne, tłumaczeniowe brzmienie
   ❌ Za formalne konstrukcje (to podcast, nie dokument urzędowy)
   ✅ Płynny, naturalny polski
   ✅ Odpowiedni ton dla podcastu audio (spokojny, dokumentalny ale nie sztywny)

2. POPRAWNOŚĆ HISTORYCZNA - czy fakty są OK?
   ❌ Błędne tytuły (np. "król Napoleon" gdy był cesarzem)
   ❌ Nieprecyzyjne określenia geograficzne
   ❌ Mylące chronologie
   ✅ Precyzyjne tytuły i określenia
   ✅ Poprawna geografia i chronologia

3. SPÓJNOŚĆ TERMINOLOGII - czy te same rzeczy mają te same nazwy?
   ❌ "Imperium Perskie" w jednym miejscu, "Cesarstwo Perskie" w innym
   ❌ Różne tłumaczenia tych samych nazw geograficznych
   ❌ Niespójne określenia władców/instytucji
   ✅ Konsekwentna terminologia przez cały tekst

4. BRZMIENIE DLA LEKTORA - czy dobrze brzmi czytane na głos?
   ❌ Zbyt długie zdania (trudne dla lektora)
   ❌ Skomplikowane konstrukcje zdaniowe
   ❌ Nieczytelne nagromadzenia cyfr/dat
   ✅ Zdania o odpowiedniej długości
   ✅ Naturalne dla mówionego języka

WAŻNE ZASADY:
- ZACHOWAJ długość tekstu (±5%)
- NIE dodawaj nowych faktów
- NIE zmieniaj dat, liczb, nazwisk
- Popraw TYLKO błędy językowe, stylistyczne i niespójności

ODPOWIEDŹ (JSON):
{{
  "severity": "none" | "minor" | "major",
  "issues_found": ["lista konkretnych problemów"],
  "corrected_text": "poprawiony tekst (cały!)",
  "explanation": "krótkie wyjaśnienie głównych poprawek"
}}"""

        elif self.target_language == "fr":
            return f"""Vous êtes un locuteur natif français et expert en podcasts historiques.

TÂCHE: Vérifier la qualité de la traduction suivante et corriger les erreurs.

ALLEMAND ORIGINAL (extrait pour contexte):
{original_sample}

TRADUCTION FRANÇAISE ({text_length} caractères):
{translated_text[:40000]}

VÉRIFIER ET CORRIGER (4 aspects clés):

1. NATUREL DE LA LANGUE - est-ce que ça sonne comme un locuteur natif?
   ❌ Germanismes dans la syntaxe
   ❌ Son artificiel de traduction
   ❌ Constructions trop formelles (c'est un podcast, pas un document officiel)
   ✅ Français fluide et naturel
   ✅ Ton approprié pour podcast audio (calme, documentaire mais pas rigide)

2. EXACTITUDE HISTORIQUE - les faits sont-ils corrects?
   ❌ Titres incorrects (ex: "roi Napoléon" quand il était empereur)
   ❌ Termes géographiques imprécis
   ❌ Chronologies confuses
   ✅ Titres et termes précis
   ✅ Géographie et chronologie correctes

3. COHÉRENCE TERMINOLOGIQUE - les mêmes choses ont-elles les mêmes noms?
   ❌ "Empire perse" à un endroit, "Perse" à un autre
   ❌ Traductions différentes des mêmes noms géographiques
   ❌ Termes incohérents pour dirigeants/institutions
   ✅ Terminologie cohérente dans tout le texte

4. QUALITÉ POUR NARRATION - est-ce que ça sonne bien lu à voix haute?
   ❌ Phrases trop longues (difficiles pour le narrateur)
   ❌ Constructions de phrases compliquées
   ❌ Accumulation illisible de chiffres/dates
   ✅ Phrases de longueur appropriée
   ✅ Naturel pour la langue parlée

RÈGLES IMPORTANTES:
- CONSERVER la longueur du texte (±5%)
- NE PAS ajouter de nouveaux faits
- NE PAS changer les dates, chiffres, noms
- Corriger UNIQUEMENT les erreurs linguistiques, stylistiques et incohérences

RÉPONSE (JSON):
{{
  "severity": "none" | "minor" | "major",
  "issues_found": ["liste des problèmes spécifiques"],
  "corrected_text": "texte corrigé (complet!)",
  "explanation": "brève explication des corrections principales"
}}"""

        else:  # en
            return f"""You are a native English speaker and expert in historical podcasts.

TASK: Check the quality of the following translation and correct errors.

ORIGINAL GERMAN (excerpt for context):
{original_sample}

ENGLISH TRANSLATION ({text_length} characters):
{translated_text[:40000]}

CHECK AND CORRECT (4 key aspects):

1. NATURAL LANGUAGE - does it sound like a native speaker?
   ❌ Germanisms in syntax
   ❌ Artificial, translation-like sound
   ❌ Too formal constructions (this is a podcast, not an official document)
   ✅ Fluid, natural English
   ✅ Appropriate tone for audio podcast (calm, documentary but not stiff)

2. HISTORICAL ACCURACY - are facts correct?
   ❌ Incorrect titles (e.g., "King Napoleon" when he was emperor)
   ❌ Imprecise geographical terms
   ❌ Confusing chronologies
   ✅ Precise titles and terms
   ✅ Correct geography and chronology

3. TERMINOLOGY CONSISTENCY - do the same things have the same names?
   ❌ "Persian Empire" in one place, "Persia" in another
   ❌ Different translations of the same geographical names
   ❌ Inconsistent terms for rulers/institutions
   ✅ Consistent terminology throughout text

4. NARRATION QUALITY - does it sound good read aloud?
   ❌ Too-long sentences (difficult for narrator)
   ❌ Complicated sentence constructions
   ❌ Unreadable accumulation of numbers/dates
   ✅ Appropriately-length sentences
   ✅ Natural for spoken language

IMPORTANT RULES:
- PRESERVE text length (±5%)
- DO NOT add new facts
- DO NOT change dates, numbers, names
- Correct ONLY linguistic, stylistic errors and inconsistencies

RESPONSE (JSON):
{{
  "severity": "none" | "minor" | "major",
  "issues_found": ["list of specific problems"],
  "corrected_text": "corrected text (complete!)",
  "explanation": "brief explanation of main corrections"
}}"""

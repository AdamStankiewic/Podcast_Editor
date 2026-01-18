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
            progress_callback(4, 4, "Editorial pass: removing repetitions...")

        full_translation = "\n\n".join(translated_chunks)
        final_text = self._editorial_pass(full_translation)

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

NAZWY WŁASNE:
- Nazwy geograficzne/historyczne tłumacz na polski: "Seidenstraße" → "Jedwabny Szlak", "Schwarzes Meer" → "Morze Czarne"
- Nazwiska osób zostaw w oryginale: "Napoleon Bonaparte" → "Napoleon Bonaparte"
- Jeśli nazwa ma ugruntowane polskie tłumaczenie, użyj go

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

NOMS PROPRES:
- Traduisez les noms géographiques/historiques en français: "Seidenstraße" → "Route de la Soie", "Schwarzes Meer" → "Mer Noire"
- Gardez les noms de personnes dans l'original: "Napoleon Bonaparte" → "Napoléon Bonaparte"
- Si le nom a une traduction française établie, utilisez-la

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

PROPER NOUNS:
- Translate geographic/historical names to English: "Seidenstraße" → "Silk Road", "Schwarzes Meer" → "Black Sea"
- Keep person names in original: "Napoleon Bonaparte" → "Napoleon Bonaparte"
- If the name has an established English translation, use it

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

    def _editorial_pass(self, text: str) -> str:
        """
        Editorial pass to remove repetitions and improve flow
        WITHOUT changing facts

        Note: Skipped if text is too long (>40k chars) to avoid max_tokens limit
        """
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

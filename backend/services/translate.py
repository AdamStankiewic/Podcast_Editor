"""
Translation service using OpenAI GPT
Implements chunking with context preservation and length matching
"""
import os
import re
from typing import List, Tuple
from openai import OpenAI


class TranslationService:
    """Handles German to Polish translation with context and length preservation"""

    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.chunk_size = 3000  # Characters per chunk
        self.overlap_sentences = 2  # Sentences to overlap for context

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
        # Simple sentence splitter for German/Polish
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

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

        system_prompt = f"""Jesteś profesjonalnym lektorem podcastów historycznych. Tłumaczysz niemieckie nagrania na polski.

KRYTYCZNE WYMAGANIE - DŁUGOŚĆ TEKSTU:
- Oryginalny tekst: {target_length} znaków
- Twoje tłumaczenie MUSI mieć: {min_length}-{max_length} znaków
- Jeśli tłumaczenie jest za krótkie, rozwiń szczegóły, dodaj opisowe przymiotniki, rozbuduj narrację
- Jeśli jest za długie, skróć niepotrzebne słowa zachowując wszystkie fakty

ZACHOWAJ:
1. WSZYSTKIE fakty, daty, liczby, nazwy (bez zmyślania nowych!)
2. Spokojny, dokumentalny ton narracji
3. Płynność i naturalność polskiego języka
4. Chronologię i logikę wydarzeń

TECHNIKA ROZSZERZANIA (gdy tekst za krótki):
- Dodaj opisowe przymiotniki (np. "bitwa" → "zaciętą bitwą", "król" → "wpływowy król")
- Rozwiń skróty myślowe (np. "wtedy" → "w tamtym burzliwym okresie")
- Użyj pełniejszych fraz (np. "w 1945" → "w pamiętnym roku 1945")
- Opisz kontekst bez dodawania faktów (np. "Hitler" → "niemiecki dyktator Hitler")

NIGDY NIE:
- Dodawaj faktów, których nie ma w oryginale
- Zmieniaj dat, liczb, nazwisk
- Twórz sztucznych powtórzeń"""

        # Build context
        context_parts = [f"KONTEKST GLOBALNY:\n{global_context}"]

        if previous_ending:
            context_parts.append(f"\nKONIEC POPRZEDNIEGO FRAGMENTU:\n{previous_ending}")

        context_parts.append(f"\n\nTo jest fragment {chunk_index + 1} z {total_chunks}.")
        context_parts.append(f"\nTEKST DO TŁUMACZENIA ({len(chunk)} znaków, cel: {min_length}-{max_length} znaków):\n{chunk}")

        user_prompt = "\n".join(context_parts)
        user_prompt += f"\n\nOdpowiedź (polskie tłumaczenie o długości {min_length}-{max_length} znaków, bez komentarzy):"

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

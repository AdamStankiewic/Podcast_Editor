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
        """Translate a single chunk with context"""

        system_prompt = """Jesteś profesjonalnym lektorem podcastów historycznych. Tłumaczysz niemieckie nagrania na polski z zachowaniem:
1. Stylu narracyjnego (spokojny, dokumentalny ton)
2. WSZYSTKICH faktów, dat, liczb, nazw (bez zmyślania!)
3. Podobnej długości tekstu (±10% znaków względem oryginału)
4. Płynności narracji

WAŻNE:
- NIE dodawaj żadnych informacji, których nie ma w oryginale
- NIE zmieniaj dat, liczb, nazwisk
- Zachowaj naturalny polski język narracyjny
- Unikaj powtórzeń i sztucznych konstrukcji"""

        # Build context
        context_parts = [f"KONTEKST GLOBALNY:\n{global_context}"]

        if previous_ending:
            context_parts.append(f"\nKONIEC POPRZEDNIEGO FRAGMENTU:\n{previous_ending}")

        context_parts.append(f"\n\nTo jest fragment {chunk_index + 1} z {total_chunks}.")
        context_parts.append(f"\nTEKST DO TŁUMACZENIA ({len(chunk)} znaków):\n{chunk}")

        user_prompt = "\n".join(context_parts)
        user_prompt += "\n\nOdpowiedź (TYLKO polskie tłumaczenie, bez komentarzy):"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4,  # Slightly creative but faithful
                max_tokens=4000
            )

            translation = response.choices[0].message.content.strip()

            # Check length ratio (warn if too different)
            ratio = len(translation) / len(chunk)
            if ratio < 0.7 or ratio > 1.4:
                print(f"Warning: Chunk {chunk_index+1} length ratio: {ratio:.2f} (original: {len(chunk)}, translated: {len(translation)})")

            return translation

        except Exception as e:
            raise RuntimeError(f"Translation failed for chunk {chunk_index+1}: {e}")

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
        """
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Jesteś redaktorem podcastów historycznych."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=len(text) + 1000
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"Warning: Editorial pass failed: {e}, using original translation")
            return text

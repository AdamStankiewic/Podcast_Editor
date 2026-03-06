"""
Clip Selection Service for parliamentary session highlights.

Takes a timestamped transcript and uses AI to select the most interesting
segments. Ensures clean cut points at sentence/clause boundaries.

Scoring criteria for parliamentary content:
  - Debate intensity (arguments, rebuttals, interruptions)
  - Policy significance (laws, votes, key proposals)
  - Named politicians / government members speaking
  - Emotional moments (applause, protests, dramatic exits)
  - Question-and-answer exchanges
  - Short, punchy statements vs. long procedural read-outs
"""
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# Sentence-ending punctuation used to find clean cut points
_SENTENCE_END_RE = re.compile(r'[.!?…]\s*$')
# Clause boundaries (softer cut points)
_CLAUSE_END_RE = re.compile(r'[,;:]\s*$')


@dataclass
class ClipSegment:
    """A selected clip segment with scoring metadata"""
    start: float          # Start time in seconds
    end: float            # End time in seconds
    score: int            # Interest score 1-10
    reason: str           # Why this segment was selected
    text: str             # Transcript text for this clip
    cut_quality_start: str = "ok"   # "ok" | "mid_sentence" | "mid_clause"
    cut_quality_end: str = "ok"     # "ok" | "mid_sentence" | "mid_clause"

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return asdict(self)


class ClipSelector:
    """
    AI-powered clip selector for long transcripts.

    Usage:
        selector = ClipSelector(api_key="sk-...")
        clips = selector.select_clips(
            timed_segments,           # from parse_vtt_with_timestamps()
            target_total_minutes=15,  # total highlight duration
            min_clip_seconds=30,      # minimum clip length
            max_clip_seconds=180,     # maximum clip length
        )
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_clips(
        self,
        timed_segments: list[dict],
        target_total_minutes: float = 15.0,
        min_clip_seconds: float = 30.0,
        max_clip_seconds: float = 180.0,
        chunk_window_seconds: float = 60.0,
    ) -> list[ClipSegment]:
        """
        Select the most interesting clips from a timed transcript.

        Args:
            timed_segments: List of {"start", "end", "text"} from VTT parser
            target_total_minutes: Desired total duration of all clips combined
            min_clip_seconds: Don't select clips shorter than this
            max_clip_seconds: Cap single clip at this duration
            chunk_window_seconds: Group VTT segments into this window for scoring

        Returns:
            Sorted list of ClipSegment (by start time)
        """
        if not timed_segments:
            return []

        # 1. Group VTT micro-segments into scoring chunks
        chunks = self._build_chunks(timed_segments, chunk_window_seconds)

        # 2. Score chunks with AI (or heuristics as fallback)
        scored = self._score_chunks(chunks)

        # 3. Select top chunks until target duration reached
        target_seconds = target_total_minutes * 60
        selected = self._select_top_chunks(scored, target_seconds, min_clip_seconds)

        # 4. Merge adjacent/overlapping selected chunks
        merged = self._merge_adjacent(selected, gap_tolerance=5.0)

        # 5. Trim to max_clip_seconds, snapping to sentence boundaries
        trimmed = []
        for clip in merged:
            if clip.duration > max_clip_seconds:
                clip = self._trim_clip(clip, max_clip_seconds, timed_segments)
            trimmed.append(clip)

        # 6. Assess cut quality
        final = [self._assess_cut_quality(clip) for clip in trimmed]

        return sorted(final, key=lambda c: c.start)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_chunks(
        self,
        segments: list[dict],
        window_seconds: float
    ) -> list[dict]:
        """
        Group micro VTT segments into fixed-window chunks for AI scoring.
        Returns list of {"start", "end", "text", "segment_count"}
        """
        if not segments:
            return []

        chunks = []
        chunk_start = segments[0]["start"]
        chunk_texts = []
        chunk_end = chunk_start

        for seg in segments:
            seg_start = seg["start"]
            seg_end = seg["end"]
            seg_text = seg["text"].strip()

            # Start a new chunk if we've exceeded the window
            if seg_start - chunk_start >= window_seconds and chunk_texts:
                chunks.append({
                    "start": chunk_start,
                    "end": chunk_end,
                    "text": " ".join(chunk_texts),
                    "segment_count": len(chunk_texts),
                })
                chunk_start = seg_start
                chunk_texts = []

            chunk_texts.append(seg_text)
            chunk_end = seg_end

        # Flush last chunk
        if chunk_texts:
            chunks.append({
                "start": chunk_start,
                "end": chunk_end,
                "text": " ".join(chunk_texts),
                "segment_count": len(chunk_texts),
            })

        return chunks

    def _score_chunks(self, chunks: list[dict]) -> list[dict]:
        """
        Score each chunk for interest level.
        Tries OpenAI first; falls back to heuristic scoring.
        """
        if self.api_key:
            try:
                return self._score_with_openai(chunks)
            except Exception as e:
                print(f"[ClipSelector] OpenAI scoring failed ({e}), using heuristic fallback")

        return self._score_heuristic(chunks)

    def _score_with_openai(self, chunks: list[dict]) -> list[dict]:
        """Use OpenAI to score chunks in batches of 20."""
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package not installed")

        client = OpenAI(api_key=self.api_key)
        batch_size = 20
        result_chunks = list(chunks)  # copy

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            numbered = "\n\n".join(
                f"[{j}] ({c['start']:.0f}s–{c['end']:.0f}s):\n{c['text']}"
                for j, c in enumerate(batch)
            )

            prompt = f"""You are analyzing a parliamentary session transcript to find highlights.

Rate each numbered segment on a scale of 1-10 for how interesting/noteworthy it would be
as a highlight clip. Consider:
- 9-10: Dramatic debates, key votes, important policy announcements, emotional moments
- 7-8: Substantive political discussion, notable questions or answers
- 5-6: Moderate interest - informational, procedural with some substance
- 3-4: Routine procedural items, administrative announcements
- 1-2: Pure formalities, roll calls, reading of names, technical announcements

For each segment, output ONLY a JSON array (no other text):
[{{"id": 0, "score": 8, "reason": "brief reason"}}, ...]

Segments to score:
{numbered}"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000,
            )

            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)

            scored_batch = json.loads(raw)
            for item in scored_batch:
                idx = i + item["id"]
                if idx < len(result_chunks):
                    result_chunks[idx]["score"] = item["score"]
                    result_chunks[idx]["reason"] = item.get("reason", "")

        # Fill any un-scored chunks
        for c in result_chunks:
            if "score" not in c:
                c["score"] = 5
                c["reason"] = "not scored"

        return result_chunks

    def _score_heuristic(self, chunks: list[dict]) -> list[dict]:
        """
        Heuristic scoring without AI.
        Based on: text length, question marks, exclamations, named entities,
        keywords associated with debate intensity.
        """
        HIGH_KEYWORDS = {
            # Polish parliamentary keywords
            "głosowanie", "głosujemy", "sprzeciw", "protest", "wniosek", "poprawka",
            "premier", "minister", "marszałek", "poseł", "senator",
            "ustawa", "rezolucja", "uchwała", "debata", "interpelacja",
            "oklaski", "skandal", "hańba", "wstyd", "kłamstwo",
            # German parliamentary keywords
            "abstimmung", "antrag", "bundesminister", "kanzler", "debatte",
            "skandal", "protest", "einspruch", "gesetz", "reform",
            # Generic
            "vote", "motion", "amendment", "minister", "prime minister",
            "scandal", "protest", "applause", "resign", "emergency",
        }

        result = []
        for chunk in chunks:
            text = chunk["text"].lower()
            score = 5  # Base score

            # Question marks suggest Q&A or challenges
            q_count = text.count("?")
            score += min(q_count, 2)

            # Exclamations suggest emotion/intensity
            e_count = text.count("!")
            score += min(e_count, 2)

            # Keyword matches
            kw_hits = sum(1 for kw in HIGH_KEYWORDS if kw in text)
            score += min(kw_hits, 3)

            # Very short chunks are usually procedural
            if chunk["segment_count"] < 3:
                score -= 2

            # Longer, denser chunks tend to be more substantive
            words = len(text.split())
            if words > 80:
                score += 1

            score = max(1, min(10, score))
            reason_parts = []
            if q_count:
                reason_parts.append(f"{q_count} questions")
            if e_count:
                reason_parts.append(f"{e_count} exclamations")
            if kw_hits:
                reason_parts.append(f"{kw_hits} key terms")

            result.append({
                **chunk,
                "score": score,
                "reason": ", ".join(reason_parts) if reason_parts else "heuristic score",
            })

        return result

    def _select_top_chunks(
        self,
        scored_chunks: list[dict],
        target_seconds: float,
        min_clip_seconds: float,
    ) -> list[dict]:
        """
        Greedily select highest-scoring chunks until target duration is met.
        Skips chunks shorter than min_clip_seconds.
        """
        eligible = [
            c for c in scored_chunks
            if (c["end"] - c["start"]) >= min_clip_seconds
        ]
        # Sort by score descending, then by position (earlier is better as tiebreaker)
        eligible.sort(key=lambda c: (-c["score"], c["start"]))

        selected = []
        total = 0.0
        for chunk in eligible:
            dur = chunk["end"] - chunk["start"]
            if total + dur > target_seconds * 1.3:  # allow 30% overshoot
                break
            selected.append(chunk)
            total += dur

        return selected

    def _merge_adjacent(self, chunks: list[dict], gap_tolerance: float = 5.0) -> list[ClipSegment]:
        """
        Merge chunks that are adjacent or overlapping into ClipSegments.
        gap_tolerance: seconds between end of one and start of next to merge.
        """
        if not chunks:
            return []

        # Sort by start time
        sorted_chunks = sorted(chunks, key=lambda c: c["start"])
        merged = []
        current = dict(sorted_chunks[0])

        for chunk in sorted_chunks[1:]:
            # Merge if overlapping or within gap tolerance
            if chunk["start"] <= current["end"] + gap_tolerance:
                current["end"] = max(current["end"], chunk["end"])
                current["text"] = current["text"] + " " + chunk["text"]
                # Keep highest score, append reason
                if chunk["score"] > current["score"]:
                    current["score"] = chunk["score"]
                    current["reason"] = chunk["reason"]
            else:
                merged.append(ClipSegment(
                    start=current["start"],
                    end=current["end"],
                    score=current["score"],
                    reason=current["reason"],
                    text=current["text"].strip(),
                ))
                current = dict(chunk)

        merged.append(ClipSegment(
            start=current["start"],
            end=current["end"],
            score=current["score"],
            reason=current["reason"],
            text=current["text"].strip(),
        ))

        return merged

    def _trim_clip(
        self,
        clip: ClipSegment,
        max_seconds: float,
        all_segments: list[dict],
    ) -> ClipSegment:
        """
        Trim a clip that exceeds max_seconds.
        Tries to find a sentence boundary near the max_seconds mark.
        """
        target_end = clip.start + max_seconds

        # Find segments within clip
        clip_segs = [
            s for s in all_segments
            if s["start"] >= clip.start and s["end"] <= clip.end + 1
        ]

        # Find best sentence boundary near target_end (within 15s window)
        best_end = target_end
        best_is_sentence = False

        for seg in clip_segs:
            if seg["end"] > target_end + 15:
                break
            if seg["end"] > target_end - 15:
                text = seg["text"].strip()
                if _SENTENCE_END_RE.search(text):
                    if not best_is_sentence or abs(seg["end"] - target_end) < abs(best_end - target_end):
                        best_end = seg["end"]
                        best_is_sentence = True
                elif not best_is_sentence and abs(seg["end"] - target_end) < abs(best_end - target_end):
                    best_end = seg["end"]

        # Rebuild text for trimmed clip
        trimmed_text = " ".join(
            s["text"] for s in clip_segs if s["start"] < best_end
        ).strip()

        return ClipSegment(
            start=clip.start,
            end=best_end,
            score=clip.score,
            reason=clip.reason,
            text=trimmed_text or clip.text,
        )

    def _assess_cut_quality(self, clip: ClipSegment) -> ClipSegment:
        """
        Assess whether start/end cut points are at clean boundaries.
        Updates cut_quality_start and cut_quality_end fields.
        """
        # Check end quality based on last sentence in text
        text = clip.text.strip()
        if _SENTENCE_END_RE.search(text):
            clip.cut_quality_end = "ok"
        elif _CLAUSE_END_RE.search(text):
            clip.cut_quality_end = "mid_clause"
        else:
            clip.cut_quality_end = "mid_sentence"

        # Start quality: heuristic - first word capitalised suggests sentence start
        first_char = text[0] if text else ""
        if first_char.isupper():
            clip.cut_quality_start = "ok"
        else:
            clip.cut_quality_start = "mid_sentence"

        return clip


def load_timed_transcript(job_dir: Path) -> list[dict]:
    """
    Load transcript_de_timed.json from a job directory.
    Returns empty list if not found.
    """
    timed_path = job_dir / "transcript_de_timed.json"
    if not timed_path.exists():
        return []
    with timed_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_selected_clips(clips: list[ClipSegment], job_dir: Path):
    """Save selected clips to clips_selected.json in job directory."""
    out_path = job_dir / "clips_selected.json"
    data = [c.to_dict() for c in clips]
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def load_selected_clips(job_dir: Path) -> list[ClipSegment]:
    """Load clips_selected.json from job directory."""
    path = job_dir / "clips_selected.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return [ClipSegment(**item) for item in data]

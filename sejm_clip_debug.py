#!/usr/bin/env python3
"""
SEJM Clip Selection Debugger
==============================
Narzędzie diagnostyczne do analizy jakości selekcji klipów z pipeline Sejm.

Użycie:
    python sejm_clip_debug.py <ścieżka_do_folderu_sesji>

Przykład:
    python sejm_clip_debug.py "temp/20260216_185905_xp95_sejm_51_2026-02-13"

Wymagane pliki w folderze sesji:
    - scored_segments.json
    - selected_clips.json  (opcjonalnie)
    - shorts_candidates.json (opcjonalnie)
"""

import json
import sys
import os
from pathlib import Path
from collections import defaultdict


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt_time(seconds: float) -> str:
    if seconds is None:
        return "??:??"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_dur(seconds: float) -> str:
    if seconds is None:
        return "?s"
    return f"{int(seconds)}s"


def analyze_scored_segments(segments: list) -> None:
    print("\n" + "=" * 70)
    print("📊 ANALIZA SCORED SEGMENTS")
    print("=" * 70)

    if not segments:
        print("  ⚠️  Brak segmentów do analizy")
        return

    # Score distribution
    scores = [s.get("score", s.get("composite_score", 0)) for s in segments]
    ai_scores = [s.get("ai_semantic_score", 0) for s in segments]

    print(f"\n📈 Rozkład score'ów ({len(segments)} segmentów):")
    buckets = [0] * 10
    for sc in scores:
        idx = min(int(sc * 10), 9)
        buckets[idx] += 1
    for i, count in enumerate(buckets):
        bar = "█" * count
        print(f"  {i/10:.1f}-{(i+1)/10:.1f}: {bar} ({count})")

    print(f"\n  Średni score: {sum(scores)/len(scores):.3f}")
    print(f"  Max score:    {max(scores):.3f}")
    print(f"  Min score:    {min(scores):.3f}")
    print(f"  >0.7:  {sum(1 for s in scores if s > 0.7)} segmentów")
    print(f"  >0.5:  {sum(1 for s in scores if s > 0.5)} segmentów")
    print(f"  <0.25: {sum(1 for s in scores if s < 0.25)} segmentów")

    # Topic distribution
    print("\n📋 Rozkład tematów (topic diversity):")
    topic_segments = defaultdict(list)
    for seg in segments:
        topic = seg.get("topic", seg.get("agenda_point", "Unknown"))
        topic_segments[topic].append(seg)

    for topic, segs in sorted(topic_segments.items(), key=lambda x: -len(x[1])):
        seg_scores = [s.get("score", s.get("composite_score", 0)) for s in segs]
        best = max(seg_scores) if seg_scores else 0
        avg = sum(seg_scores) / len(seg_scores) if seg_scores else 0
        print(f"  [{topic[:40]:40s}] {len(segs):3d} segm | best={best:.3f} avg={avg:.3f}")

    # Top 20 segments by score
    print("\n🏆 TOP 20 segmentów wg score:")
    top_segs = sorted(segments, key=lambda s: s.get("score", s.get("composite_score", 0)), reverse=True)[:20]
    for i, seg in enumerate(top_segs, 1):
        sc = seg.get("score", seg.get("composite_score", 0))
        ai_sc = seg.get("ai_semantic_score", 0)
        seg_id = seg.get("id", seg.get("segment_id", "?"))
        speaker = seg.get("speaker", seg.get("mowca", "?"))
        start = seg.get("start", seg.get("start_time", 0))
        end = seg.get("end", seg.get("end_time", 0))
        duration = end - start if end and start else seg.get("duration", 0)
        topic = seg.get("topic", seg.get("agenda_point", ""))[:30]
        text_preview = seg.get("text", seg.get("stenogram", ""))[:80].replace("\n", " ")

        print(f"\n  #{i:2d} [{seg_id}] score={sc:.3f} (ai={ai_sc:.3f})")
        print(f"       {speaker} | {fmt_time(start)}-{fmt_time(end)} ({fmt_dur(duration)}) | {topic}")
        print(f"       \"{text_preview}...\"")

    # Annotations analysis (what makes a clip viral)
    print("\n🔥 Analiza adnotacji (co wpływa na wybór):")
    annotation_counts = defaultdict(int)
    for seg in segments:
        for ann in seg.get("annotations", []):
            annotation_counts[ann] += 1
        for reason in seg.get("viral_reasons", seg.get("scoring_reasons", [])):
            if "annotation:" in str(reason):
                annotation_counts[str(reason).replace("annotation:", "")] += 1

    if annotation_counts:
        for ann, cnt in sorted(annotation_counts.items(), key=lambda x: -x[1])[:15]:
            print(f"  {cnt:3d}x  {ann}")

    # Segments with high annotations but low scores (missed opportunities)
    print("\n⚠️  Segmenty z adnotacjami ale niskim score (<0.4) - POMINIĘTE OKAZJE:")
    missed = []
    for seg in segments:
        sc = seg.get("score", seg.get("composite_score", 0))
        annotations = seg.get("annotations", [])
        if sc < 0.4 and len(annotations) >= 2:
            missed.append(seg)

    missed_sorted = sorted(missed, key=lambda s: len(s.get("annotations", [])), reverse=True)[:10]
    for seg in missed_sorted:
        sc = seg.get("score", seg.get("composite_score", 0))
        seg_id = seg.get("id", seg.get("segment_id", "?"))
        speaker = seg.get("speaker", seg.get("mowca", "?"))
        annotations = seg.get("annotations", [])
        text_preview = seg.get("text", seg.get("stenogram", ""))[:60].replace("\n", " ")
        print(f"  [{seg_id}] score={sc:.3f} | {speaker} | {len(annotations)} adnotacji: {annotations[:3]}")
        print(f"         \"{text_preview}...\"")


def analyze_selected_clips(clips: list, scored_segments: list | None) -> None:
    print("\n" + "=" * 70)
    print("✂️  ANALIZA WYBRANYCH KLIPÓW (selected_clips.json)")
    print("=" * 70)

    if not clips:
        print("  ⚠️  Brak klipów do analizy")
        return

    print(f"\n📊 Łącznie: {len(clips)} klipów")

    # Duration analysis
    durations = []
    for clip in clips:
        start = clip.get("start", 0)
        end = clip.get("end", 0)
        dur = end - start if end and start else clip.get("duration", 0)
        durations.append(dur)

    if durations:
        total = sum(durations)
        avg = total / len(durations)
        print(f"  Łączny czas: {fmt_time(total)} ({total/60:.1f} min)")
        print(f"  Avg czas klipu: {avg:.0f}s")
        print(f"  Najkrótszy: {min(durations):.0f}s")
        print(f"  Najdłuższy: {max(durations):.0f}s")
        print(f"  <20s: {sum(1 for d in durations if d < 20)} klipów (za krótkie - bez kontekstu!)")
        print(f"  <10s: {sum(1 for d in durations if d < 10)} klipów (prawdopodobnie złe cięcia)")

    # Gaps between clips (skipped content)
    print("\n⏩ Luki między klipami (pominięty materiał):")
    sorted_clips = sorted(clips, key=lambda c: c.get("start", 0))
    large_gaps = []
    for i in range(len(sorted_clips) - 1):
        cur_end = sorted_clips[i].get("end", 0)
        next_start = sorted_clips[i + 1].get("start", 0)
        gap = next_start - cur_end
        if gap > 300:  # >5 min gap
            large_gaps.append((cur_end, next_start, gap))

    if large_gaps:
        print(f"  Znaleziono {len(large_gaps)} dużych luk (>5 min):")
        for start, end, gap in large_gaps[:10]:
            print(f"    {fmt_time(start)} → {fmt_time(end)} = {gap/60:.0f} min POMINIĘTE")
    else:
        print("  Brak dużych luk - dobra pokrywalność materiału")

    # Per-clip listing
    print("\n📋 Lista wybranych klipów:")
    for i, clip in enumerate(sorted_clips, 1):
        start = clip.get("start", 0)
        end = clip.get("end", 0)
        dur = end - start if end and start else clip.get("duration", 0)
        score = clip.get("score", clip.get("composite_score", 0))
        speaker = clip.get("speaker", clip.get("mowca", "?"))
        seg_id = clip.get("id", clip.get("segment_id", "?"))
        text_preview = clip.get("text", clip.get("stenogram", ""))[:70].replace("\n", " ")
        editorial = clip.get("editorial_action", "")
        annotations = clip.get("annotations", [])

        warning = ""
        if dur < 15:
            warning = " ⚠️ ZA KRÓTKI"
        elif dur < 25:
            warning = " ⚠️ krótki"

        print(f"\n  [{i:2d}] {seg_id} | {fmt_time(start)}-{fmt_time(end)} ({dur:.0f}s){warning}")
        print(f"       score={score:.3f} | {speaker} | editorial={editorial}")
        if annotations:
            print(f"       adnotacje: {annotations[:4]}")
        if text_preview:
            print(f"       \"{text_preview}...\"")


def analyze_editorial_quality(clips: list) -> None:
    """Sprawdza czy klipy kończą się i zaczynają w sensownych miejscach."""
    print("\n" + "=" * 70)
    print("🔍 ANALIZA JAKOŚCI CIĘĆ (Stage 6.6 Editorial Pass)")
    print("=" * 70)

    editorial_stats = defaultdict(int)
    split_clips = []
    trimmed_clips = []

    for clip in clips:
        action = clip.get("editorial_action", "")
        editorial_stats[action] += 1
        if action == "split":
            split_clips.append(clip)
        elif action == "trim":
            trimmed_clips.append(clip)

    print(f"\n📊 Statystyki editorial pass:")
    for action, count in sorted(editorial_stats.items(), key=lambda x: -x[1]):
        print(f"  {action or 'brak'}: {count} klipów")

    # Check for clips that end abruptly (no sentence end)
    print("\n⚠️  Klipy które mogą kończyć się w połowie zdania:")
    for clip in clips:
        text = clip.get("text", clip.get("stenogram", ""))
        if text and not text.rstrip().endswith((".", "?", "!", "…", '"')):
            seg_id = clip.get("id", "?")
            speaker = clip.get("speaker", "?")
            last_words = text.strip()[-100:]
            print(f"  [{seg_id}] {speaker}: ...{last_words}")

    # Check for clips that start with lowercase (mid-sentence cut)
    print("\n⚠️  Klipy które mogą zaczynać się w połowie zdania:")
    for clip in clips:
        text = clip.get("text", clip.get("stenogram", "")).strip()
        if text and text[0].islower() and not text.startswith("("):
            seg_id = clip.get("id", "?")
            speaker = clip.get("speaker", "?")
            first_words = text[:100]
            print(f"  [{seg_id}] {speaker}: {first_words}...")


def generate_recommendations(scored_segments: list, selected_clips: list) -> None:
    print("\n" + "=" * 70)
    print("💡 REKOMENDACJE DO POPRAWY")
    print("=" * 70)

    recommendations = []

    if scored_segments:
        scores = [s.get("score", s.get("composite_score", 0)) for s in scored_segments]
        avg_score = sum(scores) / len(scores) if scores else 0

        if avg_score < 0.45:
            recommendations.append({
                "priorytet": "WYSOKI",
                "problem": f"Średni score segmentów jest niski ({avg_score:.3f})",
                "rozwiązanie": "Sprawdź prompt GPT w Stage 5 - może zbyt surowe kryteria dla treści sejmowych. "
                               "Sejmowe treści są formalniejsze - podwyżaj bazowe score dla politycznych debat.",
            })

        # Check topic diversity issue
        topics = set()
        for seg in scored_segments:
            topic = seg.get("topic", seg.get("agenda_point", ""))
            if "Po przerwie" in topic:
                topics.add("PRZERWA_CZASOWA")
        if "PRZERWA_CZASOWA" in topics:
            recommendations.append({
                "priorytet": "KRYTYCZNY",
                "problem": "Topic diversity używa kategorii czasowych 'Po przerwie (X min)' zamiast tematycznych",
                "rozwiązanie": "Zmień kategoryzację tematów - użyj pkt obrad z SEJM API (np. 'Pkt 4. Pierwsze czytanie...') "
                               "zamiast podziału wg przerw. 48 segmentów w jednej kategorii to zmarnowany potencjał.",
            })

    if selected_clips:
        durations = []
        for clip in selected_clips:
            start = clip.get("start", 0)
            end = clip.get("end", 0)
            dur = end - start if end and start else clip.get("duration", 0)
            durations.append(dur)

        short_clips = sum(1 for d in durations if d < 20)
        if short_clips > len(durations) * 0.3:
            recommendations.append({
                "priorytet": "WYSOKI",
                "problem": f"{short_clips}/{len(durations)} klipów jest krótszych niż 20s",
                "rozwiązanie": "Stage 6.6 GPT Editorial Pass jest zbyt agresywny w cięciu. "
                               "Dodaj minimalną długość klipu po splicie (min 25s) i ogranicz liczbę splitów na klip.",
            })

        editorial_splits = sum(1 for c in selected_clips if c.get("editorial_action") == "split")
        editorial_keep = sum(1 for c in selected_clips if c.get("editorial_action") == "keep_full")
        if editorial_keep == 0 and editorial_splits > 5:
            recommendations.append({
                "priorytet": "WYSOKI",
                "problem": "Stage 6.6: keep_full=0, wszystkie klipy są cięte/trimowane",
                "rozwiązanie": "GPT w Stage 6.6 powinien częściej wybierać 'keep_full'. "
                               "Sprawdź prompt - może jest zbyt zachęcający do cięcia. "
                               "Dodaj instrukcję: 'Jeśli cały klip jest interesujący, wybierz keep_full'.",
            })

    recommendations.append({
        "priorytet": "ŚREDNI",
        "problem": "Trudno debugować bez porównania transkrypcji z wybranymi klipami",
        "rozwiązanie": "Przygotuj plik 'debug_report.txt' z: tekstem wszystkich segmentów, "
                       "ich score'ami, adnotacjami. Potem ręcznie wskaż które segmenty uważasz za ciekawe.",
    })

    recommendations.append({
        "priorytet": "INFORMACJA",
        "problem": "Jak przekazać feedback na temat złych klipów",
        "rozwiązanie": "Przygotuj: (1) scored_segments.json, (2) selected_clips.json z sesji, "
                       "(3) listę numerów klipów które uważasz za złe + które były lepsze. "
                       "Możesz też nagrać krótki opis co konkretnie jest nie tak z danym klipem.",
    })

    for i, rec in enumerate(recommendations, 1):
        print(f"\n{'🔴' if rec['priorytet'] == 'KRYTYCZNY' else '🟡' if rec['priorytet'] == 'WYSOKI' else '🔵'} [{rec['priorytet']}] #{i}")
        print(f"  Problem: {rec['problem']}")
        print(f"  Rozwiązanie: {rec['rozwiązanie']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nBrak argumentu - szukam najnowszej sesji w ./temp/ ...")
        temp_dir = Path("temp")
        if not temp_dir.exists():
            print("  ❌ Folder 'temp' nie istnieje")
            sys.exit(1)

        sessions = sorted([d for d in temp_dir.iterdir() if d.is_dir()], reverse=True)
        if not sessions:
            print("  ❌ Brak sesji w folderze temp/")
            sys.exit(1)

        session_dir = sessions[0]
        print(f"  ✓ Znaleziono najnowszą sesję: {session_dir.name}")
    else:
        session_dir = Path(sys.argv[1])
        if not session_dir.exists():
            print(f"❌ Folder nie istnieje: {session_dir}")
            sys.exit(1)

    print(f"\n🔍 SEJM CLIP SELECTION DEBUGGER")
    print(f"📁 Sesja: {session_dir}")

    # Load data
    scored_segments = load_json(session_dir / "scored_segments.json")
    selected_clips = load_json(session_dir / "selected_clips.json")
    shorts_candidates = load_json(session_dir / "shorts_candidates.json")

    print(f"\n📂 Załadowane pliki:")
    print(f"  scored_segments.json: {'✓ ' + str(len(scored_segments)) + ' segmentów' if scored_segments else '❌ brak'}")
    print(f"  selected_clips.json:  {'✓ ' + str(len(selected_clips)) + ' klipów' if selected_clips else '❌ brak'}")
    print(f"  shorts_candidates.json: {'✓ ' + str(len(shorts_candidates)) + ' shortów' if shorts_candidates else '❌ brak'}")

    if scored_segments:
        # Handle both list and dict formats
        if isinstance(scored_segments, dict):
            segs_list = list(scored_segments.values())
        else:
            segs_list = scored_segments
        analyze_scored_segments(segs_list)
    else:
        print("\n⚠️  scored_segments.json nie znaleziony - uruchom pipeline i sprawdź czy plik jest zapisywany")

    if selected_clips:
        if isinstance(selected_clips, dict):
            clips_list = list(selected_clips.values())
        else:
            clips_list = selected_clips
        analyze_selected_clips(clips_list, scored_segments)
        analyze_editorial_quality(clips_list)
    else:
        print("\n⚠️  selected_clips.json nie znaleziony")

    # Generate recommendations based on available data
    generate_recommendations(
        segs_list if scored_segments else [],
        clips_list if selected_clips else [],
    )

    # Output summary for sharing
    print("\n" + "=" * 70)
    print("📤 CO PRZEKAZAĆ DO DALSZEJ DIAGNOZY:")
    print("=" * 70)
    print("""
  1. Pliki JSON z sesji (z folderu temp/<session_id>/):
     - scored_segments.json
     - selected_clips.json
     - shorts_candidates.json

  2. Konkretne przykłady złych klipów:
     - Numer klipu (clip_001, clip_002 itd.)
     - Co jest w nim złego (zły początek, zły koniec, nudny temat)
     - Czy wiesz który lepszy klip powinien być zamiast niego?

  3. Przykłady dobrych momentów które NIE trafiły do filmiku:
     - Przybliżony czas w sesji sejmowej (np. "około 14:30")
     - Temat/mówca

  Z tymi informacjami można precyzyjnie poprawić scoring i selekcję.
""")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
sejm_clip_debug.py – Debug and improve clip selection for parliamentary sessions.

Usage:
    python sejm_clip_debug.py <job_dir> [options]

Examples:
    python sejm_clip_debug.py temp/20260216_185905_xp95_sejm_51_2026-02-13
    python sejm_clip_debug.py temp/20260216_185905_xp95_sejm_51_2026-02-13 --run-selection
    python sejm_clip_debug.py temp/20260216_185905_xp95_sejm_51_2026-02-13 --run-selection --target 20
    python sejm_clip_debug.py temp/20260216_185905_xp95_sejm_51_2026-02-13 --show-transcript
    python sejm_clip_debug.py temp/20260216_185905_xp95_sejm_51_2026-02-13 --show-all-chunks

What this tool does:
  1. Reads job_state.json and pipeline.log to show processing history
  2. Reads transcript_de_timed.json (timestamped segments)
  3. Reads clips_selected.json (if clip selection was already run)
  4. Optionally runs clip selection and shows which moments would be chosen
  5. Reports cut quality: flags mid-sentence cuts, shows context around cuts
  6. Shows a visual timeline of the session with selected clips highlighted
"""
import argparse
import json
import os
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Terminal colours (works on Windows ≥10 and all POSIX terminals)
# ─────────────────────────────────────────────────────────────────────────────
try:
    import colorama
    colorama.init()
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False

RESET  = "\033[0m"   if _HAS_COLOR else ""
BOLD   = "\033[1m"   if _HAS_COLOR else ""
GREEN  = "\033[32m"  if _HAS_COLOR else ""
YELLOW = "\033[33m"  if _HAS_COLOR else ""
RED    = "\033[31m"  if _HAS_COLOR else ""
CYAN   = "\033[36m"  if _HAS_COLOR else ""
DIM    = "\033[2m"   if _HAS_COLOR else ""


def fmt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def fmt_duration(seconds: float) -> str:
    """Format duration with fractional seconds, e.g. '1m 23s'."""
    s = int(seconds)
    m, sec = divmod(s, 60)
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


# ─────────────────────────────────────────────────────────────────────────────
# Section headers
# ─────────────────────────────────────────────────────────────────────────────
def section(title: str):
    width = 72
    print()
    print(BOLD + CYAN + "─" * width + RESET)
    print(BOLD + CYAN + f"  {title}" + RESET)
    print(BOLD + CYAN + "─" * width + RESET)


def ok(msg):  print(f"  {GREEN}✓{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET} {msg}")
def err(msg):  print(f"  {RED}✗{RESET} {msg}")
def info(msg): print(f"  {DIM}·{RESET} {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Load helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_json(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Main debug logic
# ─────────────────────────────────────────────────────────────────────────────
def debug_job(job_dir: Path, args):
    if not job_dir.exists():
        print(f"{RED}ERROR: Job directory not found: {job_dir}{RESET}")
        sys.exit(1)

    # ── 1. Job state ──────────────────────────────────────────────────────────
    section("JOB OVERVIEW")
    state = load_json(job_dir / "job_state.json")
    if state:
        ok(f"Job ID:     {state.get('id', 'unknown')}")
        ok(f"Status:     {state.get('status', '?')}")
        ok(f"URL:        {state.get('url', '?')}")
        title = state.get("video_title") or state.get("title")
        if title:
            ok(f"Title:      {title}")
        dur = state.get("video_duration")
        if dur:
            ok(f"Duration:   {fmt_time(dur)} ({fmt_duration(dur)})")
        languages = state.get("languages", [])
        if languages:
            ok(f"Languages:  {', '.join(str(l).upper() for l in languages)}")
        err_msg = state.get("error_message")
        if err_msg:
            err(f"Error:      {err_msg}")
    else:
        warn("job_state.json not found – job may not have been processed yet")

    # ── 2. Artifact inventory ─────────────────────────────────────────────────
    section("ARTIFACTS")
    artifact_files = {
        "transcript_de.txt":       "Plain transcript (no timestamps)",
        "transcript_de_timed.json":"Timed transcript (for clip selection)",
        "transcript_pl.txt":       "Polish translation",
        "clips_selected.json":     "AI-selected clips",
        "pipeline.log":            "Processing log",
        "job_state.json":          "Job state",
    }
    for filename, desc in artifact_files.items():
        path = job_dir / filename
        if path.exists():
            size = path.stat().st_size
            ok(f"{filename:<35} {size/1024:>7.1f} KB  – {desc}")
        else:
            warn(f"{filename:<35} {'MISSING':<10}  – {desc}")

    # Also list all MP4 / WAV files
    media_files = list(job_dir.glob("*.mp4")) + list(job_dir.glob("*.wav"))
    for mf in sorted(media_files):
        size_mb = mf.stat().st_size / (1024 * 1024)
        ok(f"{mf.name:<35} {size_mb:>7.1f} MB  – media file")

    # ── 3. Timed transcript stats ─────────────────────────────────────────────
    timed_path = job_dir / "transcript_de_timed.json"
    timed_segments = load_json(timed_path) or []

    section("TIMED TRANSCRIPT ANALYSIS")
    if not timed_segments:
        warn("transcript_de_timed.json not found or empty.")
        warn("This file is generated automatically from YouTube VTT subtitles.")
        warn("If you used a manual transcript, timestamps are not available.")
        warn("Re-process the job from YouTube to get timestamps, or use --show-transcript.")
    else:
        total_seg_dur = sum(s["end"] - s["start"] for s in timed_segments)
        ok(f"Segments:    {len(timed_segments)}")
        ok(f"Time span:   {fmt_time(timed_segments[0]['start'])} → {fmt_time(timed_segments[-1]['end'])}")
        ok(f"Total text:  {sum(len(s['text']) for s in timed_segments):,} chars")
        total_words = sum(len(s["text"].split()) for s in timed_segments)
        ok(f"Total words: {total_words:,}")

        # Detect gaps (potential scene changes / speaker pauses)
        gaps = []
        for i in range(1, len(timed_segments)):
            gap = timed_segments[i]["start"] - timed_segments[i - 1]["end"]
            if gap > 2.0:
                gaps.append((timed_segments[i - 1]["end"], timed_segments[i]["start"], gap))
        if gaps:
            info(f"Detected {len(gaps)} significant pauses (>2s) – potential cut points:")
            for g_end, g_start, g_dur in gaps[:10]:
                info(f"    {fmt_time(g_end)} → {fmt_time(g_start)}  ({g_dur:.1f}s gap)")
            if len(gaps) > 10:
                info(f"    ... and {len(gaps) - 10} more")

    # ── 4. Show full transcript (optional) ───────────────────────────────────
    if args.show_transcript:
        section("FULL TIMED TRANSCRIPT")
        if timed_segments:
            for seg in timed_segments:
                ts = f"{fmt_time(seg['start'])}–{fmt_time(seg['end'])}"
                print(f"  {DIM}{ts:>14}{RESET}  {seg['text']}")
        else:
            plain = load_text(job_dir / "transcript_de.txt")
            if plain:
                print(plain[:5000])
                if len(plain) > 5000:
                    warn(f"... truncated ({len(plain):,} total chars)")
            else:
                warn("No transcript found")

    # ── 5. Existing clip selection ────────────────────────────────────────────
    clips_path = job_dir / "clips_selected.json"
    existing_clips = load_json(clips_path) or []

    if existing_clips:
        section("EXISTING CLIP SELECTION")
        total_dur = sum(c["end"] - c["start"] for c in existing_clips)
        ok(f"Total clips: {len(existing_clips)}  |  Total duration: {fmt_duration(total_dur)}")
        print()
        _print_clips(existing_clips, timed_segments)

    # ── 6. Run clip selection ─────────────────────────────────────────────────
    if args.run_selection or args.show_all_chunks:
        _run_selection(job_dir, timed_segments, args)

    # ── 7. Visual timeline ────────────────────────────────────────────────────
    clips_to_show = existing_clips
    if not clips_to_show and timed_segments:
        clips_to_show = []  # Will be populated after --run-selection

    if timed_segments and (existing_clips or args.run_selection):
        section("VISUAL TIMELINE")
        _draw_timeline(timed_segments, existing_clips or [], width=70)

    # ── 8. Recent log lines ───────────────────────────────────────────────────
    section("RECENT PIPELINE LOG")
    log_text = load_text(job_dir / "pipeline.log")
    if log_text:
        lines = log_text.strip().splitlines()
        print(f"  {DIM}(showing last 30 of {len(lines)} lines){RESET}")
        for line in lines[-30:]:
            level = "ERROR" if "ERROR" in line else ("WARNING" if "WARNING" in line else "")
            color = RED if level == "ERROR" else (YELLOW if level == "WARNING" else DIM)
            print(f"  {color}{line}{RESET}")
    else:
        warn("No pipeline.log found")

    print()


def _print_clips(clips: list[dict], timed_segments: list[dict]):
    """Print clip details with cut quality and context."""
    for i, clip in enumerate(clips, 1):
        start = clip.get("start", 0)
        end = clip.get("end", 0)
        score = clip.get("score", "?")
        reason = clip.get("reason", "")
        dur = end - start
        cut_start = clip.get("cut_quality_start", "?")
        cut_end = clip.get("cut_quality_end", "?")

        score_color = GREEN if score >= 7 else (YELLOW if score >= 5 else RED)
        print(f"  {BOLD}Clip {i:02d}{RESET}  "
              f"{fmt_time(start)} → {fmt_time(end)}  "
              f"({fmt_duration(dur)})  "
              f"Score: {score_color}{score}/10{RESET}  "
              f"Reason: {reason}")

        # Cut quality
        start_icon = f"{GREEN}✓" if cut_start == "ok" else (f"{YELLOW}~" if cut_start == "mid_clause" else f"{RED}✗")
        end_icon   = f"{GREEN}✓" if cut_end == "ok"   else (f"{YELLOW}~" if cut_end == "mid_clause"   else f"{RED}✗")
        print(f"           Cut-start: {start_icon}{RESET}  Cut-end: {end_icon}{RESET}")

        # Show first and last ~100 chars of clip text
        text = clip.get("text", "")
        if text:
            preview_start = text[:100].replace("\n", " ")
            preview_end   = text[-100:].replace("\n", " ") if len(text) > 100 else ""
            print(f"           {DIM}Start: …{preview_start}…{RESET}")
            if preview_end and preview_end != preview_start:
                print(f"           {DIM}End:   …{preview_end}…{RESET}")

        # Show context from timed transcript (2 segments before/after)
        if timed_segments:
            ctx_before = [s for s in timed_segments if s["end"] <= start][-2:]
            ctx_after  = [s for s in timed_segments if s["start"] >= end][:2]
            if ctx_before:
                prev_text = ctx_before[-1]["text"][:80]
                print(f"           {DIM}Before: «{prev_text}»{RESET}")
            if ctx_after:
                next_text = ctx_after[0]["text"][:80]
                print(f"           {DIM}After:  «{next_text}»{RESET}")

        print()


def _run_selection(job_dir: Path, timed_segments: list[dict], args):
    """Run clip selection and display results."""
    section("RUNNING CLIP SELECTION")

    if not timed_segments:
        err("Cannot run clip selection without transcript_de_timed.json")
        err("Re-process the video from YouTube to generate timestamped transcript")
        return

    # Import here so script works even without backend installed
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from backend.services.clip_selector import ClipSelector, save_selected_clips
    except ImportError as e:
        err(f"Could not import ClipSelector: {e}")
        err("Run from the project root directory.")
        return

    # Get OpenAI key from environment
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        ok(f"Using OpenAI for scoring (key: {api_key[:8]}...)")
    else:
        warn("OPENAI_API_KEY not set – using heuristic scoring (less accurate)")

    target = getattr(args, "target", 15)
    min_clip = getattr(args, "min_clip", 30)
    max_clip = getattr(args, "max_clip", 180)

    selector = ClipSelector(api_key=api_key)

    info(f"Target duration:  {target} minutes")
    info(f"Min clip length:  {min_clip}s")
    info(f"Max clip length:  {max_clip}s")
    info(f"Scoring method:   {'AI (OpenAI)' if api_key else 'Heuristic'}")
    print()

    clips = selector.select_clips(
        timed_segments,
        target_total_minutes=target,
        min_clip_seconds=min_clip,
        max_clip_seconds=max_clip,
    )

    if not clips:
        warn("No clips selected – try reducing --min-clip or increasing --target")
        return

    total_dur = sum(c.duration for c in clips)
    ok(f"Selected {len(clips)} clips  |  Total: {fmt_duration(total_dur)}")
    print()

    # Show all chunks if requested
    if args.show_all_chunks:
        chunks = selector._build_chunks(timed_segments, 60.0)
        scored = selector._score_chunks(chunks)
        scored.sort(key=lambda c: -c["score"])
        print(f"  {BOLD}All scored chunks (sorted by score):{RESET}")
        for c in scored[:30]:
            score = c["score"]
            score_color = GREEN if score >= 7 else (YELLOW if score >= 5 else RED)
            ts = f"{fmt_time(c['start'])}–{fmt_time(c['end'])}"
            preview = c["text"][:80].replace("\n", " ")
            print(f"    {score_color}[{score:2d}/10]{RESET}  {DIM}{ts:>14}{RESET}  {preview}…")
            print(f"           {DIM}Reason: {c.get('reason','')}{RESET}")
        print()

    # Print selected clips detail
    clip_dicts = [c.to_dict() for c in clips]
    _print_clips(clip_dicts, timed_segments)

    # Save to file
    out_path = save_selected_clips(clips, job_dir)
    ok(f"Saved selection to: {out_path}")
    print()
    info("To use these clips in the pipeline, re-run processing for this job.")
    info("Or manually inspect the clips and edit clips_selected.json.")


def _draw_timeline(timed_segments: list[dict], clips: list[dict], width: int = 70):
    """Draw an ASCII timeline showing selected clips vs total duration."""
    if not timed_segments:
        return

    total = timed_segments[-1]["end"]
    if total <= 0:
        return

    bar = [" "] * width
    for clip in clips:
        start_pos = int(clip["start"] / total * width)
        end_pos   = int(clip["end"]   / total * width)
        for p in range(max(0, start_pos), min(width, end_pos)):
            bar[p] = "█"

    print(f"  {fmt_time(0):<8} {''.join(bar)} {fmt_time(total)}")
    selected_dur = sum(c["end"] - c["start"] for c in clips)
    pct = selected_dur / total * 100 if total > 0 else 0
    print(f"  {GREEN}█{RESET} Selected: {fmt_duration(selected_dur)} ({pct:.1f}%)  "
          f"  Total session: {fmt_duration(total)}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="sejm_clip_debug.py",
        description="Debug and improve clip selection for Sejm/parliamentary sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("job_dir", help="Path to job directory, e.g. temp/20260216_185905_xp95_sejm_51_2026-02-13")
    parser.add_argument("--run-selection", action="store_true",
                        help="Run AI clip selection and show results")
    parser.add_argument("--show-transcript", action="store_true",
                        help="Print the full timed transcript")
    parser.add_argument("--show-all-chunks", action="store_true",
                        help="Show all scored transcript chunks (implies --run-selection)")
    parser.add_argument("--target", type=float, default=15.0, metavar="MINUTES",
                        help="Target total clip duration in minutes (default: 15)")
    parser.add_argument("--min-clip", type=float, default=30.0, metavar="SECONDS",
                        help="Minimum clip length in seconds (default: 30)")
    parser.add_argument("--max-clip", type=float, default=180.0, metavar="SECONDS",
                        help="Maximum clip length in seconds (default: 180)")

    args = parser.parse_args()

    if args.show_all_chunks:
        args.run_selection = True

    job_dir = Path(args.job_dir)
    # Support both absolute and relative (relative to cwd or to temp/)
    if not job_dir.exists():
        alt = Path("temp") / args.job_dir
        if alt.exists():
            job_dir = alt

    print()
    print(f"{BOLD}sejm_clip_debug.py{RESET} — Parliamentary clip selection debugger")
    print(f"Job: {CYAN}{job_dir}{RESET}")

    debug_job(job_dir, args)


if __name__ == "__main__":
    main()

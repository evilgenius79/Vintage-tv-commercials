"""Processing pipeline — auto-detect, split, classify, and catalog compilation videos.

This is the main orchestrator that ties together scene detection, FFmpeg splitting,
Hailo AI classification, and the catalog database. Designed to run on a Pi 5
as an always-on processing station.
"""

import os
import shutil
from pathlib import Path

from .catalog import Catalog
from .scene_detect import detect_scenes
from .splitter import split_video, extract_thumbnail
from .hailo_classifier import HailoClassifier


class CommercialPipeline:
    """End-to-end pipeline for processing compilation videos into
    individually cataloged commercials."""

    def __init__(self, catalog: Catalog, download_dir: str = "downloads",
                 clips_dir: str = "clips", model_path: str = None,
                 use_hailo: bool = True):
        """
        Args:
            catalog: Catalog instance for storing results.
            download_dir: Where raw downloads live.
            clips_dir: Where split clips get saved.
            model_path: Path to AI model (.hef or .onnx).
            use_hailo: Try to use Hailo-8 hardware.
        """
        self.catalog = catalog
        self.download_dir = download_dir
        self.clips_dir = clips_dir
        self.classifier = HailoClassifier(
            model_path=model_path, use_hailo=use_hailo
        )

        os.makedirs(clips_dir, exist_ok=True)

    def process_video(self, video_path: str, source_url: str = None,
                      parent_title: str = None,
                      detection_threshold: float = 27.0,
                      min_scene_length: float = 5.0,
                      max_scene_length: float = 120.0) -> list[dict]:
        """Process a single compilation video through the full pipeline.

        Steps:
            1. Detect scene boundaries
            2. Split into individual clips
            3. Classify each clip with AI
            4. Extract thumbnails
            5. Add each clip to the catalog

        Args:
            video_path: Path to the compilation video.
            source_url: Original URL (for catalog reference).
            parent_title: Title of the compilation video.
            detection_threshold: Scene detection sensitivity.
            min_scene_length: Minimum clip duration in seconds.
            max_scene_length: Maximum clip duration in seconds.

        Returns:
            List of catalog entry dicts for each extracted clip.
        """
        video_path = os.path.abspath(video_path)
        base_name = Path(video_path).stem

        print(f"[pipeline] Processing: {parent_title or base_name}")

        # Step 1: Detect scenes
        print(f"[pipeline] Step 1/4: Detecting scene boundaries...")
        scenes = detect_scenes(
            video_path,
            threshold=detection_threshold,
            min_scene_length=min_scene_length,
            max_scene_length=max_scene_length,
        )
        print(f"[pipeline]   Found {len(scenes)} scenes")

        if not scenes:
            print("[pipeline]   No scenes detected, treating as single commercial")
            scenes = [{
                "index": 0,
                "start_time": 0,
                "end_time": None,
                "duration": None,
            }]
            # Single video — just classify and catalog it
            return [self._process_single(video_path, source_url, parent_title)]

        # Step 2: Split into clips
        print(f"[pipeline] Step 2/4: Splitting into {len(scenes)} clips...")
        clip_dir = os.path.join(self.clips_dir, base_name)
        clip_paths = split_video(video_path, scenes, output_dir=clip_dir)
        print(f"[pipeline]   Created {len(clip_paths)} clips")

        # Steps 3 & 4: Classify and thumbnail each clip
        print(f"[pipeline] Step 3/4: Classifying clips with AI...")
        results = []
        for i, clip_path in enumerate(clip_paths):
            scene = scenes[i] if i < len(scenes) else scenes[-1]
            print(f"[pipeline]   Clip {i+1}/{len(clip_paths)}: ", end="", flush=True)

            # Classify
            classification = self.classifier.classify_clip(clip_path)

            # Extract thumbnail
            thumb_path = extract_thumbnail(clip_path)

            # Build title
            clip_title = self._build_clip_title(
                parent_title or base_name, i, classification
            )

            print(f"{clip_title} "
                  f"[{classification.get('method', '?')}, "
                  f"conf={classification.get('confidence', 0):.0%}]")

            # Step 4: Add to catalog
            entry = {
                "title": clip_title,
                "source": "split",
                "source_url": f"{source_url or video_path}#clip{i:03d}",
                "file_path": clip_path,
                "year_estimate": classification.get("decade_estimate"),
                "decade": classification.get("decade_estimate"),
                "brand": classification.get("brand"),
                "description": (
                    f"Clip {i+1} extracted from '{parent_title or base_name}'. "
                    f"Duration: {scene.get('duration', 0):.0f}s. "
                    f"AI detected: {', '.join(classification.get('tags', [])) or 'unknown'}."
                ),
                "duration_seconds": scene.get("duration"),
                "thumbnail_path": thumb_path,
                "classification": classification,
            }

            self.catalog.add(
                title=entry["title"],
                source=entry["source"],
                source_url=entry["source_url"],
                file_path=entry["file_path"],
                year_estimate=entry.get("year_estimate"),
                decade=entry.get("decade"),
                brand=entry.get("brand"),
                description=entry.get("description"),
                duration_seconds=entry.get("duration_seconds"),
                tags=classification.get("tags"),
                metadata={"classification": classification, "parent": source_url},
            )

            results.append(entry)

        # Cleanup temporary frames
        self.classifier.cleanup_frames(video_path)
        for clip_path in clip_paths:
            self.classifier.cleanup_frames(clip_path)

        print(f"[pipeline] Done! {len(results)} commercials extracted and cataloged.")
        return results

    def process_all_downloads(self, min_duration: float = 60.0) -> list[dict]:
        """Process all downloaded videos that look like compilations.

        A video is considered a compilation if its duration exceeds min_duration.

        Args:
            min_duration: Minimum duration in seconds to consider for splitting.

        Returns:
            Combined list of all extracted clip entries.
        """
        from .scene_detect import _get_duration

        all_results = []
        download_path = Path(self.download_dir)

        if not download_path.exists():
            print("[pipeline] No downloads directory found.")
            return []

        video_files = []
        for ext in ("*.mp4", "*.mkv", "*.avi", "*.webm", "*.ogv"):
            video_files.extend(download_path.glob(ext))

        if not video_files:
            print("[pipeline] No video files found in downloads.")
            return []

        print(f"[pipeline] Found {len(video_files)} videos to check")

        for video_file in sorted(video_files):
            duration = _get_duration(str(video_file))
            if not duration or duration < min_duration:
                continue

            # Check if already processed
            already_processed = self.catalog.search(
                query=video_file.stem, limit=1
            )
            clip_entries = [e for e in already_processed
                           if e.get("source") == "split"
                           and video_file.stem in (e.get("source_url") or "")]
            if clip_entries:
                print(f"[pipeline] Skipping (already processed): {video_file.name}")
                continue

            print(f"\n[pipeline] Compilation detected: {video_file.name} "
                  f"({duration:.0f}s / {duration/60:.1f}min)")

            # Look up the original catalog entry for metadata
            parent_entry = None
            catalog_results = self.catalog.search(query=video_file.stem, limit=5)
            for entry in catalog_results:
                if entry.get("file_path") and video_file.name in entry["file_path"]:
                    parent_entry = entry
                    break

            results = self.process_video(
                str(video_file),
                source_url=parent_entry.get("source_url") if parent_entry else None,
                parent_title=parent_entry.get("title") if parent_entry else None,
            )
            all_results.extend(results)

        return all_results

    def _process_single(self, video_path: str, source_url: str,
                        title: str) -> dict:
        """Process a single (non-compilation) video."""
        classification = self.classifier.classify_clip(video_path)
        thumb_path = extract_thumbnail(video_path)

        entry = {
            "title": title or Path(video_path).stem,
            "source_url": source_url or video_path,
            "file_path": video_path,
            "brand": classification.get("brand"),
            "decade_estimate": classification.get("decade_estimate"),
            "classification": classification,
            "thumbnail_path": thumb_path,
        }

        self.classifier.cleanup_frames(video_path)
        return entry

    def _build_clip_title(self, parent_title: str, index: int,
                          classification: dict) -> str:
        """Build a descriptive title for an extracted clip."""
        brand = classification.get("brand")
        if brand:
            return f"{brand.title()} Commercial (from {parent_title})"
        return f"Commercial #{index + 1} (from {parent_title})"

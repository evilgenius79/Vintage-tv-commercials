"""Hailo-8 AI classifier for vintage TV commercials.

Uses the Hailo-8 AI accelerator (26 TOPS) on Raspberry Pi 5 to classify
video clips — detecting brands, products, and estimating the era/decade.

Supports two modes:
1. Hailo HailoRT API (native, fastest)
2. CPU fallback using ONNX Runtime (works anywhere)
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Optional

# Known brand/product labels for commercial classification
COMMERCIAL_CATEGORIES = [
    # Food & Drink
    "coca cola", "pepsi", "mcdonalds", "burger king", "wendys", "taco bell",
    "pizza hut", "dominos", "kfc", "subway", "7up", "sprite", "mountain dew",
    "dr pepper", "budweiser", "miller lite", "coors",
    # Cereal
    "cheerios", "frosted flakes", "lucky charms", "fruit loops",
    "cap'n crunch", "rice krispies", "cocoa puffs",
    # Toys & Games
    "hot wheels", "barbie", "gi joe", "transformers", "lego", "nerf",
    "nintendo", "sega", "atari", "playstation", "game boy",
    # Cars
    "ford", "chevy", "toyota", "honda", "bmw", "mercedes",
    # Shoes & Clothing
    "nike", "reebok", "adidas", "converse", "levis",
    # Tech
    "apple", "ibm", "microsoft", "aol", "compaq",
    # Other
    "tide", "clorox", "gillette", "band-aid", "tylenol",
]

# Frame-level descriptors for era detection
ERA_HINTS = {
    "1970s": ["wood paneling", "earth tones", "analog", "grainy"],
    "1980s": ["neon", "synthesizer", "big hair", "vhs quality", "bright colors"],
    "1990s": ["grunge", "cgi early", "dial-up", "extreme sports", "flannel"],
}


class HailoClassifier:
    """Classify commercial clips using the Hailo-8 NPU or CPU fallback."""

    def __init__(self, model_path: str = None, labels_path: str = None,
                 use_hailo: bool = True):
        """Initialize the classifier.

        Args:
            model_path: Path to the model file (.hef for Hailo, .onnx for CPU).
            labels_path: Path to labels JSON file. Uses built-in if None.
            use_hailo: Try to use Hailo hardware. Falls back to CPU if unavailable.
        """
        self.hailo_available = use_hailo and _check_hailo()
        self.model_path = model_path
        self.labels = COMMERCIAL_CATEGORIES
        self._hailo_runner = None
        self._onnx_session = None

        if labels_path and os.path.exists(labels_path):
            with open(labels_path) as f:
                self.labels = json.load(f)

        if self.hailo_available and model_path and model_path.endswith(".hef"):
            self._init_hailo(model_path)
        elif model_path and model_path.endswith(".onnx"):
            self._init_onnx(model_path)

    def classify_clip(self, video_path: str, num_frames: int = 5) -> dict:
        """Classify a video clip by sampling frames and running inference.

        Args:
            video_path: Path to the video clip.
            num_frames: Number of frames to sample from the clip.

        Returns:
            Dict with brand, category, decade_estimate, confidence, and tags.
        """
        frames = self._extract_frames(video_path, num_frames)
        if not frames:
            return self._empty_result()

        if self._hailo_runner:
            return self._classify_hailo(frames)
        elif self._onnx_session:
            return self._classify_onnx(frames)
        else:
            # No model loaded — use text-based heuristics from filename/metadata
            return self._classify_heuristic(video_path)

    def classify_frame(self, frame_path: str) -> dict:
        """Classify a single frame image."""
        if self._hailo_runner:
            return self._classify_hailo([frame_path])
        elif self._onnx_session:
            return self._classify_onnx([frame_path])
        return self._empty_result()

    def _init_hailo(self, hef_path: str):
        """Initialize the Hailo-8 inference runner."""
        try:
            from hailo_platform import HEF, VDevice, ConfigureParams

            hef = HEF(hef_path)
            target = VDevice()
            configure_params = ConfigureParams.create_from_hef(
                hef=hef, interface=target.get_default_streams_interface()
            )
            network_group = target.configure(hef, configure_params)[0]
            self._hailo_runner = {
                "target": target,
                "network_group": network_group,
                "hef": hef,
                "input_vstream_info": hef.get_input_vstream_infos(),
                "output_vstream_info": hef.get_output_vstream_infos(),
            }
            print("[hailo] Initialized Hailo-8 (26 TOPS) inference")
        except (ImportError, Exception) as e:
            print(f"[hailo] Failed to initialize Hailo: {e}")
            print("[hailo] Falling back to CPU inference")
            self.hailo_available = False

    def _init_onnx(self, onnx_path: str):
        """Initialize ONNX Runtime session for CPU fallback."""
        try:
            import onnxruntime as ort
            self._onnx_session = ort.InferenceSession(onnx_path)
            print("[classifier] Initialized ONNX Runtime (CPU mode)")
        except ImportError:
            print("[classifier] onnxruntime not installed. Using heuristic mode.")

    def _classify_hailo(self, frame_paths: list[str]) -> dict:
        """Run classification on the Hailo-8 NPU."""
        try:
            import numpy as np
            from hailo_platform import (
                InferVStreams, InputVStreamParams, OutputVStreamParams
            )

            runner = self._hailo_runner
            input_info = runner["input_vstream_info"][0]
            input_shape = input_info.shape  # e.g., (224, 224, 3)

            # Prepare input frames
            frames = []
            for fp in frame_paths:
                frame = self._load_and_resize(fp, input_shape[0], input_shape[1])
                if frame is not None:
                    frames.append(frame)

            if not frames:
                return self._empty_result()

            batch = np.stack(frames).astype(np.uint8)

            input_params = InputVStreamParams.make(
                runner["network_group"], quantized=True
            )
            output_params = OutputVStreamParams.make(
                runner["network_group"], quantized=False
            )

            with InferVStreams(
                runner["network_group"], input_params, output_params
            ) as pipeline:
                input_dict = {input_info.name: batch}
                results = pipeline.infer(input_dict)

            # Aggregate predictions across frames
            output_name = runner["output_vstream_info"][0].name
            predictions = results[output_name]
            avg_pred = np.mean(predictions, axis=0)

            return self._interpret_predictions(avg_pred)

        except Exception as e:
            print(f"[hailo] Inference error: {e}")
            return self._empty_result()

    def _classify_onnx(self, frame_paths: list[str]) -> dict:
        """Run classification using ONNX Runtime (CPU fallback)."""
        try:
            import numpy as np

            session = self._onnx_session
            input_info = session.get_inputs()[0]
            _, h, w, c = input_info.shape if len(input_info.shape) == 4 else (1, 224, 224, 3)

            frames = []
            for fp in frame_paths:
                frame = self._load_and_resize(fp, h, w)
                if frame is not None:
                    frames.append(frame)

            if not frames:
                return self._empty_result()

            batch = np.stack(frames).astype(np.float32) / 255.0
            results = session.run(None, {input_info.name: batch})
            avg_pred = np.mean(results[0], axis=0)

            return self._interpret_predictions(avg_pred)

        except Exception as e:
            print(f"[classifier] ONNX inference error: {e}")
            return self._empty_result()

    def _classify_heuristic(self, video_path: str) -> dict:
        """Classify using filename/path heuristics when no model is available."""
        name = Path(video_path).stem.lower()
        parent = Path(video_path).parent.name.lower()
        search_text = f"{name} {parent}"

        detected_brands = []
        for brand in self.labels:
            if brand.lower() in search_text:
                detected_brands.append(brand)

        decade = None
        import re
        year_match = re.search(r'(19[789]\d)', search_text)
        if year_match:
            year = int(year_match.group(1))
            decade = f"{(year // 10) * 10}s"

        return {
            "brand": detected_brands[0] if detected_brands else None,
            "brands_detected": detected_brands,
            "category": None,
            "decade_estimate": decade,
            "confidence": 0.3 if detected_brands else 0.0,
            "tags": detected_brands,
            "method": "heuristic",
        }

    def _interpret_predictions(self, predictions) -> dict:
        """Convert model output to structured classification result."""
        import numpy as np

        if len(predictions) == 0:
            return self._empty_result()

        top_idx = int(np.argmax(predictions))
        confidence = float(predictions[top_idx])

        brand = self.labels[top_idx] if top_idx < len(self.labels) else None

        # Get top-5 for tags
        top_indices = np.argsort(predictions)[::-1][:5]
        tags = []
        for idx in top_indices:
            if idx < len(self.labels) and predictions[idx] > 0.1:
                tags.append(self.labels[idx])

        return {
            "brand": brand,
            "brands_detected": tags,
            "category": self._brand_to_category(brand),
            "decade_estimate": None,
            "confidence": confidence,
            "tags": tags,
            "method": "hailo" if self.hailo_available else "onnx",
        }

    def _extract_frames(self, video_path: str, num_frames: int) -> list[str]:
        """Extract evenly-spaced frames from a video clip."""
        from .scene_detect import _get_duration

        duration = _get_duration(video_path)
        if not duration or duration < 1:
            return []

        temp_dir = os.path.join(os.path.dirname(video_path), ".frames_tmp")
        os.makedirs(temp_dir, exist_ok=True)

        frame_paths = []
        for i in range(num_frames):
            timestamp = duration * (i + 1) / (num_frames + 1)
            frame_path = os.path.join(temp_dir, f"frame_{i:03d}.jpg")

            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{timestamp:.2f}",
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "3",
                frame_path,
            ]

            try:
                subprocess.run(cmd, capture_output=True, timeout=15)
                if os.path.exists(frame_path):
                    frame_paths.append(frame_path)
            except subprocess.TimeoutExpired:
                continue

        return frame_paths

    def _load_and_resize(self, image_path: str, height: int, width: int):
        """Load an image and resize it for model input."""
        try:
            import numpy as np
            from PIL import Image

            img = Image.open(image_path).convert("RGB")
            img = img.resize((width, height), Image.BILINEAR)
            return np.array(img)
        except ImportError:
            # Fallback: use ffmpeg to resize
            return self._load_with_ffmpeg(image_path, height, width)
        except Exception:
            return None

    def _load_with_ffmpeg(self, image_path: str, height: int, width: int):
        """Load and resize using ffmpeg (no PIL dependency)."""
        try:
            import numpy as np

            output_path = image_path + ".resized.rgb"
            cmd = [
                "ffmpeg", "-y",
                "-i", image_path,
                "-vf", f"scale={width}:{height}",
                "-pix_fmt", "rgb24",
                "-f", "rawvideo",
                output_path,
            ]
            subprocess.run(cmd, capture_output=True, timeout=10)

            if os.path.exists(output_path):
                raw = np.fromfile(output_path, dtype=np.uint8)
                os.remove(output_path)
                return raw.reshape((height, width, 3))
        except Exception:
            pass
        return None

    def _brand_to_category(self, brand: str | None) -> str | None:
        """Map a brand to a broad category."""
        if not brand:
            return None
        brand_lower = brand.lower()
        categories = {
            "fast food": ["mcdonalds", "burger king", "wendys", "taco bell",
                          "pizza hut", "dominos", "kfc", "subway"],
            "soda": ["coca cola", "pepsi", "7up", "sprite", "mountain dew", "dr pepper"],
            "beer": ["budweiser", "miller lite", "coors"],
            "cereal": ["cheerios", "frosted flakes", "lucky charms", "fruit loops",
                       "cap'n crunch", "rice krispies", "cocoa puffs"],
            "toys": ["hot wheels", "barbie", "gi joe", "transformers", "lego", "nerf"],
            "video games": ["nintendo", "sega", "atari", "playstation", "game boy"],
            "automotive": ["ford", "chevy", "toyota", "honda", "bmw", "mercedes"],
            "footwear": ["nike", "reebok", "adidas", "converse"],
            "technology": ["apple", "ibm", "microsoft", "aol", "compaq"],
        }
        for category, brands in categories.items():
            if brand_lower in brands:
                return category
        return None

    def _empty_result(self) -> dict:
        return {
            "brand": None,
            "brands_detected": [],
            "category": None,
            "decade_estimate": None,
            "confidence": 0.0,
            "tags": [],
            "method": "none",
        }

    def cleanup_frames(self, video_path: str):
        """Remove temporary frame extraction directory."""
        temp_dir = os.path.join(os.path.dirname(video_path), ".frames_tmp")
        if os.path.isdir(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


def _check_hailo() -> bool:
    """Check if Hailo hardware and SDK are available."""
    try:
        from hailo_platform import VDevice
        target = VDevice()
        target.release()
        return True
    except (ImportError, Exception):
        return False

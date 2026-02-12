# harness/vlm_provider.py
"""
Unified VLM (Vision Language Model) Provider for UI element detection.
Supports multiple backends: Gemini, HuggingFace.
"""

import os
import re
import json
import base64
import datetime
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from PIL import Image

# =============================================================================
# CONFIGURATION
# =============================================================================

RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "experiments")
DEBUG_LOG_PATH = os.path.join(RUNS_DIR, "vlm_debug.log")
ERROR_LOG_PATH = os.path.join(RUNS_DIR, "vision_error_debug.json")

MAX_RETRIES = 2

os.makedirs(RUNS_DIR, exist_ok=True)


# =============================================================================
# LOGGING
# =============================================================================

def log_debug(provider: str, message: str):
    """Log debug message to vlm_debug.log."""
    try:
        ts = datetime.datetime.now().isoformat()
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {provider} | {message}\n")
    except Exception:
        pass


def log_error(provider: str, error_body: Any):
    """Log error body to vision_error_debug.json."""
    try:
        errors = []
        if os.path.exists(ERROR_LOG_PATH):
            with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
                errors = json.load(f)
        
        errors.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "provider": provider,
            "error": str(error_body)[:2000]
        })
        
        # Keep last 50 errors
        errors = errors[-50:]
        
        with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(errors, f, indent=2)
    except Exception:
        pass


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def load_image_base64(image_path: str) -> str:
    """Load image and convert to base64."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_image_dimensions(image_path: str) -> tuple:
    """Get image width and height."""
    with Image.open(image_path) as img:
        return img.size  # (width, height)


def validate_bbox(bbox: List[int], img_width: int, img_height: int) -> List[int]:
    """Validate and normalize bounding box to image bounds."""
    x, y, w, h = bbox
    
    # Clamp to image bounds
    x = max(0, min(x, img_width - 1))
    y = max(0, min(y, img_height - 1))
    w = max(1, min(w, img_width - x))
    h = max(1, min(h, img_height - y))
    
    return [int(x), int(y), int(w), int(h)]


def parse_coordinates_from_response(response_text: str, img_width: int, img_height: int) -> List[Dict]:
    """
    Parse coordinates from LLM response text.
    Supports multiple formats: [x,y,w,h], (x,y,w,h), x=N y=N, etc.
    """
    results = []
    
    # Pattern 1: JSON-like bounding boxes [x, y, w, h] or {"bbox": [...]}
    bbox_pattern = r'\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]'
    matches = re.findall(bbox_pattern, response_text)
    
    for match in matches:
        x, y, w, h = map(int, match)
        bbox = validate_bbox([x, y, w, h], img_width, img_height)
        cx = bbox[0] + bbox[2] // 2
        cy = bbox[1] + bbox[3] // 2
        results.append({
            "bbox": bbox,
            "label": "detected",
            "conf": 0.8,
            "x": cx,
            "y": cy
        })
    
    # Pattern 2: Center coordinates (x, y) or x=N, y=N
    if not results:
        center_pattern = r'\((\d+),\s*(\d+)\)'
        matches = re.findall(center_pattern, response_text)
        
        for match in matches:
            x, y = map(int, match)
            if 0 <= x < img_width and 0 <= y < img_height:
                results.append({
                    "bbox": [max(0, x-20), max(0, y-10), 40, 20],
                    "label": "detected",
                    "conf": 0.7,
                    "x": x,
                    "y": y
                })
    
    # Pattern 3: x=N, y=N format
    if not results:
        xy_pattern = r'x\s*[:=]\s*(\d+).*?y\s*[:=]\s*(\d+)'
        match = re.search(xy_pattern, response_text, re.IGNORECASE)
        if match:
            x, y = int(match.group(1)), int(match.group(2))
            if 0 <= x < img_width and 0 <= y < img_height:
                results.append({
                    "bbox": [max(0, x-20), max(0, y-10), 40, 20],
                    "label": "detected",
                    "conf": 0.6,
                    "x": x,
                    "y": y
                })
    
    return results


# =============================================================================
# BASE VLM CLASS
# =============================================================================

class BaseVLM(ABC):
    """Abstract base class for VLM providers."""
    
    def __init__(self, api_keys: List[str] = None):
        self.api_keys = api_keys or []
        self.current_key_index = 0
        self.name = "BaseVLM"
    
    def rotate_key(self):
        """Rotate to next available API key."""
        if len(self.api_keys) > 1:
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
            log_debug(self.name, f"Rotated to key index {self.current_key_index}")
    
    @property
    def current_key(self) -> Optional[str]:
        if self.api_keys:
            return self.api_keys[self.current_key_index]
        return None
    
    @abstractmethod
    def _call_api(self, image_path: str, prompt: str) -> str:
        """Make API call and return response text."""
        pass
    
    def locate_elements(
        self, 
        screenshot_path: str, 
        task: str, 
        top_k: int = 3
    ) -> List[Dict]:
        """
        Locate UI elements matching the task description.
        """
        if not os.path.exists(screenshot_path):
            log_debug(self.name, f"Screenshot not found: {screenshot_path}")
            return []
        
        img_width, img_height = get_image_dimensions(screenshot_path)
        
        prompt = f"""Analyze this UI screenshot and locate: {task}

For each matching element, provide the bounding box coordinates as [x, y, width, height] in pixels.
Format your response as JSON array of objects with "bbox" field.
Example: [{{"bbox": [100, 200, 50, 30], "label": "Close button"}}]

Only return elements that match the task. If no match found, return empty array []."""

        for attempt in range(MAX_RETRIES):
            try:
                log_debug(self.name, f"Attempt {attempt+1}: {task[:50]}")
                response = self._call_api(screenshot_path, prompt)
                log_debug(self.name, f"Response: {response[:200]}")
                
                results = parse_coordinates_from_response(response, img_width, img_height)
                
                if results:
                    return results[:top_k]
                    
            except Exception as e:
                log_error(self.name, str(e))
                log_debug(self.name, f"Error: {e}")
                self.rotate_key()
        
        return []


# =============================================================================
# GEMINI VLM
# =============================================================================

class GeminiVLM(BaseVLM):
    """Google Gemini Vision provider."""
    
    MODELS = [
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]
    
    def __init__(self):
        keys = []
        key = os.getenv("GEMINI_API_KEY")
        if key:
            keys.append(key)
        
        super().__init__(keys)
        self.name = "GeminiVLM"
        self.model_index = 0
        
        # Import on init
        try:
            import google.generativeai as genai
            self.genai = genai
            if self.current_key:
                genai.configure(api_key=self.current_key)
            log_debug(self.name, "Initialized successfully")
        except ImportError:
            self.genai = None
            log_debug(self.name, "google-generativeai not installed")
    
    def _call_api(self, image_path: str, prompt: str) -> str:
        if not self.genai:
            raise RuntimeError("google-generativeai not installed")
        
        if not self.current_key:
            raise RuntimeError("No GEMINI_API_KEY set")
        
        # Try models in order
        for model_name in self.MODELS:
            try:
                model = self.genai.GenerativeModel(model_name)
                img = Image.open(image_path)
                response = model.generate_content([prompt, img])
                if response.text:
                    return response.text
            except Exception as e:
                log_debug(self.name, f"Model {model_name} failed: {e}")
                continue
        
        raise RuntimeError("All Gemini models failed")


# =============================================================================
# HUGGINGFACE VLM
# =============================================================================

class HFVLM(BaseVLM):
    """HuggingFace Inference API provider."""
    
    def __init__(self):
        keys = []
        key = os.getenv("HF_TOKEN")
        if key:
            keys.append(key)
        
        super().__init__(keys)
        self.name = "HFVLM"
        self.model = "Salesforce/blip-vqa-large"
    
    def _call_api(self, image_path: str, prompt: str) -> str:
        try:
            from huggingface_hub import InferenceClient
        except ImportError:
            raise RuntimeError("huggingface_hub not installed")
        
        if not self.current_key:
            raise RuntimeError("No HF_TOKEN set")
        
        client = InferenceClient(token=self.current_key)
        with open(image_path, "rb") as f:
            image_bytes = f.read()
            
        result = client.visual_question_answering(
            image=image_bytes,
            question=prompt,
            model=self.model
        )
        return str(result[0]) if isinstance(result, list) else str(result)


# =============================================================================
# VLM FACTORY
# =============================================================================

def get_available_vlm() -> Optional[BaseVLM]:
    """Get the first available VLM provider."""
    
    print("[VLM INIT] GEMINI_API_KEY present:", bool(os.getenv("GEMINI_API_KEY")))
    print("[VLM INIT] HF_TOKEN present:", bool(os.getenv("HF_TOKEN")))
    
    # Try Gemini first
    if os.getenv("GEMINI_API_KEY"):
        try:
            vlm = GeminiVLM()
            if vlm.genai:
                log_debug("Factory", "Using GeminiVLM")
                return vlm
        except Exception:
            pass
    
    # Try HuggingFace
    if os.getenv("HF_TOKEN"):
        try:
            vlm = HFVLM()
            log_debug("Factory", "Using HFVLM")
            return vlm
        except Exception:
            pass
    
    log_debug("Factory", "No VLM provider available")
    return None


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def locate_elements(
    screenshot_path: str,
    task: str,
    top_k: int = 3,
    provider: str = None
) -> List[Dict]:
    """Locate UI elements using available VLM."""
    vlm = None
    if provider == "gemini":
        vlm = GeminiVLM()
    elif provider == "hf":
        vlm = HFVLM()
    else:
        vlm = get_available_vlm()
    
    if not vlm:
        log_debug("locate_elements", "No VLM available")
        return []
    
    return vlm.locate_elements(screenshot_path, task, top_k)

# automation_tree/matcher.py
"""
Robust task-to-element matching with:
- Text normalization (suffix stripping, numeric conversion)
- Stopword removal
- Token Jaccard similarity
- Subset matching boost
- Length penalty for extra tokens
- History bonus for previously successful tasks
"""

import re
import os
import datetime
from difflib import SequenceMatcher
from typing import Optional, Dict, List, Set

from src.automation import storage


# =============================================================================
# CONFIGURATION
# =============================================================================

STOPWORDS = {"the", "a", "an", "to", "for", "on", "in", "of", "click", "press", "open", "menu", "button", "item"}

# Suffix patterns with minimum stem length
SUFFIX_RULES = [
    ("ting", 3),   # formatting → forma... wait, need smarter approach
    ("ing", 3),    # clicking → click
    ("ed", 3),     # clicked → click
    ("s", 3),      # files → file
]

NUM_TO_WORD = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "10": "ten", "11": "eleven", "12": "twelve", "13": "thirteen",
    "14": "fourteen", "15": "fifteen", "16": "sixteen", "17": "seventeen",
    "18": "eighteen", "19": "nineteen", "20": "twenty"
}

WORD_TO_NUM = {v: k for k, v in NUM_TO_WORD.items()}

DEFAULT_MIN_CONFIDENCE = 0.82
VERIFICATION_BAND_LOW = 0.65

RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "experiments")
DEBUG_LOG_PATH = os.path.join(RUNS_DIR, "matcher_debug.log")


# =============================================================================
# TEXT NORMALIZATION
# =============================================================================

def normalize_text(s: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def strip_suffix(token: str) -> str:
    """
    Strip common suffixes from token.
    Uses a simple stemmer approach.
    """
    # Handle special cases first
    if token.endswith("tting"):
        return token[:-4]  # formatting -> format
    if token.endswith("ting"):
        return token[:-4]  # formatting -> format (but check if result is valid)
    if token.endswith("ing") and len(token) > 5:
        # Check for doubled consonant before ing
        stem = token[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]  # running -> run
        return stem
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


def numeric_normalize(token: str) -> str:
    """Convert numeric tokens to word form."""
    if token in NUM_TO_WORD:
        return NUM_TO_WORD[token]
    return token


def tokenize_and_normalize(text: str) -> Set[str]:
    """
    Tokenize text, remove stopwords, normalize suffixes and numbers.
    Returns set of normalized tokens.
    """
    text = normalize_text(text)
    tokens = text.split()
    
    result = set()
    for token in tokens:
        # Skip stopwords
        if token in STOPWORDS:
            continue
        
        # Normalize numerics
        token = numeric_normalize(token)
        
        # Strip suffix
        token = strip_suffix(token)
        
        if token and len(token) > 1:
            result.add(token)
    
    return result


# =============================================================================
# SCORING SIGNALS
# =============================================================================

def token_jaccard(task_tokens: Set[str], elem_tokens: Set[str]) -> float:
    """Compute Jaccard similarity: |intersection| / |union|."""
    if not task_tokens and not elem_tokens:
        return 0.0
    intersection = task_tokens & elem_tokens
    union = task_tokens | elem_tokens
    if not union:
        return 0.0
    return len(intersection) / len(union)


def subset_score(task_tokens: Set[str], elem_tokens: Set[str]) -> float:
    """
    Score based on how well element tokens are contained in task.
    Returns 1.0 if all element tokens are in task, scaled down otherwise.
    """
    if not elem_tokens:
        return 0.0
    
    matched = elem_tokens & task_tokens
    
    # All element tokens found in task = high score
    if matched == elem_tokens:
        return 1.0
    
    # Partial match
    return len(matched) / len(elem_tokens)


def name_similarity(task: str, element_name: str) -> float:
    """Compute SequenceMatcher ratio between normalized strings."""
    task_norm = normalize_text(task)
    elem_norm = normalize_text(element_name)
    if not task_norm or not elem_norm:
        return 0.0
    return SequenceMatcher(None, task_norm, elem_norm).ratio()


def history_bonus(task: str, tasks_succeeded: List[str]) -> float:
    """Return 1.0 if this exact task previously succeeded, else 0.0."""
    task_norm = normalize_text(task)
    for prev_task in tasks_succeeded:
        if normalize_text(prev_task) == task_norm:
            return 1.0
    return 0.0


def length_penalty(task_tokens: Set[str], elem_tokens: Set[str], penalty_factor: float = 0.25) -> float:
    """Penalize elements with extra tokens not in task."""
    extra_tokens = len(elem_tokens - task_tokens)
    return 1.0 / (1.0 + extra_tokens * penalty_factor)


# =============================================================================
# MATCH SCORE
# =============================================================================

DEFAULT_WEIGHTS = {
    "subset": 0.5,
    "jaccard": 0.25,
    "name_sim": 0.15,
    "history": 0.1
}

ELECTRON_WEIGHTS = {
    "subset": 0.6,    # Prioritize name containment
    "jaccard": 0.2,
    "name_sim": 0.2,
    "history": 0.05,
    "id_penalty": 0.4  # Deprioritize dynamic Electron IDs
}

def match_score(
    task: str,
    element_name: str,
    element_auto_id: str = "",
    tasks_succeeded: List[str] = None,
    app_metadata: Dict = None
) -> Dict:
    """
    Compute robust match score between task and element.
    """
    tasks_succeeded = tasks_succeeded or []
    ui_type = app_metadata.get("ui_type", "native") if app_metadata else "native"
    
    # Select weights
    weights = DEFAULT_WEIGHTS
    if ui_type == "electron":
        weights = ELECTRON_WEIGHTS
    
    # weights = ...
    
    # 0. Exact Match Shortcut
    task_norm = normalize_text(task)
    elem_norm = normalize_text(element_name)
    if task_norm == elem_norm and task_norm != "":
        return {
            "score": 1.0,
            "token_jaccard": 1.0,
            "subset_score": 1.0,
            "name_sim": 1.0,
            "history": history_bonus(task, tasks_succeeded),
            "extra_tokens": 0,
            "penalty": 1.0,
            "weights_used": weights
        }

    # Tokenize
    task_tokens = tokenize_and_normalize(task)
    elem_tokens = tokenize_and_normalize(element_name)
    
    # Also consider automation ID tokens (but weight them less for Electron)
    aid_tokens = tokenize_and_normalize(element_auto_id) if element_auto_id else set()
    if ui_type == "electron" and element_auto_id:
        # Check if ID looks like a long hash/dynamic string
        if len(element_auto_id) > 15 and re.search(r'[0-9]{3,}', element_auto_id):
            aid_tokens = set() # Ignore dynamic Electron IDs
            
    combined_elem_tokens = elem_tokens | aid_tokens
    
    # Compute signals
    jaccard = token_jaccard(task_tokens, combined_elem_tokens)
    subset = subset_score(task_tokens, elem_tokens)
    name_sim = name_similarity(task, element_name)
    hist_bonus = history_bonus(task, tasks_succeeded)
    
    # Extra tokens and penalty
    extra = max(0, len(elem_tokens - task_tokens))
    penalty = length_penalty(task_tokens, elem_tokens)
    
    # Weighted combination
    score_raw = (
        weights.get("subset", 0.5) * subset + 
        weights.get("jaccard", 0.25) * jaccard + 
        weights.get("name_sim", 0.15) * name_sim + 
        weights.get("history", 0.1) * hist_bonus
    )
    
    # Intent-perfect boost: If all normalized tokens match exactly, boost significantly
    if jaccard == 1.0 and subset == 1.0 and task_tokens:
        score_raw = max(score_raw, 0.98)

    score = score_raw * penalty
    
    return {
        "score": round(score, 4),
        "token_jaccard": round(jaccard, 4),
        "subset_score": round(subset, 4),
        "name_sim": round(name_sim, 4),
        "history": hist_bonus,
        "extra_tokens": extra,
        "penalty": round(penalty, 4),
        "weights_used": weights
    }


# =============================================================================
# DEBUG LOGGING
# =============================================================================

def log_match_debug(
    task: str,
    element_name: str,
    jaccard: float,
    name_sim: float,
    extra: int,
    penalty: float,
    score: float,
    weights: Dict = None
):
    """Append debug line to matcher_debug.log."""
    try:
        os.makedirs(RUNS_DIR, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        w_str = f"WEIGHTS={json.dumps(weights)}" if weights else ""
        line = (
            f"{timestamp} | TASK=\"{task[:40]}\" | CAND=\"{element_name[:30]}\" | "
            f"JACCARD={jaccard:.3f} | NAME_SIM={name_sim:.3f} | "
            f"EXTRA={extra} | PENALTY={penalty:.3f} | {w_str} | SCORE={score:.3f}\n"
        )
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def init_debug_log(output_dir: str = None):
    """Initialize/clear debug log."""
    global DEBUG_LOG_PATH
    if output_dir:
        DEBUG_LOG_PATH = os.path.join(output_dir, "matcher_debug.log")
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG_PATH), exist_ok=True)
        with open(DEBUG_LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"# Matcher Debug Log - {datetime.datetime.now().isoformat()}\n\n")
    except Exception:
        pass


# =============================================================================
# CACHE MATCHING
# =============================================================================

def find_cached_element(
    app_name: str,
    task: str,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
) -> Optional[Dict]:
    """
    Find a cached element matching the task.
    
    Args:
        app_name: Application name
        task: Task description
        min_confidence: Minimum score for auto-execute (default 0.82)
    
    Returns:
        Dict with fingerprint, element data, score, requires_verification flag
        Or None if no match above verification band
    """
    cache = storage.load_cache(app_name)
    elements = cache.get("elements", {})
    
    if not elements:
        return None
    
    matches = []
    
    from src.harness import config
    app_meta = config.get_app_config(app_name)
    
    for fp, elem_data in elements.items():
        name = elem_data.get("name", "")
        auto_id = elem_data.get("automation_id", "")
        tasks_succeeded = elem_data.get("tasks_succeeded", [])
        
        # Compute score
        result = match_score(task, name, auto_id, tasks_succeeded, app_metadata=app_meta)
        score = result["score"]
        
        # Log for debugging (only meaningful scores)
        if score >= 0.3:
            log_match_debug(
                task, name,
                result["token_jaccard"],
                result["name_sim"],
                result["extra_tokens"],
                result["penalty"],
                score,
                weights=result.get("weights_used")
            )
        
        if score >= VERIFICATION_BAND_LOW:
            matches.append({
                "fingerprint": fp,
                "element": elem_data,
                "score": score,
                "name": name,
                "control_type": elem_data.get("control_type", ""),
                "automation_id": auto_id,
                "rect": elem_data.get("rect"),
                "patterns": elem_data.get("patterns", []),
                "exposure_path": elem_data.get("exposure_path"), # CRITICAL: Pass exposure path
                "requires_verification": score < min_confidence
            })
    
    # Log lookup attempt (part of Scientific Protocol)
    print(f"[matcher] Candidate matches found: {len(matches)}")
    
    if not matches:
        print(f"[matcher] No confident match (best below {VERIFICATION_BAND_LOW})")
        return None
    
    # Sort by score descending
    matches.sort(key=lambda x: x["score"], reverse=True)
    best = matches[0]
    
    # Log best match
    print(f"[matcher] Best match: '{best['name'][:30]}' (score={best['score']:.2f}, fp={best['fingerprint'][:8]})")
    
    return best

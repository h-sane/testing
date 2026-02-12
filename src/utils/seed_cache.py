
import json
import os
import datetime

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
cache_path = os.path.join(root_dir, ".cache", "notepad.json")
edit_fp = "d8d8d826046d563e" # From previous finding

def seed_cache():
    if not os.path.exists(cache_path):
        print("Cache not found (or Notepad execution needed first)!")
        return

    with open(cache_path, "r") as f:
        data = json.load(f)
    
    target_fp = "TIMEDATE_SEEDED_FP"
    
    new_elem = {
        "name": "Time/Date", 
        "control_type": "MenuItem",
        "automation_id": "", 
        "path": "Untitled - Notepad>Pane>Pane>MenuBar>Edit>Time/Date", 
        "rect": [0,0,0,0],
        "patterns": ["InvokePattern"],
        "discovery_method": "MANUAL_SEED",
        "exposure_path": [
            {
                "parent_fingerprint": edit_fp,
                "action": "expand"
            }
        ],
        "parent_fingerprint": edit_fp,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "last_used": datetime.datetime.utcnow().isoformat() + "Z"
    }
    
    data["elements"][target_fp] = new_elem
    
    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2)
        
    print(f"Seeded 'Time/Date' ({target_fp}) into cache.")

if __name__ == "__main__":
    seed_cache()

"""
General-purpose app crawl script.
Usage: python scripts/crawl_app.py [--app AppName] [--time MaxSeconds]
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness import config, app_controller
from src.automation import prober, storage


def crawl_app(app_name="Notepad", max_time=120):
    print(f"=== Crawling {app_name} ===")
    print(f"Max time: {max_time}s")
    
    app_cfg = config.get_app_config(app_name)
    controller = app_controller.create_controller(app_name, app_cfg)
    
    if not controller.start_or_connect():
        print("FAIL: Could not start/connect to app")
        sys.exit(1)
    
    window = controller.get_window()
    if not window:
        print("FAIL: Could not get window")
        controller.close()
        sys.exit(1)
    
    # Run the prober
    crawler = prober.UIProber(max_depth=12, max_time=max_time)
    
    start = time.time()
    try:
        discovered = crawler.probe_window(window, app_name, clear_cache=True)
    finally:
        # Always close the app cleanly after crawling
        print(f"\n--- Closing {app_name} ---")
        crawler._reset_ui()  # Close any open menus/dialogs first
        time.sleep(0.5)
        controller.close()
    
    elapsed = time.time() - start
    
    print(f"\n=== Results ===")
    print(f"Discovered: {discovered} elements")
    print(f"Total in cache: {crawler.session.count()}")
    print(f"Time: {elapsed:.1f}s")
    print(f"Stats: {crawler.stats}")
    print(f"Log: {crawler.log_path}")
    
    # Quick integrity sanity check
    cache = storage.load_cache(app_name)
    elements = cache.get("elements", {})
    orphans = sum(1 for n in elements.values() 
                  if n.get("parent_fingerprint") and n["parent_fingerprint"] not in elements)
    
    print(f"\nQuick check: {orphans} orphan nodes")
    if orphans == 0:
        print("✅ No orphans!")
    else:
        print(f"⚠️  {orphans} orphans detected — run analyze_cache_integrity.py for details")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="Notepad", help="App name")
    parser.add_argument("--time", type=int, default=600, help="Max crawl time (seconds)")
    args = parser.parse_args()
    crawl_app(args.app, args.time)


import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness import config, app_controller
from src.automation import prober, builder

def deep_probe():
    app_name = "Notepad"
    print(f"Starting Deep Probe for {app_name}...")
    
    app_cfg = config.get_app_config(app_name)
    controller = app_controller.create_controller(app_name, app_cfg)
    
    if not controller.start_or_connect():
        print("Failed to start app")
        return

    # Increase depth and time
    crawler = prober.UIProber(max_depth=10, max_time=300)
    
    window = controller.get_window()
    if window:
        # 1. Probe
        print("Probe started...")
        crawler.probe_window(window, app_name)
        print("Probe finished.")
        
        # 2. Check for key elements
        from src.automation import storage
        cache = storage.load_cache(app_name)
        
        found_page_setup = False
        found_document = False
        
        for fp, elem in cache.get("elements", {}).items():
            name = elem.get("name", "")
            ctype = elem.get("control_type", "")
            
            if "Page Setup" in name:
                found_page_setup = True
                print(f"FOUND: Page Setup ({fp})")
            
            if ctype == "Document" or ctype == "Edit":
                 found_document = True
                 print(f"FOUND: Edtiable Area ({name} - {ctype})")

        if found_page_setup and found_document:
            print("SUCCESS: Found both Page Setup and Document.")
        else:
            print(f"PARTIAL/FAIL: PageSetup={found_page_setup}, Document={found_document}")

    # controller.terminate_app()

if __name__ == "__main__":
    deep_probe()

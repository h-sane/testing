import os
import wave
import winsound
import pyttsx3
import asyncio
import inspect
import sys
from sara.voice.service import VoiceService

async def run_diagnostic():
    print("--- Diagnostic Started ---", flush=True)
    
    try:
        service = VoiceService()
        print("VoiceService instantiated successfully.", flush=True)
    except Exception as e:
        print(f"Failed to instantiate VoiceService: {e}", flush=True)
        return

    text = "This is a root cause diagnostic sample"
    try:
        if hasattr(service, "_deepgram_synthesize_wav"):
            method = service._deepgram_synthesize_wav
            print(f"Calling _deepgram_synthesize_wav...", flush=True)
            if inspect.iscoroutinefunction(method):
                filename = await method(text)
            else:
                filename = method(text)
            print(f"Synthesized filename: {filename}", flush=True)
        else:
            print("_deepgram_synthesize_wav method not found in VoiceService", flush=True)
            return
    except Exception as e:
        print(f"Error during _deepgram_synthesize_wav: {e}", flush=True)
        return

    if filename and os.path.exists(filename):
        stats = os.stat(filename)
        print(f"File exists: True", flush=True)
        print(f"File size: {stats.st_size} bytes", flush=True)
        
        try:
            with wave.open(str(filename), "rb") as wav_file:
                params = wav_file.getparams()
                print(f"WAV params: channels={params.nchannels}, sample_width={params.sampwidth}, framerate={params.framerate}, nframes={params.nframes}, comptype={params.comptype}", flush=True)
            
            with open(filename, "rb") as f:
                header = f.read(16)
                print(f"First 16 bytes (hex): {header.hex()}", flush=True)
        except Exception as e:
            print(f"Error reading WAV properties: {e}", flush=True)
            
        try:
            print("Attempting winsound.PlaySound...", flush=True)
            winsound.PlaySound(str(filename), winsound.SND_FILENAME)
            print("winsound.PlaySound reported success.", flush=True)
        except Exception as e:
            print(f"winsound.PlaySound failed: {e}", flush=True)
    else:
        print(f"File exists: False (Path returned: {filename})", flush=True)

    try:
        print("Attempting pyttsx3 diagnostic...", flush=True)
        engine = pyttsx3.init()
        engine.setProperty("rate", 200)
        engine.say("Diagnostic check")
        engine.runAndWait()
        print("pyttsx3 diagnostic reported success.", flush=True)
    except Exception as e:
        print(f"pyttsx3 diagnostic failed: {e}", flush=True)

    print("--- Diagnostic Finished ---", flush=True)

if __name__ == "__main__":
    asyncio.run(run_diagnostic())

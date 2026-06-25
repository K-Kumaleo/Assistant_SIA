import sys
import logging
logging.basicConfig(level=logging.INFO)

print("Starting Kokoro test...")
try:
    from kokoro import KPipeline
    print("Imported KPipeline successfully.")
    pipeline = KPipeline(lang_code='a')
    print("Initialized KPipeline successfully.")
    
    # Try generating a small test
    generator = pipeline("Hello, this is a test.", voice="af_sarah", speed=1.0)
    for gs, pt, audio in generator:
        print("Generated audio chunk shape:", audio.shape)
    print("Success!")
except Exception as e:
    print("Error occurred:")
    logging.exception(e)

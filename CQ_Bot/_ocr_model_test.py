"""Manual OCR model probe — run before switching OCR_MODEL.

Usage:
    OCR_MODEL=gpt-5.6-luna python _ocr_model_test.py

Calls run_ocr() once against two public images to verify the model
accepts the current call parameters (temperature/top_p/max_tokens/
response_format). Result quality is irrelevant here — we only care
whether the API call succeeds or 400s on params.
"""
import asyncio
import sys

import core

# Inline 1x1 PNG data URIs — param probe only, avoids external URL fetch failures
IMG1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
IMG2 = IMG1


async def main():
    print(f"OCR_MODEL = {core.OCR_MODEL!r}")
    print("Calling run_ocr() with probe images ...")
    try:
        result = await core.run_ocr(IMG1, IMG2)
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        body = getattr(e, "body", None) or getattr(e, "response", None)
        if body:
            print(f"body: {body}")
        sys.exit(1)
    print("SUCCESS — model accepted current call parameters.")
    print(f"Parsed JSON keys: {list(result.keys()) if isinstance(result, dict) else result!r}")


if __name__ == "__main__":
    asyncio.run(main())

"""A local stand-in for Gnani's API, for trying the voice path without credentials or credits.

    python -m cooksmart.fake_gnani                      # serves on http://127.0.0.1:8801
    GNANI_API_KEY=anything GNANI_STT_URL=http://127.0.0.1:8801/stt/v3 \\
    GNANI_TTS_URL=http://127.0.0.1:8801/api/v1/tts/inference python -m cooksmart

It follows the request shapes in Gnani's published curl examples. It does NOT recognise speech: STT returns
whatever FAKE_GNANI_SAYS is (default "पनीर खत्म हो गया"), and TTS returns a short tone instead of Hindi speech.
"""
from __future__ import annotations

import math
import os
import struct

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="fake Gnani")


def tone(seconds: float, rate: int = 24000) -> bytes:
    n = int(seconds * rate)
    pcm = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 440 * i / rate)
                                         * min(1, i / 800, (n - i) / 800))) for i in range(n))
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


@app.post("/stt/v3")
async def stt(request: Request):
    if not request.headers.get("x-api-key-id"):
        return JSONResponse({"error": "missing X-API-Key-ID"}, status_code=401)
    body = await request.body()
    if b'name="audio_file"' not in body or b'name="language_code"' not in body:
        return JSONResponse({"error": "audio_file and language_code are required"}, status_code=422)
    return {"transcript": os.environ.get("FAKE_GNANI_SAYS", "पनीर खत्म हो गया")}


@app.post("/api/v1/tts/inference")
async def tts(request: Request):
    if not request.headers.get("x-api-key-id"):
        return JSONResponse({"error": "missing X-API-Key-ID"}, status_code=401)
    text = (await request.json()).get("text", "")
    return Response(tone(min(6.0, 0.6 + len(text) / 22)), media_type="audio/wav")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8801")))

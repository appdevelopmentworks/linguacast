"""Google Cloud TTS (Neural2) adapter — the single cloud TTS in v0.1 (FR-8).

Uses the REST endpoint with an API key so no heavy SDK is needed. Returns
LINEAR16 WAV so the same concat path as VOICEVOX applies.
"""

from __future__ import annotations

import base64

import httpx

ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
DEFAULT_VOICE = "ja-JP-Neural2-B"
# Alternate voice for the second dialogue role.
GUEST_VOICE = "ja-JP-Neural2-C"
SAMPLE_RATE = 24000


def synthesize_text(
    text: str,
    api_key: str,
    voice_name: str = DEFAULT_VOICE,
    speaking_rate: float = 1.0,
) -> bytes:
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "ja-JP", "name": voice_name},
        "audioConfig": {
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": SAMPLE_RATE,
            "speakingRate": speaking_rate,
        },
    }
    r = httpx.post(ENDPOINT, params={"key": api_key}, json=body, timeout=60.0)
    if r.status_code != 200:
        raise RuntimeError(f"Google Cloud TTS error {r.status_code}: {r.text[:300]}")
    return base64.b64decode(r.json()["audioContent"])

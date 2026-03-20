#!/bin/bash
dnme="holly-local"
./killme.sh $dnme
export QWEN_TTS_API_BASE=http://quick-piper-endpoint:8092
export OLLAMA_API_BASE=http://holly-voice:10000
docker run -d \
-p 5500:5000 \
--restart unless-stopped \
--name $dnme \
--network tts-net \
-e WHISPER_CPP_STT_ENDPOINT="$WHISPER_CPP_STT_ENDPOINT" \
-e SESSION_COOKIE_SECURE=false \
-e TTS_MODE=qwen3 \
-e QWEN3_TTS_SPEAK_QUERY="$QWEN3_TTS_SPEAK_QUERY" \
-e FRONTEND_TTS_AUTOPLAY=true \
-e QWEN_TTS_TIMEOUT_SECONDS=360 \
-e FLASK_DEBUG=1 \
-e OLLAMA_API_BASE="$OLLAMA_API_BASE" \
-e OLLAMA_MODEL="$OLLAMA_MODEL" \
-e OLLAMA_BEARER_TOKEN="$OLLAMA_BEARER_TOKEN" \
-e QWEN_TTS_API_BASE="$QWEN_TTS_API_BASE" \
-e QWEN_TTS_ENDPOINT_STYLE=quick \
-e QWEN_TTS_MODEL=qwen3-tts \
-e QWEN_TTS_VOICE=ryan \
-e QWEN_TTS_LANGUAGE=english \
holly-ux
docker logs $dnme -f

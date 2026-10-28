# Ollama local-agents handoff (network-independent once serve is up)

## Status (as of this handoff)
- Ollama binary: <home>\AppData\Local\Programs\Ollama\ollama.exe
- Models already pulled (local, no download needed):
  - qwen2.5-coder:7b-64k      4.7 GB  (good coding agent)
  - hermes3:8b                4.7 GB  (good general agent)
  - qwen2.5-coder:7b          4.7 GB
  - qwen2.5-coder:3b          1.9 GB  (light coding agent)
  - deepseek-r1:1.5b          1.1 GB  (tiny reasoning agent)
  - deepseek-r1:7b            4.7 GB
  - llama3.2:latest           2.0 GB
  - nomic-embed-text:latest   274 MB  (embedder / retrieval)
- ollama serve NOT running at handoff time.

## Start ollama serve (run once WiFi is off / no network needed)
From WSL or Git Bash prompt at the repo root:

    export OLLAMA_ORIGIN=nohost
    nohup /mnt<home>/AppData/Local/Programs/Ollama/ollama serve > /tmp/ollama-serve.log 2>&1 &
    # wait for port 11434:
    for i in $(seq 1 90); do
      code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:11434/api/tags 2>/dev/null || echo 000)
      if [ "$code" = "200" ]; then echo "OLLAMA UP after ${i}s"; break; fi
      sleep 1
    done

## Verify
    curl -s http://127.0.0.1:11434/api/tags
    ollama list   # should show the models above

## Local agent alternates (no network)
Once serve is up, switch between models with `ollama run <model>` or via the API
http://127.0.0.1:11434. 추천 교대 순서 (light ↔ heavy):
  - 빠른 응답/작은 편집: qwen2.5-coder:3b 또는 deepseek-r1:1.5b
  - 실제 코딩 작업: qwen2.5-coder:7b-64k 또는 hermes3:8b
  - 임베딩/검색: nomic-embed-text:latest

## Notes
- ollama serve는 로컬 모델만 있으면 네트워크 없이 동작. OLLAMA_ORIGIN=nohost는
  업데이트 호출 시도를 억제하려는 힌트.
- Windows 쪽 Ollama GUI가 아니라 serve 프로세스를 직접 띄우는 것이 WSL에서의
  안정적 접근.

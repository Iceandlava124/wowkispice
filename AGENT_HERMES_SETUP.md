# Hermes Agent — isolated local coding agent (Hermes Agent v0.19.0)

Runs the Hermes coding agent in an isolated Docker container with **full read/write
access to this repo**, driven by your **local Ollama** models. Offline-capable once
Docker Desktop + local Ollama are up. No cloud providers needed.

## What's wired
- Image: `hermes-app:latest` (the real agent; `hermes --version` => v0.19.0).
  Do **not** use `hermes-container:latest` (empty stub) or the `/hello` images
  (`hermes-ready`, `hermes-configured`).
- Backend: local Ollama at `http://host.docker.internal:11434` (Docker Desktop
  resolves `host.docker.internal` to the host).
- Default model: `qwen2.5-coder:7b-64k` (already pulled locally, ~4.7 GB).
- Fallback model: `hermes3:8b` (already pulled locally, ~4.7 GB).
- Workspace: repo root bind-mounted to `/app` in the container.
- Config persists in `./.hermes-home` on the host (sessions, config, state).

## Pre-flight: start local Ollama (once)
Ollama must be serving locally before the agent can talk to it.

    export OLLAMA_ORIGIN=nohost
    nohup /c/Users/gudae/AppData/Local/Programs/Ollama/ollama serve > /tmp/ollama-serve.log 2>&1 &
    # wait for port 11434:
    for i in $(seq 1 90); do
      code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:11434/api/tags 2>/dev/null || echo 000)
      if [ "$code" = "200" ]; then echo "OLLAMA UP after ${i}s"; break; fi
      sleep 1
    done
    ollama list  # should show qwen2.5-coder:7b-64k, hermes3:8b, etc.

## Start Docker Desktop (once, when daemon is down)
If `docker ps` says it can't connect to the Docker daemon, start Docker Desktop
first (this is the only manual step that needs you). Then:

    docker ps   # should list containers (possibly none) instead of a connection error

## Start the agent
From the repo root:

    docker compose -f docker-compose.hermes.yml up -d

Watch the init + first prompt:

    docker compose -f docker-compose.hermes.yml logs -f hermes-agent

The init prints the Hermes "◆ Model" section so you can confirm
`qwen2.5-coder:7b-64k` + Ollama backend are configured before the chat prompt.

## Attach to the agent
The agent runs `hermes chat` interactively. To drive it, attach a terminal:

    docker compose -f docker-compose.hermes.yml exec hermes-agent bash

Then inside the container you're already in `/app` (repo root). Start a chat:

    hermes chat

Or, if you prefer to run chat directly from the host without dropping into a shell:

    docker compose -f docker-compose.hermes.yml exec hermes-agent hermes chat

When you're done, stop the container:

    docker compose -f docker-compose.hermes.yml down

## Switch models (inside the container)
While in a `hermes chat` session, Hermes can switch providers/models. From the
container shell you can also reconfigure non-interactively:

    # Switch default to hermes3:8b (lighter, faster)
    hermes config set model "hermes3:8b"

    # Switch back to the stronger coder
    hermes config set model "qwen2.5-coder:7b-64k"

    # Confirm
    hermes config get model

## Hand the agent a task
The agent has full access to the mounted repo at `/app`. A good first task for it
is the live QEMU Phase A deliverable:

    In /app, the pinned QEMU source is at /app/../qemu-build/qemu-esp_develop_9.2.2_20260417
    (i.e. /qemu-build/... from the container's /app? No — repo is mounted at /app,
    so the QEMU tree is at /app/../../Music/qemu-build/... — tell the agent the
    absolute Windows-path mount is /app and the QEMU source is one level up from
    the repo root on the host: /c/Users/gudae/Music/qemu-build/qemu-esp_develop_9.2.2_20260417.
    Task:
      1. Apply tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch into
         that QEMU source tree.
      2. Configure and build qemu-system-xtensa (./configure
         --target-list=xtensa-softmmu --enable-trace-backends=nop && ninja).
      3. Boot the real firmware at
         /app/firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin
         on -M esp32 and confirm app_main() is reached AND at least one control-loop
         sample completes past adc_oneshot_read() without the interrupt-wdt panic.
      4. Report the qemu-system-xtensa path and the boot evidence.

Note: the container does NOT have the Xtensa cross toolchain or the QEMU build
deps (gcc for xtensa, glib, pixman, libgcrypt, flex, bison, meson, ninja) unless
they're installed in the image. If the agent hits "meson not found" / "xtensa
compiler missing", that's expected — either install the toolchain inside the
container or run the QEMU compile on the WSL host side and let the agent drive the
patch + boot verification.

## Restart / reset
- Restart without losing state: `docker compose -f docker-compose.hermes.yml restart`
- Reset Hermes config to defaults: inside the container, `hermes setup --reset`,
  then reconfigure. Or delete `./.hermes-home` on the host and restart.
- Start fresh with a clean task: `docker compose -f docker-compose.hermes.yml down
  -v` removes the named volume only if you convert .hermes-home to a named volume —
  for now, just remove `rm -rf .hermes-home` on the host if you want a clean slate.

## Troubleshooting
- "Config key not set: providers.openai-compat.base_url" — that key doesn't exist in
  v0.19.0. Use `providers.ollama.base_url` (set in the init) or
  `providers.openai.base_url` with the `/v1` compat path. Don't use the compat key.
- Agent can't reach Ollama: confirm `OLLAMA_HOST=http://host.docker.internal:11434`
  and that Docker Desktop is running. Test from a throwaway container:
    docker run --rm --add-host=host.docker.internal:host-gateway alpine/curl -s
    http://host.docker.internal:11434/api/tags
  Should return 200 with your model list.
- Model not found: confirm it's pulled with `ollama list` on the host.
- `hermes model` says "requires an interactive terminal" — that subcommand is
  interactive-only. Use `hermes config set model <name>` + `hermes config get model`
  to switch non-interactively, or just tell the agent in chat to switch.

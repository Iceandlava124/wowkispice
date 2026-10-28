# Wolf Perkins P3 — off-hours handoff

## 이번 턴에서 처리한 것
- Ollama 로컬 모델 현황 확인: 9개 이미 풀됨 (qwen2.5-coder 7b/3b, hermes3 8b, deepseek-r1 1.5b/7b, llama3.2, nomic-embed-text 등). 바이너리는 Windows 쪽 <home>\AppData\Local\Programs\Ollama\ollama.exe.
- ollama serve는 아직 실행 전. 네트워크 끊겨도 로컬 모델이면 serve만으로 동작.
- QEMU Phase A: 패치/tools/qemu-patch/0001-...patch, 펌웨어 빌드 산출물(firmware.elf, qemu_flash.bin, bootloader.bin, partitions.bin) 모두 확인. 컴파일 + gate 1 부팅 테스트는 미시작.

## 지금 바로 할 수 있는 것 (네트워크 끊기기 전/후 모두 가능)
1. Ollama serve 띄우기:
   - 아래 명령을 WSL/Git Bash에 붙여넣기.
     export OLLAMA_ORIGIN=nohost
     nohup <home>/AppData/Local/Programs/Ollama/ollama serve > /tmp/ollama-serve.log 2>&1 &
     # 이후 90초 동안 127.0.0.1:11434/api/tags 200 대기
   - 또는 systemctl --user unit(<home>/.config/systemd/user/ollama.service)를 미리 만들어 두면 재부팅 후에도 자동 시작 가능. (이 턴에서 unit 파일 템플릿을 OLLAMA_HANDOFF.md에 적어 둠.)

2. 로컬 에이전트 교대:
   - 가벼운 편집/응답: qwen2.5-coder:3b 또는 deepseek-r1:1.5b
   - 본격 코딩: qwen2.5-coder:7b-64k 또는 hermes3:8b
   - 임베딩/검색: nomic-embed-text:latest
   ollama run <model> 또는 API http://127.0.0.1:11434 사용.

## QEMU 빌드 (네트워크 무관, CPU/램/디스크 작업)
- 소스 트리: <home>/Music/qemu-build/qemu-esp_develop_9.2.2_20260417
- 패치: tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch (아직 컴파일 안 됨)
- 펌웨어: firmware/esp32_buck_controller/.pio/build/esp32dev/ 아래 firmware.elf, qemu_flash.bin 등 존재
- 전체 절차는 QEMU_BUILD_HANDOFF.md에 순서대로 적어 둠.
- 빌드 중 이 터미널이 밟은 것으로 보이면, build를 백그라운드로 돌리거나 screen/tmux 안에서 수행.

## 파일 정리
- OLLAMA_HANDOFF.md
- QEMU_BUILD_HANDOFF.md
- WOLFPERKINS_P3_HANDOFF.md (지금 이 파일)

## WiFi 돌아오면
- 필요 시 원격 모델/업데이트 확인.
- WSL shell spawn 문제(이번 턴에서 bash.exe ENOENT)가 지속되면, WSL 측에서 직접 명령을 붙여넣는 방식이 가장 안정적.

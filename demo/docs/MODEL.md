# 실제 로컬 백엔드

공식 [Qwen3-0.6B-GGUF 카드](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF)를 확인했다. 범용 지시 모델을 JSON choice 생성에 이용하며, 전용 결정모델이나 실재 소비자 행동을 검증한 모델로 설명하지 않는다. 작은 모델의 구조 준수와 반응 품질은 별개다.

| 항목 | 고정한 값 |
| --- | --- |
| 공식 모델 | Qwen/Qwen3-0.6B-GGUF |
| revision | `23749fefcc72300e3a2ad315e1317431b06b590a` |
| 파일 | `Qwen3-0.6B-Q8_0.gguf` |
| 크기 | 639,446,688 bytes |
| SHA-256 | `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` |
| 모델 조건 | Apache-2.0, [공식 LICENSE](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/blob/main/LICENSE) |
| 공식 런타임 | [ggml-org/llama.cpp b11429](https://github.com/ggml-org/llama.cpp/releases/tag/b11429) |
| 배포물 | `llama-b11429-bin-macos-arm64.tar.gz`, 11,971,406 bytes |
| archive SHA-256 | `740288ec6887be94280a5dfa25b5e23a78285cab104519e6c7e218904ee82459` |
| 런타임 조건 | [MIT](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE) |

두 다운로드의 실제 SHA-256이 공식 API 메타데이터와 일치함을 확인했다. 파일은 `models/`, `tools/llama/` 내부에 있고 Git에서는 제외한다. 글로벌 설치·보안 설정·키 발급을 하지 않았다. 디스크 약 48GB 여유를 확인한 뒤 확장 요청에 따라 Qwen 약0.64GB와 Julia 공식 파일 약0.61GB를 준비했다. 현재 CPU 4 threads, context 4096, GPU layers 0, loopback `127.0.0.1:8081`이며 CORS를 UI 출처로 제한한다.

```sh
sh tools/start-model.sh
```

프로젝트를 복사할 때 ignored 모델/바이너리는 따라가지 않는다. 다시 준비하려면 위의 공식 고정 revision/asset에서만 받고 SHA-256을 확인한다. macOS ARM64용 개발 장비 런타임이지 모든 PC 배포 OS를 지원하는 설치본은 아니다.

macOS ARM64에서 선택적으로 준비할 때만 다음 명령을 수행한다. 별도 네트워크 다운로드이며 기본 Mock에는 필요 없다. 기존 파일이 없는 새 checkout 기준이다.

```sh
(
set -e
mkdir -p models tools/downloads tools/llama
test ! -e models/Qwen3-0.6B-Q8_0.gguf
test ! -e tools/downloads/llama-b11429-bin-macos-arm64.tar.gz
curl --fail --location 'https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/23749fefcc72300e3a2ad315e1317431b06b590a/Qwen3-0.6B-Q8_0.gguf' --output models/Qwen3-0.6B-Q8_0.gguf
curl --fail --location 'https://github.com/ggml-org/llama.cpp/releases/download/b11429/llama-b11429-bin-macos-arm64.tar.gz' --output tools/downloads/llama-b11429-bin-macos-arm64.tar.gz
printf '%s\n' '9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031  models/Qwen3-0.6B-Q8_0.gguf' '740288ec6887be94280a5dfa25b5e23a78285cab104519e6c7e218904ee82459  tools/downloads/llama-b11429-bin-macos-arm64.tar.gz' | shasum -a 256 -c -
tar -xzf tools/downloads/llama-b11429-bin-macos-arm64.tar.gz -C tools/llama
sh tools/start-model.sh
)
```

체크섬 검사에 실패하면 추출·실행 단계로 진행하지 않는다. 기존 파일이 있는 장비에서는 위 다운로드 명령으로 덮어쓰지 말고 보존된 파일을 먼저 검사한다.

`LocalLLMBackend`는 profile·상품·질문·명시 가정을 JSON 입력으로 보내고 응답 schema·선택·상태·근거 경로를 검사한다. thinking을 끄고 점수를 확률로 받지 않는다. 예산 미제공 구매와 사건 미제공 이탈은 unknown gate다. 서버 장애·invalid JSON·응답 잘림은 실패로 남으며 재개할 수 있다. 사유의 의미적 정확성은 아직 검증되지 않았다.

## 전용 유한 선택 모델 Julia-1

공식 [SupersonicLabs/Julia-1](https://huggingface.co/SupersonicLabs/Julia-1) 카드와 소스를 확인하고 CPU Torch 경로로 실행했다. `state + question + 2–20 options`의 유한 선택 모델이며 사유를 생성하는 범용 대화 모델과 구분한다. 공개 모델의 범용 벤치마크는 이 상품 반응 과제의 정확도 근거로 사용하지 않는다.

| 항목 | 실제 준비한 값 |
| --- | --- |
| 모델 revision | `a85b127321d580d65176c89ced8273f305745d85` |
| 공개 조건 | ungated, Apache-2.0 |
| model.safetensors | 577,189,056 bytes |
| weight SHA-256 | `df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72` |
| 필수 소스·tokenizer 포함 | 25 files, 611,646,497 bytes |
| 격리 환경 | `.venv-julia`, 이미 있던 Python 3.13.14로 생성 |
| 실제 의존성 | torch 2.14.1, transformers 5.0.0, numpy 2.5.3, safetensors 0.8.0 |
| 추론 | CPU 4 threads, strict encoding, max length8192/head512 |
| 선택 서비스 | loopback8082, 요청 최대32개·1MB, ID별 결과/오류 |

`verification/julia-download.json`에 파일별 SHA-256, `julia-environment.txt`에 실제 환경을 기록했다. native/Bend 빌드·컴파일·CUDA·Metal·원격 custom code는 활성화하지 않았다. 서비스는 검증된 프로젝트 내 모델 소스를 명시적으로 import하며 가상환경의 editable .pth 동작에 의존하지 않는다. 모델 로딩은 로컬 경로와 offline 플래그를 사용한다.

```sh
sh tools/start-julia.sh
```

현재 프로젝트는 준비되어 있다. 다른 Mac에서 Julia를 선택적으로 다시 준비하는 다음 단계는 **별도 네트워크 다운로드와 격리 환경 설치**다. 앱/Mock에는 필요 없다. 실행 전 리소스와 설치 범위를 확인한다.

```sh
python3 tools/prepare_julia.py
uv venv .venv-julia --python 3.13 --no-python-downloads
uv pip install --python .venv-julia/bin/python -r verification/julia-requirements.txt
sh tools/start-julia.sh
```

다운로더는 공식 고정 revision·공개 라이선스·파일 크기·weight SHA를 검사한다. 3.13이 장비에 없으면 `--no-python-downloads` 단계가 실패하므로 별도 Python 준비가 필요하다. Qwen 모델과 macOS ARM64 런타임은 위의 고정 official artifact/checksum으로 준비해야 한다. 파일 복사나 Git checkout에는 ignored 모델·가상환경·runtime이 포함되지 않는다. 배포 OS 호환성을 보장하지 않는다.

Julia의 adapter는 점수/softmax를 구매 확률로 저장하지 않는다. `finite_choice_selection`은 모델 선택이었다는 코드이고 입력 참조는 `supplied_input_only`다. 알려진 원인/설명이라고 표시하지 않는다. 구매 상한 없는 구매, 사건 없는 이탈, 다른 통화/정기결제의 상한 환산은 unknown gate다.

앱은 실제 `decide_batch`를 사용해 ID를 매핑하고, 오류 항목만 재시도한다. 서비스는 무손실 인코딩 실패를 항목 오류로 반환하고 다른 항목을 계속 처리한다. padded token 작업량 cap을 넘어서는 묶음은 추가로 나누며 한 행이 넘으면 거부한다. 이 cap은 측정된 RAM 보장이 아니다.

측정·반대 필요/옵션순서 비교는 [VERIFICATION.md](VERIFICATION.md)에 있다. 예산상한 위반 및 순서 민감성이 남았다. 전용 구조나 높은 처리량만으로 구매 반응이 올바르다고 주장하지 않는다. 외부 API adapter는 미구성이다.

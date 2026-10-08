# 현재 모델 정책과 과거 보관 기록

이 색인은 로컬 작업 이력을 설명한다. 아래의 `build/`·`verification/`·이동 영수증은 Git에 포함하지 않는다.

## 2026-10-08 현재 정책

사용자가 이전 모델 가중치와 로컬 모델 캐시 삭제를 요청했다. 0.8.1·빌드 9는 현재 Clef 가중치만 포함한다.
20개 경로의 이전 Qwen·후보·중복 준비 가중치·이전 생성 앱/ZIP·외부 Qwen/Julia 가중치와 Julia tokenizer를 삭제했다. 이전 서버 4255/4256을 정상 종료했다.
남은 가중치는 작업 자원과 현재 앱 안의 Clef 두 사본이다. 실행기·인물 데이터·모든 DB·원시 호출·실패 증거·명세·라이선스는 유지한다.
이전 Qwen 결과의 열람·내보내기·복제는 가능하지만 재개·재실행은 중단한다. 제거한 모델을 자동 다운로드하거나 다른 모델로 대체하지 않는다.
기존 Clef 3단계·8문항·10문항은 원래 계약으로 재개한다.

새 앱은 기존 경로의 앱을 교체했으며 6,688,901,403바이트(약 6.69GB)다. 최종 서명·이동 후 import·집중 검사 3개와 이전 결과 53명/159행 열람·HTML 내보내기를 확인했다. 모델은 실행하지 않았다.
Hugging Face·ModelScope·llama.cpp 표준 캐시에 모델 가중치가 없었고 무관한 작은 로그·잠금 파일은 그대로 뒀다.
삭제 파일의 논리 크기 합계는 77,980,905,902바이트다. 확인한 여유 공간 증가는 23,234,174,976바이트(약 23.23GB)이며 두 값을 구분한다.
최종 범위와 검증은 `../verification/current-model-only.json` (정리 영수증, 로컬 기록)에 있다.
아래는 가중치를 보관했던 2026-10-07의 이동 기록이다. 현재 파일의 가용성이나 영구 보존 약속을 뜻하지 않는다.
삭제된 가중치는 이 보관 위치에서 복원할 수 없다. 당시 복원 안내도 현재 삭제 정책을 변경하지 않는다.

## 2026-10-07 이동 설명 · 과거

2026-10-07: 현재 제품 작업에서 사용하지 않는 모델 후보 staging과 일회성 진단 자료를 이곳으로 옮겼습니다. 파일은 삭제하지 않았습니다. 같은 파일시스템에서 이름만 바꾸었으며 파일 수·크기·심볼릭 링크 대상을 확인했습니다. 이 이동은 저장 공간을 줄이지 않습니다.

## 2026-10-07 이동 목록 · 과거

| 이전 경로 | 보관 경로 |
|---|---|
| `build/model-candidate` | `2026-10-07-model-review/build/model-candidate` (`archive/2026-10-07-model-review/build/model-candidate`, 로컬 기록) |
| `build/model-candidate35` | `2026-10-07-model-review/build/model-candidate35` (`archive/2026-10-07-model-review/build/model-candidate35`, 로컬 기록) |
| `build/clef-resources` | `2026-10-07-model-review/build/clef-resources` (`archive/2026-10-07-model-review/build/clef-resources`, 로컬 기록) |
| `verification/candidate-quality.json` | `2026-10-07-model-review/verification/candidate-quality.json` (`archive/2026-10-07-model-review/verification/candidate-quality.json`, 로컬 기록) |
| `verification/candidate35-quality.json` | `2026-10-07-model-review/verification/candidate35-quality.json` (`archive/2026-10-07-model-review/verification/candidate35-quality.json`, 로컬 기록) |
| `verification/candidate35-final-quality.json` | `2026-10-07-model-review/verification/candidate35-final-quality.json` (`archive/2026-10-07-model-review/verification/candidate35-final-quality.json`, 로컬 기록) |
| `verification/korean-model-probe.json` | `2026-10-07-model-review/verification/korean-model-probe.json` (`archive/2026-10-07-model-review/verification/korean-model-probe.json`, 로컬 기록) |
| `verification/download_model_candidate.py` | `2026-10-07-model-review/verification/download_model_candidate.py` (`archive/2026-10-07-model-review/verification/download_model_candidate.py`, 로컬 기록) |
| `verification/download_model_candidate35.py` | `2026-10-07-model-review/verification/download_model_candidate35.py` (`archive/2026-10-07-model-review/verification/download_model_candidate35.py`, 로컬 기록) |
| `verification/probe_grounded_model.py` | `2026-10-07-model-review/verification/probe_grounded_model.py` (`archive/2026-10-07-model-review/verification/probe_grounded_model.py`, 로컬 기록) |
| `verification/probe_korean_model.py` | `2026-10-07-model-review/verification/probe_korean_model.py` (`archive/2026-10-07-model-review/verification/probe_korean_model.py`, 로컬 기록) |
| `verification/probe_decision_factors.py` | `2026-10-07-model-review/verification/probe_decision_factors.py` (`archive/2026-10-07-model-review/verification/probe_decision_factors.py`, 로컬 기록) |

## 당시 남긴 자료 · 과거

- `assets/`는 그대로 둡니다. 현재 Clef 모델·실행기와 이전 Qwen 호환 모델은 저장된 실험을 원래 모델로 재개할 때 필요합니다. 정리 시 확인한 Qwen3.5 원본 자원 누락은 빌드 담당자에게 전달했습니다. 보존한 0.7 출시 앱에는 해당 파일이 있습니다.
- 기존 출시 앱·ZIP과 0.7 `build/releases/survey-flow/Persona Lab.app`을 유지합니다.
- 실제 사용자 저장소와 QA 데이터베이스·실험 홈은 건드리지 않았습니다.
- Clef의 실패 사례·반복성·원시 호출, 출시 검증 영수증과 `verification/diagnostics/`를 유지합니다. 과거 실패 근거를 지우지 않습니다.
- 현재 문서·참조 코드·공용 검사 도구가 사용하는 `.research/`와 `docs/`는 유지합니다.

## 당시 경로와 복원 안내 · 과거

이전 검증 영수증 안의 경로와 해시는 검증 당시의 기록입니다. 그 기록은 수정하지 않았습니다. 예를 들어 `verification/clef-resources.json`의 `build/clef-resources/…` 파일은 위 표의 보관 경로에서 찾습니다.

보관한 진단 스크립트는 당시 모델·입력·출력 경로를 사용합니다. 현재 제품 검사로 실행하지 마십시오. 과거 실행을 재현해야 하면 필요한 디렉터리와 스크립트를 위 표의 이전 경로로 함께 복원한 뒤 입력과 버전을 확인합니다. 이전 경로가 이미 생겼다면 덮어쓰지 마십시오.

`2026-10-07-model-review/cleanup.json` (이동 영수증, 로컬 기록)에 파일 수와 크기를 기록했습니다.

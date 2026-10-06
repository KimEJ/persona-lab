# Persona Lab

상품·가격·기능·소개 문구를 같은 합성 인물들에게 제시하고 반응을 비교하는 **실행 가능한 1차 로컬 데모**입니다. `persona-lab`은 변경 가능한 작업명입니다. 최종 PC 설치 패키지와 배포 OS는 미정이며 Mac은 개발 장비입니다.

새 checkout에는 소스·문서·테스트와 자체4명 fixture만 있습니다. 모델·NVIDIA 인물 원문·실행/검증 산출물은 포함하지 않습니다. [새 장비 실행·선택 재설치](docs/REINSTALL.md)를 먼저 확인하세요. 아래의 원본125,000명과 실제 모델 측정은 개발 Mac의 별도 로컬 준비·검증 기록입니다.

데이터 목록·원문·출처·결측, 필터, 상품 A/B 입력, 7개 판단 영역, 배치 진행률·중단·재개, 비교·사유·판단 불가, JSON/CSV/Markdown 보고서·재실행 명세를 연결했습니다. 결과는 합성 패널의 선택 비율이며 실제 구매 확률이나 매출 예측이 아닙니다.

## 한 번에 시작·종료

이 프로젝트 폴더에서 Python 3.12 이상으로 실행합니다. 모델을 자동 다운로드하거나 설치하지 않습니다.

```sh
sh tools/demo.sh start
sh tools/demo.sh status
sh tools/demo.sh stop
```

시작은 준비된 Qwen·Julia와 앱을 loopback에서 실행하고, 종료는 이 실행기가 만든 경로 확인된 프로세스만 종료합니다. 주소는 `http://127.0.0.1:8787`이며 Codex IAB에서 여세요. 모델 파일/격리 환경이 없으면 안내를 출력하고 Mock으로 앱을 실행합니다. 다른 프로세스가 8081·8082·8787을 사용하면 포트 충돌 안내와 함께 중단합니다. 해당 프로세스를 임의로 종료하지 않습니다. 로그와 PID 기록은 `runs/services/`에 있습니다.

앱만 필요하면 `sh tools/start-demo.sh`, 개별 모델은 `sh tools/start-model.sh`와 `sh tools/start-julia.sh`로 실행할 수 있습니다. 개별 실행과 통합 실행을 동시에 시작하면 포트가 충돌합니다.

이 Mac에는 공식 Qwen3-0.6B Q8_0/llama.cpp와 Julia-1/Torch CPU 경로를 준비했습니다. Qwen은 범용 지시 모델, Julia는 유한 선택지 전용 결정모델입니다. **두 모델 모두 실제 구매 행동 정확도를 입증하지 않았습니다.** [설치 범위·체크섬·재현 조건](docs/MODEL.md)을 참고하세요. 앱/Mock은 표준 라이브러리이며, 원본 Parquet 선택 의존성은 `.venv-data`, Julia는 `.venv-julia`, DOM 테스트 도구는 `node_modules`에 격리했습니다.

## 데모 사용 순서

1. NVIDIA 원본 첫 Parquet shard 125,000명, 공개 소형 Viewer 53명 또는 자체 합성 fixture 4명을 선택합니다. 여섯 서술은 UUID 하나의 관점이며 Viewer53명은 원본 첫53명과 겹칩니다. 별도 팩을 독립 인구로 합산하지 않습니다.
2. 지역·나이·프로필 검색으로 패널을 고르고 원문과 결측을 확인합니다. 화면의 20행은 페이지 크기이며 실험 인원 상한이 아닙니다.
3. A/B의 가격·기능·소개를 바꿉니다. 일본어 입력을 사용한 실제 로컬 추론 경로를 검증했습니다.
4. Mock·로컬 Qwen·전용 Julia를 선택합니다. 예산은 일시불 JPY 구매의 절대 상한이라는 명시 가정으로 입력합니다. 모델의 상한 위반 선택은 강제 보정하지 않고 원결과와 경고를 유지합니다. 예산 미제공의 구매 판단, 사건 미제공의 이탈 판단은 정보 부족으로 남깁니다.
5. 실행 후 중단하거나 저장된 실험에서 재개합니다. 중단은 현재 모델 요청이 끝난 뒤 처리됩니다. 입력·출처·실험·모델이 바뀐 체크포인트는 재사용하지 않습니다.
6. 같은 패널의 선택 변화·예산 충돌·오류와 사유 코드를 비교하고, ‘조건 검토’에서 원문·상품·질문·선택지·가정을 확인한 뒤 보고서를 내보냅니다. 일부 완료 결과는 처리 순서에 따른 편향과 분모를 표시합니다. 오류는 unknown과 별도로 세며, 첫 실행 완료 뒤 오류 항목만 명시적으로 재시도할 수 있습니다. Julia의 입력 참조는 투입 사실을 표시할 뿐 모델이 생성한 사유가 아닙니다.

자체 fixture의 명시적 예산을 적용하면 A 2,000 JPY → B 900 JPY에서 한 명의 선택이 거절 → 구매로 바뀝니다. 이는 동작 검증용 규칙입니다. NVIDIA 원본에 그 예산이나 구매 성향이 있다는 뜻이 아닙니다.

## 데이터 가져오기

화면의 ‘공개 소형 샘플 가져오기’ 또는 다음 명령으로 고정된 공식 Viewer 응답을 가져옵니다. 응답당 최대 1MB, 잘림·라이선스 변경·중복 UUID는 거부하며 새 스냅샷 폴더 항목으로 보존합니다. 임의 URL과 파일 업로드는 지원하지 않습니다.

```sh
PYTHONPATH=src python3 -m persona_lab fetch-sample
```

원본 Parquet 입력도 연결했습니다. 화면의 ‘원본 Parquet 가져오기 · 진행/취소/재개’에서 선택한 공식 shard 또는 `data/inbox`의 명시적 로컬 파일을 처리합니다. 현재 첫 shard216MB/125,000행을 검증했고 row-group cursor·UUID index·원문 SHA·취소/재개·전체 필터를 유지합니다. [설치·로컬 출처 파일·CLI·복구 계약](docs/PARQUET.md)을 참고하세요.

전체 100만 행/약 1.73GB 다운로드는 하지 않았습니다. Viewer와 선택 shard는 무작위·대표 표본이 아닙니다. [출처·귀속·실제 22열 목록](docs/DATA_SOURCES.md), [실행 계약](docs/CONTRACTS.md), [구현 계획](docs/PLAN.md)을 확인하세요.

## CLI와 테스트

```sh
PYTHONPATH=src python3 -m persona_lab run --store runs/contract-demo-v3.sqlite --max-batches 1
PYTHONPATH=src python3 -m persona_lab run --store runs/contract-demo-v3.sqlite
PYTHONPATH=src python3 -m persona_lab export --store runs/contract-demo-v3.sqlite --format md --output runs/report.md
PYTHONPATH=src .venv-data/bin/python -m unittest discover -s tests -v
node --check web/app.js
```

개발 Mac의 Python/HTTP50개와 기존 데모 DOM/API30개, 원본 Parquet DOM/API12개와 Parquet→실제Julia 접점11개를 통과했습니다. 새 checkout은 선택 PyArrow/공개샘플 준비 전12개가 skip되며38개를 실행합니다. PyArrow만 준비하면48개·공개샘플2개skip, 둘 다 준비하면50개를 실행합니다.

HTTP 테스트는 임시 loopback 서버를 사용합니다. 실행 환경이 소켓을 제한하면 승인된 로컬 실행 경로가 필요합니다. Node 26의 개발 테스트 도구 jsdom 30.1.2는 프로젝트 `node_modules`에만 설치했습니다. 앱 실행에는 필요 없습니다.

```sh
npm ci --ignore-scripts --no-audit --no-fund
PERSONA_LAB_TEST_JULIA=1 npm run test:dom
PYTHONPATH=src python3 tools/smoke_local.py
PYTHONPATH=src python3 tools/smoke_http_batch.py
PYTHONPATH=src python3 tools/check_persona_sensitivity.py
```

DOM 테스트는 실행 중인 데모 서버를 사용합니다. 실제 로컬 smoke는 실행 중인 모델 서버와 선택 공개샘플을 사용합니다. 로컬 전용 `STATUS.json`과 [검증 기록](docs/VERIFICATION.md)에서 통과·실패·미실행을 구분합니다. 상세 검증 산출물은 Git에 포함하지 않습니다. IAB가 이 위임 환경에서 제공되지 않아 실제 브라우저 시각 검증은 별도 미검증 항목입니다.

## 저장된 실험 복구

프로세스를 종료하거나 장비에서 실행이 끊겨도 `runs/<실험 ID>/`의 명세·SQLite를 삭제하지 마세요. 다시 `sh tools/demo.sh start`로 시작하고 화면의 저장된 실험을 선택한 뒤 ‘체크포인트에서 재개’를 누릅니다. 미완료 실행은 ‘이전 실행이 중단됨’으로 표시됩니다. 반환받아 커밋한 배치는 재사용하며 진행 중이던 미저장 호출은 다시 수행할 수 있습니다. 입력·백엔드·engine 버전이 다르면 재개를 거부합니다. 기존 버전의 완료 보고서는 읽을 수 있습니다.

## 실측과 한계

공개 Viewer 53명 × 2안 × 7질문, 일시불 JPY 상한·반복 오류 사건을 명시한 Julia CPU 배치 경로에서 742건/24요청, 연속 실행 42.51초(약 17.46 작업/초)를 측정했습니다. 64건에서 중단·재개한 결과가 연속 실행과 모두 일치했습니다. **구조 유효 742건·백엔드 오류 0건이지만 예산상한 위반 구매 11건이 남았습니다.** 모델 품질 성공으로 해석하지 않습니다. 자체 반대 필요 입력 및 선택지 순서 교체에서도 순서 민감성을 관찰했습니다.

이 수치는 해당 53명·입력 길이·7질문·2조건·CPU·warm 모델 한 workload입니다. 백만 명의 처리 시간이나 정확도를 추정하지 않았습니다. 입력 길이·질문/선택지 수·배치/하드웨어·저장 비용이 달라지면 별도 실측이 필요합니다. [측정과 미검증 항목](docs/VERIFICATION.md)을 확인하세요.

## 구조와 다음 단계

`src/persona_lab`의 데이터 어댑터·계약·결정 백엔드·실행기·보고서·HTTP UI를 분리했습니다. `data/packs`는 귀속을 포함한 메타데이터와 원문 JSONL, `examples`는 재실행 명세, `tests`는 회귀, `verification`은 증거, `runs`는 영속 체크포인트입니다.

현재는 단일 장비·단일 실행 writer와 로컬 JSONL/SQLite입니다. Parquet 입력은 row-group cursor로 재개하고 catalog에서 전체 패널을 필터링합니다. 전체 작업 조합을 메모리에 펼치지 않지만, 일반 실험 시작 검사와 재개 시 JSONL 입력을 다시 스캔합니다. 다음은 결과 분할 저장·실험 cursor 최적화, 전용 결정모델 입력/순서 민감도 평가 확장, 상태 유지 여정, OS별 패키지입니다. 대규모 실측, 행동 정확도와 배포 라이선스 확정은 후속 작업입니다. 사용자 승인으로 `KimEJ/persona-lab` 비공개 저장소에 소스를 보존합니다. 공개 배포·사용자 키·전역 설정은 변경하지 않습니다.

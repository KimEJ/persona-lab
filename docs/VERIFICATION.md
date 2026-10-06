# 검증 기록

완료 상태는 `STATUS.json`, 실측은 `verification/`의 timestamp와 원결과를 기준으로 한다. 모든 자동 기록의 시간은 UTC ISO 형식이다. 수기 진행 메시지의 KST 환산 오류는 증거 파일에 영향을 주지 않았다. ‘구조 유효’는 계약·형식 통과이며 소비자 행동 정확도를 뜻하지 않는다.

`STATUS.json`과 아래의 상세 산출물은 개발 Mac에 보존하는 로컬 기록이며 비공개 소스 저장소에도 업로드하지 않는다. 소스 checkout의 재검증·선택 설치 절차는 [REINSTALL.md](REINSTALL.md)에 있다. 선택 데이터 없는 검사는 skip을 명시하며 원본 준비 상태를 성공으로 가장하지 않는다.

## 현재 완료된 검사

- Python/HTTP 회귀 **50개 통과, 0실패** (`.venv-data` 포함). 원문 UUID·22필드·여섯 관점·결측·fixture 출처, 인원 제한 없는 스트리밍, ID 기반 배치, checkpoint, 취소/재개, fingerprint, 오류 항목 재시도, import 검증, CSV 수식 escape, Host/Origin/path, 원조건 상세 보기/원문 변경 거부를 포함한다.
- 10,000명 가짜 fixture, 140,000 예정 작업에서 16건만 처리한 뒤 24건까지 재개했다. Python tracemalloc peak <12MiB 기준을 통과했다. 전체 RSS나 백만 명 실행 성능 검증은 아니다.
- 실제 일본어 NVIDIA Viewer 한 인물의 Qwen 14건, 10회 모델 HTTP 요청, 오류0, unknown10. 나머지4건은 구매 상한/사용 후 사건 미제공 gate다. engine0.3.0/prompt-v3, 약7.21초. `local-inference.json`·`local-japanese-report.json`·`mock-japanese-report.json`에 기록했다.
- Julia 실제 CPU 서비스에서 정상 이웃1건·과도한 입력1건·선택지 오류1건을 같은 요청에 넣었다. 정상 행을 추론하고 나머지는 각 ID의 오류로 남겼다. 입력을 몰래 자르지 않았다. `julia-item-errors.json`.
- CLI fixture56건의 중단·재개, 실제 앱 mock/Julia·저장 보고서·내보내기·재실행 명세·원조건 검토의 DOM/API 연결 검사를 실행했다. 최신 **30개 검사 그룹**은 `dom-api.json` 기준이다. 실제 Julia A 입력 오류28건/B 정상28건의 UI 표시와 오류만 재시도, 정상 사례 불변도 확인했다. 지속 오류28건을 unknown이나 성공으로 바꾸지 않았다. jsdom은 렌더링이나 OS 브라우저를 제어하지 않는다.

## 원본 Parquet 입력·복구

`parquet-source-download.json`: 공식 첫shard216,054,745bytes만 선택했다.2MiB에서 다운로드를 취소하고 HTTP206 Range로 재개해 고정revision/LFS SHA와 일치했다.125,000행·22필드·5row groups다. 전체8shard를 받지 않았다.

`parquet-dom-api.json`:1280행 저장 후 앱 재시작 상태에서 UI재개·14,336행UI취소·최종125,000행완료·전체UUID필터·페이징·귀속12검사를 통과했다. `parquet-original-import.json`: 고유UUID125,000개, 저장1280행순서불변, 처음53행 raw가 관측Viewer와 같음을 대조했다. 보고된 끝페이지 약0.003초/UUID필터 약0.725초는 해당 catalog 요청의 한 측정이며 모델 처리량이 아니다.

`parquet-large-fixture.json`: 자체 명시적100,000행/그룹1024/배치256에서768행중단·재개와 별도연속실행의 최종SHA가 일치했다. Python tracemalloc peak2.85MiB, process high-waterRSS125.30MiB; 진행시 표본Arrow allocation 최대0.65MiB. 해당 fixture의32/256MiB 검사 기준을 통과한 결과이며 임의Parquet/native allocation의 보장은 아니다. 모델 추론을 하지 않았다.

추가 회귀는 원본/출력변조·UUID중복rollback·출력후커밋전crash·명세변경·완료팩변조·라이선스/revision변경·Range무시거부·local source sidecar·실제HTTP로컬팩 A/B·원조건연결이다. 첫 추가HTTP 검사에서는 출처가 persona 안에 있다고 잘못 가정한 assertion1오류를 top-level source 계약으로 수정한 뒤50개를 통과했다. [Parquet 운영/한도](PARQUET.md)를 참고한다.

전체원본125,000명 모델실험은 실행하지 않았다. 다음의53명 모델 실측과 위의원본입력 검증을 별도 증거로 유지한다.

원본 팩의 한UUID만 Mock으로14개 판단→SQLite저장→원문 상세→JSON/CSV/Markdown내보내기를 실제 앱 API에서 확인했다. CC BY4.0/귀속/raw가 유지됐으며 모델요청0회다. 해당 연결 증거는 `parquet-original-import.json`의 `one_person_mock_connected_path`다.

## 원본 목록과 실제 Julia의 접점

`parquet-julia-dom-api.json`:125,000명원본목록에서UUID한명필터→실제Julia→원문/가정/상품/질문상세→A/B조건비교→JSON/CSV/MD귀속을11개DOM/API검사로 확인했다. 성공한최종실험은모델요청1회·14행·구조유효14건·오류0건·7영역×2조건·구매쌍1개다. unknown8건, 구매unknown→unknown, 예산충돌0건을 그대로 보존했다. 전체125,000명처리량이나 행동정확도의 검증이 아니다.

검증스크립트 첫 실행의14개판단도 저장됐지만 검사코드가 `/api/personas`에 source가 있다고 가정해실패했다. 실제 `/api/packs`의 출처를 대조하고 UI비교의 A/B label을 확인하도록 수정해14건만 재실행했다. 두 작은실험/28건을 수행했고 앱코드 변경·대규모추가추론은 없었다. 첫실험ID와 수정을 `parquet-julia-verifier-repair.json`에 기록했다. 마지막보고서3종·원문상세를 보존했다. 반복명령은 `node tools/check_parquet_julia_dom.cjs`이며 새 작은실험을 만든다.

## 실제 앱 Julia 배치·복구

`http-julia-batch-resume.json`과 `julia-public53-batch-report.json/.csv/.md`가 증거다.

| 조건 | 실측 |
| --- | --- |
| 패널 | 공개 Viewer53명, 대표/무작위 표본 아님 |
| 실험 | 2상품 × 7질문 × 1회 =742작업 |
| 입력 | 일본어, state JSON1144–1460자, question47–60자, choices3–4개 |
| 추론 profile | 중심 persona 및 구조/인구 속성; 전문 관점5개는 원문에 보존하되 prompt에서 제외 |
| 가정 | 일시불JPY 절대 구매상한1500·반복 오류 사건 |
| 장비/경로 | Mac ARM64 CPU4threads, resident warm Julia, 앱→배치→SQLite→보고서 |
| 요청 | 24회/742행, 실제 최대 묶음32 |
| 연속 실행 | 42.507초, 약17.456 app 작업/초 |
| 중단·재개 | 64건에서 중단, 저장64건 그대로, 별도 연속 실행742 payload와 전부 일치 |
| 구조 계약/오류 | 742통과, backend_error0 |
| 예산 일관성 | **상한보다 비싼 A 구매11건: 원선택 보존+경고** |

처리량은 위 workload의 한 실행 실측이며, 백만 명의 성능 추정이 아니다. 입력 길이·질문/선택지 수·조건/반복 수·하드웨어·캐시·저장 비용이 달라지면 별도로 측정해야 한다. Qwen은 앱에서 순차 호출한다. GPU·분산 실행 성능은 측정하지 않았다.

초기 순차 Julia53명742건은9건에서 중단·재개해 보존했고 약50.01초를 기록했다(`http-julia-serial-resume.json`). 이후 실제 배치 연결을 완료했다. 별도 동일 한 행 반복의 batch1/8/32 CPU 측정은14.4/17.4/18.7행/초, 서비스 peak RSS 최대2392.7MiB였다(`julia-benchmark.json`). 반복 행의 모델 측정과 다양한 행의 앱 측정은 구분한다. 서비스 high-water RSS는 장비 전체 메모리가 아니다.

`process-restart.json`: `sh tools/demo.sh stop`으로 실행 중인 관리 프로세스를 종료한 뒤 `start`로 새 프로세스를 만들었다. 앱이 저장32건의 상태를 interrupted로 감지했고742건까지 재개했다. 저장32건은 변하지 않았고 오류0이었다. 프로세스 종료 중 미저장 요청은 재호출될 수 있다. 외부 API 과금 exactly-once 보장을 주장하지 않는다.

## 페르소나 대비·선택지 순서

`persona-sensitivity.json`은 프로젝트가 명시적으로 만든 두 반대 필요 프로필, need/purchase, 원순서/역순서, mock/Qwen/Julia의 **24개 출력 전부**와 입력을 보존한다. NVIDIA 원문을 바꾸지 않았다. 공통 예산3000JPY, 상품2000JPY, seed17이다.

| backend | 원순서 필요: 필요 있음 / 없음 | 원순서 구매 | 순서 교체 시 달라진 사례 |
| --- | --- | --- | --- |
| Mock | unknown / unknown | buy / buy | 없음; 프로필 필요를 판단하는 모델 아님 |
| Qwen | unknown / unknown | unknown / unknown | 필요 양쪽, 구매 필요 있음 쪽 |
| Julia | now / none | unknown / unknown | 필요 없음 쪽, 구매 양쪽 |

Julia 필요 선택이 두 입력에서 달랐다는 제한된 관찰은 있지만 순서 민감성이 남았다. 구매 둘 다unknown인 원결과도 그대로 남긴다. Qwen은 같은 seed여도 생성 확률과 선택지 배치에 민감했다. 두 프로필은 일반적인 인과 귀속·일본어 안정성·구매 예측 정확도의 검증이 아니다.

초기 공개 한 인물·상한1500JPY 비교에서도 Qwen/Julia가2000JPY 구매를 선택했다. 불리한 결과를 삭제하거나 강제 보정하지 않았다. 현재 보고서 경고는 절대 상한의 입력 일관성 검사이며 행동 검증은 아니다.

## 수정한 실패

첫 core 검사15통과/1실패는 필드 기대값23의 오류였다. 실제 UUID 포함22열로 수정 후 통과했다. 초기 local 구매가 정보 없는 예산을 추론하는 문제는 명시 context gate로 막았고 새 backend 버전으로 실제 재검증했다.

DOM 재실행 중 완료 상태가 갱신된 직후 아직 이전 partial report를 검사하는 대기 조건 실패가 있었다. 최종 보고서 완료 건수까지 기다리도록 수정해 재실행했다. 통합 실행기의 첫 Julia 시작은 editable .pth import 실패로 중단했고 이미 시작한 자체 Qwen을 정리했다. 검증한 로컬 모델 소스를 명시 경로로 import하여 통합 start/stop/restart를 실제 재검증했다.

## 반복 실행

```sh
sh tools/demo.sh start
PYTHONPATH=src .venv-data/bin/python -m unittest discover -s tests -v
node --check web/app.js
PERSONA_LAB_TEST_JULIA=1 npm run test:dom
PYTHONPATH=src python3 tools/smoke_local.py
PYTHONPATH=src python3 tools/smoke_http_batch.py
PYTHONPATH=src python3 tools/check_persona_sensitivity.py
sh tools/demo.sh status
```

smoke 실행은 새 store를 만들어 실제 요청을 수행한다. 개발 기록 `benchmark_julia.py`는 기존 비교 checkpoint를 재사용할 수 있으므로 반복 시 요청0을 새 추론으로 해석하지 않는다. 종료는 `sh tools/demo.sh stop`. 모델/포트 안내와 복구 절차는 README에 있다.

## 별도 미검증·블로커

IAB 생성은 `Browser is not available: iab`, inventory는 `[]`였다. Codex panel open은 숨겨진 위임 작업에 queued였다. Chrome/Safari·직접 CDP·외부 브라우저로 우회하지 않았다. **실제 브라우저 렌더링·시각·키보드·좁은 화면 E2E는 미검증**이다.

전체8shard·백만/억 단위 모델 작업·배포 OS 설치 패키지·실제 구매 행동 정확도·대표성/가중치 보정·외부 API·장기 여정·분산 실행은 구현 또는 검증하지 않았다. 전용 모델 실제 연결과 형식 유효성만으로 이러한 항목을 입증하지 않는다. Codex 앱 전역 프로젝트 등록은 완료했다고 보고하지 않는다.

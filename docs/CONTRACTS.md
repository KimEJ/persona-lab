# 실행 가능한 v0.1 계약

계약 검증 코드는 `src/persona_lab/contracts.py`, 예시는 `examples/experiment.json`, 회귀는 `tests`에 있다. JSON Schema 라이브러리를 설치하는 대신 실행 시 명시적 Python 검증을 적용한다.

## 인물과 소스

`Persona`는 원본 UUID를 그대로 갖고, `persona_id = SHA256(source_id, version, uuid)`를 갖는다. 여섯 narrative를 같은 record에 담는다. raw 값·알 수 없는 확장·field provenance·license·origin·원문 content hash를 보존한다. 결측은 `absent`, `null`, `empty`로 구분한다. 합성 원본은 실재 소비자 관측으로 표기하지 않는다. 동일 UUID의 반복은 실행 전에 disk-backed unique index로 거부한다. 서로 다른 UUID의 유사 인물 병합은 구현하지 않았다.

## Parquet 입력 계약

`parquet-import-v1`은 선택한 고정 공식 shard 또는 출처가 명시된 로컬 파일을 batch로 읽는다. 다운로드 byte cursor/SHA와 변환 row-group/row-offset·출력 byte cursor/SHA를 SQLite UUID index와 함께 저장한다.1UUID=1인물이며 null/empty/absent·확장·원문·version/license를 보존한다. 완료 후 manifest를 게시하고 catalog로 전체 필터·20행 페이지를 제공한다. 중복UUID/라이선스 변경/Range 무시/입력·출력 변조/명세 변경은 거부한다. 자세한 설치·복구·메모리 한도와 실측은 [PARQUET.md](PARQUET.md)다. 이 입력 cursor와 일반 실험의 JSONL 재개 스캔을 구분한다.

## 실험

명세는 source와 분리되어 있으며 `schema_version`, `experiment_id`, `mode=independent_comparison`, `panel`, `seed`, `repeats`, `batch_size`, `products`, `questions`, `scenario`, `assumptions`를 갖는다. panel은 전체 또는 지역·나이·문자열 필터다. 필터는 전체 입력 스트림에 적용한다. 현재 무작위 표본·가중치는 구현하지 않았다.

상품은 id·이름·소개·기능·가격을 갖는다. 가격은 currency의 최소 단위 정수이며 일시불/월/년 결제를 구분한다. 질문은 필요·이해·대안·구매·신뢰·온보딩·이탈 domain, 제한된 choices, prompt를 갖는다. 모든 choices에 `unknown`이 있어야 한다. source raw와 사용자 입력 속 명령은 실행하지 않는다.

조건마다 동일 `initial_state_id`로 평가한다. 예산은 `assumptions.purchase_budget_jpy_minor` 또는 자체 fixture용 UUID별 명시 가정이다. 인물의 알려진 실제 성향으로 저장하지 않는다. 예산은 참고 선호가 아니라 일시불 JPY 구매의 절대 상한이라는 실험 가정이다. 모델 원선택을 강제로 보정하지 않고 상한을 넘는 buy는 일관성 경고로 남긴다. 다른 통화·정기 결제를 이 예산에 임의 환산하지 않는다. 예산 미제공의 로컬 구매 판단과 사건 미제공의 이탈 판단은 `unknown`으로 gate한다. 상태를 이어 가는 여정과 인물 간 사회 영향은 별도 후속 실험이다.

## 작업·결정·백엔드

한 작업은 인물×상품 조건×반복×질문이다. 안정 job ID에 source identity와 조합을 포함한다. A/B에는 같은 인물·질문·반복의 seed를 사용한다. Python range/nested loop로 지연 생성하며 전체 조합이나 반복 수를 리스트로 만들지 않는다. 배치 1–1,024는 메모리 보호 한도이며 대상 인원 상한이 아니다. SQLite checkpoint는 64-bit 작업 번호를 사용한다.

`DecisionBackend`는 `backend_id`, `kind`, `decide(Job)->Decision`만 요구한다. 소형 전용 결정모델을 이 경계에 교체 연결할 수 있다. 현재 FixtureBackend는 mock 규칙, LocalLLMBackend는 loopback Qwen 범용 지시 모델, JuliaBackend는 loopback 전용 유한 선택 모델, APIBackend는 미구성으로 호출을 거부한다. 모델은 인물별로 복제하지 않는다. Julia는 선택적 `decide_batch(list[Job])->dict[job_id, Decision|Exception]` 경계와 `batch_limit=32`를 사용한다. 응답 순서 대신 ID를 검증해 연결한다. runner의 저장 배치 1–1,024와 모델 묶음 최대 32를 구분한다. 서비스는 엄격한 무손실 인코딩과 padded token 제곱 작업량 cap으로 추가 분할·항목 거부할 수 있다. Qwen은 순차 호출이며 GPU/분산 성능은 주장하지 않는다.

Decision은 제한된 choice, `ok`/`insufficient_information`, reason codes, 실제 입력 evidence paths를 반환한다. unknown과 정보 부족 상태가 일치해야 한다. 알려진 선택에는 유효 근거 경로가 필요하다. 숫자 score는 현재 받지 않는다. 사유 코드·근거 연결은 모델 출력이며 인과적 사실 검증을 대신하지 않는다. Julia의 `evidence_semantics=supplied_input_only`는 투입 입력의 참조이고 생성 사유·인과 근거가 아니다. Qwen은 `backend_cited_input`으로 모델이 인용한 경로를 구분한다. 모델 응답 오류·잘림·부정합은 항목별 `backend_error`, `decision=null`로 저장하고 다음 항목을 처리한다. unknown으로 바꾸거나 mock으로 대체하지 않는다. 요청 전체 timeout/ID 부정합은 해당 묶음 모두 오류로 남긴다.

## 체크포인트·취소·보고서

source·입력 파일 SHA-256·experiment·backend version·engine version을 fingerprint로 고정한다. 결과 insert와 다음 cursor update를 한 SQLite 트랜잭션으로 저장한다. 중복 job ID를 unique key로 막는다. 예상 밖 엔진 실패는 저장 배치를 rollback하며 직전 커밋부터 재개한다. 취소는 현재 호출 뒤 확인한다. 단건 호출은 완성한 연속 항목, 배치 호출은 반환받은 연속 전체 chunk를 원자적으로 저장한다. 프로세스 종료 중 미저장 chunk는 재호출할 수 있다. 첫 pass를 완료하면 오류 ordinal만 묶음 재시도한다. 정상 payload와 cursor는 변경하지 않는다. 반복 오류가 남으면 completed_with_errors다. 단일 run은 한 writer만 허용한다. 재개 시 입력을 다시 스캔하므로 큰 완료 cursor에서는 시간이 걸린다. 실행 중 입력 파일을 바꾸지 않아야 한다.

동일 결과의 중복 커밋을 막지만, 백엔드 호출 자체를 정확히 한 번 실행하거나 미래 외부 API 과금 중복 방지까지 보장하지 않는다. 모델은 파일·브라우저·도구 실행 권한을 갖지 않는다.

집계는 SQL, 보고서는 템플릿으로 만든다. choice share의 분모는 unknown 포함 구조 유효 판단이다. backend_error는 유효 선택 분모에서 제외하고 별도로 센다. 예산 충돌은 선택을 삭제/보정하지 않고 별도 경고로 세며 JSON/CSV/Markdown에 함께 남긴다. 부분 실행은 편향 가능성을 표시한다. A/B transition은 같은 인물·질문·반복의 완료된 짝만 센다. JSON/CSV/Markdown·재실행 명세를 내보낸다. CSV 사용자 문자열은 수식 시작 문자 escape를 적용한다. 원조건 상세 보기는 저장된 상품·질문·선택지·가정과 해당 UUID의 원문을 표시한다. 원문 hash나 출처 identity가 저장 기록과 다르면 당시 입력이라고 표시하지 않고 거부한다. 전체 원문은 immutable 팩 JSONL에 유지하며 결과마다 중복 복제하지 않는다. 상세 결과 전체는 SQLite, 보고서 사례는 최초 28건이다. 자유 보고서 생성모델은 사용하지 않는다.

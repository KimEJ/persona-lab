# 1차 데모 체크리스트

범위: 기본 기능이 연결된 로컬 데모. 완성 PC 설치본·검증된 구매 예측 제품은 아니다. 다음 표를 기준으로 누락/명확한 오류를 점검했으며 큰 후속 기능은 추가하지 않았다.

| 항목 | 상태와 근거 |
| --- | --- |
| 새 작업 폴더·변경 가능한 이름 | persona-lab, 기존 프로젝트 덮어쓰기 없음 |
| 기획·공개 카드/스키마·귀속 | BIWA r1 직접 확인, NVIDIA22필드/1M 원본 안내/CC BY4.0; 전체 다운로드 없음 |
| 실제 데이터·자체 fixture | 원본 첫shard125,000명/216MB, Viewer53명·자체4명, 여섯 narrative=UUID 하나, provenance/missing/raw 유지 |
| 원본·로컬 Parquet 입력 | 고정revision/SHA·Range 재개·row-group cursor·UUID index·disk catalog·UI 취소/재개; 자체100k SHA/RSS proof |
| 안전한 소형 가져오기 | 고정 공식 API,1MB,license/UUID/truncation 검증; 실제 CLI import+회귀 |
| 패널 검사·필터·페이지 | API/DOM 통과;20행 미리보기와 전체 실험 수를 분리 |
| 상품·가격·기능·소개 A/B | 입력 검증·통화 최소단위·결제 유형·조건 교환·명세 저장 |
| 7영역·가정·unknown | 단건 계약·상한/사건 gate; 인물 사실에 구매 성향 추가하지 않음 |
| 실제 모델/Mock 구분 | Qwen 범용 지시·Julia 전용 유한 선택·Mock 표시; 원본Parquet한명→실제Julia14건·원문/조건/귀속확인; API 미구성 |
| 스트리밍·실제 배치 | 지연 작업·SQLite unique preflight; Julia keyed32 묶음;10k fixture 및53명742건 검증 |
| 항목 오류·취소·재개·재시도 | batch ID/timeout/rollback 회귀, 실제 HTTP/DOM 및 process restart 증거 |
| 저장·비교·쌍별 변화 | unknown 분모·오류 별도·partial 경고·SQL 집계 |
| 예산 일관성·모델 한계 | 원결과 유지, 상한 위반11건·옵션순서 민감성/unknown 문서화 |
| 조건 검토 상세 | 원문·source hash·상품·질문/선택지·가정·원결과; 변경된 원문 거부 |
| 보고서·명세 내보내기 | JSON/CSV/MD·license/source/assumptions·수식 escape; 저장 명세 |
| 시작·종료·재시작 안내 | demo.sh start/stop/status, missing model/port conflict/log 안내, interrupted→742건 복구 |
| 앱 외부 경계 | loopback Host/Origin/path 제한, arbitrary upload/URL·paid API·keys·GitHub/public deploy 없음 |
| 테스트 | Python/HTTP50통과, 기본DOM/API30·ParquetDOM/API12·Parquet→Julia접점11검사 그룹, 실제 모델/원본/프로세스 복구 증거 |
| 실제 브라우저/시각 E2E | **미완료: IAB 미제공. 외부 브라우저 우회 없음** |
| Codex 앱 전역 프로젝트 등록 | **미완료: 새 local folder를 등록하는 callable API 없음** |

다음 단계는 IAB가 제공되는 환경에서 실제 렌더링/키보드/좁은 화면 검증, 일반 실험 cursor 최적화와 결과 분할 저장, 다양한 입력/선택지의 결정 품질 평가, 배포 OS 결정·설치 패키지다. 백만 명 성능·소비자 행동 정확도·API·장기 여정·분산 실행은 후속 범위다.

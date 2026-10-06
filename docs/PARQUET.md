# 원본 Parquet 입력

현재 Mac에서 선택한 NVIDIA 원본 첫 shard를 125,000행까지 가져왔다. 전체 8개 shard를 자동 다운로드하지 않는다. 화면의 20행은 미리보기 페이지 크기이며 인원 제한이 아니다. 완료된 팩은 기존 A/B·Mock·로컬 모델·보고서 경계에 연결된다. 전체125,000명 모델 실험은 실행하지 않았다. 목록에서 한 명을 고른 실제Julia14건 접점 검증을 별도로 완료했다.

## 준비와 사용

Parquet만 선택 의존성 PyArrow가 필요하다. 이 Mac에는 기존 Python3.12로 `.venv-data`를 만들고 공식 PyPI의 PyArrow25.0.1 ARM64 wheel 한 패키지를 설치했다. wheel 크기는35,861,559bytes, 공식 메타데이터 SHA-256은 `df961f2e7ae9cf496459259d798652c70625f6c080650d6952f8c04053c58ee9`다. PyArrow는 Apache2.0이다. 전역 Python·설정을 변경하지 않았으며 모델 환경 `.venv-julia`와 분리했다.

```sh
sh tools/demo.sh start
```

실행기는 `.venv-data`가 있으면 앱에 사용한다. UI에서 ‘원본 Parquet 가져오기 · 진행/취소/재개’를 펼치고 공식 shard 또는 명시적 로컬 파일을 선택한다. 저장된 가져오기를 선택하면 진행·취소·재개가 이어진다. 완료 전에는 인물 팩으로 게시하지 않는다. 완료된 ‘NVIDIA 일본 · 원본 train-00000-of-00008.parquet’를 선택하면 전체125,000명에 필터가 적용된다.

다른 장비에서 준비할 때만 다음 선택 설치를 수행한다. 이 작업은 네트워크 접근과 프로젝트 내부 의존성 설치를 수반한다. 앱 시작은 이를 자동 실행하지 않는다.

```sh
uv venv .venv-data --python python3 --no-python-downloads
uv pip install --python .venv-data/bin/python --index-url https://pypi.org/simple --only-binary :all: pyarrow==25.0.1
```

CLI는 같은 체크포인트를 사용한다. `--max-batches`는 테스트용 중단이며 인원 상한이 아니다. Ctrl-C는 다음 안전한 블록/배치 경계에서 저장한다. CLI 작업 중 UI는 외부 writer로 표시하며 UI 취소 대신 해당 터미널에서 Ctrl-C를 사용한다.

```sh
PYTHONPATH=src .venv-data/bin/python -m persona_lab parquet-import --shard train-00000-of-00008.parquet --max-batches 1
PYTHONPATH=src .venv-data/bin/python -m persona_lab parquet-import --resume <표시된-import-id>
```

공식 목록·버전·크기·SHA는 `data/official-shards.json`에 있다. 선택한 첫 파일은216,054,745bytes, revision `f1f37019d8497143c507b3deb547e65646de2ab7`, SHA-256 `fa6b2fd3a2b32a9591685bedea693de44b3ad9154b259071e041b976bc222ba1`이다.5개 row group,22필드,125,000UUID를 확인했다. 여섯 서술은 UUID 하나의 관점이며600만 인물로 합산하지 않는다. CC BY4.0·저자·자료명·원문 URL·변경 표시를 유지한다.

## 명시적 로컬 파일

UI는 프로젝트 `data/inbox`의 `.parquet` 파일과 같은 이름 뒤에 `.source.json`을 붙인 출처 파일만 열거한다. 예: `data/inbox/my-panel.parquet`, `data/inbox/my-panel.parquet.source.json`. 출처 JSON은 다음 필수 값을 포함한다. 아래 예시는 자체 테스트 자료에만 사용하는 값이다. 다른 원본의 라이선스·저자를 이 값으로 바꾸어 표시하지 않는다.

```json
{
  "schema_version": "0.1",
  "source_id": "my-project/explicit-synthetic-panel",
  "version": "fixture-v1",
  "url": "https://example.com/my-explicit-fixture",
  "license_id": "LicenseRef-Project-Fixture",
  "license_url": "https://example.com/my-explicit-fixture/license",
  "origin": "project_synthetic_fixture",
  "attribution": "Project-authored explicit synthetic test data"
}
```

`LicenseRef-Project-Fixture`는 내부 테스트 표식이며 공인 배포 라이선스가 아니다. 로컬 파일 SHA를 version에 덧붙이고 원래 version도 보존한다. 게시자·라이선스는 사용자가 제공한 메타데이터이며 별도 검증됐다고 표시하지 않는다. 원문 UUID와 필드 타입이 계약에 맞아야 한다. 없는 구매 성향·예산을 인물 사실로 채우지 않는다.

```sh
PYTHONPATH=src .venv-data/bin/python -m persona_lab parquet-import --path data/inbox/my-panel.parquet --source data/inbox/my-panel.parquet.source.json
```

CLI의 `--path`는 사용자가 명시한 로컬 파일을 받는다. UI는 inbox basename만 받으며 경로 이탈·symlink 이탈·임의 URL·업로드를 거부한다.

## 저장과 복구 계약

`imports/<id>/`에 명세, 다운로드 prefix SHA/byte cursor, 원본 파일, JSONL byte cursor/SHA, row-group/row-offset, SQLite UUID index와 상태를 보관한다. 다운로드는1MiB 단위로 저장하며 재개 시 prefix SHA와 HTTP206 Content-Range를 확인한다. 최종 공식 SHA가 다르면 거부한다. 원본 버전·라이선스도 고정된 공식 메타데이터와 대조한다.

변환은 `ParquetFile.iter_batches`로 현재 row group만 읽는다. row group 중간에서 재개하면 그 그룹의 저장 지점 앞 batch를 다시 읽어 건너뛴다. 기본256행, 최대4,096행의 배치이며 전체 인물을 리스트로 펼치지 않는다. raw/null/empty/absent/확장 필드를 보존하고 UUID 중복은 현재 배치를 rollback해 실패로 남긴다. 유사한 다른 UUID의 자동 병합이나 서로 다른 팩을 합친 패널은 아직 지원하지 않는다.

출력을 flush/fsync한 뒤 UUID index와 cursor를 SQLite 한 트랜잭션으로 커밋한다. 중단 시 미커밋 출력 꼬리를 잘라내고 SHA를 검증한다. 완료 후 원문 JSONL·필터/offset SQLite catalog를 준비하고 manifest를 마지막에 게시한다. 이미 게시된 팩을 다른 원문으로 덮어쓰지 않는다. 앱 재시작 뒤 저장된 가져오기에서 재개할 수 있다.

decoded row-group 메타데이터128MiB·생성 batch8MiB·단일 row8MiB 보호 한도를 둔다. 이는 임의 Parquet encoding의 총 RSS 보장이 아니다. reader/native allocation·긴 셀·row group 크기·디스크 비용을 별도로 측정해야 한다. source hash·출력 prefix hash는 재개 때 파일을 읽으므로 큰 파일일수록 시간이 든다. 일반 실험 실행기는 입력 JSONL을 시작/재개 때 다시 스캔하며 결과 분할 저장·분산 실행은 후속 단계다.

원본 Parquet와 큰 JSONL·SQLite는 Git에서 제외한다. metadata·출처·검증 기록은 남긴다. 이 Mac의 실제 데이터 파일은 계속 존재하지만 소스 폴더만 복사한 새 장비에서는 다시 가져와야 한다. 가져오기 중 `imports`나 파일을 삭제/수정하지 않는다.

## 검증 근거

- `verification/parquet-source-download.json`: 실제2MiB에서 취소, Range 재개, 최종 SHA 일치.
- `verification/parquet-dom-api.json`: 원본1,280행 저장 후 앱 재시작·UI 재개·14,336행 취소·125,000행 완료,12개 DOM/API 검사. 브라우저 렌더링 검증은 아니다.
- `verification/parquet-original-import.json`:125,000개 고유 UUID, 저장1,280행 순서 불변,22필드/5그룹, 처음53행 raw 값이 관측한 Viewer53행과 일치, 끝 페이지·전체UUID 필터.
- 같은 원본 팩에서 UUID 한 명만 Mock으로14개 판단→저장된 원문 검토→JSON/CSV/MD 내보내기를 확인했다. 원문/귀속을 유지했고 모델 요청은0회다. 원본125,000명 모델실험이나 행동 정확도 검증으로 해석하지 않는다.
- `verification/parquet-large-fixture.json`: 자체100,000행,768행 중단·재개와 연속 실행의 SHA 일치. Python tracemalloc peak2.85MiB, process high-water RSS125.30MiB. Arrow allocation은 진행 중 표본 최대0.65MiB이며 모든 순간의 최대라고 주장하지 않는다. 해당 fixture 결과이며 NVIDIA 전체/모델 처리량이 아니다.
- `verification/parquet-julia-dom-api.json`: 원본목록→1명필터→실제Julia1요청/14건→원문/조건상세→A/B14그룹·구매1쌍→JSON/CSV/MD귀속의11개 DOM/API 검사를 통과했다. 전체unknown8건, 구매unknown→unknown, 예산충돌0건을 보존했다. 구조 유효성과 행동 정확도는 구분한다. 세 보고서와 원문/조건 상세는 `parquet-one-person-julia-report.*`, `parquet-one-person-julia-details.json`에 있다.
- `tests/test_parquet.py`, `tests/test_http.py`: 중복 UUID·원본/출력 변조·post-write crash·명세 변경·라이선스 변경·Range 거부·전체 필터·로컬 파일 A/B/원조건 연결 회귀.

[공식 PyArrow iter_batches](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html)와 [Parquet 문서](https://arrow.apache.org/docs/python/parquet.html)를 참고했다. 실제 Julia 처리량은 Viewer53명 실험의 별도 기록이며 이 입력 검증과 합쳐 백만 명 추론 성능으로 해석하지 않는다.

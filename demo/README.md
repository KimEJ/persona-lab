# Persona Lab 데모

제품화 전에 구현한 로컬 웹 데모입니다.
현재 화면은 상품안 2개를 비교합니다.
실험 설계는 [BIWA 위키](https://wiki.biwa.dedyn.io/#personal-wiki/persona-lab-experiment-design)에서 관리합니다.
제품화 방향은 [저장소 README](../README.md)를 확인하세요.

## 실행

Python 3.12 이상을 준비하세요.
명령은 이 디렉터리에서 실행하세요.

```sh
sh tools/demo.sh start
```

브라우저에서 [데모 화면](http://127.0.0.1:8787)을 여세요.
모델과 선택 데이터를 준비하지 않았다면 자체 합성 인물 4명과 Mock을 사용하세요.
앱은 데이터와 모델을 자동으로 다운로드하지 않습니다.

```sh
sh tools/demo.sh status
sh tools/demo.sh stop
```

## 기본 동작 확인

기본 상품 입력과 자체 fixture 예산을 유지하세요.
Mock으로 실행하면 56개 판단과 4개의 구매 판단 쌍을 저장합니다.
한 명의 구매 선택이 거절에서 구매로 바뀝니다.
이 결과는 테스트 예산 규칙을 확인한 것입니다.

## 검증

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
```

선택 데이터나 PyArrow가 없으면 관련 검사를 건너뜁니다.
DOM 검사는 실행 중인 데모와 별도로 준비한 테스트 도구가 필요합니다.

## 알려진 문제

| 문제 | 사용 시 확인할 사항 |
| --- | --- |
| 실행 중 보고서의 집계 시점 불일치 | 실행 완료 후 보고서 저장 |
| 결과가 없는 실험으로 전환하면 이전 보고서 유지 | 화면 새로고침 후 대상 실험 다시 선택 |
| 일부 잘못된 Qwen 응답이 전체 실행 중단 | 응답 문제를 해결한 뒤 체크포인트에서 재개 |

## 개발 기록

| 내용 | 문서 |
| --- | --- |
| 새 장비 실행 | [REINSTALL.md](docs/REINSTALL.md) |
| 데이터와 귀속 | [DATA_SOURCES.md](docs/DATA_SOURCES.md) |
| Parquet 입력과 복구 | [PARQUET.md](docs/PARQUET.md) |
| 모델 준비 | [MODEL.md](docs/MODEL.md) |
| 실행 계약 | [CONTRACTS.md](docs/CONTRACTS.md) |
| 과거 검증과 미검증 범위 | [VERIFICATION.md](docs/VERIFICATION.md) |
| 데모 구현 계획 | [PLAN.md](docs/PLAN.md) |

이 문서들은 기존 데모의 개발 기록입니다.
과거 장비의 측정값을 현재 장비의 성능으로 해석하지 마세요.

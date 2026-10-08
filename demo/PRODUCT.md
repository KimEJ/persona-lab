# Persona Lab

<!-- impeccable:product-schema 1 -->

## Platform
web

로컬 실행 UI를 1차 데모로 사용한다. 최종 PC 설치 패키지와 배포 OS는 미정이다.

## Stack
사용자의 무중단 진행 요청에 따라 개발자가 선택: Python 3.12 표준 라이브러리, SQLite, HTML/CSS/JavaScript. 일반 앱 의존성 추가 설치 없이 로컬에서 실행한다.

## Users
상품·가격·기능·소개 문구를 바꾸며 같은 합성 패널의 반응을 비교하려는 사용자.

## Product Purpose
필요, 이해, 대안, 구매, 신뢰, 온보딩, 명시적 사용 후 사건에 대한 조건부 이탈을 판단하고 결과를 비교한다. 실재 구매 확률을 주장하지 않는다.

## Operating Context
NVIDIA 일본 데이터팩을 첫 입력으로 사용한다. Mac은 개발 장비다. 로컬 추론과 외부 API 어댑터를 분리한다. 공개 배포·GitHub·과금·키 생성은 범위 밖이다.

## Capabilities and Constraints
대상 인원 상한 없이 스트리밍, 제한된 배치, 영속 체크포인트를 사용한다. 원본 UUID·여섯 관점·결측·라이선스·출처를 유지한다. 구매 성향이 없는 데이터에는 이를 사실처럼 추가하지 않는다. mock과 실제 로컬 추론을 화면과 출력에서 표시한다. 원격 API는 이번 데모에서 호출하지 않는다.

## Evidence on Hand
BIWA persona-product-simulator-plan r1, NVIDIA 공개 카드와 데이터 Viewer 소형 응답, 자체 합성 테스트 fixture. 모델 성능·대규모 처리량은 실측 없이 주장하지 않는다.

## Product Principles
- 같은 패널·같은 초기 조건으로 비교한다.
- 판단 불가를 결과에서 제외하지 않는다.
- 출처와 가정, 판단과 보고서 집계를 구분한다.
- 큰 작업은 메모리에 전체 조합을 펼치지 않는다.

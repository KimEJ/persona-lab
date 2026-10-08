---
name: Persona Lab
description: macOS 상품 설문 작업면과 저장된 실행의 독립 HTML·PDF 보고서
colors:
  work: '#f9fafb'
  sidebar: '#edf1f3'
  paper: '#fff'
  ink: '#243339'
  muted: '#52646b'
  line: '#cbd3d7'
  accent: '#176f68'
  selected: '#dce9e6'
  danger: '#aa3532'
  warning: '#755112'
  work-dark: '#1d2428'
  sidebar-dark: '#181e22'
  paper-dark: '#252d32'
  ink-dark: '#edf2f4'
  muted-dark: '#b5c2c8'
  line-dark: '#47545b'
  accent-dark: '#83d5c7'
  selected-dark: '#263f3d'
  danger-dark: '#ffaaa3'
  warning-dark: '#f0cb80'
  dialog-backdrop: rgba(20,30,35,.25)
  rr-negative: '#809b96'
  rr-unknown: '#cbd3d7'
  rr-hold: '#af8b48'
  rr-band0: '#d5e4df'
  rr-band1: '#8ab8ad'
  rr-band3: '#0e4b46'
  rr-negative-dark: '#526e67'
  rr-unknown-dark: '#65747c'
  rr-hold-dark: '#c8ae7b'
  rr-band0-dark: '#344a45'
  rr-band1-dark: '#426e65'
  rr-band3-dark: '#bbdfd6'
  rr-na: '#b5c2ad'
  rr-not-run: '#ddd8cb'
  rr-na-dark: '#75816b'
  rr-not-run-dark: '#8d8776'
  report-accent: '#167d79'
  report-series-2: '#73aaa3'
  report-series-3: '#b8d4ca'
  report-series-4: '#d9c6a3'
  report-bg: '#f3f5f5'
  report-ink: '#202c32'
  report-muted: '#66747b'
  report-rule: '#d8e0e1'
  report-table-rule: '#e1e7e8'
  report-chart-ink: '#33444c'
  report-header-ink: '#50626b'
  report-unknown: '#a8afb5'
  report-error: '#b85a50'
  report-pending: '#e4e8eb'
  report-not-run: '#c7cdd1'
  report-not-applicable: '#a8a39a'
typography:
  body:
    fontFamily: -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif
    fontSize: 14px
    lineHeight: 1.45
  title:
    fontSize: 22px
    fontWeight: 600
    letterSpacing: -.025em
  document-body:
    fontSize: 16px
    lineHeight: 1.65
  document-heading:
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: -.025em
  document-section:
    fontSize: 21px
    fontWeight: 600
    lineHeight: 1.4
  document-subheading:
    fontSize: 18px
  settings-title:
    fontSize: 24px
    fontWeight: 600
  field-label:
    fontSize: 13px
  label:
    fontSize: 12px
  table:
    fontSize: 13px
  document-diff:
    fontFamily: ui-monospace,SFMono-Regular,monospace
    fontSize: 13px
    lineHeight: 1.6
  code:
    fontFamily: ui-monospace,SFMono-Regular,monospace
    fontSize: .9em
  results-title:
    fontSize: 17px
    fontWeight: 500
  results-section:
    fontSize: 15px
    fontWeight: 500
  results-assessment:
    fontSize: 13px
    fontWeight: 500
  result-summary:
    fontSize: 13px
    lineHeight: 1.6
  report-body:
    fontFamily: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif
    fontSize: 13px
    lineHeight: 1.6
  report-title:
    fontSize: 30px
    lineHeight: 1.25
    letterSpacing: -.7px
  report-section:
    fontSize: 23px
    lineHeight: 1.3
  report-subheading:
    fontSize: 16px
  report-note:
    fontSize: 11px
  report-print-body:
    fontSize: 10.5pt
    lineHeight: 1.5
  report-print-table:
    fontSize: 9pt
rounded:
  navigation: '0'
  progress: 4px
  field: 6px
  control: 7px
  editor: 9px
  dialog: 12px
spacing:
  label-gap: 6px
  compact-gap: 8px
  control-gap: 12px
  row-padding: 14px
  group-gap: 18px
  section-gap: 24px
  heading-gap: 28px
  page-inline: 32px
  window-top: 45px
  chart-gap: 30px
components:
  button-primary:
    backgroundColor: '{colors.accent}'
    textColor: '{colors.paper}'
    typography: '{typography.body}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  button-secondary:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.body}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  button-quiet:
    textColor: '{colors.muted}'
    typography: '{typography.body}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  field:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.body}'
    rounded: '{rounded.field}'
    padding: 7px 9px
  item-tab-selected:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.accent}'
    typography: '{typography.body}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  editor:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.document-body}'
    rounded: '{rounded.editor}'
    padding: 24px 30px
  format-control:
    textColor: '{colors.ink}'
    typography: '{typography.field-label}'
    rounded: '{rounded.control}'
    padding: 6px 9px
  document-diff:
    typography: '{typography.document-diff}'
  detail-current:
    backgroundColor: '{colors.selected}'
    textColor: '{colors.ink}'
    typography: '{typography.body}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  review-note:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.body}'
    rounded: '{rounded.field}'
    padding: 9px 12px
  product-field:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.body}'
    rounded: '{rounded.field}'
    padding: 7px 9px
    height: 36px
  response-person-selected:
    backgroundColor: '{colors.selected}'
    textColor: '{colors.ink}'
    typography: '{typography.label}'
    rounded: '{rounded.navigation}'
    padding: 12px 3px
  response-heat-cell:
    textColor: '{colors.ink}'
    typography: '{typography.label}'
    rounded: '{rounded.navigation}'
    padding: 4px 0
  workflow-step-current:
    textColor: '{colors.accent}'
    typography: '{typography.field-label}'
    rounded: '{rounded.navigation}'
    padding: 12px 0
  response-distribution-strip:
    backgroundColor: '{colors.line}'
    rounded: '{rounded.navigation}'
    height: 14px
    width: 100%
  frozen-result-context:
    textColor: '{colors.ink}'
    typography: '{typography.result-summary}'
  report-page:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.report-ink}'
    typography: '{typography.report-body}'
    rounded: '{rounded.navigation}'
    padding: 42px 50px
---

# Persona Lab 앱·보고서 디자인

## Overview

기존 Operate 작업면의 시스템 글꼴·회백색 면·청록색 주요 동작을 유지한다. 0.8 기본 흐름은 `product-survey-v2`의 독립 질문 열 개이며, 상품 입력 → 대상·실행 → 결과의 비대화형 진행 표시와 상단 이전·주요 동작으로 이동한다. 독립 HTML 보고서는 저장한 실행을 읽는 문서로, 고정된 흰 면·청록색·인라인 CSS/SVG를 사용한다.

기존 0.4–0.7 검증 기록은 현재 규칙 안에 반복하지 않는다. `.impeccable/`과 `verification/`은 Git에 포함하지 않는 로컬 작업 기록이다. 로컬 `.impeccable/archive/DESIGN-0.7.md`과 로컬 `.impeccable/archive/design-0.7.json`에 전체 이전 기록을 보존했다. 알려진 이전 조건 검사 16개 중 4개 미충족 이력은 남아 있다. 현재 실행에서도 전환 부담의 동일 입력이 `not_applicable`과 `low`로 달라졌으며 가격 비공개 입력 쌍 9개 중 8개만 선택이 같았다. 실행 성공과 모델 선택의 안정성을 구분하고, 새로운 질문·보고서를 정확도나 소비자 확률 검증으로 표현하지 않는다. 최종 `verification/survey-report.json`은 1명 × 2조건 × 10질문의 20건·실제 21요청·출력 토큰 0·실행 오류 0을 기록한다. 최종 브라우저 UI와 대표 PDF의 독립 마감 판정은 `ship`이다. 네이티브 비동기 인쇄 PDF는 12개 A4 페이지이며 primary가 PDFKit으로 전부 확인했다. 네이티브 저장 패널과 앱 전체·macOS 14·한글 IME는 검증 완료로 확대하지 않는다. 브라우저 다운로드 이벤트는 시간 초과였고 HTML API 성공과 구분한다.

**Key Characteristics:**

- 문서·판매조건·평가 가격대·대상을 한 흐름에서 고정한다.
- 같은 회차와 같은 코호트의 결과·상태·원문을 함께 읽는다.
- 화면 조작과 독립 보고서의 읽기·인쇄 표현을 구분한다.

## Colors

Operate 기본 팔레트와 다크 대응값은 유지한다. `accent`·`selected`는 주요 동작·선택, `work`·`sidebar`·`paper`는 면, `ink`·`muted`·`line`은 본문·보조 글자·경계다. 오류는 `danger`다.

결과의 긍정·중간·부정과 네 가격대는 기존 `rr-*` 색을 쓴다. 판단 불가, 해당 없음, 미실시, 오류, 대기는 각각 라벨·별도 상태색으로 보존한다. `rr-na`와 `rr-not-run`은 해당 없음·미실시 전용이며 판단 불가와 섞지 않는다.

`report-*`는 독립 보고서 전용이다. 흰 페이지와 `report-bg`, `report-ink`, `report-muted`, `report-accent` 및 네 범주·다섯 상태 색을 사용한다. 앱의 다크 팔레트를 보고서에 상속하지 않는다. 값의 기준은 frontmatter다.

## Typography

앱은 기존 macOS 시스템 글꼴·한국어 대체 글꼴과 본문 (14px), 문서 (16px /1.65), 결과 제목 (17px /15px /13px), 보조 라벨 (12px)을 유지한다. 진행 표시는 (13px), 현재 단계는 (600) 굵기다. 문서·결과 원문 폭은 (75ch), 숫자와 선택 점수는 `tabular-nums`를 쓴다.

보고서는 같은 시스템 계열의 본문 `report-body`, 제목 `report-title`, 절 제목 `report-section`, 보조 정보 `report-note`를 쓴다. 인쇄 본문·표는 별도 `report-print-*` 크기로 지정한다.

## Layout

앱 목록은 (222px), 작업 여백은 (45px /32px /30px)다. 창 너비 (1000px) 이하에서는 목록 (190px)과 가로 여백 (24px)을 쓴다. AppKit 시작·최소 크기는 (1220×860 /900×650)이며 지원 기준은 macOS 14 이상 Apple Silicon이다.

입력 안의 아이템 탭·상품 조건·문서 편집기를 유지한다. 대상은 검색·지역·나이·성별과 기본 100명 표본으로 정하며 10,000명 합성 풀에서 실제 추출 수를 표시한다. 실행 시 내부 UUID 코호트를 고정한다. 후보 인물 미리보기는 없다. 질문 개요·평가 가격대·고급 설정은 접힌 `details`다.

결과는 `minmax(0,1.3fr) minmax(0,1fr)` 두 열과 (24px) 간격이다. 오른쪽 인물 패널은 상단 (20px), 최대 높이 `calc(100vh - 40px)` 안에서 스크롤한다. 컨테이너 (620px) 이하는 한 열이며 패널 고정을 푼다. (380px) 이하는 히트맵을 세 칸씩 나눈다. 결과 위에는 판매조건·문서 두 줄 요약·조건/인원/회차/상태를 짧게 두고 원문과 전체 조건을 펼쳐 확인한다. 입력 단계로 돌아갈 필요가 없다.

독립 보고서는 화면에서 최대 (900px), 페이지 안쪽 여백 (42px 50px)이다. (700px) 이하에서는 한 열과 (24px 20px) 여백을 쓴다. A4 인쇄용 CSS는 절별 페이지 나눔·표 머리 반복·행 분리 억제를 지정한다. 네이티브 PDF는 비동기 AppKit `printOperation`으로 변환한다. 최종 표본 12개 A4 페이지의 한국어·SVG는 PDFKit에서 확인했으며, 원시 실행 기록의 10월 7일 날짜를 현재 클라이언트 10월 8일로 바꾸지 않는다.

## Elevation & Depth

앱은 면 색과 얇은 경계로 깊이를 구분하며 그림자는 원문·검토 dialog에만 둔다. 보고서는 흰 면·구분선·절 간격을 사용하고 그림자를 두지 않는다.

## Shapes

필드 (6px), 버튼 (7px), 편집기 (9px), dialog (12px)의 기존 모서리를 유지한다. 진행 연결선·누적 막대·표는 직선이다. 진단 막대는 (14px), 그래프 선택 외곽선은 (2px)다. 새로운 장식 형태는 추가하지 않는다.

## Components

### Workflow, editor and valuation

진행 단계는 클릭하지 않는 상품 입력·대상/실행·결과 목록이다. 이전과 `다음`·`실험 시작`·`이어 실행`·`결과 보기`·`보고서 저장`은 상태에 따라 상단에 둔다. 알려진 주요·보조·조용한 버튼과 키보드 포커스 (2px)를 재사용한다.

Markdown은 같은 편집 영역에서 표현하며 아이템별 이력과 Unicode 20,000자 한도를 유지한다. 상품명·판매가격과 문서를 함께 고정한다. `평가 가격대`를 펼치면 아이템별 경계값 세 개·통화·결제 주기를 입력한다. 필드는 (36px), 경계는 양수·오름차순이며 전부 비우면 가격 평가는 미실시다. 일부만 입력하거나 순서가 잘못되면 실행을 막는다. 판매가격과 평가 단위는 별도다.

### Frozen result context and states

결과 헤더는 저장한 상품·문서·판매조건·필터·N·실행 상태와 선택한 한 회차를 보여준다. 펼친 `상품·실험 조건`에는 원문·가격대·자료·모델·질문 버전·추출 기준을 둔다. 현재 편집 값으로 과거 결과를 다시 설명하지 않는다.

판단 불가·해당 없음·미실시·오류·대기를 구분하고 전체 선택 회차의 인원을 분모로 유지한다. 가격대 미설정과 판매가격 미입력은 해당 질문만 미실시이며 판단 불가나 0%의 알려진 선택으로 바꾸지 않는다. 알려진 유한 선택의 근거는 비워 두고 입력 참조·원시 요청·선택 점수를 설명이나 소비자 확률로 부르지 않는다.

### Ten questions and comparisons

문제 관련성·현재 해결 수준·설명 명확성·개선 효익·차별성·주장 신뢰성·전환 부담·사용 의향·적정가격 인식·제시 조건 선택은 독립 질문이다. 최종 선택에도 다른 답을 주입하지 않는다. 사용 의향의 `사용을 고려함`은 중간 선택이며 판단 불가가 아니다. 이전 고정 v1의 여덟 질문 계약은 그대로 읽는다.

일곱 진단 누적 막대, 사용 의향·최종 선택 도넛, 가격대·연령/성별 분포를 직접 라벨·비율·인원으로 표시한다. 같은 인물의 사용 의향×선택 교차표는 조합이며 인과 설명이 아니다. 항목 비교표는 가장 많은 응답과 동률을 보여준다. 가격별 점은 다른 상품 정보·단위가 같고 판매가격만 다른 조건의 관찰 비율이다. 측정하지 않은 가격의 곡선·정확한 적정금액·지불 상한을 추론하지 않는다.

오른쪽 네 열 인물 목록·6명 페이지를 유지한다. 상세는 제시 조건 선택을 먼저 두고 열 개 질문을 표시한다. 그래프·교차표·범례 선택은 목록을 좁히며 선택 인물·회차·스크롤 문맥을 보존한다.

### Standalone report and export

HTML은 저장된 입력·집계·고정 조건으로만 만든다. 보고서용 LLM 호출은 없으며 CSS·SVG는 인라인, JavaScript·네트워크는 사용하지 않는다. 헤더는 실행 시점·선택 회차/N·상태를 표시한다. 비교·상품별 분포·집단·실행 조건·질문·확인 사례·상품 원문을 이어 둔다. 대표 사례는 최대 세 명의 검토용 선택이며 인터뷰 인용이나 대표 표본이 아니다.

보고서와 HTML·PDF·Markdown·CSV·JSON은 현재 선택한 한 회차를 사용한다. PDF는 스크립트가 꺼진 비영구 WKWebView에서 비동기 오프라인 인쇄 작업으로 만든다. 로컬 PDF 표본 `verification/survey-report.pdf`은 155,746바이트·12페이지다. 앱의 PDF 지원을 전체 네이티브 UI·IME 검증으로 확대하지 않는다.

## Do's and Don'ts

- **Do** 기존 시스템 글꼴·Operate 팔레트·아이템 탐색을 유지한다.
- **Do** 고정 입력·선택 회차·N·상태·원문을 함께 표시한다.
- **Do** 해당 없음·미실시·판단 불가·오류·대기를 각각 보존한다.
- **Do** 현재 기록과 로컬 이전 보관본 `.impeccable/archive/DESIGN-0.7.md`을 구분한다.
- **Don't** 집계·교차표·선택 점수·보고서를 모델 정확도나 소비자 확률로 표시한다.
- **Don't** 가격대 선택을 정확한 금액·지불 상한·가격 탄력성으로 표현한다.
- **Don't** 이전 네이티브·반복성 검증을 새 버전의 검증으로 이어 붙인다.

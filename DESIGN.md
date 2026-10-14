---
name: "Paneloom · 패널룸"
description: "상품 문서와 고정 표본의 응답을 함께 읽는 macOS 작업 화면과 독립 보고서"
colors:
  work: "#F4F3EF"
  sidebar: "#ECEFEB"
  paper: "#FFFEFA"
  ink: "#182B38"
  muted: "#586874"
  line: "#CAD3D7"
  accent: "#245C7A"
  accent-ink: "#FFFEFA"
  accent-hover: "#1C4D68"
  selected: "#DFE8ED"
  hover: "#D3E2EA"
  scrollbar-thumb: "#9AAEB9"
  positive: "#2F6E63"
  negative: "#647487"
  hold: "#AC792A"
  unknown: "#9298A1"
  danger: "#B24338"
  warning: "#805A1D"
  not-applicable: "#9B8C7A"
  not-run: "#CED2D1"
  pending: "#ACAFC1"
  work-dark: "#101D25"
  sidebar-dark: "#132530"
  paper-dark: "#172A36"
  ink-dark: "#EFF3F2"
  muted-dark: "#B6C5CE"
  line-dark: "#405563"
  accent-dark: "#91C2DC"
  accent-ink-dark: "#172A36"
  accent-hover-dark: "#AACFE2"
  selected-dark: "#263F4F"
  hover-dark: "#304B5C"
  scrollbar-thumb-dark: "#627889"
  positive-dark: "#78B6A3"
  negative-dark: "#9BAAB8"
  hold-dark: "#D3AB68"
  unknown-dark: "#8F929B"
  danger-dark: "#F3A196"
  warning-dark: "#D3AB68"
  not-applicable-dark: "#B5A38A"
  not-run-dark: "#525B5F"
  pending-dark: "#747C98"
  rr-band0: "#CBDCE6"
  rr-band1: "#88B0C6"
  rr-band2: "#4D85A4"
  rr-band3: "#245C7A"
  rr-band0-dark: "#385C73"
  rr-band1-dark: "#5686A2"
  rr-band2-dark: "#8EBBD2"
  rr-band3-dark: "#C5DFED"
  dialog-backdrop: "rgba(20,30,35,.25)"
typography:
  body:
    fontFamily: "-apple-system,BlinkMacSystemFont,\"Apple SD Gothic Neo\",sans-serif"
    fontSize: "14px"
    lineHeight: 1.45
  brand:
    fontFamily: "-apple-system,BlinkMacSystemFont,\"Apple SD Gothic Neo\",sans-serif"
    fontSize: "18px"
    fontWeight: 600
    letterSpacing: "-.02em"
  title:
    fontSize: "22px"
    fontWeight: 600
    letterSpacing: "-.025em"
  document-body:
    fontSize: "16px"
    lineHeight: 1.65
  document-heading:
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-.025em"
  document-section:
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1.4
  document-subheading:
    fontSize: "18px"
  field-label:
    fontSize: "13px"
  label:
    fontSize: "12px"
  document-diff:
    fontFamily: "ui-monospace,SFMono-Regular,monospace"
    fontSize: "13px"
    lineHeight: 1.6
  results-title:
    fontSize: "17px"
    fontWeight: 500
  results-section:
    fontSize: "15px"
    fontWeight: 500
  results-assessment:
    fontSize: "13px"
    fontWeight: 500
  result-summary:
    fontSize: "13px"
    lineHeight: 1.6
  report-body:
    fontFamily: "-apple-system,BlinkMacSystemFont,\"Apple SD Gothic Neo\",sans-serif"
    fontSize: "13px"
    lineHeight: 1.6
  report-title:
    fontSize: "30px"
    lineHeight: 1.25
    letterSpacing: "-.7px"
  report-section:
    fontSize: "23px"
    lineHeight: 1.3
  report-subheading:
    fontSize: "16px"
  report-note:
    fontSize: "11px"
  report-print-body:
    fontSize: "10.5pt"
    lineHeight: 1.5
  report-print-table:
    fontSize: "9pt"
rounded:
  flat: "0"
  progress: "4px"
  field: "6px"
  control: "7px"
  editor: "9px"
  dialog: "12px"
spacing:
  label-gap: "6px"
  compact-gap: "8px"
  control-gap: "12px"
  row-padding: "14px"
  group-gap: "18px"
  section-gap: "24px"
  heading-gap: "28px"
  chart-gap: "30px"
  page-inline: "32px"
  window-top: "45px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-quiet:
    textColor: "{colors.muted}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  product-field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.field}"
    padding: "7px 9px"
    height: "36px"
  item-tab-selected:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.accent}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  workflow-step-current:
    textColor: "{colors.accent}"
    typography: "{typography.field-label}"
    rounded: "{rounded.flat}"
    padding: "12px 0"
  editor:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.document-body}"
    rounded: "{rounded.editor}"
    padding: "24px 30px"
  response-person-selected:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.flat}"
    padding: "12px 3px"
  response-distribution-strip:
    backgroundColor: "{colors.line}"
    rounded: "{rounded.flat}"
    height: "14px"
    width: "100%"
  report-page:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.report-body}"
    rounded: "{rounded.flat}"
    padding: "42px 50px"
---

# Design System: Paneloom · 패널룸

## Overview

**Creative North Star: "같은 표본을 겹쳐 읽는 판"**

Paneloom(패널룸)은 상품 문서를 작성하고 같은 합성 인물 표본의 응답을 비교하는 작업 도구다. 겹친 두 판과 그 사이의 열린 통로를 브랜드 심벌로 사용한다. 광물청색(Field)은 작업의 시작·현재 위치·선택을 짚고, 밝은 종이 면과 짙은 청색 다크 면은 긴 문서와 밀도 높은 데이터를 받친다.

시스템 글꼴, 얇은 경계, 평면 도형을 유지한다. 시선은 상단의 다음 동작에서 입력·결과로 이어진다. 장식보다 고정한 상품·판매조건·표본·회차가 먼저 읽혀야 한다. 독립 보고서는 같은 내용을 읽고 인쇄하는 고정 라이트 문서다.

**Key Characteristics:**

- 겹친 판 심벌과 광물청색을 일관되게 사용한다.
- 브랜드, 응답 범주, 실행 상태를 서로 다른 역할로 표현한다.
- 문서·그래프·인물 데이터에 필요한 밀도와 여백을 구분한다.

프런트매터의 값이 규범이다. 색은 `web/style.css`·`web/results.css`, 보고서는 `src/persona_desktop/reporting.py`에 대응한다. 글꼴·간격·모서리 값은 현재 컴포넌트에서 추출한 공통 기준이며 CSS 변수로 존재한다는 뜻은 아니다. 도구용 확장은 `.impeccable/design.json`에 둔다.

## Colors

### Primary

광물청색(Field)의 `accent`는 심벌·주요 동작·현재 진행·링크에 쓴다. `accent-ink`는 주요 버튼 위의 글자, `accent-hover`는 그 버튼의 호버다. `selected`와 `hover`는 선택·호버 면을 구분한다. 가격대의 마지막 색과 같은 값이어도 두 역할을 합치지 않는다.

### Neutral

`work`는 작업 배경, `sidebar`는 실험 목록, `paper`는 입력·문서 면이다. `ink`는 본문, `muted`는 보조 정보와 입력 안내, `line`은 경계다. `scrollbar-thumb`는 스크롤 위치를 표시한다. 앱은 시스템의 `prefers-color-scheme`을 따라 같은 이름의 `-dark` 대응값을 사용한다.

### Response and state

`positive`·`hold`·`negative`는 응답 범주다. `unknown`·`not-applicable`·`not-run`·`danger`·`pending`은 각각 판단 불가·해당 없음·미실시·오류·대기다. `warning`은 실행·검토의 주의 문구다. 상태를 중간 응답으로 합치거나 브랜드 강조색으로 덮지 않는다.

가격 구간은 낮은 구간부터 `rr-band0` → `rr-band3`의 청색 명도 순서를 고정한다. 라이트는 밝은 색에서 짙은 색으로, 다크는 짙은 색에서 밝은 색으로 진행한다. 경계값·통화·결제 주기는 저장한 실행 조건에서 가져온다. 가격별 관측의 선택 비율 점은 `positive`를 쓴다.

독립 보고서와 앱 아이콘은 라이트 값을 고정한다. 보고서는 앱의 다크 색을 상속하지 않으며 응답·상태·가격 구간도 라이트 기준을 유지한다.

**The Role Separation Rule.** 브랜드 색은 동작·선택·탐색에 쓴다. 응답과 실행 상태는 해당 의미색으로 표시하며, 색만으로 의미를 전달하지 않는다.

## Typography

macOS 시스템 계열과 한국어 대체 글꼴을 공통으로 사용한다. 추가 웹폰트를 도입하지 않는다. 본문은 `body`, 브랜드 락업은 `brand`, 실험 제목은 `title`이다. 문서 편집기는 `document-*`, 결과는 `results-*`·`result-summary`, 독립 보고서는 `report-*` 계층을 따른다.

상품 편집기의 문단과 결과의 원문·요약은 최대 (75ch)로 읽기 폭을 제한한다. 독립 보고서는 페이지 너비를 따른다. 인원·비율·금액·내부 점수는 `tabular-nums`로 정렬한다. 고정폭 글꼴은 코드·문서 차이에만 쓴다. 화면 제목은 작은 글자의 과도한 굵기보다 크기와 간격으로 구분한다. 창 너비 (1000px) 이하의 실험 제목은 (20px)로 줄인다.

## Layout

왼쪽 고정 실험 목록은 (222px), 작업 여백은 상단·가로·하단 (45px 32px 30px)다. 창 너비 (1000px) 이하에서는 목록 (190px), 가로 여백 (24px)을 쓴다. 목록을 접으면 작업 화면이 전체 너비를 사용한다. 기본 창 (1220×860)과 최소 창 (900×650)에서 같은 흐름을 유지한다.

상품·판매조건·대상·평가 가격대의 입력 행은 (36px) 높이다. 결과의 반복·필터 입력은 (34px)이며 일반 버튼에는 고정 높이를 덧씌우지 않는다. 관련 필드는 짧게 묶고, 절은 `section-gap`·`heading-gap` 등 기존 간격으로 구분한다. 편집기의 안쪽 여백은 `editor`를 따르며 좁은 창에서는 (20px 24px)다.

결과는 왼쪽 그래프·오른쪽 인물 데이터의 두 열이다. 열 비율은 `minmax(0,1.3fr) minmax(0,1fr)`, 간격은 (24px)다. 오른쪽은 상단 (20px)에 고정하고 최대 `calc(100vh - 40px)` 안에서 스크롤한다. 결과 컨테이너 (620px) 이하에서는 한 열로 바꾸고 고정을 푼다. (380px) 이하에서는 히트맵을 세 칸씩 나누고 셀에 짧은 라벨을 붙인다.

독립 보고서는 최대 너비 (900px), 여백은 `report-page`를 따른다. 화면 (700px) 이하에서는 한 열·여백 (24px 20px)이다. 인쇄는 A4·페이지 여백 (16mm 15mm 17mm), 절별 페이지 나눔·표 머리 반복·행 분리 억제를 사용한다.

## Elevation & Depth

작업 화면은 면 색과 얇은 경계로 구분한다. 그림자는 원문·검토 대화상자에만 쓰며, 테마별 `shadow` 값은 sidecar에 기록한다. 보고서는 구분선과 절 간격으로 깊이를 표현하고 그림자를 쓰지 않는다. 호버가 카드 전체를 떠오르게 만들지 않는다.

## Shapes

필드·버튼·편집기·대화상자의 모서리는 프런트매터 `rounded`를 따른다. 표·히트맵·누적 막대·결과 행은 직선 경계를 유지한다. 브랜드 판의 큰 곡선을 모든 컴포넌트에 반복하지 않는다.

### Brand mark

표시 이름은 **Paneloom**, 한국어 이름은 **패널룸**이다. `web/brand-mark.svg`의 두 채움 경로를 기준으로 사용한다. 원본은 (200×200), 실제 도형 경계는 (8–192)이며 사방의 내장 여백은 (8단위·4%)다. 수직 통로의 (x=66–80·14단위) 간격을 비롯해 두 판의 상대 위치·곡선·열린 공간을 보존한다. 자르거나 회전·반전·재그리기하지 않는다.

앱 락업은 마크 (26×26px)·글자와의 간격 (10px), 보고서 푸터는 마크 (22×22px)·간격 (8px)을 사용한다. 이 내장 여백과 락업 간격이 현재의 보호 공간이다. 화면 사용은 (22px)보다 작게 줄이지 않고 통로가 읽히는지 확인한다. 옆에 이름이 있으면 마크는 장식으로 처리하고, 단독으로 쓰면 접근 가능한 이름을 제공한다.

`macos/AppIcon.svg`는 (1024×1024) 원본을 사용한다. 광물청색 판의 경계는 (72–952), 밝은 마크는 `translate(208 208) scale(3.04)`다. 아이콘 출력은 이 원본에서 만들며 별도의 로고 변형을 추가하지 않는다. 보고서는 같은 마크 경로를 인라인 SVG로 넣어 파일 외부 자원에 의존하지 않는다.

## Components

### Actions and workflow

주요·보조·조용한 버튼은 프런트매터의 세 변형을 사용한다. 일반 호버는 `hover`, 선택은 `selected`, 비활성은 불투명도 (.45)다. 키보드 포커스는 브랜드색 (2px) 윤곽선으로 표시한다. 버튼·링크·펼치기는 바깥 간격 (3px), 입력은 (1px)이다. 편집기는 포커스 시 경계색을 바꾼다. 버튼의 (.12s ease-out) 상태 전환은 `prefers-reduced-motion: no-preference`에서만 적용한다.

상품 입력 → 대상·실행 → 결과의 상단 진행 표시는 클릭하지 않는 목록이다. 현재 단계는 색과 (600) 굵기·`aria-current="step"`으로 표시한다. 이동은 상단 `이전`과 상태별 `다음`·`실험 시작`·`이어 실행`·`결과 보기`·`보고서 저장`으로 수행한다. 아이템 탭은 선택 상태를 유지한다.

실험이 없으면 `실험이 없습니다.`와 `새 실험`을 첫 화면에 둔다. 저장된 판단이 없으면 그 상태를 짧게 설명한다. 실행 중·중단·오류에는 상태와 가능한 복구 동작을 함께 표시한다. 문구는 대상과 동작을 직접 말하고 내부 식별자나 구현 용어를 사용자 흐름에 추가하지 않는다.

### Documents and fields

태그는 앱의 기본 언어로 표시한다. 현재 기본 언어는 한국어이며 태그만 바꾸는 언어 선택은 제공하지 않는다. 태그 ID와 대상 조건은 표시 언어와 분리하고 한국어·영어·일본어 검색을 유지한다. 결과와 보고서에도 같은 표시 언어를 적용한다.

상품 문서·판매조건·최대 지불 가격대의 평가 구간은 서로 구분한다. 문서는 같은 편집 영역에서 서식을 표시하며 빈 문단 안내는 저장 원문에 포함하지 않는다. 상품별 가격대는 자동 탐색을 기본으로 하고, 접힌 설정에서 통화·결제 주기와 직접 입력을 선택한다. 직접 입력은 양의 오름차순 경계값 세 개를 사용한다. 잘못된 필드는 `aria-invalid`·오류색·문제로 식별하고 수정 방법을 설명한다. 직접 입력한 경계값이 일부만 있거나 순서가 잘못되면 실행을 막고, 모두 비우면 해당 가격 평가는 미실시다. 자동 탐색이 구간을 확정하지 못하면 이유와 복제 후 직접 입력 동작을 표시한다. 본 평가와 재개는 확정 구간을 유지한다.

### Results and data boundaries

결과 상단은 상품 선택과 접힌 상품·실험 조건만 둔다. 상품 원문·판매조건·표본과 적용한 필터를 조건 안에서 확인한다. 상단 요약과 인물 목록 위 상품 설명은 반복하지 않는다. 질문 버전·탐색 과정·모델·인물 자료·seed는 실행 기록과 JSON 보고서에 보존하고 완료 화면 조건에는 표시하지 않는다. 그래프는 직접 라벨·비율·인원을 함께 표시한다. 범례·교차표·그래프 선택은 오른쪽 목록을 좁히고 선택 인물·회차·스크롤 문맥을 보존한다. 인물 목록은 네 열·여섯 명 페이지이며 사용 의향·최대 지불 가격대·가격 수용을 함께 읽는다. 최종 선택 문항과 사용 의향·최종 선택 교차표는 새 결과에서 표시하지 않는다.

판단 불가·해당 없음·미실시·오류·대기를 각 라벨과 상태색으로 보존한다. 질문 분포의 분모는 선택 회차의 전체 인원이다. 집단 히트맵은 해당 집단 인원, 교차표는 기록된 분모·제외 수를 표시한다. 저장되지 않은 값은 알려진 0이나 중간 응답으로 표시하지 않는다. 내부 점수는 선택 점수로 이름 붙이고 소비자 확률·실제 경험·생성된 설명으로 꾸미지 않는다. 교차표는 조합, 가격별 점은 관측 비율이며 인과·수요 곡선이나 측정하지 않은 가격을 추론하지 않는다.

**The Frozen Context Rule.** 결과와 내보내기는 저장된 입력·표본·선택 회차·분모를 함께 보여준다. 현재 편집 값으로 과거 실행을 설명하지 않는다.

### Standalone report

보고서는 저장된 입력·집계·고정 조건으로 만들며 추가 모델 호출을 하지 않는다. HTML·PDF는 상품명·Markdown 설명을 첫 페이지에 두고 개요, 기본 평가, 사용·가격, 연령·성별 그래프 순서로 페이지를 나눈다. 긴 원문은 잘라내지 않고 다음 페이지로 이어 둔다. 같은 원문·요약 목록·그래프를 반복하지 않는다. 상단 실행일·시간대·완료 상태·기본 1/1회차와 기술 메타데이터는 표시하지 않는다. 여러 회차에서는 선택 회차만 개요에 표시하고 분모·단위는 해당 그래프에 둔다. 오류·판단 불가·미실시 사유와 자료 귀속·라이선스는 유지한다. 전체 조건·문항·원문·기록은 JSON에 보존한다. CSS·SVG는 인라인, JavaScript·네트워크 자원은 사용하지 않는다. HTML·PDF·Markdown·CSV·JSON은 같은 선택 회차를 사용한다.

브랜드 변경은 표시 이름과 시각 자산에 적용한다. 패키지·번들 식별자·환경 변수·내부 ID와 `Application Support/Persona Lab` 저장 경로는 기존 호환을 유지한다.

## Do's and Don'ts

### Do

- **Do** 원본 마크의 통로·비율·여백과 테마별 색을 유지한다.
- **Do** 본문과 입력 안내는 대비 4.5:1 이상, 큰 글자는 3:1 이상으로 확인한다.
- **Do** 그래프에 직접 라벨·비율·인원을 함께 표시하고 선택 상태를 텍스트와 구조로도 드러낸다.
- **Do** 고정 입력·표본·선택 회차·실행 상태·원문을 결과와 보고서에서 확인할 수 있게 한다.

### Don't

- **Don't** 브랜드 색을 긍정 응답·오류·완료의 의미색으로 대체한다.
- **Don't** 로고에 그라데이션·외곽선·장식 그림자를 넣거나 판 사이 통로를 메운다.
- **Don't** 클릭하지 않는 진행 표시를 이동 버튼처럼 꾸민다.
- **Don't** 내부 선택 점수·응답 비율을 실제 소비자의 구매 확률이나 모델 정확도로 표현한다.
- **Don't** 가격대 응답을 정확한 적정금액·지불 상한·가격 탄력성으로 확장한다.
- **Don't** 표시 이름 변경을 내부 식별자·환경 변수·기존 저장 경로 변경으로 이어 붙인다.

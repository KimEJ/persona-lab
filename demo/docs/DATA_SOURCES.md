# 데이터 출처와 귀속

## NVIDIA 일본 팩

[공개 카드](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Japan), [파일 목록](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Japan/tree/f1f37019d8497143c507b3deb547e65646de2ab7/data)를 2026-10-05 UTC에 확인했다. 카드는 100만 레코드, 8개 Parquet와 약 1.73GB를 안내한다. 여섯 서술은 같은 UUID의 관점이다. 독립 인물을 600만 명으로 합산하지 않는다. 첫 shard125,000행의 UUID 고유성을 검증했다. 전체8파일의 인물 중복률은 검증하지 않았다.

출처 표기: NVIDIA; Atsunori Fujita, Vincent Gong, Masaya Ogushi, Kotaro Yamamoto, Yoshi Suhara, Dane Corneil, Yev Meyer (2025), *Nemotron-Personas-Japan: Synthetic Personas Aligned to Real-World Distributions*.

데이터는 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)이다. 팩 메타데이터와 보고서에 저자·자료명·원문 URL·라이선스 URL·변경 표시를 남긴다. 프로젝트 코드와 모델의 라이선스로 바꾸어 표시하지 않는다. 구매 이력·가격 민감도·예산을 원본에 제공된 사실로 추가하지 않는다.

먼저 받은 공개 미리보기는 고정된 [공식 Viewer first-rows API](https://datasets-server.huggingface.co/first-rows?dataset=nvidia%2FNemotron-Personas-Japan&config=default&split=train)의 53행, 응답 198,291 bytes이다. `truncated_cells`가 비어 있음을 검사했고 원문 값을 유지해 JSONL로 변환했다. Viewer 미리보기는 무작위나 대표 표본이 아니다. 원본 API 응답 SHA-256을 source version으로, JSONL SHA-256을 로컬 파일 무결성으로 기록한다. main revision은 공식 metadata API에서 별도로 관측했으며 Viewer 응답이 immutable Parquet revision에 고정됐다고 주장하지 않는다.

추가로 pinned revision의 `train-00000-of-00008.parquet` 하나를216,054,745bytes 다운로드했다. 공식 SHA-256과 일치하며125,000행/5row groups/22필드/125,000개 고유 UUID를 확인했다. raw 값·UUID·출처·버전·라이선스를 유지해 JSONL과 disk catalog로 변환했다. 처음53행은 관측한 Viewer53행과 raw 값이 같았다. 이는 Viewer API 자체의 immutable revision 보장을 뜻하지 않는다. Viewer 팩과 원본 팩의 겹치는UUID를 별도 독립 인물로 합산하지 않는다. 원본 선택 shard의 대표성은 입증하지 않았다. [Parquet 계약과 실측](PARQUET.md)에 파일SHA·복구·자원 범위를 기록했다.

## 실제 필드 목록과 정정

카드·Viewer API의 실제 열은 **UUID 포함 22열**, 서술 6개와 문맥 16개다. 초기 진행 보고에서 UUID를 별도로 더해 23열이라고 잘못 셌다. 실제 API `features`, 어댑터와 raw row의 필드 집합이 일치하는 회귀로 이를 확인하고 정정했다. 원문 필드는 삭제하거나 합치지 않았다.

| 분류 | 필드 | Viewer 타입 |
| --- | --- | --- |
| 식별 | `uuid` | string |
| 같은 인물의 여섯 관점 | `professional_persona`, `sports_persona`, `arts_persona`, `travel_persona`, `culinary_persona`, `persona` | string |
| 서술 문맥 | `cultural_background`, `skills_and_expertise`, `skills_and_expertise_list`, `hobbies_and_interests`, `hobbies_and_interests_list`, `career_goals_and_ambitions` | string |
| 인구·지역 문맥 | `sex`, `marital_status`, `education_level`, `occupation`, `region`, `area`, `prefecture`, `country` | string |
| 나이 | `age` | int64 |

`*_list`도 문자열이다. Python `eval`을 사용하지 않는다. raw field와 확장 필드를 보존하며 없는 필드, null, 빈 문자열을 구분한다. source/version/license/origin/field provenance/content hash는 원문과 별도로 유지한다.

## Synthetic fixture

`synthetic-fixture`의 4개 프로필은 이 프로젝트에서 명시적으로 만든 테스트 자료다. NVIDIA 인물이나 파생 소비자 관측 자료가 아니다. fixture 원문에 구매 성향을 넣지 않았다. 테스트 예산은 `experiment.assumptions`의 별도 가정이다. 프로필에는 여섯 관점, null·미제공·빈 문자열, 확장 필드를 의도적으로 섞었다.

`LicenseRef-Project-Fixture`는 자체 테스트 자료를 외부 CC BY 데이터와 구분하는 내부 표식이다. 프로젝트 코드·fixture의 공개 배포 라이선스는 아직 확정하지 않았다. 이 표식을 공인 라이선스나 외부 데이터 약관이라고 설명하지 않는다.

같은 Viewer payload hash를 다시 가져온 메뉴 항목은 동일 53명의 재게시 스냅샷이며 별도 독립 인물로 합산하지 않는다. `persona-sensitivity.json`의 반대 필요 사례도 프로젝트 자체 합성 입력이고 NVIDIA 원문과 분리되어 있다.

## 안전한 가져오기

Viewer import는 고정 공식 API와 응답1MB 상한을 사용한다. Parquet import는 고정 revision/공식 파일목록 또는 명시적 로컬 파일을 사용한다. 공식 license/revision/SHA·UUID·타입을 검사하고 중복 UUID와 원문 변경을 거부한다. 해시로 새 팩 이름을 만들고 manifest를 마지막에 게시한다. UI는 arbitrary URL/업로드/경로 이탈을 받지 않는다. CLI 로컬 경로는 사용자가 명시하며 출처 JSON이 필수다. 로컬 게시자·라이선스는 제공 메타데이터임을 표시한다. row-group cursor·prefix SHA·disk UUID index로 취소/재개하며 기존 팩을 덮어쓰지 않는다. 전체 데이터 대표성·팩 통합 중복 검사·원본100만 인물 실험은 후속 단계다.

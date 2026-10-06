# 새 checkout에서 실행하기

이 저장소는 소스·테스트·문서·작은 자체 synthetic fixture만 포함한다. NVIDIA 인물 원문, 모델 weight, 원본/변환 Parquet 데이터, 가상환경, 실행 DB/log/PID/cache와 상세 검증 산출물은 로컬에 보존하며 업로드하지 않는다. 코드·자체 fixture의 배포 라이선스는 아직 확정하지 않았다. 비공개 저장소 생성은 배포 라이선스를 정하는 행위가 아니다.

## 기본 Mock 데모

기존 Python3.12 이상으로 프로젝트 폴더에서 실행한다. 모델·데이터를 자동 다운로드하지 않는다.

```sh
sh tools/demo.sh start
sh tools/demo.sh status
sh tools/demo.sh stop
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

처음에는 자체4명 패널과 Mock으로 동작한다. 주소는 loopback `http://127.0.0.1:8787`이며 이번 사용자 환경에서는 IAB만 사용한다. 다른 프로세스가8081·8082·8787을 점유하면 실행기는 종료시키지 않고 안내한다. 전역 사용자 설정은 변경하지 않는다.

기본 Python에서 Parquet와 공개 원본 검사12개는 선택 준비 전 skip된다. PyArrow를 준비하면 자체 Parquet 검사10개가 활성화되고, 선택적 공개 소형 샘플을 준비하면 원본 검사2개가 활성화된다. 이 Mac의 실제50개 통과 기록과 소스만 있는 checkout의 준비 상태를 구분한다.

## 선택적 테스트 도구·데이터·모델

다음 명령은 요청할 때만 네트워크/격리 설치를 수행한다. 앱 시작은 이를 실행하지 않는다.

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run test:dom
python3 tools/prepare_public_sample.py
```

DOM 시험은 실행 중인 loopback 앱과 jsdom을 사용하며 렌더링된 브라우저 검증은 아니다. 공개 샘플 명령은 고정된 공식 NVIDIA metadata/Viewer endpoint, 응답1MB 제한, CC BY4.0/UUID/잘림 검사와 원본 hash를 적용한다. 전체 Parquet나 모델을 받지 않는다. 기존 로컬 샘플이 있으면 보존한다. 실제 모델 smoke는 해당 모델을 준비하고 명시적으로 실행할 때만 호출된다.

- [데이터 출처·22필드·CC BY4.0 귀속](DATA_SOURCES.md)
- [원본 Parquet 고정 revision/SHA·선택 PyArrow·취소/재개](PARQUET.md)
- [Qwen/Julia 고정 revision/SHA·공식 다운로드·격리 환경](MODEL.md)
- [검증 명령·실측 범위·unknown/예산/순서 민감성](VERIFICATION.md)
- [인물·실험·백엔드·체크포인트 계약](CONTRACTS.md)

`STATUS.json`, `PROJECT_FILES.txt`, 상세 `verification`은 이 Mac의 로컬 기록이며 Git checkout에 포함되지 않는다. 원본125,000명 입력, Viewer53명 추론, 별도1명 Julia 접점과 실제 행동 정확도의 미검증 상태는 문서에 남긴다. 새 장비에서는 완료 실험이 이미 존재한다고 가정하지 않는다.

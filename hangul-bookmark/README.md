# Hancom Agent 사용·개발 안내

`0.6.0-dev.2`는 Windows 한글에 연결해 HWP·HWPX의 본문, 수식, 표, 사진, 쪽 설정을 다룹니다. [설치와 요청 예시](../README.md)

## 문서 선택과 편집

- **열린 창**을 편집하려면 “지금 열린 한글 문서”라고 지정하세요. 여러 문서가 열려 있으면 작업할 창을 고릅니다. 선택한 문단이나 셀을 작업하려면 한글에서 범위를 먼저 선택하세요. 결과는 창에 반영되며 저장은 한글에서 직접 합니다.
- **파일 수정본**을 만들려면 HWP·HWPX 경로를 전달하거나 파일 선택을 요청하세요. 작업을 마친 문서는 저장하고 닫은 뒤 선택합니다. 수정본은 원본과 같은 형식으로 저장합니다.
- **입력 위치**는 문장, 제목, 빈 문단, 표·셀, 한글에서 선택한 범위나 기존 책갈피로 지정할 수 있습니다. 동일한 문구가 반복되면 주변 문맥이나 등장 순서를 함께 알려주세요.
- **사진과 수식**은 개체로 다룹니다. 수식 입력에 LaTeX를 쓸 수 있고, 사진 속 내용은 내장된 그림을 열어 판독합니다. 흐린 기호나 모호한 위치는 확인한 뒤 처리합니다.

## 문서 읽기와 검증

선택한 문서의 스냅샷으로 `read_document`와 `find_targets`를 처리합니다. 다음 페이지에는 같은 `revision`과 `next_cursor`를 전달합니다. 한 작업에서 이미 읽은 범위와 대상 식별자를 재사용하세요. 읽기 오류를 복구하거나 변경된 문서를 새로 확인할 때는 첫 페이지에서 `refresh=true`를 사용할 수 있습니다. 파일이 외부에서 변경됐거나 선택 영역이 달라진 경우에는 문서를 다시 선택합니다.

편집 단계는 적용 직전의 대상 및 문서 상태를 검증합니다. 파일 방식은 임시 사본을 검증한 뒤 수정본을 저장합니다. 열린 창 편집은 작업 전 사본을 남깁니다. 중간 실패로 일부 변경 가능성이 표시되면 같은 요청을 새 ID로 반복하기 전에 현재 창과 반환된 백업을 확인하세요.

## 연결 진단과 테스트

- **연결 상태만 확인**하려면 Codex에서 한글 버전과 연결 상태 확인을 요청하거나 `python launch.py --check`를 실행합니다.
- **임시 문서로 테스트**하려면 Codex에 “Hancom Agent 플러그인 테스트해줘”라고 요청하거나 `python launch.py --smoke`를 실행합니다. 설치 중 한 번 실행하려면 `setup.ps1`에 `-SmokeTest`를 추가합니다.
- 전용 도구가 보이지 않으면 [로컬 MCP 연결 절차](skills/hangul-bookmark/references/local-connection.md)를 참고하세요.

## 개발 자료

플러그인은 Python·pyhwpx와 로컬 표준 입출력 MCP로 구성됩니다. 한글 자동화 작업은 순차 실행합니다. 환경 진단, 문서 및 책갈피 선택, 내용 변환과 삽입, 문서 읽기와 검색, 편집, 이미지 읽기를 아홉 개의 도구로 제공합니다.

[구조 편집 API](skills/hangul-bookmark/references/structure-editing.md) · [문단·수식 편집 API](skills/hangul-bookmark/references/editing.md) · [수식 변환](skills/hangul-bookmark/references/equations.md) · [이미지 읽기](skills/hangul-bookmark/references/images.md) · [시험 기록](TEST-RESULTS.md)

자동 검사는 플러그인 폴더에서 `python -m pytest tests -q`로 실행합니다. 실제 한글 통합 시험은 사용자 문서와 분리된 새 폴더를 지정합니다.

```powershell
python integration_structure_check.py --output C:/새시험폴더/core
```

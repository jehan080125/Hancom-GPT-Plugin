# Hancom Agent

Hancom Agent `0.6.0-dev.2`는 Windows 한글의 HWP·HWPX 문서를 Codex에서 읽고 편집하는 로컬 플러그인입니다.

## 할 수 있는 일

| 대상 | 기능 |
| --- | --- |
| 본문·수식 | 문장, 선택 범위, 빈 문단, 표 셀을 지정해 글과 수식을 입력·교체·삭제합니다. LaTeX는 한글에서 편집할 수 있는 수식 개체로 넣습니다. |
| 사진 | 문서에 내장된 사진 속 글이나 수식을 읽습니다. 지정한 위치에 사진을 삽입하고 교체·삭제하거나 크기를 바꿀 수 있습니다. |
| 표 | 표를 만들고 셀에 글·수식·사진을 채웁니다. 행·열 추가와 삭제, 셀 병합과 비우기, 병합 셀 분할을 지원합니다. |
| 서식·쪽 | 글꼴·글자 크기·문단 정렬, 용지·여백, 머리말·꼬리말, 각주·미주, 쪽 번호를 편집할 수 있습니다. |

## 설치

Windows에 한컴 한글 2022 이상, Python 3.10 이상, Codex 데스크톱 앱과 `codex` 명령이 필요합니다. 실제 시험한 한글 빌드는 `12.0.0.535`입니다. [시험 기록](hangul-bookmark/TEST-RESULTS.md)

PowerShell에서 다음 명령을 실행합니다.

```powershell
git clone --branch preview/hancom-agent-0.6.0 https://github.com/jehan080125/Hancom-GPT-Plugin.git
cd Hancom-GPT-Plugin
./hangul-bookmark/setup.ps1 -RegisterModule
codex plugin marketplace add "$PWD"
codex plugin add hangul-bookmark@hangul-local
```

Codex 앱을 다시 시작하고 플러그인 목록에서 **Hancom Agent**를 사용합니다. 설치 폴더를 옮겼다면 옮긴 폴더에서 연결 설정을 다시 생성하세요.

`-RegisterModule`은 현재 Windows 사용자에게 한글 자동화 보안 모듈을 등록합니다. 해당 모듈을 로드한 자동화 인스턴스에서 파일 접근 승인 창을 생략합니다. [보안 모듈 안내](hangul-bookmark/security/SOURCE.md)

## 사용 예시

> 지금 열린 한글 문서의 두 번째 표에서 빈칸에 풀이와 수식을 써줘.

> 지금 선택한 문단에서 계산 오류를 찾아 수정해줘.

> 첫 번째 그림을 첨부한 사진으로 교체하고, 마지막 줄의 수식 개체만 삭제해줘.

> 이 HWPX 파일의 ‘실험 결과’ 제목 아래에 표를 넣고 수정본을 만들어줘.

열린 문서는 현재 창에서 편집합니다. 내용을 확인한 뒤 한글에서 `Ctrl+S`로 저장하세요. 파일을 선택해서 편집하면 원본 형식의 별도 수정본을 만듭니다. 파일 방식에서는 대상 문서를 먼저 저장하고 닫아 주세요.

요청을 처리할 때 선택한 문서의 분석 결과를 페이지 조회와 검색에 재사용합니다. 읽기가 실패하거나 문서가 바뀌었다는 오류가 있을 때 새로 읽습니다. 편집 직전에는 대상이 여전히 같은지 확인합니다.

## 플러그인 테스트

Codex에 **“Hancom Agent 플러그인 테스트해줘”**라고 요청하세요. 임시 HWP·HWPX에서 열기, 입력, 편집, 저장과 재열기를 시험하고 결과를 알려줍니다. 터미널에서는 설치 폴더의 `hangul-bookmark` 안에서 `python launch.py --smoke`로 실행할 수 있습니다. 일반 문서 작업에서는 테스트를 자동 실행하지 않습니다.

## 적용 범위

사진 편집은 실제 위치를 확인할 수 있는 내장 그림을 대상으로 합니다. 표의 셀 분할은 병합된 셀을 기본 격자로 되돌립니다. 메모 답글, 일반 셀의 임의 분할, 개체·서식 변경 추적은 지원 범위 밖입니다.

[상세 사용·개발 안내](hangul-bookmark/README.md) · [구조 편집 API](hangul-bookmark/skills/hangul-bookmark/references/structure-editing.md)

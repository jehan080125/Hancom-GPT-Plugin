# Hancom-GPT-Plugin

**Hangul Bookmark Writer** — Codex에서 전달한 글·LaTeX 수식·문제 사진을 Windows 한글 문서의 **책갈피 위치**에 작성하는 로컬 플러그인입니다. 수식은 그림이 아닌 한글에서 편집할 수 있는 수식 개체로 생성합니다.

현재 버전: **0.2.1**

## 필요한 환경

- Windows PC와 설치된 한컴 한글
- Codex 데스크톱 앱
- Python 3.10 이상과 인터넷 연결(최초 라이브러리 설치에 사용)
- Codex 플러그인 등록에 사용할 `codex` 명령

**한글 2022 이후는 지원 목표입니다.** 실제 시험한 버전은 한글 2022 **12.0.0.535**이며, 한글 2024와 이후 모든 버전을 시험한 것은 아닙니다. 실행 전에 실제 버전과 필수 API를 검사합니다. 자세한 범위는 [시험 기록](hangul-bookmark/TEST-RESULTS.md)을 참고하세요.

## 설치

### 1. 저장소 내려받기

GitHub의 **Code → Download ZIP**으로 내려받아 압축을 풀거나, Git이 설치되어 있다면 아래 명령을 실행합니다.

```powershell
git clone https://github.com/jehan080125/Hancom-GPT-Plugin.git
cd Hancom-GPT-Plugin
```

내려받은 폴더는 설치 후에도 유지하세요. 폴더를 옮겼다면 연결 설정을 다시 생성하고 플러그인을 다시 설치해야 합니다.

### 2. Python 라이브러리와 한글 연결 설정

저장소의 `hangul-bookmark` 폴더에서 PowerShell을 열어 실행합니다.

```powershell
cd hangul-bookmark
./setup.ps1 -RegisterModule
```

특정 Python을 사용하려면 다음처럼 지정합니다.

```powershell
./setup.ps1 -Python 'C:\설치된Python폴더\python.exe' -RegisterModule
```

설치 프로그램은 플러그인 전용 폴더에 `pyhwpx`, `mcp`, `Pillow`를 설치하고 연결 설정을 만듭니다. 임시 문서로 파일 열기·책갈피 이동·수식 삽입·저장·재열기를 시험합니다.

`-RegisterModule`은 **현재 Windows 사용자**의 한컴 자동화 설정에 `HangulBookmark` 보안 모듈을 등록하는 선택입니다. 해당 모듈을 로드한 자동화 인스턴스의 파일 접근 승인 창을 생략하며, 시스템 전체 보안 수준을 낮추는 기능은 아닙니다. 모듈 등록을 원하지 않으면 옵션을 빼되, 기본 파일 작업은 모듈 로드가 확인되어야 시작합니다. 시험에 실패하면 설치 완료로 간주하지 않습니다.

저장소에는 한컴 DLL을 포함하지 않습니다. 등록 프로그램은 설치된 pyhwpx의 모듈을 찾습니다. 다른 모듈이 필요한 환경에서는 [한컴 공식 개발 자료](https://developer.hancom.com/hwpautomation)의 보안 모듈을 `hangul-bookmark/security/FilePathCheckerModule.dll`로 준비한 뒤 다시 등록·검사하세요. [모듈 안내](hangul-bookmark/security/SOURCE.md)도 확인하세요.

### 3. Codex에 플러그인 등록

**저장소 루트 폴더**에서 실행합니다. 아래 `C:\실제경로\Hancom-GPT-Plugin`은 자신의 다운로드 경로로 바꾸세요.

```powershell
codex plugin marketplace add 'C:\실제경로\Hancom-GPT-Plugin'
codex plugin add hangul-bookmark@hangul-local
```

Codex 앱의 플러그인 목록에서 **Hangul Bookmark Writer**를 활성화하세요. 앱을 다시 열고 새 대화에서 플러그인을 선택해 사용합니다. Codex 앱이 설치되어 있어도 `codex` 명령을 찾지 못한다면 먼저 CLI 명령의 실행 경로를 확인하세요.

## 책갈피 만들기

1. 한글에서 문서를 엽니다.
2. 본문 또는 표 셀에서 내용을 넣을 위치에 커서를 둡니다.
3. 한글의 메뉴 검색에서 **책갈피** 기능을 찾아 실행합니다.
4. 이름을 `1`, `풀이 1`처럼 지정해 책갈피를 넣습니다.

글을 선택하지 않고 커서 위치에 넣는 **점 책갈피**를 권장합니다. 책갈피와 누름틀은 서로 다릅니다. 대화에 지정하는 이름은 공백까지 실제 책갈피 이름과 같아야 합니다.

## 사용 방법

### 열린 문서에 바로 작성

한글 문서를 열어 둔 상태에서 Codex 대화에 플러그인을 선택하고 요청합니다.

> 지금 열린 한글 문서의 책갈피 '1'에 수식 E = mc^2를 넣어줘.

> 지금 열린 한글 문서의 책갈피 '풀이 1'에 첨부한 문제 사진의 풀이를 작성해줘.

문서가 여러 개 열려 있으면 PC의 선택 창에서 대상을 고릅니다. **창에 작성한 뒤 자동 저장하지 않습니다.** 내용을 확인하고 한글에서 `Ctrl+S`로 직접 저장하세요. 작업 중에는 같은 문서를 동시에 편집하지 마세요.

문제 풀이 생성은 사용자가 요청한 경우에 수행합니다. 원문을 옮기는 요청에는 임의의 풀이·요약·교정을 추가하지 않습니다.

### 파일을 선택해 수정본 만들기

> 한글 파일 선택해줘.

PC에 파일 선택 창이 나타납니다. `.hwp` 또는 `.hwpx` 파일을 선택하고 책갈피를 고르세요. 대화에서 책갈피 이름을 직접 지정해도 됩니다.

> 책갈피는 '풀이 1'이야. 다음 글과 수식을 그대로 작성해줘.

최초에는 `원본이름_수정본.hwp`처럼 별도 파일을 생성합니다. 같은 이름이 이미 있으면 번호를 붙이며, 원본 형식과 원본 파일을 유지합니다. 같은 문서 선택으로 이어서 작성하면 수정본에 계속 저장합니다. 파일 방식에서는 대상 파일을 한글에서 저장하고 닫은 뒤 작업하세요.

### 텍스트·수식·이미지

- 본문은 책갈피 위치의 글꼴·크기·문단 서식을 따릅니다.
- LaTeX는 지원하는 표현을 한글 수식 문법으로 변환합니다.
- 사진의 글·수식은 Codex가 읽어 편집 가능한 내용으로 작성합니다. 그래프·기하 도형은 필요한 영역을 잘라 그림으로 삽입합니다.
- 불명확한 기호나 지원하지 않는 수식은 추측해서 저장하지 않고 확인합니다.
- 미리보기는 사용자가 요청할 때 제공합니다.
- 같은 책갈피에 반복 작성하면 새 내용이 앞선 내용보다 앞에 들어갑니다. 기존 내용을 교체하는 기능은 아닙니다.

수식의 지원 예시는 [수식 참고 자료](hangul-bookmark/skills/hangul-bookmark/references/equations.md)를 참고하세요.

## 연결 문제 해결

**“플러그인 도구가 제공되지 않는다”**

0.2.1은 Codex가 거부하던 절대 Python 실행 경로 설정을 수정한 버전입니다. 설치 폴더에서 설정을 다시 생성한 뒤 플러그인을 다시 등록하고 Codex를 재시작하세요.

```powershell
cd hangul-bookmark
python configure.py
codex plugin add hangul-bookmark@hangul-local
```

다른 Python이나 의존성 폴더를 지정해 설치했다면 같은 Python으로 `configure.py --deps '실제의존성폴더'`를 실행하세요. 현재 등록 상태는 `codex mcp list`로 확인할 수 있습니다. 전용 도구가 누락된 환경을 위한 [로컬 MCP 연결 절차](hangul-bookmark/skills/hangul-bookmark/references/local-connection.md)도 포함되어 있습니다.

**“보안 모듈 등록 또는 파일 접근 실패”**

설치 폴더에서 `./setup.ps1 -SkipInstall -RegisterModule`로 등록과 연결 시험을 다시 실행하세요. 기본 실행은 모듈 로드 실패 시 파일 작업을 중단합니다. DLL 파일의 존재만으로 정상 연결을 판단하지 마세요.

**“책갈피 없음 / 파일 잠금”**

책갈피 이름과 선택한 문서를 확인하세요. 파일 수정본 방식의 잠금 오류는 대상 문서를 저장·닫은 뒤 다시 선택해 해결합니다. 열린 창 방식은 문서를 닫지 않고 사용합니다.

**“입력 중 오류 / 시간 초과”**

일부 내용이 이미 입력되었을 수 있습니다. 같은 내용을 새 요청으로 반복 삽입하지 말고 현재 창과 반환된 작업 전 백업을 확인하세요. 열린 문서의 기존 사용자 입력까지 자동으로 실행 취소하거나 창을 닫지는 않습니다.

## 지원 범위와 제한

본문·표 셀·점 책갈피·범위 책갈피를 지원합니다. PDF 입력, 글상자·머리말·꼬리말·각주·미주 내부 작성, 기존 내용 교체, 그래프의 한글 도형 재구성은 지원하지 않습니다.

표 구조를 유지하지만 고정 높이 셀의 잘림이나 복잡한 페이지 배치는 직접 확인해야 합니다. 수식 스크립트와 개체 검사 통과가 모든 수식의 화면 표시까지 보장하지는 않습니다.

문서 경로·요청 기록과 작업 전 백업은 로컬 상태 폴더에 보관됩니다. 연결 프로그램은 문서를 외부 서버에 전송하지 않습니다. 대화에 전달한 내용은 사용 중인 Codex 서비스의 처리 범위를 따릅니다.

## 개발 및 구성

```text
Hancom-GPT-Plugin/
├─ README.md
├─ .agents/plugins/marketplace.json
└─ hangul-bookmark/
   ├─ setup.ps1
   ├─ configure.py
   ├─ launch.py
   ├─ src/hangul_bookmark/
   ├─ skills/hangul-bookmark/
   ├─ tests/
   └─ TEST-RESULTS.md
```

노출 도구는 `check_environment`, `select_document`, `select_bookmark`, `preview_content`, `insert_content` 다섯 가지입니다. Python·pyhwpx·로컬 stdio MCP 서버로 구성하며 한글 COM 작업을 순차 실행합니다.

개발 검사 방법은 [플러그인 상세 안내](hangul-bookmark/README.md)를 참고하세요. PC별 연결 설정, Python 의존성, 문서·백업·개인 경로가 들어 있는 원시 시험 보고서는 저장소에 포함하지 않습니다.

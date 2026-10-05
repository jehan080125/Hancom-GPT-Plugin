# 한글 자동화 보안 모듈

이 공개 저장소에는 DLL을 포함하지 않습니다. `register_module.py`는 먼저 이 폴더의 `FilePathCheckerModule.dll`을 찾고, 없으면 설치한 pyhwpx 패키지의 같은 이름 모듈을 찾습니다.

필요하다면 [한컴 공식 자동화 개발 자료](https://developer.hancom.com/hwpautomation)의 `보안모듈(Automation).zip`에서 환경에 맞는 모듈을 준비하고 이 폴더에 `FilePathCheckerModule.dll`이라는 이름으로 놓으세요. DLL의 사용 조건은 원 제공 자료를 따릅니다.

이 프로젝트의 한글 2022 시험에 사용한 공식 샘플 DLL의 SHA-256은 `9ac5b97c47ac8aed1e8bca27a3eef39411361d8f68c262509f0c40a8f9d21bb6`입니다. 다른 DLL이나 다른 한글 빌드의 호환성을 보증하지 않습니다.

파일 접근을 허용하는 예제 모듈을 한글 `RegisterModule`로 로드하면 해당 자동화 인스턴스의 파일 승인 창이 생략됩니다. 선택한 파일과 작업 사본만 처리하는 제한은 연결 프로그램이 수행합니다. 등록은 `setup.ps1 -RegisterModule`을 사용자가 선택할 때 현재 사용자 레지스트리에 수행합니다.

DLL이나 등록 값의 존재만으로 성공을 판단하지 않습니다. `RegisterModule` 반환값과 실제 임시 문서 시험을 확인합니다. 기본 실행은 모듈 로드가 실패하면 파일 작업 전에 중단합니다.

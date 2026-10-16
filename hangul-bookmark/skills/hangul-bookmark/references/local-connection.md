# 전용 도구가 제공되지 않을 때

이 SKILL.md가 들어 있는 설치 패키지의 `mcp.json`을 읽어 `mcpServers.hangul-bookmark`를 확인한다. 다른 대화의 작업 폴더나 이전 문서 식별자를 가정하지 않는다. 설정의 PATH 첫 경로와 command를 결합하면 설정된 Python 실행 파일을 얻는다.

`scripts/mcp_bridge.py`는 설치된 MCP 서버에 표준 입출력으로 연결한다. 한 JSON 작업 안에서 연결을 유지하며 아홉 도구만 호출한다. 새 대화의 쓰기 가능한 폴더에 job.json을 만들고 설정된 Python으로 아래 스크립트를 실행한다. 작업 폴더는 자유롭게 선택하며 스크립트 경로는 이 스킬의 실제 설치 경로로 지정한다.

```powershell
& '설정된 Python 실행 파일' '이 스킬의 절대경로/scripts/mcp_bridge.py' --job 'job.json의 절대경로' --result '아직 없는 result.json의 절대경로'
```

열린 문서에 책갈피 `1`과 수식 `E=mc^2`를 지정한 사용자 요청의 예시:

```json
[
  {"id":"check","tool":"check_environment","arguments":{"run_smoke":true}},
  {"id":"document","tool":"select_document","arguments":{"mode":"open"}},
  {"id":"bookmark","tool":"select_bookmark","arguments":{"document_id":{"$ref":"document.document_id"},"name":"1"}},
  {"id":"write","tool":"insert_content","arguments":{"document_id":{"$ref":"document.document_id"},"bookmark":"1","request_id":"새 요청마다 생성하고 재시도에는 유지하는 UUID","blocks":[{"type":"equation","format":"latex","display":"block","script":"E=mc^2"}]}}
]
```

각 단계의 ok=false면 다음 단계를 실행하지 않는다. 문서가 여러 개면 서버가 로컬 선택 창을 표시한다. 결과에 pending이 남거나 실행이 끊겼으면 해당 도구가 이미 수행되었을 수 있다. 기록을 확인하고 임의로 새 요청 ID를 만들어 다시 쓰지 않는다. 브리지는 오류를 자동 재시도하지 않는다. 결과 파일에는 문서 경로 등 로컬 정보가 포함된다.

전용 도구가 없는 것과 서버 실행 실패는 구분해서 설명한다. 실행 권한 문제는 환경의 정상적인 승인 절차로 처리하고, 보안 설정을 낮추거나 전역 한글 창을 임의로 제어하지 않는다. 작성 성공은 도구의 실제 반환 결과로 판단하며 열린 창은 saved=false이다.

0.3.0 읽기·범위 편집에는 [편집 규격](editing.md)을 따른다. 먼저 읽기/검색 작업의 결과를 확인하고, 그때 얻은 document_id·revision·target_id로 다음 JSON 작업을 구성한다. 이전 작업 결과 파일을 덮어쓰거나 불확실한 요청을 새 ID로 반복하지 않는다. $ref는 이전 단계의 객체 키와 배열 인덱스(예: found.matches.0.target_id)를 참조할 수 있다.

read_image의 이미지 응답은 브리지가 결과 파일 옆의 결과이름-images 폴더에 PNG로 저장하고 image_paths를 반환한다. 그 실제 파일을 이미지 보기 도구로 열어 확인한다. 경로/메타데이터만 읽고 사진을 판독했다고 하지 않는다. [이미지 규격](images.md)을 참고한다.

# 내용 블록

도구: check_environment, select_document, select_bookmark, preview_content, insert_content. 임의 한글 명령·Python 실행 도구는 없다.

```json
[
  {"type":"text","text":"함수 "},
  {"type":"equation","format":"latex","script":"f(x)=\\frac{x^2}{2}","display":"inline"},
  {"type":"text","text":"를 고려한다."},
  {"type":"paragraph_break"},
  {"type":"equation","format":"latex","script":"\\int_0^1 x^2 dx=\\frac{1}{3}","display":"block"},
  {"type":"image","path":"C:/data/figure.png","crop":[40,80,700,500]}
]
```

본문의 개행은 문단 구분으로 처리한다. block 수식은 독립 문단, inline은 현재 문장에 삽입한다. crop은 원본 픽셀 좌표 [왼쪽, 위, 오른쪽, 아래], 오른쪽·아래는 영역에 포함하지 않는다. 생략하면 전체 그림이다. 원본 비율을 유지하고 현재 본문/셀 너비 안에 놓는다. `uncertain:true,reason:"..."` 블록은 저장 전체를 거부한다.

최대 2,000 블록, 텍스트·수식 합계 200,000자, 수식 20,000자, 이미지 4,000만 픽셀. 파일 선택 전의 preview_content는 문서를 수정하지 않는다. 결과 counts의 text_blocks는 본문 조각 수이며 실제 문단 수와 다르다. paragraph_breaks는 명시된 문단 구분 수(독립 수식이 자동으로 만든 문단은 별도)다.

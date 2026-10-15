# 한글 수식 문법과 변환

자동 변환은 아래 범위의 보수적 부분집합이다. 알 수 없는 명령·사용자 매크로는 오류로 돌려준다. 수식 스크립트 보존과 개체 생성 검사는 수학적 동치성의 증명이 아니다. 새로운 복잡한 표기는 사용자 원문과 실제 한글 표시를 대조한다.

| 표기 | LaTeX | 한글 스크립트 |
|---|---|---|
| 분수 | `\frac{a}{b}` | `{a} over {b}` |
| 첨자 | `x_{i}^{2}` | `x_{i} ^{2} ` |
| 제곱근 | `\sqrt{x}` | `sqrt {x}` |
| n제곱근 | `\sqrt[n]{x}` | `root {n} of {x}` |
| 합 | `\sum_{i=1}^{n} i` | `sum _{i=1} ^{n} i` |
| 적분 | `\int_0^1 x dx` | `int _0 ^1 x dx` |
| 괄호 | `\left( x \right)` | `LEFT ( x RIGHT )` |
| 행렬 | `\begin{pmatrix}a&b\\c&d\end{pmatrix}` | `LEFT ( matrix {a & b # c & d} RIGHT )` |

그리스 문자, sin/cos/tan/log/ln/lim, 곱·합·적분, 일부 관계·화살표를 지원한다. 행렬은 matrix/pmatrix/bmatrix, 같은 열 수만 허용한다. 중첩 행렬, cases, align, 사용자 매크로, LaTeX 문서 전체는 지원하지 않는다. 모델은 명확히 대응하는 원문만 직접 한글 문법으로 작성할 수 있고, 거부된 표현을 추측해 우회하지 않는다.

한글 API는 Bookmark action의 Name·Command(0 생성/1 이동), EquationCreate action의 String·BaseUnit을 사용한다. BaseUnit은 현재 글자 Height를 따른다. 누름틀 MoveToField와 혼용하지 않는다. 새로운 한글 버전은 실제 smoke 시험을 통과해야 한다.

공식·원개발자 자료: [pyhwpx API](https://martiniifun.github.io/pyhwpx/core.html), [한컴 수식 API](https://forum.developer.hancom.com/t/topic/2882), [한컴 책갈피 API](https://forum.developer.hancom.com/t/topic/2040), [한컴 자동화](https://developer.hancom.com/hwpautomation).

## 첨자 뒤 공백 (0.2.2)

위첨자와 아래첨자의 묶음이 끝나면 공백 한 칸을 넣는다. 중괄호를 유지하며 중첩된 첨자에도 각각 적용한다. LaTeX 변환과 직접 한글 스크립트 입력 모두 연결 프로그램이 이 규칙을 적용한다.

- `2^{2k}+1` → `2^{2k} +1`
- `2^2k+1` → `2^2k +1`
- `x_{i+1}+y` → `x_{i+1} +y`
- `x_i^2+y` → `x_i ^2 +y`

중괄호 없는 한글 첨자는 공백·연산자·다음 첨자 등 구분자까지를 묶음으로 읽는다. 여러 항이 들어가는 첨자는 중괄호로 명시한다. 이미 있는 뒤 공백은 한 칸으로 정리한다. 큰따옴표 안의 문자 그대로의 ^와 _는 바꾸지 않으며 일반 본문 블록도 바꾸지 않는다.

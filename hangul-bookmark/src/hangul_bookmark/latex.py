"""A conservative parser: unsupported commands fail rather than disappear."""
import re
from .errors import WriterError

COMMANDS = {n: n for n in (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi "
    "pi rho sigma tau upsilon phi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega "
    "sin cos tan cot sec csc sinh cosh tanh log ln exp lim max min det gcd sum int prod inf"
).split()}
COMMANDS.update({"infty": "inf", "cdot": "cdot", "times": "times", "div": "div",
                 "le": "<=", "leq": "<=", "ge": ">=", "geq": ">=", "neq": "!=",
                 "ne": "!=", "pm": "+-", "mp": "-+", "approx": "approx",
                 "rightarrow": "rarrow", "to": "rarrow", "partial": "partial",
                 "nabla": "nabla", "in": "in", "notin": "notin", "ldots": "ldots",
                 "cdots": "cdots", "vdots": "vdots", "ddots": "ddots"})

class Parser:
    def __init__(self, source):
        self.s, self.i = source, 0

    def fail(self, message):
        raise WriterError("UNSUPPORTED_LATEX", f"{message} (위치 {self.i})")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i].isspace(): self.i += 1

    def group(self):
        self.ws()
        if self.i >= len(self.s) or self.s[self.i] != "{": self.fail("중괄호 인수가 필요합니다")
        self.i += 1
        return self.sequence("}")

    def sequence(self, end=None):
        out = []
        while self.i < len(self.s):
            c = self.s[self.i]
            self.i += 1
            if c == end: return "".join(out)
            if c == "}": self.fail("닫는 중괄호가 짝을 이루지 않습니다")
            if c == "{": out.append("{" + self.sequence("}") + "}"); continue
            if c != "\\":
                if c in "&%#$": self.fail(f"지원하지 않는 문자: {c}")
                out.append(c); continue
            match = re.match(r"[A-Za-z]+", self.s[self.i:])
            if not match:
                if self.i < len(self.s) and self.s[self.i] in ",;! ":
                    self.i += 1; out.append(" "); continue
                self.fail("지원하지 않는 이스케이프")
            cmd = match.group(); self.i += len(cmd)
            if cmd in ("frac", "dfrac", "tfrac"):
                a, b = self.group(), self.group(); out.append("{" + a + "} over {" + b + "}")
            elif cmd == "sqrt":
                self.ws(); index = None
                if self.i < len(self.s) and self.s[self.i] == "[":
                    stop = self.s.find("]", self.i + 1)
                    if stop < 0: self.fail("근호 차수의 대괄호가 닫히지 않았습니다")
                    index = convert(self.s[self.i + 1:stop]); self.i = stop + 1
                body = self.group()
                out.append("sqrt {" + body + "}" if index is None else "root {" + index + "} of {" + body + "}")
            elif cmd in ("left", "right"):
                self.ws()
                if self.i >= len(self.s) or self.s[self.i] not in "()[]|.": self.fail("지원하지 않는 가변 괄호")
                delimiter = self.s[self.i]; self.i += 1
                out.append(" " + cmd.upper() + " " + delimiter + " ")
            elif cmd == "begin":
                raw_start = self.i; env = self.group()
                if env not in ("matrix", "pmatrix", "bmatrix"): self.fail("지원하지 않는 수식 환경: " + env)
                marker = "\\end{" + env + "}"; stop = self.s.find(marker, self.i)
                if stop < 0: self.fail("행렬 환경이 닫히지 않았습니다")
                body = self.s[self.i:stop]; self.i = stop + len(marker)
                rows = re.split(r"\\\\", body)
                cells = [r.split("&") for r in rows]
                if not cells or any(len(r) != len(cells[0]) for r in cells): self.fail("행렬의 열 개수가 다릅니다")
                matrix = "matrix {" + " # ".join(" & ".join(convert(x.strip()) for x in r) for r in cells) + "}"
                if env == "pmatrix": matrix = "LEFT ( " + matrix + " RIGHT )"
                if env == "bmatrix": matrix = "LEFT [ " + matrix + " RIGHT ]"
                out.append(matrix)
            elif cmd in COMMANDS: out.append(" " + COMMANDS[cmd] + " ")
            else: self.fail("지원하지 않는 LaTeX 명령: \\" + cmd)
        if end: self.fail("중괄호가 닫히지 않았습니다")
        return "".join(out)


def space_after_scripts(script):
    """Terminate each HWP superscript/subscript operand with one space.

    Braced operands use their matching closing brace; unbraced HWP operands
    continue to whitespace, an operator, or another structural delimiter.
    Quoted HWP text is opaque, including any literal ^ or _ inside it.
    """
    pairs, stack, opaque = {}, [], set()
    i = 0
    while i < len(script):
        c = script[i]
        if c == '"':
            end = script.find('"', i + 1)
            end = len(script) - 1 if end < 0 else end
            opaque.update(range(i, end + 1))
            i = end + 1
            continue
        if c == '{': stack.append(i)
        elif c == '}' and stack: pairs[stack.pop()] = i
        i += 1

    ends = set()
    delimiters = set('^_{}+-=<>*/(),;[]|&#' + '−±×÷≤≥≠')
    for i, c in enumerate(script):
        if c not in '^_' or i in opaque: continue
        start = i + 1
        while start < len(script) and script[start].isspace(): start += 1
        if start == len(script):
            raise WriterError("INVALID_EQUATION", "첨자 내용이 없습니다.")
        if script[start] == '{':
            if start not in pairs:
                raise WriterError("INVALID_EQUATION", "첨자 중괄호가 맞지 않습니다.")
            end = pairs[start] + 1
        elif script[start] == '"':
            end = start + 1
            while end < len(script) and end in opaque: end += 1
        else:
            end = start
            if script[end] in '+-−': end += 1
            operand_start = end
            while end < len(script) and not script[end].isspace() and script[end] not in delimiters and end not in opaque:
                end += 1
            if end == operand_start:
                raise WriterError("INVALID_EQUATION", "첨자 내용은 중괄호로 묶어 전달하세요.")
        ends.add(end)

    out, i = [], 0
    while i < len(script):
        out.append(script[i]); i += 1
        if i in ends:
            out.append(' ')
            while i < len(script) and script[i].isspace(): i += 1
    return ''.join(out)

def validate_script(script):
    if not isinstance(script, str) or not script.strip():
        raise WriterError("INVALID_EQUATION", "빈 수식은 작성할 수 없습니다.")
    if len(script) > 20000 or "\\" in script or "$" in script or "\x00" in script:
        raise WriterError("INVALID_EQUATION", "한글 수식 문법이 필요합니다. LaTeX는 format=latex로 전달하세요.")
    depth = 0
    for c in script:
        if c == "{": depth += 1
        elif c == "}": depth -= 1
        if depth < 0: raise WriterError("INVALID_EQUATION", "수식 중괄호가 맞지 않습니다.")
    if depth: raise WriterError("INVALID_EQUATION", "수식 중괄호가 맞지 않습니다.")
    result = space_after_scripts(script)
    if len(result) > 20000:
        raise WriterError("INVALID_EQUATION", "공백 처리 후 수식이 20,000자를 초과합니다.")
    return result

def convert(source):
    if not isinstance(source, str) or len(source) > 20000:
        raise WriterError("INVALID_EQUATION", "수식은 20,000자 이내 문자열이어야 합니다.")
    source = source.strip()
    for a, b in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if source.startswith(a) and source.endswith(b) and len(source) >= len(a) + len(b):
            source = source[len(a):-len(b)]; break
    try:
        return validate_script(Parser(source).sequence().strip())
    except RecursionError:
        raise WriterError("INVALID_EQUATION", "수식의 중첩이 너무 깊습니다.") from None

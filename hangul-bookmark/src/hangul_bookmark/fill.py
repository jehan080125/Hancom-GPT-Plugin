"""Fill explicitly selected empty paragraphs without creating bookmarks."""
from . import content, document as dm


def compile_edits(doc, edits):
    if any(e.get('type') != 'insert_blocks' for e in edits):
        dm.fail('INVALID_EDIT', '빈칸 입력과 기존 내용 수정은 별도 요청으로 실행하세요.')
    ops = []
    seen = set()
    total = 0
    block_count = 0
    for edit in edits:
        if edit.get('uncertain'):
            dm.fail('UNCERTAIN_CONTENT', '불명확한 입력 내용을 먼저 확인하세요.')
        ranges = dm.expand(doc, edit.get('target_id'))
        if len(ranges) != 1:
            dm.fail('INVALID_EDIT', '입력할 빈 문단을 하나씩 지정하세요.')
        r = ranges[0]
        p = doc['paragraphs'][r['paragraph']]
        if edit.get('target_id') != p['id'] or edit.get('expected_text') != '':
            dm.fail('INVALID_EDIT', '빈 문단의 target_id와 expected_text=""가 필요합니다.')
        if p['scope'] == 'excluded' or not p.get('mapped'):
            dm.fail('UNMAPPED_LOCATION', '실제 위치가 검증된 본문·표 셀만 입력할 수 있습니다.')
        if p['parts'] or p['length']:
            dm.fail('TARGET_NOT_EMPTY', '입력 대상에 내용이나 개체가 있습니다. 다시 읽고 위치를 확인하세요.')
        if p['index'] in seen:
            dm.fail('OVERLAPPING_EDITS', '같은 빈 문단의 입력을 하나로 합치세요.')
        seen.add(p['index'])
        blocks = content.normalize(edit.get('blocks'))
        if any(b['type'] == 'image' or (b['type'] == 'text' and '\t' in b['text']) for b in blocks):
            dm.fail('INVALID_CONTENT', '빈칸 직접 입력은 글·문단 구분·수식을 지원합니다. 표 구조나 그림을 추가하지 않습니다.')
        total += sum(len(b.get('text', '')) + len(b.get('script', '')) for b in blocks)
        block_count += len(blocks)
        if total > 200000 or block_count > 2000:
            dm.fail('INVALID_CONTENT', '한 요청은 2,000블록·200,000자 이내여야 합니다.')
        lines = [[]]
        for b in blocks:
            if b['type'] == 'paragraph_break':
                lines.append([])
            elif b['type'] == 'equation' and b['display'] == 'block':
                if lines[-1]:
                    lines.append([])
                lines[-1].append(b)
                lines.append([])
            else:
                lines[-1].append(b)
        ops.append(dict(r, type='insert_blocks', blocks=blocks, lines=lines))
    return ops


def expected_events(blocks):
    events = []
    for b in blocks:
        if b['type'] == 'text':
            events.extend(('text', c) for c in b['text'])
        else:
            events.append(('equation', ''.join(b['script'].split())))
    return events


def verify(before, after, ops):
    if before['table_structure'] != after['table_structure'] or before['bookmarks'] != after['bookmarks']:
        dm.fail('VERIFY_FAILED', '표 구조 또는 책갈피 구성이 바뀌었습니다.')
    by_index = {op['paragraph']: op for op in ops}
    count = len(before['paragraphs']) + sum(len(op['lines']) - 1 for op in ops)
    if len(after['paragraphs']) != count:
        dm.fail('VERIFY_FAILED', '지정한 칸 밖의 문단 개수가 달라졌습니다.')
    cursor = 0
    for old in before['paragraphs']:
        op = by_index.get(old['index'])
        if op is None:
            new = after['paragraphs'][cursor]
            for key in ('scope', 'cell_path', 'paragraph_shape', 'style', 'attributes'):
                if old[key] != new[key]:
                    dm.fail('VERIFY_FAILED', '요청 밖 문단 위치·서식이 바뀌었습니다.')
            if dm.expected_atoms({'paragraphs': [old]}, []) != dm.expected_atoms({'paragraphs': [new]}, []):
                dm.fail('VERIFY_FAILED', '요청 밖 내용·글자 서식이 바뀌었습니다.')
            cursor += 1
            continue
        for line in op['lines']:
            new = after['paragraphs'][cursor]
            for key in ('scope', 'cell_path', 'paragraph_shape', 'style'):
                if old[key] != new[key]:
                    dm.fail('VERIFY_FAILED', '입력 내용이 지정한 칸을 벗어나거나 문단 서식이 바뀌었습니다.')
            actual = []
            for part in new['parts']:
                if part['kind'] == 'text':
                    actual.extend(('text', c) for c in part['text'])
                    if part['style'] != old.get('empty_style', {}):
                        dm.fail('VERIFY_FAILED', '입력한 글자의 원래 서식이 유지되지 않았습니다.')
                elif part['kind'] == 'equation':
                    actual.append(('equation', ''.join(part['script'].split())))
                    if part['size_pt'] != old.get('empty_style', {}).get('size_pt'):
                        dm.fail('VERIFY_FAILED', '수식의 기본 크기가 대상 칸과 다릅니다.')
                else:
                    dm.fail('VERIFY_FAILED', '입력하지 않은 개체가 생겼습니다.')
            if actual != expected_events(line):
                dm.fail('VERIFY_FAILED', '지정한 칸의 글·수식·문단 순서가 요청과 다릅니다.')
            cursor += 1


def apply_native(hancom, before, ops, ready):
    from . import native_edit
    h = hancom.hwp
    for op in sorted(ops, key=lambda o: o['paragraph'], reverse=True):
        ready()
        p = before['paragraphs'][op['paragraph']]
        h.Cancel()
        if not h.set_pos(*p['native'], 0):
            dm.fail('POSITION_MAP_FAILED', '빈칸 위치로 이동하지 못했습니다.')
        charshape, parashape = h.get_charshape(), h.get_parashape()
        size = int(h.CharShape.Item('Height'))
        for i, line in enumerate(op['lines']):
            if i:
                ready()
                if not h.Run('BreakPara'):
                    dm.fail('HANCOM_FAILED', '문단 나누기 실패')
                h.set_charshape(charshape)
                h.set_parashape(parashape)
            for b in line:
                ready()
                if b['type'] == 'text':
                    if not h.insert_text(b['text']):
                        dm.fail('HANCOM_FAILED', '본문 입력 실패')
                else:
                    hancom.equation(b['script'], size)
                h.set_charshape(charshape)
                h.set_parashape(parashape)
    ready()
    after = native_edit.inspect(hancom, validate_target=ready)
    verify(before, after, ops)
    h.Cancel()
    counts = content.counts([b for op in ops for b in op['blocks']])
    counts['filled_paragraphs'] = len(ops)
    return {'counts': counts, 'revision': after['revision'],
            'verification': {'content': True, 'outside_scope': True, 'format': True,
                             'table_structure': True, 'equation_scripts': True, 'bookmarks_unchanged': True},
            'warnings': ['표 셀의 고정 높이에 따른 시각적 넘침은 한글에서 확인하세요.'],
            'excluded': before['excluded']}

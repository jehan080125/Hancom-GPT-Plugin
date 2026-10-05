"""Inspect Hancom's HWPML export, not binary HWP offsets."""
import collections
import xml.etree.ElementTree as ET
from .errors import WriterError

def tag(e): return e.tag.rsplit('}', 1)[-1].upper()

def parse(xml):
    try: return ET.fromstring(xml)
    except (ET.ParseError, TypeError): raise WriterError('EXPORT_FAILED', '한글 문서 구조를 읽지 못했습니다.') from None

def bookmarks(xml):
    root = parse(xml); result = []
    def walk(e, ancestors):
        kind = 'range' if tag(e) == 'FIELDBEGIN' and e.get('Type') == 'Bookmark' else 'point'
        name = e.get('Name') if tag(e) == 'BOOKMARK' or kind == 'range' else None
        if name:
            forbidden = {'HEADER', 'FOOTER', 'FOOTNOTE', 'ENDNOTE', 'TEXTBOX', 'DRAWTEXT'}
            scope = 'unsupported' if set(ancestors) & forbidden else ('table' if 'CELL' in ancestors else 'body')
            result.append({'name': name, 'scope': scope, 'kind': kind})
        for child in e: walk(child, ancestors + [tag(e)])
    walk(root, [])
    counts = collections.Counter(x['name'] for x in result)
    return [dict(x, ambiguous=counts[x['name']] != 1) for x in result]

def snapshot(xml):
    root = parse(xml)
    tables = []
    for e in root.iter():
        if tag(e) == 'TABLE':
            cells = []
            for c in e.iter():
                if tag(c) == 'CELL':
                    cells.append({k: v for k, v in c.attrib.items() if k in ('ColAddr', 'RowAddr', 'ColSpan', 'RowSpan', 'Width')})
            tables.append({'attributes': {k: v for k, v in e.attrib.items() if k in ('RowCount', 'ColCount', 'CellSpacing', 'RepeatHeader')}, 'cells': cells})
    eq = []
    for e in root.iter():
        if tag(e) == 'EQUATION':
            eq.append(''.join(x.text or '' for x in e.iter() if tag(x) == 'SCRIPT'))
    text = ''.join(e.text or '' for e in root.iter() if tag(e) == 'CHAR')
    events, anchors = [], {}
    def walk(e):
        t = tag(e)
        if t == 'CHAR': events.extend(('text', c) for c in (e.text or ''))
        elif t == 'EQUATION':
            events.append(('equation', ''.join(''.join(x.text or '' for x in e.iter() if tag(x) == 'SCRIPT').split())))
            return
        elif t == 'PICTURE': events.append(('image', '')); return
        elif t == 'BOOKMARK' or (t == 'FIELDBEGIN' and e.get('Type') == 'Bookmark'):
            anchors.setdefault(e.get('Name'), len(events))
        for c in e: walk(c)
    for body in root.iter():
        if tag(body) == 'BODY': walk(body)
    return {'tables': tables, 'equations': eq, 'text': text, 'bookmarks': bookmarks(xml), 'events': events, 'anchors': anchors}

def verify(before, after, blocks, bookmark=None):
    if before['tables'] != after['tables']:
        raise WriterError('VERIFY_FAILED', '표의 행·열·병합·너비 구조가 변경되어 저장을 취소합니다.')
    available = collections.Counter(after['equations'])
    needed = collections.Counter(before['equations'])
    needed.update(b['script'] for b in blocks if b['type'] == 'equation')
    def canonical(s): return ''.join(s.split())
    actual = collections.Counter(canonical(s) for s in after['equations'])
    expected = collections.Counter()
    for s, n in needed.items(): expected[canonical(s)] += n
    if any(actual[s] < n for s, n in expected.items()):
        raise WriterError('VERIFY_FAILED', '저장된 수식 개체가 요청과 일치하지 않습니다.')
    if bookmark is not None:
        index = before['anchors'].get(bookmark)
        if index is None: raise WriterError('VERIFY_FAILED', '책갈피의 문서 내 위치를 확인하지 못했습니다.')
        inserted_events = []
        for b in blocks:
            if b['type'] == 'text': inserted_events.extend(('text', c) for c in b['text'])
            elif b['type'] == 'equation': inserted_events.append(('equation', canonical(b['script'])))
            elif b['type'] == 'image': inserted_events.append(('image', ''))
        expected_events = before['events'][:index] + inserted_events + before['events'][index:]
        if after['events'] != expected_events:
            raise WriterError('VERIFY_FAILED', '책갈피의 작성 순서 또는 기존 본문·개체의 내용이 달라 저장을 취소합니다.')
    # Existing text must remain in order; inserted text must be present.
    it = iter(after['text'])
    if not all(any(x == c for x in it) for c in before['text']):
        raise WriterError('VERIFY_FAILED', '기존 본문의 순서 또는 내용이 변경되었습니다.')
    inserted = ''.join(b['text'] for b in blocks if b['type'] == 'text')
    it = iter(after['text'])
    if not all(any(x == c for x in it) for c in inserted):
        raise WriterError('VERIFY_FAILED', '작성한 본문을 저장 결과에서 확인할 수 없습니다.')
    oldnames = collections.Counter(b['name'] for b in before['bookmarks'])
    newnames = collections.Counter(b['name'] for b in after['bookmarks'])
    if any(newnames[n] < count for n, count in oldnames.items()):
        raise WriterError('VERIFY_FAILED', '기존 책갈피가 사라졌습니다.')
    oldkind = {b['name']: b.get('kind') for b in before['bookmarks']}
    newkind = {b['name']: b.get('kind') for b in after['bookmarks']}
    if any(newkind.get(n) != k for n, k in oldkind.items()):
        raise WriterError('VERIFY_FAILED', '책갈피의 점/범위 형태가 변경되었습니다.')

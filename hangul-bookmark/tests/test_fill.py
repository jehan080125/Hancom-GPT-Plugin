import copy
import pytest
from hangul_bookmark import document as d
from hangul_bookmark.errors import WriterError
from hangul_bookmark.fill import verify
from test_document import doc


def operation(m, blocks=None):
    return {'type': 'insert_blocks', 'target_id': m['paragraphs'][0]['id'],
            'expected_text': '', 'blocks': blocks or [{'type': 'text', 'text': '새 내용'}]}


def test_fill_empty_paragraph_and_multiline_equation():
    m = doc('')
    op = operation(m, [{'type': 'text', 'text': '문제\n풀이 '},
                       {'type': 'equation', 'format': 'latex', 'script': r'\frac{1}{2}'}])
    ops = d.compile_edits(m, [op])
    assert len(ops[0]['lines']) == 2
    assert ops[0]['lines'][1][1]['script'] == '{1} over {2}'
    assert not m['bookmarks']


@pytest.mark.parametrize('mutation', ['nonempty', 'control', 'unmapped', 'wrong_target', 'expected', 'duplicate', 'mixed'])
def test_fill_rejects_unsafe_targets(mutation):
    m = doc('')
    op = operation(m)
    edits = [op]
    if mutation == 'nonempty': m['paragraphs'][0]['length'] = 1
    if mutation == 'control': m['paragraphs'][0]['parts'] = [{'kind': 'control'}]
    if mutation == 'unmapped': m['paragraphs'][0]['mapped'] = False
    if mutation == 'wrong_target': op['target_id'] = 'all'
    if mutation == 'expected': del op['expected_text']
    if mutation == 'duplicate': edits.append(copy.deepcopy(op))
    if mutation == 'mixed': edits.append({'type': 'set_format', 'target_id': 'all', 'properties': {'size_pt': 12}})
    with pytest.raises(WriterError): d.compile_edits(m, edits)


def test_block_equation_has_explicit_paragraph_plan():
    m = doc('')
    ops = d.compile_edits(m, [operation(m, [{'type': 'text', 'text': '앞'},
        {'type': 'equation', 'script': 'x^{2}', 'display': 'block'}, {'type': 'text', 'text': '뒤'}])])
    assert [len(x) for x in ops[0]['lines']] == [1, 1, 1]


def test_fill_verifier_detects_outside_content_and_bookmarks():
    m = doc('', '<P ParaShape="0" Style="0"><TEXT CharShape="0"><CHAR>보존</CHAR></TEXT></P>')
    ops = d.compile_edits(m, [operation(m)])
    after = copy.deepcopy(m)
    filled = doc('새 내용')['paragraphs'][0]
    after['paragraphs'][0] = filled
    verify(m, after, ops)
    after['bookmarks'] = [{'name': 'unrequested'}]
    with pytest.raises(WriterError): verify(m, after, ops)
    after['bookmarks'] = []
    after['paragraphs'][1]['parts'][0]['text'] = '변경'
    with pytest.raises(WriterError): verify(m, after, ops)


def test_fill_verifier_rejects_wrong_cell_and_changed_character_style():
    m = doc('')
    ops = d.compile_edits(m, [operation(m)])
    after = doc('새 내용')
    after['paragraphs'][0]['cell_path'] = [{'table': 1}]
    with pytest.raises(WriterError): verify(m, after, ops)
    after['paragraphs'][0]['cell_path'] = []
    after['paragraphs'][0]['parts'][0]['style']['size_pt'] = 99
    with pytest.raises(WriterError): verify(m, after, ops)

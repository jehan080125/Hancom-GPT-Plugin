
"""Regression coverage for Hancom's whitespace-delimited script operands."""
import pytest
from hangul_bookmark.content import normalize
from hangul_bookmark.latex import convert, validate_script
from hangul_bookmark.errors import WriterError

@pytest.mark.parametrize('source,expected', [
    ('2^{2k}+1', '2^{2k} +1'),
    ('2^2k+1', '2^2k +1'),
    ('x_{i+1}+y', 'x_{i+1} +y'),
    ('x_i+y', 'x_i +y'),
    ('x_{i}^{2}', 'x_{i} ^{2} '),
    ('x_i^2+y', 'x_i ^2 +y'),
    ('2^{2^{k}+1}+x', '2^{2^{k} +1} +x'),
    ('x_{i_{j}+1}+y', 'x_{i_{j} +1} +y'),
    ('x_{i}   +y^2', 'x_{i} +y^2 '),
    ('x_i\t\n+y', 'x_i +y'),
    ('{x_i}+1', '{x_i }+1'),
    ('x^-2+1', 'x^-2 +1'),
    ('sum _{i=1}^{n} i', 'sum _{i=1} ^{n} i'),
    ('int _0^1 x dx', 'int _0 ^1 x dx'),
    ('"literal ^ and _"+x^2', '"literal ^ and _"+x^2 '),
    ('x^"a+b"+1', 'x^"a+b" +1'),
    ('a+b', 'a+b'),
])
def test_hwp_script_boundaries(source, expected):
    assert validate_script(source) == expected
    assert validate_script(expected) == expected  # Revalidation must not add spaces.

@pytest.mark.parametrize('fmt', ['hwp', 'latex'])
def test_insertion_and_preview_use_same_script_rule(fmt):
    block={'type':'equation','format':fmt,'script':'2^{2k}+x_{i+1}+1'}
    assert normalize([block])[0]['script']=='2^{2k} +x_{i+1} +1'

def test_nested_latex_fraction():
    assert convert(r'\frac{2^{2k}+1}{x_{i+1}}') == '{2^{2k} +1} over {x_{i+1} }'

@pytest.mark.parametrize('source',['x^','x_ ','x^+','x_^2'])
def test_missing_operand_rejected(source):
    with pytest.raises(WriterError): validate_script(source)

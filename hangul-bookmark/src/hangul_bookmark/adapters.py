"""Use common API first. Unseen builds must pass runtime feature/smoke tests."""
from .errors import WriterError

REQUIRED = ('Open', 'SaveAs', 'Clear', 'CreateAction', 'CreateSet', 'GetTextFile',
            'GetPos', 'SetPos', 'GetSelectedPos', 'InsertPicture', 'HAction', 'HParameterSet',
            'InitScan', 'GetText', 'ReleaseScan', 'MovePos')

def probe(hwp, version):
    if int(version[0]) < 12:
        raise WriterError('UNSUPPORTED_VERSION', '한글 2022 이전 버전입니다.')
    missing = []
    for name in REQUIRED:
        try:
            if getattr(hwp, name) is None: missing.append(name)
        except Exception: missing.append(name)
    if missing: raise WriterError('MISSING_API', '필요 API가 없습니다: ' + ', '.join(missing))
    return {'name': '2022-common' if int(version[0]) == 12 else 'newer-common-probe',
            'required_api': list(REQUIRED), 'object_selection_api': 'anchor-and-type-verified'}

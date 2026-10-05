param([string]$Python = 'python', [switch]$RegisterModule, [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$pluginDir = $PSScriptRoot
$depsDir = Join-Path $pluginDir 'runtime/deps'
if (-not $SkipInstall) {
    & $Python -m pip install --index-url https://pypi.org/simple --target $depsDir --upgrade 'pyhwpx==1.7.2' 'mcp==2.3.0' 'Pillow>=10,<13'
    if ($LASTEXITCODE -ne 0) { throw 'Python 의존성 설치 실패' }
}
$pythonPath = (& $Python -c 'import sys; print(sys.executable)').Trim()
$env:HANGUL_DEPS = $depsDir
if ($RegisterModule) {
    & $pythonPath (Join-Path $pluginDir 'register_module.py')
    if ($LASTEXITCODE -ne 0) { throw '현재 사용자 보안 모듈 등록 실패' }
}
& $pythonPath (Join-Path $pluginDir 'configure.py') --deps $depsDir
if ($LASTEXITCODE -ne 0) { throw 'MCP 연결 설정 실패' }
& $pythonPath (Join-Path $pluginDir 'launch.py') --smoke
if ($LASTEXITCODE -ne 0) { throw '한글 연결 시험 실패. 화면의 한글 승인 창과 오류를 확인하세요.' }
Write-Host '설정 완료. README.md의 Codex 플러그인 등록 방법을 따르세요.'

param([string]$Output = "")
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Set-Location -LiteralPath $repo
if (-not $Output) { $Output = Join-Path $repo ('artifacts/next-step/replay-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$Output = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $Output) { throw 'Replay requires a NEW output directory; old evidence is never overwritten.' }
New-Item -ItemType Directory -Path $Output | Out-Null
$env:PATH = "$repo/tools/toolchain/mingw64/mingw64/bin;$env:PATH"
function Invoke-Checked([string[]]$Arguments) {
    & python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: python $($Arguments -join ' ')" }
}
Invoke-Checked @('-m','cmake','-S','.','-B','build-next','-G','Ninja','-DCMAKE_BUILD_TYPE=Release',"-DCMAKE_CXX_COMPILER=$repo/tools/toolchain/mingw64/mingw64/bin/c++.exe", "-DCMAKE_C_COMPILER=$repo/tools/toolchain/mingw64/mingw64/bin/gcc.exe", "-DCMAKE_MAKE_PROGRAM=$repo/tools/toolchain/mingw64/mingw64/bin/ninja.exe")
Invoke-Checked @('-m','cmake','--build','build-next','-j','4')
& "$repo/build-next/photoengine_tests.exe" *> "$Output/unit-tests.log"
if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed' }
Invoke-Checked @('tools/next_step/reference.py','--out',"$Output/reference")
Invoke-Checked @('tools/next_step/rt_repeatability.py','--run',$Output)
Invoke-Checked @('tools/next_step/rt_stable.py','--run',$Output)
Invoke-Checked @('tools/next_step/core.py','--out',"$Output/core",'--section','all')
Invoke-Checked @('tools/next_step/contracts.py','--out',"$Output/contracts")
Invoke-Checked @('tools/next_step/darktable_controls.py','--out',"$Output/darktable")
Invoke-Checked @('tools/next_step/verify_reference.py','--run',$Output)
Invoke-Checked @('tools/next_step/analyze.py','--run',$Output)
Invoke-Checked @('tools/next_step/finalize.py','--run',$Output)
Write-Host "Evidence ready: $Output/index.html"
Write-Host "Human acceptance remains NOT_REVIEWED. G2 is not approved."

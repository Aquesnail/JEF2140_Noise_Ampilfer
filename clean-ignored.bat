@echo off
rem ===========================================================================
rem  clean-ignored.bat
rem
rem  Deletes everything that this repository's .gitignore covers - LTspice
rem  waveforms and logs, KiCad backups/autosaves/local history, caches, etc.
rem
rem  Deleting ignored files is DESTRUCTIVE: git cannot restore them. So the
rem  script previews every path with its total size and asks for confirmation
rem  first. Pass /y only when you are certain.
rem
rem  USAGE
rem    clean-ignored.bat            preview, ask, then delete
rem    clean-ignored.bat /y         delete without asking
rem    clean-ignored.bat /n         preview only - dry run, changes nothing
rem    clean-ignored.bat /deep      also remove ignored directories that hold
rem                                 their own nested git repo, e.g. .history/
rem    clean-ignored.bat /untrack   also un-track files that are already
rem                                 committed even though .gitignore matches
rem                                 them - uses git rm --cached, files stay put
rem    clean-ignored.bat /?         show this help
rem
rem  Flags can be combined, e.g.  clean-ignored.bat /n /deep
rem
rem  SAFETY NOTES
rem   - The repo root is located with git, so the script works from any
rem     sub-directory, including a double-click in Explorer.
rem   - Only IGNORED paths are removed. Tracked files and untracked-but-visible
rem     files are never touched - this script never passes -x to git clean.
rem   - A nested git repository is skipped unless /deep is given, so
rem     .history/ survives a plain run.
rem   - This file is intentionally ASCII-only so it behaves under any console
rem     code page.
rem
rem  For automation, set CI_NO_PAUSE=1 to suppress the final "Press any key".
rem ===========================================================================

setlocal EnableExtensions EnableDelayedExpansion

set "PROG=%~nx0"

rem ---------------------------------------------------------------- defaults
set "ASSUME_YES=0"
set "DRY_RUN=0"
set "DEEP=0"
set "UNTRACK=0"
set "SHOW_HELP=0"

rem ----------------------------------------------------------- parse options
:parse_args
if "%~1"=="" goto args_done
set "A=%~1"
if /i "%A%"=="/y"        set "ASSUME_YES=1"
if /i "%A%"=="--yes"     set "ASSUME_YES=1"
if /i "%A%"=="-y"        set "ASSUME_YES=1"
if /i "%A%"=="/n"        set "DRY_RUN=1"
if /i "%A%"=="/dry"      set "DRY_RUN=1"
if /i "%A%"=="--dry-run" set "DRY_RUN=1"
if /i "%A%"=="/deep"     set "DEEP=1"
if /i "%A%"=="--deep"    set "DEEP=1"
if /i "%A%"=="/untrack"  set "UNTRACK=1"
if /i "%A%"=="--untrack" set "UNTRACK=1"
if /i "%A%"=="/?"        set "SHOW_HELP=1"
if /i "%A%"=="-h"        set "SHOW_HELP=1"
if /i "%A%"=="--help"    set "SHOW_HELP=1"
shift
goto parse_args
:args_done

if "%SHOW_HELP%"=="1" goto usage

rem UTF-8 console so non-ASCII paths in git output display correctly.
chcp 65001 >nul 2>nul

echo.
echo ============================================================
echo   clean-ignored   -   purge everything .gitignore covers
echo ============================================================
echo.
if "%DRY_RUN%"=="1"    echo   Mode: DRY RUN - nothing will be deleted
if "%DEEP%"=="1"       echo   Mode: DEEP - nested git repos are included
if "%UNTRACK%"=="1"    echo   Mode: also un-track already committed files
if "%DRY_RUN%"=="1" echo.

rem ------------------------------------------------------------------- git
where git >nul 2>nul
if errorlevel 1 goto no_git

set "REPO_ROOT="
for /f "usebackq delims=" %%R in (`git rev-parse --show-toplevel 2^>nul`) do set "REPO_ROOT=%%R"
if not defined REPO_ROOT goto no_repo

echo   Repository : %REPO_ROOT%
if exist "%REPO_ROOT%\.gitignore" (
  echo   Rules file : .gitignore
) else (
  echo   Rules file : .gitignore not found - only global/info exclude rules apply
)
echo.

cd /d "%REPO_ROOT%" 2>nul
if errorlevel 1 goto no_cd

rem --------------------------------------------------------------- preview
set "TMP_LIST=%TEMP%\clean_ignored_%RANDOM%%RANDOM%.list"
set "TMP_SIZE=%TEMP%\clean_ignored_%RANDOM%%RANDOM%.size"

if "%DEEP%"=="1" (
  git -c core.quotepath=false clean -Xdnff > "%TMP_LIST%" 2>nul
) else (
  git -c core.quotepath=false clean -Xdn   > "%TMP_LIST%" 2>nul
)

set "COUNT=0"
for /f "usebackq delims=" %%L in ("%TMP_LIST%") do set /a COUNT+=1

if "%COUNT%"=="0" goto no_ignored

rem ------------------------------------------------------- total size (PS)
set "HUMAN_SIZE=unknown"
set "CI_LIST=%TMP_LIST%"
set "CI_SIZE=%TMP_SIZE%"
where powershell >nul 2>nul
if errorlevel 1 goto size_done
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $t=[int64]0; foreach($p in [System.IO.File]::ReadAllLines($env:CI_LIST)){ $p=$p.Trim(); if($p.StartsWith('Would remove ')){ $p=$p.Substring(13) }; $p=$p.Trim([char]34); if(-not $p){continue}; if(Test-Path -LiteralPath $p){ $i=Get-Item -LiteralPath $p -Force; if($i.PSIsContainer){ $s=(Get-ChildItem -LiteralPath $p -Recurse -Force -File | Measure-Object -Property Length -Sum).Sum; if($s){$t+=[int64]$s} } else { $t+=[int64]$i.Length } } }; $u=('' + $t + ' B'); if($t -ge 1KB){ $u=('{0:N1} KB' -f ($t/1KB)) }; if($t -ge 1MB){ $u=('{0:N2} MB' -f ($t/1MB)) }; if($t -ge 1GB){ $u=('{0:N2} GB' -f ($t/1GB)) }; [System.IO.File]::WriteAllText($env:CI_SIZE,$u)" >nul 2>nul
if exist "%TMP_SIZE%" set /p HUMAN_SIZE=<"%TMP_SIZE%"
if not defined HUMAN_SIZE set "HUMAN_SIZE=unknown"
:size_done

rem ------------------------------------------------------------ show list
echo   Paths matched by .gitignore that are present on disk:
echo.
set "SHOWN=0"
for /f "usebackq delims=" %%L in ("%TMP_LIST%") do (
  set "LINE=%%L"
  set "LINE=!LINE:Would remove =!"
  if !SHOWN! lss 40 (
    echo     !LINE!
    set /a SHOWN+=1
  )
)
if %COUNT% gtr 40 echo     ... and %COUNT% - 40 more
echo.
echo   Total: %COUNT% path^(s^), about %HUMAN_SIZE%.
echo   Tracked files are not affected.
echo.

if "%DRY_RUN%"=="1" goto after_clean

rem -------------------------------------------------------------- confirm
if "%ASSUME_YES%"=="1" goto do_clean

set "ANSWER="
set /p "ANSWER=Delete these %COUNT% path^(s^) permanently? type y to confirm: "
if /i "%ANSWER%"=="y"   goto do_clean
if /i "%ANSWER%"=="yes" goto do_clean
echo.
echo Aborted - nothing was changed.
goto after_clean

rem --------------------------------------------------------------- delete
:do_clean
echo.
echo Removing ...
if "%DEEP%"=="1" (
  git -c core.quotepath=false clean -Xdff
) else (
  git -c core.quotepath=false clean -Xdf
)
if errorlevel 1 (
  echo.
  echo [WARN] git clean reported an error, see output above.
) else (
  echo Done.
)

rem ------------------------------------------------------------- untrack
:after_clean
if not "%UNTRACK%"=="1" goto verify
call :do_untrack

rem --------------------------------------------------------------- verify
:verify
echo.
echo ------------------------------------------------------------
echo  Remaining ignored paths on disk:
set "LEFT=0"
for /f "usebackq delims=" %%L in (`git ls-files --others --ignored --exclude-standard 2^>nul`) do set /a LEFT+=1
echo    %LEFT%
echo.
echo  Working tree status:
git -c core.quotepath=false status --short
if errorlevel 1 echo    clean - no pending changes
echo ------------------------------------------------------------
goto final

rem =================================================================== subs
:do_untrack
set "TMP_U=%TEMP%\clean_ignored_u_%RANDOM%%RANDOM%.list"
git -c core.quotepath=false ls-files -c -i --exclude-standard > "%TMP_U%" 2>nul
set "UCOUNT=0"
for /f "usebackq delims=" %%L in ("%TMP_U%") do set /a UCOUNT+=1
if "%UCOUNT%"=="0" (
  echo.
  echo No committed file matches .gitignore - nothing to un-track.
  del /q "%TMP_U%" >nul 2>nul
  goto :eof
)
echo.
echo ------------------------------------------------------------
echo  Files that are committed but now matched by .gitignore:
for /f "usebackq delims=" %%L in ("%TMP_U%") do echo     %%L
echo.
echo  git rm --cached keeps them on disk and only unstages them.
if "%ASSUME_YES%"=="0" (
  set "UANS="
  set /p "UANS=Un-track these %UCOUNT% path^(s^)? type y to confirm: "
  if /i not "!UANS!"=="y" if /i not "!UANS!"=="yes" (
    echo Skipped - tracking unchanged.
    del /q "%TMP_U%" >nul 2>nul
    goto :eof
  )
)
for /f "usebackq delims=" %%L in ("%TMP_U%") do git rm --cached --quiet -- "%%L"
if errorlevel 1 (
  echo [WARN] some paths could not be un-tracked.
) else (
  echo Un-tracked %UCOUNT% path^(s^). Commit the change to make it permanent.
)
del /q "%TMP_U%" >nul 2>nul
goto :eof

rem ================================================================= routes
:no_git
echo [ERROR] git was not found on PATH.
echo         Install Git for Windows, or add it to PATH.
goto fail

:no_repo
echo [ERROR] This folder is not inside a git repository:
echo         %CD%
goto fail

:no_cd
echo [ERROR] Cannot enter the repository root:
echo         %REPO_ROOT%
goto fail

:no_ignored
echo   Nothing to clean - no ignored paths exist on disk.
echo.
if "%UNTRACK%"=="1" goto after_clean
goto final

rem ================================================================= final
:final
if exist "%TMP_LIST%" del /q "%TMP_LIST%" >nul 2>nul
if exist "%TMP_SIZE%" del /q "%TMP_SIZE%" >nul 2>nul
echo.
if not defined CI_NO_PAUSE if "%ASSUME_YES%"=="0" pause
endlocal
exit /b 0

:fail
if exist "%TMP_LIST%" del /q "%TMP_LIST%" >nul 2>nul
if exist "%TMP_SIZE%" del /q "%TMP_SIZE%" >nul 2>nul
echo.
if not defined CI_NO_PAUSE pause
endlocal
exit /b 1

:usage
echo.
echo clean-ignored.bat - delete everything .gitignore covers in this repo
echo.
echo   clean-ignored.bat            preview, ask, then delete
echo   clean-ignored.bat /y         delete without asking
echo   clean-ignored.bat /n         preview only - dry run
echo   clean-ignored.bat /deep      also remove ignored dirs holding nested repos
echo   clean-ignored.bat /untrack   also git rm --cached files already committed
echo   clean-ignored.bat /?         this help
echo.
echo Only ignored paths are removed; tracked and visible untracked files are
echo never touched. The script never passes -x to git clean.
echo.
endlocal
exit /b 0

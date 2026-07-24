@echo off
setlocal
rem Apply a standard unified diff from stdin without touching unrelated files.
git apply --whitespace=nowarn -
exit /b %errorlevel%

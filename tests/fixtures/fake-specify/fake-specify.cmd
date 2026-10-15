@echo off
rem T008: fake-specify Windows shim (for speckitGui.specifyCliPath)
rem ASCII-only: cmd.exe parses this file under the system codepage (GBK on zh-CN),
rem non-ASCII bytes corrupt batch line parsing.
node "%~dp0fake-specify.js" %*
exit /b %ERRORLEVEL%
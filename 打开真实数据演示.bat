@echo off
cd /d "%~dp0"
if exist "outputs\real_demo\index.html" (
    start "" "outputs\real_demo\index.html"
) else (
    echo Run this command from the project folder first:
    echo python run.py real-demo --data-dir D:\saitidata
    pause
)

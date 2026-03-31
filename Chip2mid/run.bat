@echo off
:: This tells the computer to use the Python inside your virtual environment
:: by using a full path to the interpreter and the script.
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
pause

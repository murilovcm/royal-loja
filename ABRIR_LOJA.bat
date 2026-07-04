@echo off
title Royal - Servidor da Loja
color 0E
cd /d "%~dp0"

echo.
echo    =========================================
echo       ROYAL - Iniciando sua loja...
echo    =========================================
echo.

rem Verifica se o Flask esta instalado; se nao, instala (so na 1a vez)
python -c "import flask" 2>nul
if errorlevel 1 (
    echo    Preparando pela primeira vez, aguarde...
    echo    ^(isso so acontece uma vez^)
    echo.
    python -m pip install flask >nul 2>&1
)

echo    Abrindo no navegador...
echo.
echo    Para DESLIGAR a loja: feche esta janela.
echo.

rem Abre o navegador na loja depois de 2 segundos
start "" cmd /c "timeout /t 2 >nul & start http://localhost:5000"

rem Liga o servidor (tenta python, depois py como reserva)
python app.py 2>nul
if errorlevel 1 py app.py

echo.
echo    O servidor parou. Pressione uma tecla para fechar.
pause >nul

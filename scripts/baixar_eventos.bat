@echo off
REM Baixa o eventos.xlsx (ou outro arquivo) da BeagleBone para esta mesma
REM pasta, no Windows. So dar duplo clique.
REM
REM Uso normal (sem nada digitado): baixa ~/Read_485_beaglebone/eventos.xlsx
REM Uso com nome de arquivo: baixar_eventos.bat outro_nome.xlsx
REM   arraste o arquivo ou chame do prompt: baixar_eventos.bat eventos2.xlsx

setlocal

set HOST=beaglebone.local
set USUARIO=debian
set PASTA_REMOTA=~/Read_485_beaglebone

if "%~1"=="" (
    set ARQUIVO=eventos.xlsx
) else (
    set ARQUIVO=%~1
)

echo Baixando %ARQUIVO% de %USUARIO%@%HOST% ...
echo (vai pedir a senha do usuario debian da BeagleBone)
echo.

scp "%USUARIO%@%HOST%:%PASTA_REMOTA%/%ARQUIVO%" "%~dp0%ARQUIVO%"

if errorlevel 1 (
    echo.
    echo FALHOU. Confira:
    echo   - a BeagleBone esta ligada e conectada ao notebook via USB?
    echo   - o arquivo %ARQUIVO% existe mesmo na BeagleBone?
    echo     ^(so existe depois de apertar X no monitor pelo menos uma vez^)
) else (
    echo.
    echo Pronto! Arquivo salvo em: %~dp0%ARQUIVO%
)

echo.
pause

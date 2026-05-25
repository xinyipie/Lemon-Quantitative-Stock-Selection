@echo off
chcp 65001 >nul
echo ========================================
echo   A股超短线AI交易助手
echo ========================================
echo.

echo [信息] 配置说明：
echo   - API密钥配置在 config.py 文件中
echo   - 也可以通过环境变量设置（优先级更高）
echo.

REM 激活虚拟环境
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo [信息] 虚拟环境已激活
) else (
    echo [警告] 虚拟环境不存在，使用系统Python
)

echo.
echo [信息] 启动程序...
echo ========================================
echo.

python main.py

echo.
echo ========================================
echo [信息] 程序执行完毕
pause

@echo off
REM ============================================================
REM 知微 ziwi SaaS — 本地开发环境一键启动 & 验证脚本
REM 用法: 双击运行或在命令行执行
REM ============================================================

echo ========================================
echo   知微 ziwi SaaS 开发环境验证脚本
echo ========================================
echo.

REM ---- 步骤 1: 检查 Docker ----
echo [1/5] 检查 Docker 环境...
docker --version >nul 2>&1
if %errorlevel% equ 0 (
    echo   ✅ Docker 已安装
    docker compose version >nul 2>&1
    if %errorlevel% equ 0 (
        echo   ✅ Docker Compose 已安装
    ) else (
        echo   ⚠️  Docker Compose 未安装
    )
) else (
    echo   ⚠️  Docker 未安装，请先安装 Docker Desktop
    echo      下载地址: https://www.docker.com/products/docker-desktop/
)
echo.

REM ---- 步骤 2: 启动依赖服务 ----
echo [2/5] 启动基础设施服务（PostgreSQL + Redis + MinIO + EMQX）...
cd /d "%~dp0"
docker compose up -d postgres redis minio emqx pgbouncer 2>nul
if %errorlevel% equ 0 (
    echo   ✅ 基础设施服务启动命令已执行
    echo   等待服务就绪...
    timeout /t 10 /nobreak >nul
) else (
    echo   ⚠️  启动失败，请检查 Docker 是否正常运行
)
echo.

REM ---- 步骤 3: 检查服务健康状态 ----
echo [3/5] 验证服务健康状态...

REM PostgreSQL
docker compose exec postgres pg_isready -U ziwi >nul 2>&1
if %errorlevel% equ 0 ( echo   ✅ PostgreSQL 运行正常 ) else ( echo   ⚠️  PostgreSQL 未就绪 )

REM Redis
docker compose exec redis redis-cli -a ziwi_redis_password ping 2>nul | find "PONG" >nul
if %errorlevel% equ 0 ( echo   ✅ Redis 运行正常 ) else ( echo   ⚠️  Redis 未就绪 )

REM MinIO
curl -s http://localhost:9000/minio/health/live >nul 2>&1
if %errorlevel% equ 0 ( echo   ✅ MinIO 运行正常 ) else ( echo   ⚠️  MinIO 未就绪 )

REM EMQX
curl -s http://localhost:18083/api/v5/status >nul 2>&1
if %errorlevel% equ 0 ( echo   ✅ EMQX 运行正常 ) else ( echo   ⚠️  EMQX 未就绪 )
echo.

REM ---- 步骤 4: 执行 DDL 脚本 ----
echo [4/5] 执行数据库 DDL 脚本...
set DB_PATH=..\..\01-数据库Schema设计文档\sql

for %%f in (%DB_PATH%\*.sql) do (
    echo   执行 %%~nxf...
    docker compose exec -T postgres psql -U ziwi -d ziwi < "%%f" >nul 2>&1
    if %errorlevel% equ 0 ( echo     ✅ %%~nxf 执行成功 ) else ( echo     ⚠️  %%~nxf 执行失败 )
)
echo.

REM ---- 步骤 5: 验证后端 ----
echo [5/5] 检查后端服务状态...
if exist ..\..\..\backend\app\main.py (
    echo   ✅ FastAPI 源码已就绪
    curl -s http://localhost:8000/health >nul 2>&1
    if %errorlevel% equ 0 (
        echo   ✅ FastAPI 服务运行正常
        echo   访问 http://localhost:8000/docs 查看 API 文档
    ) else (
        echo   ⚠️  FastAPI 服务未启动
        echo   请手动执行: cd backend ^&^& uvicorn app.main:app --reload
    )
) else (
    echo   ℹ️  后端代码尚未创建（等待脚手架搭建）
)
echo.

echo ========================================
echo   环境验证完成
echo ========================================
echo.
echo 访问地址:
echo   - API 文档:    http://localhost:8000/docs
echo   - 前端页面:    http://localhost:5173
echo   - MinIO 管理:  http://localhost:9001 (admin/ziwi_minio_password)
echo   - EMQX 管理:   http://localhost:18083 (admin/public)
echo.

pause

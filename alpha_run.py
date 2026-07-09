#!/usr/bin/env python3
"""知微 ziwi SaaS — Alpha 启动脚本
使用 SQLite 数据库启动后端和前端服务。
用法: python alpha_run.py
"""
import os, sys, subprocess, signal, time

BASE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE, "backend")
FRONTEND_DIR = os.path.join(BASE, "frontend")
DB_PATH = os.path.join(BASE, "ziwi_alpha.db")
BACKEND_PORT = 8000
FRONTEND_PORT = 5173

PYTHON = "C:/Users/Kane.liu/.workbuddy/binaries/python/versions/3.13.12/python.exe"
NODE = "C:/Users/Kane.liu/.workbuddy/binaries/node/versions/22.22.2/node.exe"

procs = []

def print_banner():
    print("=" * 60)
    print("  知微 ziwi SaaS — Alpha 测试环境")
    print("=" * 60)
    print()
    print(f"  后端 API:  http://localhost:{BACKEND_PORT}")
    print(f"  Swagger:   http://localhost:{BACKEND_PORT}/docs")
    print(f"  前端:      http://localhost:{FRONTEND_PORT}")
    print()
    print(f"  登录账号:  admin / admin123")
    print(f"               demo / admin123")
    print()
    print("  按 Ctrl+C 停止所有服务")
    print("=" * 60)
    print()

def start_backend():
    """Start backend with SQLite database override"""
    env = os.environ.copy()
    env["APP_ENV"] = "testing"
    env["DB_ECHO_SQL"] = "false"
    env["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "1440"
    env["APP_CORS_ORIGINS"] = "*"

    # Inject Python seed script that patches the database module
    patch_code = f"""
import os, sys
os.environ["APP_ENV"] = "testing"
os.chdir(r"{BACKEND_DIR}")
sys.path.insert(0, r"{BACKEND_DIR}")

# Override database module with SQLite
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import app.core.database as db_mod
SQLITE_URL = "sqlite+aiosqlite:///{DB_PATH}"
sqlite_engine = create_async_engine(SQLITE_URL, echo=False)
db_mod.engine = sqlite_engine
db_mod.async_session_factory = async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)

# Run uvicorn
import uvicorn
uvicorn.run("app.main:app", host="0.0.0.0", port={BACKEND_PORT}, log_level="info", reload=False)
"""
    proc = subprocess.Popen(
        [PYTHON, "-c", patch_code],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    procs.append(("Backend", proc))
    return proc

def start_frontend():
    proc = subprocess.Popen(
        [NODE, "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", str(FRONTEND_PORT)],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    procs.append(("Frontend", proc))
    return proc

def tail_output(name, proc):
    for line in iter(proc.stdout.readline, ''):
        if line:
            decoded = line.rstrip()
            if any(w in decoded.lower() for w in ["error", "warning", "startup", "application",
                                                    "listening", "started", "uvicorn", "ready",
                                                    "local", "vite", "running on", "http://"]):
                print(f"  [{name}] {decoded}")

if __name__ == "__main__":
    backend_db = os.path.join(BASE, "ziwi_alpha.db")
    if not os.path.exists(backend_db):
        print("[Alpha] 数据库不存在，请先运行 python alpha_seed.py")
        sys.exit(1)

    db_size = os.path.getsize(backend_db)
    print(f"[Alpha] 数据库: {backend_db} ({db_size/1024:.0f} KB)")

    print_banner()

    print(">>> 启动后端服务...")
    be = start_backend()
    time.sleep(2)

    print(">>> 启动前端服务...")
    fe = start_frontend()

    import threading
    threads = []
    for name, proc in procs:
        t = threading.Thread(target=tail_output, args=(name, proc), daemon=True)
        t.start()
        threads.append(t)

    try:
        while True:
            time.sleep(1)
            # Check if any process died
            for name, proc in procs:
                if proc.poll() is not None:
                    print(f"[Alpha] {name} 进程已退出 (code {proc.returncode})")
                    raise KeyboardInterrupt
    except KeyboardInterrupt:
        print("\n[Alpha] 正在停止服务...")
        for name, proc in procs:
            proc.terminate()
        print("[Alpha] 服务已停止")

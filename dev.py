#!/usr/bin/env python3
"""
Creator AI Toolbox — 本地开发启动器
用法: python3 dev.py [--tunnel] [--port 5000]
"""

import os
import sys
import time
import json
import signal
import socket
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
PID_FILE = Path("/tmp/creator_toolbox.pid")
LOG_FILE = Path("/tmp/flask_server.log")

# ── ANSI Colors ──────────────────────────────────────────
C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
}


def banner():
    print(f"""
{C['cyan']}{C['bold']}╔══════════════════════════════════════════╗
║     Creator AI Toolbox  本地开发环境      ║
║     内容创作者AI工具箱                    ║
╚══════════════════════════════════════════╝{C['reset']}
""")


def ok(msg):
    print(f"  {C['green']}✅{C['reset']} {msg}")


def warn(msg):
    print(f"  {C['yellow']}⚠️{C['reset']}  {msg}")


def fail(msg):
    print(f"  {C['red']}❌{C['reset']} {msg}")


def info(msg):
    print(f"  {C['blue']}ℹ️{C['reset']}  {msg}")


def section(title):
    print(f"\n{C['bold']}{C['magenta']}▸ {title}{C['reset']}")


# ── Step 1: Find Python ─────────────────────────────────
def find_python():
    """Find a working Python 3 that has (or can get) flask"""
    candidates = ["python3", "python3.11", "python3.10", "python"]

    for py in candidates:
        try:
            result = subprocess.run(
                [py, "-c", "import sys; print(sys.executable)"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                py_path = result.stdout.strip()
                # Quick check: can it import flask?
                check = subprocess.run(
                    [py, "-c", "import flask"],
                    capture_output=True, timeout=5
                )
                if check.returncode == 0:
                    return py, py_path, True  # flask ready
                else:
                    return py, py_path, False  # need install
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return None, None, None


# ── Step 2: Install deps ────────────────────────────────
def install_deps(python_bin):
    req_file = BACKEND_DIR / "requirements.txt"
    if not req_file.exists():
        fail(f"requirements.txt 不存在: {req_file}")
        return False

    info("安装依赖...")
    result = subprocess.run(
        [python_bin, "-m", "pip", "install", "-r", str(req_file), "-q"],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT)
    )
    if result.returncode == 0:
        ok("依赖安装完成")
        return True
    else:
        fail(f"安装失败:\n{result.stderr[-500:]}")
        return False


# ── Step 3: Check config files ──────────────────────────
def check_config():
    workspace = Path("/mnt/c/Users/chmx0/.qclaw/workspace")
    api_key_file = workspace / "rewrite_api_key.json"
    cookies_file = workspace / "toutiao_cookies.json"

    all_ok = True

    if api_key_file.exists():
        try:
            data = json.loads(api_key_file.read_text())
            if data.get("deepseek", {}).get("api_key"):
                ok(f"DeepSeek API Key 就绪 ({api_key_file.name})")
            else:
                warn("DeepSeek API Key 格式异常")
                all_ok = False
        except json.JSONDecodeError:
            warn("DeepSeek API Key 文件损坏")
            all_ok = False
    else:
        warn(f"DeepSeek API Key 文件不存在: {api_key_file}")
        all_ok = False

    if cookies_file.exists():
        try:
            cookies = json.loads(cookies_file.read_text())
            if isinstance(cookies, list) and len(cookies) > 0:
                ok(f"头条 Cookie 就绪 ({len(cookies)} 条)")
            elif isinstance(cookies, dict) and len(cookies) > 0:
                ok(f"头条 Cookie 就绪 (dict, {len(cookies)} 键)")
            else:
                warn("头条 Cookie 为空")
        except json.JSONDecodeError:
            warn("头条 Cookie 文件损坏")
    else:
        warn(f"头条 Cookie 文件不存在: {cookies_file}")
        info("热榜/搜索功能将无法使用，但改写/选题仍可用")

    return all_ok


# ── Step 4: Kill existing server ────────────────────────
def kill_existing(port):
    """Kill any process on the given port"""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split("\n")
        pids = [p for p in pids if p]
        if pids:
            info(f"端口 {port} 被占用 (PID: {', '.join(pids)})，正在释放...")
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            time.sleep(1)
            ok(f"端口 {port} 已释放")
    except FileNotFoundError:
        # lsof not available — try fuser
        try:
            subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                capture_output=True, timeout=5
            )
            time.sleep(1)
        except FileNotFoundError:
            pass  # no tools, just try to start


# ── Step 5: Start Flask ─────────────────────────────────
def start_flask(python_bin, port):
    kill_existing(port)

    info(f"启动 Flask 后端 (端口 {port})...")
    env = os.environ.copy()
    env["FLASK_PORT"] = str(port)

    # Write port override to a temp file so app.py can read it
    # (app.py defaults to 5000, but we allow override)
    proc = subprocess.Popen(
        [python_bin, str(BACKEND_DIR / "app.py")],
        cwd=str(BACKEND_DIR),
        stdout=open(str(LOG_FILE), "w"),
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )

    # Wait for server to be ready
    for i in range(20):
        time.sleep(0.3)
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1)
            sock.close()
            ok(f"Flask 后端就绪 → http://localhost:{port}")
            return proc.pid
        except (socket.error, OSError):
            if proc.poll() is not None:
                fail("Flask 进程意外退出")
                # Show last few lines of log
                log_content = ""
                if LOG_FILE.exists():
                    lines = LOG_FILE.read_text().split("\n")
                    log_content = "\n".join(lines[-10:])
                print(f"\n{C['red']}日志 (最后10行):{C['reset']}\n{log_content}")
                return None

    fail(f"Flask 启动超时 (20秒)")
    return None


# ── Step 6: Tunnel (optional) ───────────────────────────
def start_cloudflare_tunnel(port):
    """Start cloudflared tunnel for public access"""
    cloudflared_bin = None
    for path in [
        Path.home() / ".local/bin/cloudflared",
        Path("/usr/local/bin/cloudflared"),
        Path("/usr/bin/cloudflared"),
    ]:
        if path.exists() and os.access(path, os.X_OK):
            cloudflared_bin = str(path)
            break

    if not cloudflared_bin:
        warn("cloudflared 未安装，跳过公网隧道")
        info("安装: wget -O ~/.local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x ~/.local/bin/cloudflared")
        return None

    info("启动 Cloudflare Tunnel...")
    proc = subprocess.Popen(
        [cloudflared_bin, "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )

    # Wait for tunnel URL
    url_file = Path("/tmp/creator_toolbox_url.txt")
    start = time.time()
    while time.time() - start < 15:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                fail("cloudflared 启动失败")
                return None
            continue
        print(f"  {C['dim']}[tunnel]{C['reset']} {line.rstrip()}")
        if "trycloudflare.com" in line:
            import re
            match = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
            if match:
                url = match.group(0)
                url_file.write_text(url)
                ok(f"公网地址: {C['bold']}{C['cyan']}{url}{C['reset']}")
                return url

    warn("Tunnel 超时 (仍在后台运行)")
    return None


# ── Main ────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Creator AI Toolbox 本地开发启动器")
    parser.add_argument("--tunnel", action="store_true", help="同时启动 Cloudflare Tunnel 公网访问")
    parser.add_argument("--port", type=int, default=5000, help="Flask 端口 (默认 5000)")
    parser.add_argument("--skip-deps", action="store_true", help="跳过依赖安装")
    args = parser.parse_args()

    banner()

    # 1. Find Python
    section("检查 Python 环境")
    python_bin, py_path, has_flask = find_python()
    if not python_bin:
        fail("未找到可用的 Python 3")
        info("请在 WSL 中安装: sudo apt install python3 python3-pip")
        sys.exit(1)
    ok(f"Python: {py_path}")

    # 2. Install deps
    if not has_flask and not args.skip_deps:
        section("安装依赖")
        if not install_deps(python_bin):
            info("请手动安装: pip install -r backend/requirements.txt")
            sys.exit(1)

    # 3. Check config
    section("检查配置文件")
    check_config()

    # 4. Start Flask
    section("启动服务")
    pid = start_flask(python_bin, args.port)
    if not pid:
        sys.exit(1)

    # Save PID
    PID_FILE.write_text(str(pid))

    # 5. Tunnel (optional)
    if args.tunnel:
        section("公网隧道")
        start_cloudflare_tunnel(args.port)

    # 6. Summary
    print(f"""
{C['green']}{C['bold']}╔══════════════════════════════════════════╗
║  🎉 Creator AI Toolbox 已就绪！         ║
╠══════════════════════════════════════════╣
║  🔗 本地: http://localhost:{args.port:<5}        ║
║  📋 PID:  {pid:<5}                         ║
║  📄 日志: /tmp/flask_server.log         ║
║  🛑 停止: kill {pid}                    ║
╠══════════════════════════════════════════╣
║  ⌨️  按 Ctrl+C 停止所有服务              ║
╚══════════════════════════════════════════╝{C['reset']}
""")

    # Keep running until Ctrl+C
    try:
        while True:
            time.sleep(1)
            # Check if Flask is still alive
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                print(f"\n{C['red']}Flask 进程已退出{C['reset']}")
                break
    except KeyboardInterrupt:
        print(f"\n\n{C['yellow']}正在关闭...{C['reset']}")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Clean up any cloudflared
        subprocess.run(["pkill", "-f", "cloudflared tunnel"], capture_output=True)
        PID_FILE.unlink(missing_ok=True)
        ok("已停止所有服务")
        print(f"{C['dim']}下次启动: python3 dev.py{C['reset']}\n")


if __name__ == "__main__":
    main()

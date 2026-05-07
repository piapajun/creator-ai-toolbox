#!/usr/bin/env python3
"""Deploy Creator AI Toolbox to Railway"""
import json
import os
import subprocess
import sys

RAILWAY_TOKEN = os.environ.get("RAILWAY_TOKEN", "")

def deploy():
    if not RAILWAY_TOKEN:
        print("❌ 请先设置 RAILWAY_TOKEN 环境变量")
        print("   export RAILWAY_TOKEN=你的token")
        print()
        print("📌 获取 Token：")
        print("   1. 打开 https://railway.app/")
        print("   2. 用 GitHub 登录")
        print("   3. 进入 Account Settings → API Tokens")
        print("   4. 创建新 token，复制")
        sys.exit(1)
    
    # Use Railway CLI with token
    os.environ["RAILWAY_TOKEN"] = RAILWAY_TOKEN
    
    print("🚀 部署到 Railway...")
    subprocess.run(
        ["~/.local/bin/railway", "up", "--detach"],
        cwd="/mnt/c/Users/chmx0/.qclaw/workspace/creator-ai-toolbox/backend",
        check=True
    )
    
    print("✅ 部署成功！")
    print("查看状态: ~/.local/bin/railway status")

if __name__ == "__main__":
    deploy()

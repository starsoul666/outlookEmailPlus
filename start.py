#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
启动脚本 - 智能初始化环境变量并启动 Flask 应用
"""

import os
import secrets
import shutil
import sys

# Windows 控制台 UTF-8 支持
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv


def ensure_env_file():
    """确保 .env 文件存在且 SECRET_KEY 已正确配置"""
    env_file = ".env"
    env_example = ".env.example"

    # 1. 如果 .env 不存在，从 .env.example 复制
    if not os.path.exists(env_file):
        if os.path.exists(env_example):
            print(f"⚠️  未找到 {env_file}，从 {env_example} 复制...")
            shutil.copy(env_example, env_file)
        else:
            print(f"❌ 错误：{env_example} 文件不存在")
            sys.exit(1)

    # 2. 读取 .env 文件内容
    with open(env_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 3. 检查 SECRET_KEY 是否需要生成
    secret_key_line_index = -1
    current_secret_key = None

    for i, line in enumerate(lines):
        if line.strip().startswith("SECRET_KEY="):
            secret_key_line_index = i
            current_secret_key = line.split("=", 1)[1].strip()
            break

    # 4. 如果 SECRET_KEY 是占位符或为空，生成新的
    if current_secret_key in [None, "", "your-secret-key-here"]:
        new_secret_key = secrets.token_hex(32)

        if secret_key_line_index >= 0:
            lines[secret_key_line_index] = f"SECRET_KEY={new_secret_key}\n"
        else:
            # 如果没有找到 SECRET_KEY 行，添加到文件开头
            lines.insert(0, f"SECRET_KEY={new_secret_key}\n")

        # 写回文件
        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(lines)

        print("=" * 60)
        print("✅ 已自动生成新的 SECRET_KEY")
        print(f"🔑 SECRET_KEY: {new_secret_key}")
        print("=" * 60)
        print("⚠️  重要提醒：")
        print("   1. SECRET_KEY 用于加密数据库中的敏感信息")
        print("   2. 请务必备份 .env 文件，丢失后将无法解密旧数据")
        print("   3. 不要将 .env 文件提交到 Git 仓库")
        print("=" * 60)
    else:
        print(f"✅ 使用现有的 SECRET_KEY（已保护数据安全）")


# 初始化环境文件
ensure_env_file()

# 加载 .env 文件中的环境变量
load_dotenv()

# 确保环境变量已加载
if not os.getenv("SECRET_KEY"):
    print("❌ 错误：SECRET_KEY 环境变量未设置")
    sys.exit(1)

# 直接运行 web_outlook_app.py
if __name__ == "__main__":
    # 使用 exec 运行 web_outlook_app.py，保持 __name__ == "__main__"
    with open("web_outlook_app.py", "r", encoding="utf-8") as f:
        code = f.read()
    exec(code, {"__name__": "__main__", "__file__": "web_outlook_app.py"})

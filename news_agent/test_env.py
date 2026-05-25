import os
from dotenv import load_dotenv

# 显式加载当前目录下的 .env
load_dotenv()

print("GNEWS_API_KEY =", os.getenv("GNEWS_API_KEY"))
print("DEEPSEEK_API_KEY =", os.getenv("DEEPSEEK_API_KEY"))
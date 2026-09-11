FROM python:3.11-slim

WORKDIR /app

# 设置 Python 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 安装轻量级依赖 (仅 requests 与 PyYAML)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目核心代码
COPY . /app

# 开放控制台 8080 端口
EXPOSE 8080

# 启动 Web 控制台
CMD ["python", "-m", "agentpoker.cli", "dashboard", "--host", "0.0.0.0", "--port", "8080"]

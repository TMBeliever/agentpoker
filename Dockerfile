FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 复制依赖并使用国内清华源加速安装 (国内服务器秒下)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || \
    pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . /app

# 确保必要目录与 .env 存在
RUN mkdir -p /app/models /app/data /app/logs && touch /app/.env

EXPOSE 8080

CMD ["python", "-m", "agentpoker.cli", "dashboard", "--host", "0.0.0.0", "--port", "8080"]

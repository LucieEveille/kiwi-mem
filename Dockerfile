# 用 Python 精简镜像（体积小，部署快）
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存加速
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 默认端口 8080（与 .env.example 和 main.py 一致）
ENV PORT=8080

# 声明端口
EXPOSE 8080

# 启动网关
CMD ["python", "main.py"]

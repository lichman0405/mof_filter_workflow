# 使用一个官方的、轻量级的 Python 3.11 镜像作为基础
FROM python:3.11-slim

# 设置容器内的工作目录
WORKDIR /app

# 为了利用 Docker 的层缓存机制，我们先拷贝依赖文件
# 只有当 requirements.txt 变化时，下面这层才会重新执行，可以大大加快构建速度
COPY requirements.txt .

# 安装所有 Python 依赖
# --no-cache-dir 选项可以减小镜像体积
RUN pip install --no-cache-dir -r requirements.txt

# 将项目的所有代码拷贝到工作目录中
COPY . .

# （注意：我们不在 Dockerfile 中指定 CMD 或 ENTRYPOINT）
# （因为我们的 API, Worker, Beat 三个服务会使用同一个镜像，但运行不同的命令）
# （这些命令将在 docker-compose.yml 文件中分别定义）

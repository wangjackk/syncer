# 文件夹同步系统 (Folder Syncer)

一个简单的文件夹映射系统，可将Linux上的文件夹映射到Windows上，并同步文件的创建和删除操作。使用FastAPI和SocketIO实现实时通信。

## 功能特点

- 支持多个文件夹映射配置
- 自动监控文件和目录的创建与删除
- 支持嵌套文件夹结构
- 使用WebSocket进行实时通信
- 配置简单，无需命令行参数

## 系统要求

- Python 3.10+
- Linux服务器（运行服务器端）
- Windows客户端（运行客户端）

## 安装

```bash
# 克隆仓库
git clone <仓库地址>
cd syncer

# 安装依赖
pip install -e .
```

## 配置方法

### 服务器端配置 (Linux)

编辑 `server.py` 文件，修改以下配置部分：

```python
# 要监控的Linux文件夹路径，可以配置多个路径
MONITOR_PATHS = [
    "/home/user/projects",  # 替换为实际路径
    "/var/www"              # 替换为实际路径
]

# 服务器监听地址和端口
SERVER_HOST = "0.0.0.0"  # 监听所有网络接口
SERVER_PORT = 8000
```

### 客户端配置 (Windows)

编辑 `client.py` 文件，修改以下配置部分：

```python
# 服务器配置
SERVER_HOST = "192.168.1.100"  # 替换为Linux服务器的实际IP地址
SERVER_PORT = 8000

# 映射配置 - 将Linux路径映射到Windows路径
MAPPINGS = {
    "/home/user/projects": "E:\\synced\\projects",  # 替换为实际路径
    "/var/www": "D:\\websites"                     # 替换为实际路径
}
```

## 使用方法

### 1. 启动服务器端（在Linux上）

```bash
python server.py
```

### 2. 启动客户端（在Windows上）

```bash
python client.py
```

## 工作原理

1. 服务器端使用watchdog库监控指定的Linux文件夹
2. 当文件或目录被创建或删除时，服务器发送事件到客户端
3. 客户端根据映射配置，在Windows上执行相应的文件操作

## 注意事项

- 当前版本只支持文件和目录的创建与删除操作
- 如果需要同步文件内容，需要进一步扩展系统
- 确保服务器和客户端之间的网络连通
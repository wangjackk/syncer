#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
服务器端 - 在Linux系统上运行
监控Linux文件夹变化并通过SocketIO发送到Windows客户端
"""

import asyncio
import logging
import mimetypes
import os
import queue
from datetime import datetime
from pathlib import Path

import socketio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(title="文件夹同步系统 - 服务器端")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建SocketIO服务器
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app)

# 全局变量
MONITORED_PATHS = []  # 监控的路径列表
clients = set()  # 存储已连接的客户端
event_queue = queue.Queue()  # 事件队列


class FileSystemChangeHandler(FileSystemEventHandler):
    """监控文件系统变化的处理器"""
    
    def __init__(self, base_path):
        self.base_path = Path(base_path)
        logger.info(f"初始化文件系统监控处理器: {self.base_path}")
    
    def _queue_event(self, event_type, file_path):
        """将事件放入队列"""
        logger.info(f'将事件放入队列: {event_type}, {file_path}')
        
        # 计算事件数据
        event_data = self._calculate_event_data(event_type, file_path)
        if not event_data:
            return
            
        # 将事件放入队列
        event_queue.put(event_data)
        logger.info(f"事件已加入队列: {event_type}, 路径: {event_data['path']}")
    
    def _calculate_event_data(self, event_type, file_path):
        """计算事件数据"""
        # 计算相对路径
        try:
            rel_path = os.path.relpath(file_path, self.base_path)
            # 确保路径分隔符统一为 /
            rel_path = rel_path.replace('\\', '/')
        except ValueError:
            logger.error(f"无法计算相对路径: {file_path}")
            return None
        
        # 找出源目录在MONITORED_PATHS中的索引
        try:
            source_dir_index = MONITORED_PATHS.index(str(self.base_path))
        except ValueError:
            # 如果找不到索引，尝试使用完整路径
            source_dir_index = -1
            for i, path in enumerate(MONITORED_PATHS):
                if str(self.base_path) == path:
                    source_dir_index = i
                    break
            
            if source_dir_index == -1:
                logger.error(f"无法找到源目录在MONITORED_PATHS中的索引: {self.base_path}")
                source_dir_index = 0  # 默认使用第一个路径
        
        return {
            "event_type": event_type,
            "path": rel_path,
            "source_dir_index": source_dir_index,
            "timestamp": datetime.now().isoformat(),
            "is_file": os.path.isfile(file_path) if os.path.exists(file_path) else False,
            "file_size": os.path.getsize(file_path) if os.path.exists(file_path) and os.path.isfile(file_path) else 0
        }
    
    def on_created(self, event):
        """文件或目录创建事件"""
        if not event.is_directory:
            logger.info(f"文件创建: {event.src_path}")
            print(f"检测到文件创建事件: {event.src_path}")
            self._queue_event('created', event.src_path)
        else:
            logger.info(f"目录创建: {event.src_path}")
            print(f"检测到目录创建事件: {event.src_path}")
            self._queue_event('dir_created', event.src_path)
            
    def on_modified(self, event):
        """文件修改事件"""
        if not event.is_directory:
            logger.info(f"文件修改: {event.src_path}")
            print(f"检测到文件修改事件: {event.src_path}")
            self._queue_event('modified', event.src_path)
    
    def on_deleted(self, event):
        """文件或目录删除事件"""
        if not event.is_directory:
            logger.info(f"文件删除: {event.src_path}")
            print(f"检测到文件删除事件: {event.src_path}")
            self._queue_event('deleted', event.src_path)
        else:
            logger.info(f"目录删除: {event.src_path}")
            print(f"检测到目录删除事件: {event.src_path}")
            self._queue_event('dir_deleted', event.src_path)


# SocketIO事件处理
@sio.event
async def connect(sid, environ):
    """客户端连接事件"""
    logger.info(f"客户端连接: {sid}")
    print(f"客户端连接: {sid}")
    clients.add(sid)
    await sio.emit('welcome', {"message": "欢迎连接到文件夹同步系统服务器"}, room=sid)
    print(f"发送欢迎消息给客户端: {sid}")


@sio.event
async def disconnect(sid):
    """客户端断开连接事件"""
    logger.info(f"客户端断开连接: {sid}")
    print(f"客户端断开连接: {sid}")
    clients.discard(sid)


@app.get("/")
async def root():
    """API根路径"""
    return {
        "message": "文件夹同步系统 - 服务器端",
        "status": "运行中",
        "monitored_paths": MONITORED_PATHS,
        "connected_clients": len(clients)
    }


@app.get("/download/{source_dir_index}/{file_path:path}")
async def download_file(source_dir_index: int, file_path: str):
    """文件下载接口
    
    Args:
        source_dir_index: 源目录索引，对应MONITORED_PATHS中的位置
        file_path: 文件相对路径
    """
    # 检查源目录索引是否有效
    if source_dir_index < 0 or source_dir_index >= len(MONITORED_PATHS):
        raise HTTPException(status_code=404, detail=f"无效的源目录索引: {source_dir_index}")
    
    # 获取源目录
    source_dir = MONITORED_PATHS[source_dir_index]
    
    # 构建完整文件路径
    file_path = file_path.replace('/', os.path.sep)  # 路径分隔符转换
    full_path = os.path.join(source_dir, file_path)
    
    # 检查文件是否存在
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    
    # 返回文件
    return FileResponse(
        path=full_path,
        filename=os.path.basename(full_path),
        media_type=mimetypes.guess_type(full_path)[0] or 'application/octet-stream'
    )


@app.get("/status")
async def status():
    """获取服务器状态"""
    return {
        "status": "运行中",
        "monitored_paths": MONITORED_PATHS,
        "connected_clients": len(clients),
        "timestamp": datetime.now().isoformat()
    }


def start_file_watcher(paths):
    """启动文件监控
    
    Args:
        paths: 要监控的路径列表
    
    Returns:
        Observer对象
    """
    global MONITORED_PATHS
    MONITORED_PATHS = paths
    
    observer = Observer()
    
    for path in paths:
        logger.info(f"开始监控路径: {path}")
        event_handler = FileSystemChangeHandler(path)
        observer.schedule(event_handler, path, recursive=True)
    
    observer.start()
    return observer


# ========================
# 服务器配置
# ========================

# 要监控的Linux文件夹路径，可以配置多个路径
# 例如: ["/home/user/projects", "/var/www", "/opt/data"]
MONITOR_PATHS = [
    "E:\mydir1",  # 请替换为实际路径
    # "/path/to/folder2"   # 请替换为实际路径
]

# 服务器监听地址和端口
SERVER_HOST = "127.0.0.1"  # 监听本地接口
# SERVER_HOST = "0.0.0.0"  # 如果需要监听所有网络接口，可以使用这个
SERVER_PORT = 8000


async def process_event_queue():
    """处理事件队列中的事件"""
    while True:
        try:
            # 检查队列是否有事件
            if not event_queue.empty():
                # 获取事件数据
                event_data = event_queue.get_nowait()
                
                # 检查是否有连接的客户端
                if clients:
                    logger.info(f"发送事件: {event_data['event_type']}, 路径: {event_data['path']}")
                    print(f"发送事件到 {len(clients)} 个客户端: {event_data['event_type']}")
                    
                    # 发送事件
                    await sio.emit('file_event', event_data)
                    print(f"事件发送成功: {event_data['event_type']}")
                else:
                    logger.warning("没有连接的客户端，无法发送事件")
                
                # 标记任务完成
                event_queue.task_done()
            
            # 短暂休眠，避免CPU占用过高
            await asyncio.sleep(0.1)
        except Exception as e:
            import traceback
            logger.error(f"处理事件队列时出错: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(1)  # 出错时等待更长时间

def main():
    """主函数"""
    # 确保所有监控路径存在
    valid_paths = []
    for path in MONITOR_PATHS:
        if not os.path.exists(path):
            logger.error(f"监控路径不存在: {path}")
        else:
            valid_paths.append(path)
    
    if not valid_paths:
        logger.error("没有有效的监控路径，退出程序")
        return
    
    logger.info(f"将监控以下路径: {valid_paths}")
    
    # 启动文件监控
    observer = start_file_watcher(valid_paths)
    
    # 获取事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 添加事件队列处理任务
    loop.create_task(process_event_queue())
    
    try:
        # 启动FastAPI服务器
        import uvicorn
        logger.info(f"启动服务器: {SERVER_HOST}:{SERVER_PORT}")
        config = uvicorn.Config(socket_app, host=SERVER_HOST, port=SERVER_PORT, loop="asyncio")
        server = uvicorn.Server(config)
        loop.run_until_complete(server.serve())
    except KeyboardInterrupt:
        logger.info("接收到退出信号，停止服务")
    finally:
        # 停止文件监控
        observer.stop()
        observer.join()
        loop.close()


if __name__ == "__main__":
    main()

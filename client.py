#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
客户端 - 在Windows系统上运行
接收Linux服务器发送的文件变更事件并在Windows本地执行相应操作
"""

import os
import sys
import asyncio
import socketio
import logging
from pathlib import Path
import argparse
import json
import aiohttp
import shutil
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,  # 使用DEBUG级别获取更详细的日志
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 设置socketio的日志级别
logging.getLogger('socketio').setLevel(logging.DEBUG)
logging.getLogger('engineio').setLevel(logging.DEBUG)

# 创建SocketIO客户端
sio = socketio.AsyncClient()


class FileSyncer:
    """文件同步器类"""
    
    def __init__(self, mappings):
        """初始化
        
        Args:
            mappings: 字典，键为Linux上的源路径，值为Windows上的目标路径
        """
        self.mappings = {}
        
        # 处理映射配置
        for source_path, target_dir in mappings.items():
            # 确保目标目录存在
            target_path = Path(target_dir)
            if not target_path.exists():
                logger.info(f"目标目录不存在，创建目录: {target_path}")
                target_path.mkdir(parents=True, exist_ok=True)
            
            # 添加到映射字典中
            self.mappings[source_path] = target_path
            
        logger.info(f"初始化完成，映射配置: {self.mappings}")
    
    async def handle_file_event(self, data):
        """处理文件事件"""
        event_type = data.get('event_type')
        rel_path = data.get('path')
        source_dir = data.get('source_dir', '')
        source_dir_index = data.get('source_dir_index', 0)
        is_file = data.get('is_file', False)
        file_size = data.get('file_size', 0)
        
        if not event_type or not rel_path:
            logger.error(f"接收到无效的事件数据: {data}")
            return
        
        # 检查是否有匹配的映射
        logger.debug(f"当前映射配置: {self.mappings}")
        logger.debug(f"收到源目录: {source_dir}, 类型: {type(source_dir)}")
        
        # 尝试不同的路径格式
        found_mapping = False
        target_dir = None
        
        # 直接匹配
        if source_dir in self.mappings:
            found_mapping = True
            target_dir = self.mappings[source_dir]
        else:
            # 尝试转换路径分隔符
            normalized_source = source_dir.replace('\\', '/').rstrip('/')
            for src, dst in self.mappings.items():
                normalized_src = src.replace('\\', '/').rstrip('/')
                if normalized_source == normalized_src:
                    found_mapping = True
                    target_dir = dst
                    break
        
        if not found_mapping:
            logger.warning(f"没有找到源目录的映射配置: {source_dir}")
            logger.warning(f"尝试使用默认映射，请检查配置是否正确")
            # 如果没有找到映射，尝试使用第一个映射
            if self.mappings:
                first_src = next(iter(self.mappings.keys()))
                target_dir = self.mappings[first_src]
                logger.warning(f"使用默认映射: {first_src} -> {target_dir}")
            else:
                logger.error("没有可用的映射配置")
                return
        
        # 构建目标路径
        target_path = Path(target_dir) / rel_path
        
        if event_type == 'created' or event_type == 'modified':
            if is_file:
                await self.handle_file_download(source_dir_index, rel_path, target_path, file_size)
            else:
                await self.handle_dir_created(target_path)
        elif event_type == 'deleted':
            await self.handle_file_deleted(target_path)
        elif event_type == 'dir_created':
            await self.handle_dir_created(target_path)
        elif event_type == 'dir_deleted':
            await self.handle_dir_deleted(target_path)
        else:
            logger.warning(f"未知的事件类型: {event_type}")
    
    async def handle_file_download(self, source_dir_index, rel_path, target_path, file_size):
        """下载文件并保存
        
        Args:
            source_dir_index: 源目录索引
            rel_path: 文件相对路径
            target_path: 目标路径
            file_size: 文件大小（字节）
        """
        logger.info(f"处理文件下载: {rel_path} -> {target_path} (大小: {file_size} 字节)")
        
        # 确保父目录存在
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 构建下载URL
        download_url = f"http://{SERVER_HOST}:{SERVER_PORT}/download/{source_dir_index}/{rel_path}"
        
        # 下载文件
        try:
            # 创建临时文件
            temp_file = str(target_path) + ".tmp"
            
            # 使用aiohttp下载文件
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    if response.status == 200:
                        # 打开临时文件并写入内容
                        with open(temp_file, 'wb') as f:
                            while True:
                                chunk = await response.content.read(8192)  # 8KB块
                                if not chunk:
                                    break
                                f.write(chunk)
                        
                        # 完成后将临时文件重命名为目标文件
                        if os.path.exists(str(target_path)):
                            os.remove(str(target_path))
                        shutil.move(temp_file, str(target_path))
                        
                        logger.info(f"文件下载成功: {target_path}")
                    else:
                        logger.error(f"文件下载失败: {download_url}, 状态码: {response.status}")
                        # 如果下载失败，创建空文件
                        if not target_path.exists():
                            target_path.touch()
                            logger.info(f"创建空文件: {target_path}")
        except Exception as e:
            logger.error(f"文件下载异常: {e}")
            # 如果发生异常，创建空文件
            if not target_path.exists():
                target_path.touch()
                logger.info(f"创建空文件: {target_path}")
            # 清理临时文件
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
    
    async def handle_file_deleted(self, target_path):
        """处理文件删除事件"""
        logger.info(f"处理文件删除: {target_path}")
        
        if target_path.exists() and target_path.is_file():
            target_path.unlink()
            logger.info(f"删除文件成功: {target_path}")
        else:
            logger.warning(f"文件不存在，跳过删除: {target_path}")
    
    async def handle_dir_created(self, target_path):
        """处理目录创建事件"""
        logger.info(f"处理目录创建: {target_path}")
        
        if not target_path.exists():
            target_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建目录成功: {target_path}")
        else:
            logger.warning(f"目录已存在，跳过创建: {target_path}")
    
    async def handle_dir_deleted(self, target_path):
        """处理目录删除事件"""
        logger.info(f"处理目录删除: {target_path}")
        
        if target_path.exists() and target_path.is_dir():
            # 注意：这里只删除空目录，如果需要递归删除，需要使用shutil.rmtree
            try:
                target_path.rmdir()
                logger.info(f"删除目录成功: {target_path}")
            except OSError as e:
                logger.error(f"删除目录失败: {target_path}, 错误: {e}")
        else:
            logger.warning(f"目录不存在，跳过删除: {target_path}")


# SocketIO事件处理
@sio.event
async def connect():
    """连接成功事件"""
    logger.info("已连接到服务器")


@sio.event
async def disconnect():
    """断开连接事件"""
    logger.info("与服务器断开连接")


@sio.event
async def welcome(data):
    """欢迎事件"""
    logger.info(f"收到服务器欢迎消息: {data}")


@sio.event
async def file_event(data):
    """文件事件"""
    logger.info(f"收到文件事件: {data}")
    await syncer.handle_file_event(data)


async def main_async():
    """异步主函数"""
    global syncer
    
    # 验证映射配置
    if not MAPPINGS:
        logger.error("没有有效的映射配置，退出程序")
        return
    
    logger.info(f"映射配置: {MAPPINGS}")
    
    # 初始化文件同步器
    syncer = FileSyncer(MAPPINGS)
    
    # 确保安装了aiohttp
    try:
        import aiohttp
    except ImportError:
        logger.error("aiohttp库未安装，请先安装: pip install aiohttp")
        return
    
    # 连接到服务器
    server_url = f"http://{SERVER_HOST}:{SERVER_PORT}"
    logger.info(f"连接到服务器: {server_url}")
    
    retry_count = 0
    max_retries = 5
    retry_delay = 5  # 秒
    
    while retry_count < max_retries:
        try:
            await sio.connect(server_url)
            logger.info("连接成功")
            
            # 保持连接直到程序终止
            await sio.wait()
            break
            
        except socketio.exceptions.ConnectionError as e:
            retry_count += 1
            logger.error(f"连接失败 ({retry_count}/{max_retries}): {e}")
            
            if retry_count < max_retries:
                logger.info(f"将在 {retry_delay} 秒后重试...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("达到最大重试次数，退出程序")
                break
                
        except Exception as e:
            logger.error(f"发生错误: {e}")
            break


# ========================
# 客户端配置
# ========================

# 服务器配置
SERVER_HOST = "127.0.0.1"  # 请替换为Linux服务器的实际IP地址
SERVER_PORT = 8000

# 映射配置 - 将源路径映射到目标路径
# 注意：路径必须使用双反斜杠或正斜杠，例如 'E:\\mydir1' 或 'E:/mydir1'
MAPPINGS = {
    'E:\\mydir1': 'E:\\mydir2',
    # 也可以使用正斜杠
    # 'E:/mydir1': 'E:/mydir2',
    # "/path/to/folder1": "E:\\synced\\folder1",  # 请替换为实际路径
    # "/path/to/folder2": "E:\\synced\\folder2"   # 请替换为实际路径
}


def main():
    """主函数"""
    try:
        # 直接使用配置的参数
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("接收到中断信号，停止客户端")
    except Exception as e:
        logger.error(f"运行时错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

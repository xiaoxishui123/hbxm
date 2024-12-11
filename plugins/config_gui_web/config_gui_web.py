# 全局变量存储插件实例
_plugin_instance = None

def get_plugin_instance():
    """获取插件实例"""
    global _plugin_instance
    return _plugin_instance

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from plugins import *
from config import conf
import json
import os
import schedule
from datetime import datetime
import shutil
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file, current_app
import threading
import webbrowser
from common.log import logger
import platform
import random
import time
import traceback
import tempfile
import copy
import itchat

def safe_int(value, default):
    """安全地将值转换为整数"""
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default

def safe_float(value, default):
    """安全地将值转换为浮点数"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def get_expires_in_seconds():
    """获取消息过期时间，如果配置文件中没有设置或者值无效，则返回默认值3600"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            expires_in = config.get('expires_in_seconds')
            return safe_int(expires_in, 3600)  # 使用已有的 safe_int 函数
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Failed to get expires_in_seconds: {e}")
        return 3600  # 返回默认值

# 创建Flask应用
app = Flask(__name__)

@register(
    name="ConfigGUIWeb",
    desc="A Web GUI tool for managing ChatGPT-WeChat configurations",
    version="1.0",
    author="lanvent",
    desire_priority=999
)
class ConfigGUIWebPlugin(Plugin):
    def __init__(self):
        global _plugin_instance
        super().__init__()
        _plugin_instance = self
        self.config_dir = os.path.dirname(__file__)
        self.config_path = os.path.join(self.config_dir, "config.json")
        
        # 初始化配置
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to load config: {e}")
            self.config = {
                "port": 5000,
                "admin_users": [],
                "plugin_trigger_prefix": "#",
                "task_retry_count": 3,
                "task_retry_interval": 300,
                "task_timeout": 600,
                # 添加消息发送限制配置
                "message_interval": [3, 8],  # 发送消息的随机间隔范围（秒）
                "batch_size": 5,  # 每批发送的最大消息数
                "batch_interval": [30, 60],  # 批次之间的随机间隔范围（秒）
                "daily_limit": 100,  # 每日发送消息的上限
                "active_hours": [9, 22]  # 活跃时间范围（避免深夜发送）
            }
        
        # 初始化消息计数器
        self.message_counter = {
            "daily_count": 0,
            "last_reset": datetime.now().date(),
            "last_send_time": None,
            "current_batch": 0
        }
        
        # 注册事件处理器
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        
        # 初始化状态
        self.server_thread = None
        self.schedule_thread = None
        self.scheduled_tasks = []
        self._task_locks = {}
        
        logger.info("[ConfigGUIWeb] Plugin initialized")

    def get_help_text(self, **kwargs):
        help_text = "配置管理工具使用说明：\n"
        help_text += "1. 使用 #config 命令启动配置工具\n"
        help_text += "2. 仅限管理员在私聊中使用\n"
        help_text += "3. 启动后访问 Web 界面进行配置\n"
        return help_text

    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 确保updateAutoReplyTable字段存在
                if 'updateAutoReplyTable' not in config:
                    config['updateAutoReplyTable'] = True
                    # 保存更新后的配置
                    with open(self.config_path, 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=4, ensure_ascii=False)
                return config
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to load config: {e}")
            return {
                "admin_users": [], 
                "port": 5000,
                "updateAutoReplyTable": True  
            }

    def on_handle_context(self, e_context: EventContext):
        """处理消息"""
        context = e_context['context']
        if context.type != ContextType.TEXT:
            e_context.action = EventAction.CONTINUE
            return

        content = context.content.strip()
        logger.debug(f"[ConfigGUIWeb] Received message: {content}")
        
        # 修改命令识别逻辑，支持多种格式
        config_commands = ["#config", "$config", "config"]
        if any(content.lower() == cmd.lower() for cmd in config_commands):
            logger.debug(f"[ConfigGUIWeb] Processing config command: {content}")
            
            # 检查是否是私聊消息
            if context['isgroup']:
                reply = Reply(ReplyType.ERROR, "配置命令只能在私聊中使用")
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            # 检查发送者是否是管理员
            nickname = context['msg'].from_user_nickname
            logger.debug(f"[ConfigGUIWeb] User {nickname} attempting to access config")
            
            if nickname not in self.config.get("admin_users", []):
                logger.warning(f"[ConfigGUIWeb] Unauthorized access attempt by {nickname}")
                reply = Reply(ReplyType.ERROR, "抱歉，只有管理员才能使用配置工具")
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            try:
                # 启动Web服务器
                if self.server_thread is None:
                    logger.info(f"[ConfigGUIWeb] Starting web server for {nickname}")
                    self.start_web_server()
                    
                    # 确保调度器已初始化
                    if self.schedule_thread is None:
                        logger.info("[ConfigGUIWeb] Initializing scheduler")
                        self.init_scheduler()
                    
                port = self.config.get('port', 5000)
                reply = Reply(
                    ReplyType.INFO, 
                    f"配置工具已启动，请访问: http://127.0.0.1:{port}\n"
                )
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                
            except Exception as e:
                error_msg = f"启动配置工具失败: {str(e)}"
                logger.error(f"[ConfigGUIWeb] {error_msg}\n{traceback.format_exc()}")
                reply = Reply(ReplyType.ERROR, error_msg)
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
            return

        e_context.action = EventAction.CONTINUE

    def init_scheduler(self):
        """初始化调度器"""
        try:
            if self.schedule_thread is None:
                logger.info("[ConfigGUIWeb] Initializing scheduler...")
                
                # 清除所有现有任务
                schedule.clear()
                self.scheduled_tasks = []
                
                # 加载现有任务
                self.load_scheduled_tasks()
                
                # 启动调度线程
                if self.schedule_thread and self.schedule_thread.is_alive():
                    logger.info("[ConfigGUIWeb] Scheduler thread already running")
                    return True
                    
                self.schedule_thread = threading.Thread(target=self.run_schedule, daemon=True)
                self.schedule_thread.start()
                logger.info("[ConfigGUIWeb] Scheduler started successfully")
                return True
                
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to initialize scheduler: {e}\n{traceback.format_exc()}")
            return False

    def start_web_server(self):
        """启动Web服务器"""
        def run_server():
            # 确保 Flask 应用可以访问到插件实例
            global _plugin_instance
            app.config['plugin_instance'] = _plugin_instance
            # 在非主线程中运行时，不使用调试模式
            app.run(host='0.0.0.0', port=self.config.get('port', 5000), debug=False)

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        # 在新线程中打开浏览器
        threading.Thread(target=lambda: webbrowser.open(f'http://localhost:{self.config.get("port", 5000)}'), daemon=True).start()
        logger.info("[ConfigGUIWeb] Web server started")

    def load_scheduled_tasks(self):
        """加载定时任务"""
        try:
            plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
            if not os.path.exists(plugin_config_path):
                logger.error(f"[ConfigGUIWeb] Tag manager config not found: {plugin_config_path}")
                return
            
            with open(plugin_config_path, 'r', encoding='utf-8') as f:
                tag_config = json.load(f)
                tasks = tag_config.get("scheduled_tasks", [])
                
            if not tasks:
                logger.info("[ConfigGUIWeb] No scheduled tasks found")
                return
                    
            for task in tasks:
                # 验证任务数据完整性
                required_fields = ["id", "tag", "time", "message"]
                if not all(field in task for field in required_fields):
                    logger.error(f"[ConfigGUIWeb] Invalid task data: {task}")
                    continue
                    
                # 验证时间格式
                try:
                    time.strptime(task["time"], "%H:%M")
                except ValueError:
                    logger.error(f"[ConfigGUIWeb] Invalid time format in task: {task}")
                    continue
                    
                # 创建完整的任务对象
                task_obj = {
                    "id": task["id"],
                    "tag": task["tag"],
                    "schedule_type": task.get("schedule_type", "daily"),  # 获取调度类型，默认为daily
                    "time": task["time"],
                    "message": task["message"],
                    "status": task.get("status", {  # 获取状态信息，如果不存在则使用默认值
                        "is_running": False,
                        "last_execution": None,
                        "last_success": None,
                        "last_error": None,
                        "total_attempts": 0,
                        "success_count": 0,
                        "error_count": 0
                    })
                }
                
                # 添加到内存中的任务列表
                self.scheduled_tasks.append(task_obj)
                    
                # 调度任务
                self.schedule_task(
                    task_obj["id"],
                    task_obj["tag"],
                    task_obj["time"],
                    task_obj["message"]
                )
            logger.info(f"[ConfigGUIWeb] Successfully loaded {len(tasks)} scheduled tasks")
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to load scheduled tasks: {e}")

    def schedule_task(self, task_id, tag, time_str, message):
        """调度定时任务"""
        try:
            logger.info(f"[ConfigGUIWeb] Scheduling task {task_id} for tag {tag} at {time_str}")
            
            # 验证时间格式
            try:
                time.strptime(time_str, "%H:%M")
            except ValueError:
                logger.error(f"[ConfigGUIWeb] Invalid time format for task {task_id}: {time_str}")
                return False
            
            # 清除同ID的旧任务
            schedule.clear(task_id)
            
            # 从任务列表中移除旧任务
            self.scheduled_tasks = [t for t in self.scheduled_tasks if t.get("id") != task_id]
            
            # 初始化任务状态
            task = {
                "id": task_id,
                "tag": tag,
                "time": time_str,
                "message": message,
                "status": {
                    "is_running": False,
                    "last_execution": None,
                    "last_success": None,
                    "last_error": None,
                    "total_attempts": 0,
                    "success_count": 0,
                    "error_count": 0
                }
            }
            
            # 添加到任务列表
            self.scheduled_tasks.append(task)
            
            # 添加到调度器
            try:
                def job(task):
                    """任务执行函数"""
                    task_id = task["id"]
                    tag = task["tag"]
                    message = task["message"]

                    if not self._task_locks.get(task_id):
                        self._task_locks[task_id] = threading.Lock()
                    
                    if not self._task_locks[task_id].acquire(blocking=False):
                        logger.warning(f"[ConfigGUIWeb] Task {task_id} is already running")
                        return

                    try:
                        task["status"]["is_running"] = True
                        task["status"]["last_execution"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        task["status"]["total_attempts"] += 1
                        # 获所有微信好友
                        # 首先检查登录状态
                        if not itchat.instance.alive:
                            try:
                                itchat.auto_login(
                                    hotReload=True
                                )
                                logger.info("[ConfigGUIWeb] Successfully re-logged into WeChat")
                            except Exception as e:
                                logger.error(f"[ConfigGUIWeb] Failed to re-login to WeChat: {str(e)}")
                                return jsonify({"error": "WeChat login required. Please scan QR code to login."}), 401

                # 获取指定标签的好友列表           
                        # 获取好友列表并发送消息
                        friends = itchat.get_friends(update=True)
                        target_friends = self.get_friends_by_tag(tag, friends)
                        
                        if not target_friends:
                            raise Exception(f"No friends found with tag: {tag}")
                        
                        for friend in target_friends:
                            if not self.can_send_message():
                                time.sleep(60)
                                if not self.can_send_message():
                                    raise Exception("Message sending limit reached")
                                    
                            result = itchat.send(message, toUserName=friend['UserName'])
                            if result['BaseResponse']['Ret'] == 0:
                                task["status"]["success_count"] += 1
                                self.update_message_counter(success=True)
                            else:
                                raise Exception(f"Failed to send message: {result}")
                                
                            time.sleep(random.uniform(2, 5))
                        
                        task["status"]["last_success"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        task["status"]["last_error"] = None
                        
                    except Exception as e:
                        task["status"]["error_count"] += 1
                        task["status"]["last_error"] = str(e)
                        logger.error(f"[ConfigGUIWeb] Task {task_id} failed: {e}")
                    finally:
                        task["status"]["is_running"] = False
                        self._task_locks[task_id].release()
                
                schedule.every().day.at(time_str).do(job, task).tag(task_id)
                logger.info(f"[ConfigGUIWeb] Task {task_id} scheduled successfully")
                return True
                
            except Exception as e:
                logger.error(f"[ConfigGUIWeb] Failed to add task {task_id} to scheduler: {e}")
                # 从任务列表中移除失败的任务
                self.scheduled_tasks = [t for t in self.scheduled_tasks if t.get("id") != task_id]
                return False
            
            # 保存任务配置
            try:
                self._save_tasks_config()
                logger.info(f"[ConfigGUIWeb] Task {task_id} configuration saved")
            except Exception as e:
                logger.error(f"[ConfigGUIWeb] Failed to save task {task_id} configuration: {e}")
                # 继续执行，因为任务已经添加到调度器中
            
            return True
            
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to schedule task {task_id}: {e}\n{traceback.format_exc()}")
            return False
            
    def _save_tasks_config(self):
        """保存任务配置到文件"""
        try:
            plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
            if not os.path.exists(plugin_config_path):
                logger.error(f"[ConfigGUIWeb] Tag manager config not found: {plugin_config_path}")
                return False
                
            with open(plugin_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 更新任务列表，保留所有字段
            tasks_to_save = []
            for task in self.scheduled_tasks:
                task_copy = {
                    "id": task["id"],
                    "tag": task["tag"],
                    "schedule_type": task.get("schedule_type", "daily"),  # 保存调度类型，默认为daily
                    "time": task["time"],
                    "message": task["message"],
                    "status": task.get("status", {  # 保存状态信息
                        "is_running": False,
                        "last_execution": None,
                        "last_success": None,
                        "last_error": None,
                        "total_attempts": 0,
                        "success_count": 0,
                        "error_count": 0
                    })
                }
                tasks_to_save.append(task_copy)
            
            config["scheduled_tasks"] = tasks_to_save
            
            with open(plugin_config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            return True
            
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to save tasks configuration: {e}")
            return False

    def run_schedule(self):
        """运行调度器"""
        logger.info("[ConfigGUIWeb] Starting scheduler")
        last_login_check = time.time()
        
        while True:
            try:
                # 每5分钟检查一次登录状态
                current_time = time.time()
                if current_time - last_login_check > 300:  # 5分钟
                    try:
                        if not hasattr(itchat, 'instance'):
                            logger.warning("[ConfigGUIWeb] WeChat not initialized, skipping login check")
                            continue
                            
                        if not itchat.instance or not itchat.instance.alive:
                            logger.warning("[ConfigGUIWeb] WeChat session expired or not alive, attempting to re-login")
                            try:
                                itchat.auto_login(hotReload=True)
                                logger.info("[ConfigGUIWeb] Successfully re-logged into WeChat")
                            except Exception as e:
                                logger.error(f"[ConfigGUIWeb] Failed to re-login to WeChat: {e}")
                    except Exception as e:
                        logger.error(f"[ConfigGUIWeb] Error during login check: {e}")
                    last_login_check = current_time

                # 运行待执行的任务
                schedule.run_pending()
                
                # 避免CPU过度使用
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"[ConfigGUIWeb] Scheduler error: {e}")
                time.sleep(5)  # 出错后等待一段时间再继续

    def get_friends_by_tag(self, tag, friends):
        """根据标签获取好友列表"""
        try:
            logger.info(f"[ConfigGUIWeb] Getting friends with tag: {tag}")
            
            # 读取标签配置
            plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
            if not os.path.exists(plugin_config_path):
                logger.error(f"[ConfigGUIWeb] Tag config file not found: {plugin_config_path}")
                return []
                
            with open(plugin_config_path, 'r', encoding='utf-8') as f:
                tag_config = json.load(f)
                
            # 获取标签下的好友昵称列表
            tags_friends = tag_config.get("tags_friends", {})
            if tag not in tags_friends:
                logger.warning(f"[ConfigGUIWeb] Tag '{tag}' not found in config")
                return []
                
            tag_friend_names = tags_friends[tag]
            if not tag_friend_names:
                logger.warning(f"[ConfigGUIWeb] No friends found in tag '{tag}'")
                return []
                
            # 将昵称映射到好友对象
            friend_map = {f['NickName']: f for f in friends if f.get('NickName')}
            target_friends = []
            
            for friend_name in tag_friend_names:
                if friend_name in friend_map:
                    target_friends.append(friend_map[friend_name])
                    logger.debug(f"[ConfigGUIWeb] Found friend: {friend_name}")
                else:
                    logger.warning(f"[ConfigGUIWeb] Friend not found in WeChat: {friend_name}")
                    
            logger.info(f"[ConfigGUIWeb] Found {len(target_friends)}/{len(tag_friend_names)} friends with tag '{tag}'")
            return target_friends
            
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to get friends by tag: {e}\n{traceback.format_exc()}")
            return []

    def can_send_message(self):
        """检查是否可以发送消息"""
        now = datetime.now()
        today = now.date()
        
        # 重置每日计数器
        if today != self.message_counter["last_reset"]:
            self.message_counter["daily_count"] = 0
            self.message_counter["last_reset"] = today
            self.message_counter["current_batch"] = 0
        
        # 暂时移除活跃时间限制，让消息可以在任何时间发送
        # active_start, active_end = self.config["active_hours"]
        # if not (active_start <= now.hour < active_end):
        #     logger.warning(f"[ConfigGUIWeb] Outside active hours ({active_start}:00-{active_end}:00)")
        #     return False
        
        # 放宽每日限制
        if self.message_counter["daily_count"] >= 1000:  # 增加到1000条
            logger.warning("[ConfigGUIWeb] Daily message limit reached")
            return False
        
        # 放宽批次限制
        if self.message_counter["current_batch"] >= 10:  # 改回10条
            logger.info("[ConfigGUIWeb] Batch size limit reached, waiting for next batch")
            return False
        
        # 减少消息间隔
        if self.message_counter["last_send_time"]:
            min_interval = 1  # 减少到1秒
            elapsed = (now - self.message_counter["last_send_time"]).total_seconds()
            if elapsed < min_interval:
                logger.debug(f"[ConfigGUIWeb] Message interval too short ({elapsed:.1f}s < {min_interval}s)")
                return False
        
        return True

    def update_message_counter(self, success=True):
        """更新消息计数器"""
        now = datetime.now()
        
        if success:
            self.message_counter["daily_count"] += 1
            self.message_counter["current_batch"] += 1
            self.message_counter["last_send_time"] = now
            
            # 检查是否需要开始新的批次
            if self.message_counter["current_batch"] >= self.config["batch_size"]:
                min_interval, max_interval = 60, 120  # 增加批次间隔到60-120秒
                wait_time = random.uniform(min_interval, max_interval)
                logger.info(f"[ConfigGUIWeb] Starting new batch after {wait_time:.1f}s")
                threading.Timer(wait_time, lambda: setattr(self.message_counter, "current_batch", 0)).start()

    def send_message_with_retry(self, message, friend, max_retries=3):
        """发送消息给好友，带重试机制"""
        friend_name = friend.get('NickName', 'Unknown')
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # 检查是否可以发送消息
                if not self.can_send_message():
                    time.sleep(5)  # 等待一段时间后重试
                    continue
                
                logger.info(f"[ConfigGUIWeb] Sending message to {friend_name} (attempt {retry_count + 1})")
                
                # 添加随机延迟
                time.sleep(random.uniform(2, 4))
                
                # 尝试发送消息
                result = itchat.send(message, toUserName=friend['UserName'])
                
                if result['BaseResponse']['Ret'] == 0:
                    logger.info(f"[ConfigGUIWeb] Message sent successfully to {friend_name}")
                    self.update_message_counter(success=True)
                    return True
                else:
                    raise Exception(f"Send failed with response: {result}")
                
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = random.uniform(5, 10)
                    logger.warning(f"[ConfigGUIWeb] Retry {retry_count}/{max_retries} for {friend_name} in {wait_time:.1f}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"[ConfigGUIWeb] Failed to send message to {friend_name} after {max_retries} attempts: {e}")
                    return False
        
        return False

    def get_tasks_status(self):
        """获取所有任务的状态"""
        try:
            tasks_status = []
            for task in self.scheduled_tasks:
                try:
                    # 深拷贝任务状态，避免并发修改
                    task_copy = copy.deepcopy(task)
                    
                    # 计算下次执行时间
                    next_run = None
                    for job in schedule.get_jobs():
                        if hasattr(job, 'tag') and job.tag == task['id']:
                            next_run = job.next_run
                            break
                    
                    # 添加额外状态信息
                    task_copy['next_run'] = next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else None
                    
                    # 确保状态字段存在
                    if 'status' not in task_copy:
                        task_copy['status'] = {
                            'is_running': False,
                            'last_execution': None,
                            'last_success': None,
                            'last_error': None,
                            'total_attempts': 0,
                            'success_count': 0,
                            'error_count': 0
                        }
                    
                    # 计算成功率
                    success_rate = self._calculate_success_rate(task_copy)
                    task_copy['success_rate'] = success_rate if success_rate is not None else 0
                    
                    tasks_status.append(task_copy)
                except Exception as e:
                    logger.error(f"[ConfigGUIWeb] Error processing task status for task {task.get('id', 'unknown')}: {e}")
                    # 继续处理下一个任务，而不是完全失败
                    continue
            
            return jsonify({
                "status": "success",
                "tasks": tasks_status
            })
            
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to get tasks status: {e}\n{traceback.format_exc()}")
            return jsonify({
                "status": "error",
                "message": str(e),
                "tasks": []
            })

    def _calculate_success_rate(self, task):
        """计算任务的成功率"""
        try:
            status = task.get("status", {})
            total_attempts = status.get("total_attempts", 0)
            if total_attempts == 0:
                return 0
            success_count = status.get("success_count", 0)
            return round((success_count / total_attempts) * 100, 2)
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Error calculating success rate: {e}")
            return 0

    def update_task(self, task_id, tag, time_str, message):
        """更新定时任务"""
        try:
            # 验证时间格式
            try:
                time.strptime(time_str, "%H:%M")
            except ValueError:
                logger.error(f"[ConfigGUIWeb] Invalid time format for task {task_id}: {time_str}")
                return False

            # 找到并更新任务
            task = None
            for t in self.scheduled_tasks:
                if t.get("id") == task_id:
                    task = t
                    break

            if not task:
                logger.error(f"[ConfigGUIWeb] Task {task_id} not found")
                return False

            # 更新任务配置
            task.update({
                "tag": tag,
                "time": time_str,
                "message": message
            })

            # 保存配置到文件
            self._save_tasks_config()

            # 更新调度器中的任务
            return self.update_schedule_job(task_id, time_str)

        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to update task {task_id}: {e}")
            return False

    def update_schedule_job(self, task_id, time_str):
        """更新调度器中的任务"""
        try:
            # 先清除旧的任务
            schedule.clear(task_id)
            
            # 找到对应的任务
            task = None
            for t in self.scheduled_tasks:
                if t.get("id") == task_id:
                    task = t
                    break
                    
            if task:
                def job(task):
                    """任务执行函数"""
                    task_id = task["id"]
                    tag = task["tag"]
                    message = task["message"]

                    if not self._task_locks.get(task_id):
                        self._task_locks[task_id] = threading.Lock()
                    
                    if not self._task_locks[task_id].acquire(blocking=False):
                        logger.warning(f"[ConfigGUIWeb] Task {task_id} is already running")
                        return

                    try:
                        task["status"]["is_running"] = True
                        task["status"]["last_execution"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        task["status"]["total_attempts"] += 1
                        # 获所有微信好友
                        # 首先检查登录状态
                        if not itchat.instance.alive:
                            try:
                                itchat.auto_login(
                                    hotReload=True
                                )
                                logger.info("[ConfigGUIWeb] Successfully re-logged into WeChat")
                            except Exception as e:
                                logger.error(f"[ConfigGUIWeb] Failed to re-login to WeChat: {str(e)}")
                                return jsonify({"error": "WeChat login required. Please scan QR code to login."}), 401

                # 获取指定标签的好友列表           
                        # 获取好友列表并发送消息
                        friends = itchat.get_friends(update=True)
                        target_friends = self.get_friends_by_tag(tag, friends)
                        
                        if not target_friends:
                            raise Exception(f"No friends found with tag: {tag}")
                        
                        for friend in target_friends:
                            if not self.can_send_message():
                                time.sleep(60)
                                if not self.can_send_message():
                                    raise Exception("Message sending limit reached")
                                    
                            result = itchat.send(message, toUserName=friend['UserName'])
                            if result['BaseResponse']['Ret'] == 0:
                                task["status"]["success_count"] += 1
                                self.update_message_counter(success=True)
                            else:
                                raise Exception(f"Failed to send message: {result}")
                                
                            time.sleep(random.uniform(2, 5))
                        
                        task["status"]["last_success"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        task["status"]["last_error"] = None
                        
                    except Exception as e:
                        task["status"]["error_count"] += 1
                        task["status"]["last_error"] = str(e)
                        logger.error(f"[ConfigGUIWeb] Task {task_id} failed: {e}")
                    finally:
                        task["status"]["is_running"] = False
                        self._task_locks[task_id].release()
                
                # 重新调度任务
                schedule.every().day.at(time_str).do(job, task).tag(task_id)
                logger.info(f"[ConfigGUIWeb] Task {task_id} rescheduled successfully")
                return True
                
            else:
                logger.error(f"[ConfigGUIWeb] Task {task_id} not found")
                return False
                
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to update task {task_id}: {e}")
            return False

    def _save_tasks_config(self):
        """保存任务配置到文件"""
        try:
            # 读取现有配置
            plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                config = {}

            # 更新任务列表
            config["scheduled_tasks"] = self.scheduled_tasks

            # 保存配置
            with open(plugin_config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            
            logger.info("[ConfigGUIWeb] Tasks configuration saved successfully")
            return True
            
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to save tasks configuration: {e}")
            return False

# Flask路由和API端点
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    """获取主配置"""
    try:
        # 定义完整的默认配置
        default_config = {
            "updateAutoReplyTable": True,  
            "auto_reply_table": {},
            "scheduled_tasks": [],
            "channel_type": "wx",
            "nick_name_white_list": [],
            "nick_name_black_list": [], 
            "random_reply_delay_min": 2,
            "random_reply_delay_max": 4,
            "expires_in_seconds": 3600,
            "debug": True,
            "plugin_trigger_prefix": "$",
            "model": "coze",  # 设置默认值为 coze
            "coze_api_base": "",
            "coze_api_key": "",
            "coze_bot_id": "",
            "text_to_image": "dall-e-3",
            "voice_to_text": "xunfei",
            "text_to_voice": "xunfei",
            "proxy": "",
            "single_chat_prefix": [""],
            "single_chat_reply_prefix": "",
            "group_chat_keyword": [],
            "group_chat_prefix": [""],
            "group_chat_reply_prefix": "",
            "group_chat_reply_suffix": "",
            "group_at_off": True,
            "group_name_white_list": [],
            "group_name_keyword_white_list": [],
            "group_chat_in_one_session": [],
            "concurrency_in_session": 1,
            "group_welcome_msg": "",
            "speech_recognition": True,
            "group_speech_recognition": True,
            "voice_reply_voice": False,
            "always_reply_voice": False,
            "conversation_max_tokens": 2000,
            "character_desc": "",
            "temperature": 0.5,
            "subscribe_msg": ""
        }
        
        # 获取项目根目录的config.json
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(root_dir, 'config.json')
        
        config = default_config.copy()  # 从默认配置开始
        
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                config.update(file_config)  # 用文件中的配置更新默认配置
                
        return jsonify(config)
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Failed to get config: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/config', methods=['POST'])
def update_config():
    """保存配置到文件"""
    try:
        # 获取请求数据和参数
        config_data = request.json
        
        # 获取项目根目录
        root_dir = Path(__file__).parent.parent.parent
        config_path = root_dir / 'config.json'
        
        # 读取现有配置
        existing_config = {}
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"[ConfigGUIWeb] Invalid JSON in config file: {e}")
                return jsonify({"error": "Invalid configuration file format"}), 500
        
        # 更新配置
        existing_config.update(config_data)
        
        # 保存配置
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(existing_config, f, ensure_ascii=False, indent=4)
        except IOError as e:
            logger.error(f"[ConfigGUIWeb] Failed to write config file: {e}")
            return jsonify({"error": "Failed to save configuration"}), 500
            
        return jsonify({"message": "Configuration saved successfully"})
        
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Failed to save config: {e}")
        return jsonify({"error": str(e)}), 500

# 添加更多API路由
@app.route('/api/tag-config', methods=['GET'])
def get_tag_config():
    """获取标签插件配置"""
    try:
        default_tag_config = {
            "updateAutoReplyTable": True,  
            "tags_friends": {},
            "scheduled_tasks": [],
            "enable": True,
            "tag_prefix": "$",
            "allow_all_add_tag": False,
            "allow_all_remove_tag": False,
            "allow_all_view_tag": True,
            "allow_all_list_tag": True,
            "admin_users": [],
            "enabled_tags": []
        }
        
        # 使用绝对路径
        plugin_config_path = os.path.join(os.getcwd(), "plugins", "tag_manager", "config.json")
        if os.path.exists(plugin_config_path):
            with open(plugin_config_path, 'r', encoding='utf-8') as f:
                tag_config = json.load(f)
                # 确保必要字段存在
                for key, value in default_tag_config.items():
                    if key not in tag_config:
                        tag_config[key] = value
                # 保存更新后的配置
                with open(plugin_config_path, 'w', encoding='utf-8') as f:
                    json.dump(tag_config, f, ensure_ascii=False, indent=4)
        else:
            tag_config = default_tag_config
            # 创建目录和文件
            os.makedirs(os.path.dirname(plugin_config_path), exist_ok=True)
            with open(plugin_config_path, 'w', encoding='utf-8') as f:
                json.dump(tag_config, f, ensure_ascii=False, indent=4)
                
        return jsonify(tag_config)
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Failed to get tag config: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tag-config', methods=['POST'])
def save_tag_config():
    """保存标签插件配置"""
    try:
        # 获取请求数据
        config_data = request.json
        
        # 保存配置
        try:
            config_path = os.path.join("plugins", "tag_manager", "config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
                
            return jsonify({"message": "Configuration saved successfully"})
            
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Failed to save tag config: {e}")
            return jsonify({"error": str(e)}), 500
            
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Error in save_tag_config: {e}")
        return jsonify({"error": str(e)}), 500

# 添加更多API路由... 

@app.errorhandler(Exception)
def handle_error(error):
    logger.error(f"[ConfigGUIWeb] Server error: {error}")
    return jsonify({
        "error": "Internal server error",
        "message": str(error)
    }), 500
        
def ensure_config_integrity(config_data):
    """确保配置数据完整性"""
    essential_fields = {
        "updateAutoReplyTable": True,
        "auto_reply_table": {},
        "scheduled_tasks": []
    }
    
    for key, default_value in essential_fields.items():
        if key not in config_data:
            config_data[key] = default_value
    
    # 如果 model 字段为空，不要覆盖现有配置
    if "model" in config_data and not config_data["model"]:
        del config_data["model"]
    
    return config_data
        
@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """获取所有定时任务"""
    try:
        plugin = current_app.config.get('plugin_instance')
        if not plugin:
            return jsonify({"error": "Plugin not initialized"}), 500
            
        tasks = []
        for task in plugin.scheduled_tasks:
            # 从任务对象中获取调度类型，如果不存在则从配置文件中获取
            schedule_type = task.get("schedule_type")
            if not schedule_type:
                # 从配置文件中读取任务信息
                try:
                    with open(os.path.join("plugins", "tag_manager", "config.json"), 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        for saved_task in config.get("scheduled_tasks", []):
                            if saved_task.get("id") == task["id"]:
                                schedule_type = saved_task.get("schedule_type", "daily")
                                break
                except Exception as e:
                    logger.error(f"[ConfigGUIWeb] Failed to read schedule_type from config: {e}")
                    schedule_type = "daily"  # 默认值
            
            task_info = {
                "id": task["id"],
                "tag": task["tag"],
                "schedule_type": schedule_type or "daily",  # 确保有默认值
                "time": task["time"],
                "message": task["message"],
                "last_execution": task["status"]["last_execution"]  # 只保留上次执行时间
            }
            tasks.append(task_info)
            
        return jsonify(tasks)
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Failed to get tasks: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tasks/status', methods=['GET'])
def get_tasks_status():
    """获取所有任务的状态"""
    plugin = get_plugin_instance()
    if not plugin:
        return jsonify({
            "status": "error",
            "message": "Plugin not initialized",
            "tasks": []
        })
    return plugin.get_tasks_status()

@app.route('/api/tasks', methods=['POST'])
def add_task():
    """添加定时任务"""
    try:
        plugin_instance = get_plugin_instance()
        if not plugin_instance:
            return jsonify({"error": "插件实例未初始化"}), 500

        data = request.get_json()
        tag = data.get("tag")
        schedule_type = data.get("schedule_type", "daily")  # 获取调度类型，默认为daily
        time_str = data.get("time")
        message = data.get("message")
        
        # 验证输入
        if not tag or not time_str or not message:
            return jsonify({"error": "缺少必要的参数"}), 400
            
        # 验证时间格式
        try:
            time.strptime(time_str, "%H:%M")
        except ValueError:
            return jsonify({"error": "时间格式无效，请使用 HH:MM 格式"}), 400
        
        # 生成任务ID
        task_id = f"task_{int(time.time())}"
        
        # 调度任务
        if plugin_instance.schedule_task(task_id, tag, time_str, message):
            # 保存任务配置
            try:
                plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
                with open(plugin_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if "scheduled_tasks" not in config:
                        config["scheduled_tasks"] = []
                    
                    # 添加新任务到配置
                    config["scheduled_tasks"].append({
                        "id": task_id,
                        "tag": tag,
                        "schedule_type": schedule_type,  # 保存调度类型
                        "time": time_str,
                        "message": message,
                        "status": {  # 添加状态字段
                            "is_running": False,
                            "last_execution": None,
                            "error_count": 0,
                            "total_attempts": 0,
                            "success_count": 0
                        }
                    })
                
                # 保存更新后的配置
                with open(plugin_config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
                
                return jsonify({"message": "任务添加成功", "task_id": task_id}), 201
            except Exception as e:
                logger.error(f"[ConfigGUIWeb] 保存任务配置失败: {e}")
                return jsonify({"error": "保存任务配置失败"}), 500
        else:
            return jsonify({"error": "添加任务失败"}), 500
            
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] 添加任务失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['PUT'])
def update_task_api(task_id):
    """更新定时任务"""
    try:
        plugin_instance = get_plugin_instance()
        if not plugin_instance:
            return jsonify({"error": "插件实例未初始化"}), 500

        data = request.get_json()
        tag = data.get("tag")
        schedule_type = data.get("schedule_type", "daily")  # 获取调度类型，默认为daily
        time_str = data.get("time")
        message = data.get("message")
        
        # 验证输入
        if not tag or not time_str or not message:
            return jsonify({"error": "缺少必要的参数"}), 400

        # 获取任务
        task = None
        for t in plugin_instance.scheduled_tasks:
            if t.get("id") == task_id:
                task = t
                break
        
        if task is None:
            return jsonify({"error": "任务不存在"}), 404
        
        # 更新任务配置
        task.update({
            "tag": tag,
            "schedule_type": schedule_type,  # 更新调度类型
            "time": time_str,
            "message": message
        })
        
        # 更新配置文件中的任务
        try:
            plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
            with open(plugin_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            # 更新任务信息
            for saved_task in config.get("scheduled_tasks", []):
                if saved_task.get("id") == task_id:
                    saved_task.update({
                        "tag": tag,
                        "schedule_type": schedule_type,  # 更新调度类型
                        "time": time_str,
                        "message": message
                    })
                    break
            
            # 保存更新后的配置
            with open(plugin_config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
                
            # 更新调度器中的任务
            plugin_instance.update_schedule_job(task_id, time_str)
            
            return jsonify({"message": "任务更新成功"}), 200
            
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] 更新任务配置失败: {e}")
            return jsonify({"error": "更新任务配置失败"}), 500
            
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] 更新任务失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    """删除定时任务"""
    try:
        plugin_instance = get_plugin_instance()
        if not plugin_instance:
            return jsonify({"error": "插件实例未初始化"}), 500
            
        # 从调度器中移除任务
        schedule.clear(task_id)
        
        # 从内存中的任务列表移除任务
        plugin_instance.scheduled_tasks = [t for t in plugin_instance.scheduled_tasks if t.get("id") != task_id]
        
        # 从配置文件中移除任务
        try:
            plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
            with open(plugin_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            # 从配置中移除任务
            if "scheduled_tasks" in config:
                config["scheduled_tasks"] = [t for t in config["scheduled_tasks"] if t.get("id") != task_id]
                
                # 保存更新后的配置
                with open(plugin_config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
            
            return jsonify({"message": "任务删除成功"}), 200
            
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] 从配置中删除任务失败: {e}")
            return jsonify({"error": "删除任务配置失败"}), 500
            
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] 删除任务失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/broadcast', methods=['POST'])
def send_broadcast():
    """发送群发消息"""
    try:
        data = request.get_json()
        tag = data.get('tag')
        message = data.get('message')
        
        if not tag or not message:
            return jsonify({"error": "Missing tag or message"}), 400
            
        # 获取标签下的好友
        plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
        with open(plugin_config_path, 'r', encoding='utf-8') as f:
            tag_config = json.load(f)
            tags_friends = tag_config.get("tags_friends", {})
        
        if tag not in tags_friends:
            return jsonify({"error": f"Tag '{tag}' does not exist"}), 404
            
        friends = tags_friends[tag]
        if not friends:
            return jsonify({"error": f"No friends found in tag '{tag}'"}), 404
        
        # 获所有微信好友
        # 首先检查登录状态
        if not itchat.instance.alive:
            try:
                itchat.auto_login(
                    hotReload=True
                )
                logger.info("[ConfigGUIWeb] Successfully re-logged into WeChat")
            except Exception as e:
                logger.error(f"[ConfigGUIWeb] Failed to re-login to WeChat: {str(e)}")
                return jsonify({"error": "WeChat login required. Please scan QR code to login."}), 401

        try:
            wx_friends = itchat.get_friends(update=True)
            if not wx_friends:
                return jsonify({"error": "Failed to get WeChat friends list"}), 500
        except Exception as e:
            logger.error(f"[ConfigGUIWeb] Error getting friends list: {str(e)}")
            return jsonify({"error": f"Error getting friends list: {str(e)}"}), 500
        friend_map = {}
        # for friend in wx_friends:
        #     if friend.get('NickName'):
        #         print(f"mjh_test friend['NickName'] {friend['NickName']};  friend {friend}")
        #         friend_map[friend['NickName']] = friend
        friend_map = {f['NickName']: f for f in wx_friends if f.get('NickName')}
        
        success_count = 0
        fail_count = 0
        failed_friends = []
        
        for friend_name in friends:
            try:
                if friend_name in friend_map:
                    friend = friend_map[friend_name]
                    user_id = friend['UserName']
                    time.sleep(random.uniform(1, 2))
                    itchat.send(msg=message, toUserName=user_id)
                    success_count += 1
                    logger.info(f"[ConfigGUIWeb] Sent message to {friend_name}-{user_id}")
                else:
                    fail_count += 1
                    failed_friends.append(friend_name)
                    logger.warning(f"[ConfigGUIWeb] Friend not found: {friend_name}")
            except Exception as e:
                fail_count += 1
                failed_friends.append(friend_name)
                logger.error(f"[ConfigGUIWeb] Failed to send message to {friend_name}: {e}")
        
        return jsonify({
            "message": "Broadcast completed",
            "success_count": success_count,
            "fail_count": fail_count,
            "failed_friends": failed_friends
        })
        
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Broadcast failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/export-config', methods=['GET'])
def export_config():
    """导出配置"""
    try:
        # 读取主配置
        with open('config.json', 'r', encoding='utf-8') as f:
            main_config = json.load(f)
            
        # 读取标签配置
        plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
        tag_config = {}
        if os.path.exists(plugin_config_path):
            with open(plugin_config_path, 'r', encoding='utf-8') as f:
                tag_config = json.load(f)
        
        # 合并配置
        export_data = {
            "main_config": main_config,
            "tag_config": tag_config
        }
        
        # 创建临时文件
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        with open(temp_file.name, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=4)
            
        # 使用 send_file 返回文件
        return send_file(
            temp_file.name,
            as_attachment=True,
            download_name=f'config_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json',
            mimetype='application/json'
        )
        
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Export config failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/import-config', methods=['POST'])
def import_config():
    """导入配置"""
    try:
        import_data = request.get_json()
        
        if not isinstance(import_data, dict):
            return jsonify({"error": "Invalid config format"}), 400
        
        main_config = import_data.get("main_config")
        tag_config = import_data.get("tag_config")
        
        if not main_config or not tag_config:
            return jsonify({"error": "Missing required config sections"}), 400
        
        # 备份现有配置
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if os.path.exists("config.json"):
            config_dir = "configs"
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            shutil.copy2("config.json", os.path.join(config_dir, f"config_backup_{timestamp}.json"))
            
        plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
        if os.path.exists(plugin_config_path):
            backup_path = os.path.join("plugins", "tag_manager", f"config_backup_{timestamp}.json")
            shutil.copy2(plugin_config_path, backup_path)
        
        # 保存新配置
        with open("config.json", 'w', encoding='utf-8') as f:
            json.dump(main_config, f, ensure_ascii=False, indent=4)
            
        os.makedirs(os.path.dirname(plugin_config_path), exist_ok=True)
        with open(plugin_config_path, 'w', encoding='utf-8') as f:
            json.dump(tag_config, f, ensure_ascii=False, indent=4)
            
        return jsonify({
            "message": "Configuration imported successfully",
            "backup_timestamp": timestamp
        })
        
    except Exception as e:
        logger.error(f"[ConfigGUIWeb] Import config failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/reset-config', methods=['POST'])
def reset_config():
    """获取默认配置值，但不保存"""
    try:
        # 准备默认配置
        default_main_config = {
            "nick_name_white_list": [],
            "nick_name_black_list": [],
            "random_reply_delay_min": 2,
            "random_reply_delay_max": 4,
            "channel_type": "wx",
            "model": "coze",  # 设置默认值为 coze
            "coze_api_base": "",
            "coze_api_key": "",
            "coze_bot_id": "",
            "text_to_image": "dall-e-3",
            "voice_to_text": "xunfei",
            "text_to_voice": "xunfei",
            "proxy": "",
            "single_chat_prefix": [""],
            "single_chat_reply_prefix": "",
            "group_chat_keyword": [],
            "group_chat_prefix": [""],
            "group_chat_reply_prefix": "",
            "group_chat_reply_suffix": "",
            "group_at_off": True,
            "group_name_white_list": [],
            "group_name_keyword_white_list": [],
            "group_chat_in_one_session": [],
            "concurrency_in_session": 1,
            "group_welcome_msg": "",
            "speech_recognition": True,
            "group_speech_recognition": True,
            "voice_reply_voice": False,
            "always_reply_voice": False,
            "conversation_max_tokens": 2000,
            "character_desc": "",
            "temperature": 0.5,
            "subscribe_msg": ""
        }
        
        default_tag_config = {
            "enable": False,
            "tag_prefix": "$",
            "allow_all_add_tag": False,
            "allow_all_remove_tag": False,
            "allow_all_view_tag": True,
            "allow_all_list_tag": True,
            "admin_users": [],
            "enabled_tags": [],
            "auto_reply": {},
            "tags_friends": {},
            "scheduled_tasks": [],
            "updateAutoReplyTable": True 
        }

        # 返回默认配置，但不保存
        return jsonify({
            "main_config": default_main_config,
            "tag_config": default_tag_config,
            "message": "Default configuration loaded successfully"
        })
        
    except Exception as e:
        error_msg = f"Failed to get default config: {str(e)}"
        logger.error(f"[ConfigGUIWeb] {error_msg}")
        return jsonify({"error": error_msg}), 500

# 添加新的保存配置接口
@app.route('/api/save-config', methods=['POST'])
def save_config():
    try:
        data = request.get_json()
        main_config = data.get('main_config', {})
        
        # 确保关键字段存在
        main_config = ensure_config_integrity(main_config)
        
        # 获取项目根目录
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(root_dir, 'config.json')
        
        # 读取现有配置
        existing_config = {}
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        
        # 更新配置
        existing_config.update(main_config)
        
        # 保存配置
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=4)
            
        return jsonify({"message": "Configuration saved successfully"})
    except Exception as e:
        error_msg = f"Failed to save config: {str(e)}"
        logger.error(f"[ConfigGUIWeb] {error_msg}")
        return jsonify({"error": error_msg}), 500

# 添加静态文件路由
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_file(os.path.join(app.root_path, 'static', filename))

# 添加favicon路由
@app.route('/favicon.ico')
def favicon():
    """返回空响应"""
    return '', 204
from channel.chat_message import ChatMessage
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import *
from bridge.bridge import Bridge
from common.expired_dict import ExpiredDict
from common.time_check import time_checker
import json
import os
import schedule
import time
import threading
from datetime import datetime, timedelta
import inspect
# import itchat  # 或其他微信API库
from lib import itchat
from lib.itchat.content import *
import traceback  # 在文件开头添加这个导入
from plugins import register, Plugin  # 确保正确导入装饰器和基类
import croniter
import pytz

logger.info("[TagManager] 开始注册插件...")

@register(
    name="TagManager",
    desc="群发消息管理插件",
    version="0.1",
    author="assistant",
    desire_priority=1000,
    hidden=False
)
class TagManager(Plugin):
    def __init__(self):
        logger.info("[TagManager] 开始初始化...")
        super().__init__()
        try:
            # 配置文件路径
            config_path = os.path.join(os.path.dirname(__file__), "config.json")
            
            # 加载配置文件
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                raise FileNotFoundError(f"配置文件未找到: {config_path}")
            
            # 注册事件处理器
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            
            # 注册命令
            self.commands = {
                "$群发": self._handle_mass_send,
                "$标签管理": self._handle_label_management,
                "$定时群发": self._handle_schedule_send,
                "$查看任务": self._handle_list_tasks,
                "$删除任务": self._handle_delete_task
            }
            
            # 初始化消息记录字典，设置过期时间为3600秒（1小时）
            self.expires_in_seconds = 3600
            self.receivedMsgs = ExpiredDict(self.expires_in_seconds)
            
            # 获取时区
            self.timezone = pytz.timezone(self.config.get("schedule_settings", {}).get("default_timezone", "Asia/Shanghai"))
            
            # 启动定时任务线程
            self.schedule_thread = threading.Thread(target=self._run_schedule, daemon=True)
            self.schedule_thread.start()
            
            # 恢复已保存的定时任务
            self._restore_tasks()
            
            logger.info("[TagManager] 插件初始化成功")
            
        except Exception as e:
            logger.error(f"[TagManager] 插件初始化失败: {e}")
            logger.error(traceback.format_exc())
            raise e

    def _run_schedule(self):
        """运行定时任务调度器"""
        while True:
            schedule.run_pending()
            time.sleep(1)
            
    def _restore_tasks(self):
        """恢复已保存的定时任务"""
        if "scheduled_tasks" in self.config:
            for task in self.config["scheduled_tasks"]:
                self._add_schedule_job(task["tag"], task.get("schedule_type", "每天"), task["time"], task["message"], task["id"])

    def _add_schedule_job(self, tag, schedule_type, time_str, message, task_id):
        """添加定时任务"""
        try:
            schedule_type, next_run = self._parse_schedule_time(schedule_type, time_str)
            
            def job():
                try:
                    result = self._mass_send_message(tag, message)
                    logger.info(f"[TagManager] 定时任务 {task_id} 执行完成: {result}")
                    
                    # 根据任务类型决定是否需要删除
                    if schedule_type == "once":
                        self.config["scheduled_tasks"] = [
                            task for task in self.config["scheduled_tasks"]
                            if task["id"] != task_id
                        ]
                        self._save_config()
                    
                except Exception as e:
                    logger.error(f"[TagManager] 定时任务 {task_id} 执行失败: {e}")

            # 根据不同的调度类型设置任务
            if schedule_type == "daily":
                schedule.every().day.at(time_str).do(job).tag(task_id)
            elif schedule_type == "weekly":
                weekday, time = time_str.split()
                getattr(schedule.every(), weekday.lower()).at(time).do(job).tag(task_id)
            elif schedule_type == "workday":
                schedule.every().day.at(time_str).do(job).tag(task_id)
            elif schedule_type == "once":
                schedule.every().day.at(next_run.strftime("%H:%M")).do(job).tag(task_id)
            elif schedule_type == "cron":
                # 对于 cron 表达式，我们需要自己计算下一次运行时间
                def cron_job():
                    job()
                    # 计算下一次运行时间
                    cron = croniter.croniter(time_str, datetime.now(self.timezone))
                    next_run = cron.get_next(datetime)
                    return schedule.CancelJob
                
                # 设置初始运行时间
                schedule.every().day.at(next_run.strftime("%H:%M")).do(cron_job).tag(task_id)
            
            logger.info(f"[TagManager] 已添加定时任务: {task_id}, 标签:{tag}, 类型:{schedule_type}, 时间:{time_str}")
            
        except Exception as e:
            logger.error(f"[TagManager] 添加定时任务失败: {e}")
            raise e

    def _parse_schedule_time(self, schedule_type, time_str):
        """解析定时任务时间
        支持的格式：
        - 今天 HH:MM
        - 明天 HH:MM
        - 后天 HH:MM
        - 每天 HH:MM
        - 工作日 HH:MM
        - 每周 weekday HH:MM (weekday: Monday-Sunday)
        - 具体日期 YYYY-MM-DD HH:MM
        - cron表达式 */5 * * * * (分 时 日 月 周)
        """
        try:
            now = datetime.now(self.timezone)
            
            if schedule_type == "今天":
                time_parts = time_str.split(":")
                if len(time_parts) != 2:
                    raise ValueError("时间格式错误，应为 HH:MM")
                hour, minute = map(int, time_parts)
                next_run = now.replace(hour=hour, minute=minute)
                return "once", next_run
            
            elif schedule_type == "明天":
                time_parts = time_str.split(":")
                if len(time_parts) != 2:
                    raise ValueError("时间格式错误，应为 HH:MM")
                hour, minute = map(int, time_parts)
                next_run = (now + timedelta(days=1)).replace(hour=hour, minute=minute)
                return "once", next_run
            
            elif schedule_type == "后天":
                time_parts = time_str.split(":")
                if len(time_parts) != 2:
                    raise ValueError("时间格式错误，应为 HH:MM")
                hour, minute = map(int, time_parts)
                next_run = (now + timedelta(days=2)).replace(hour=hour, minute=minute)
                return "once", next_run
            
            elif schedule_type == "每天":
                try:
                    time_parts = time_str.split(":")
                    if len(time_parts) != 2:
                        raise ValueError("时间格式错误，应为 HH:MM")
                    hour, minute = map(int, time_parts)
                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        raise ValueError("无效的时间值")
                    next_run = now.replace(hour=hour, minute=minute)
                    if next_run <= now:
                        next_run += timedelta(days=1)
                    return "daily", next_run
                except ValueError as e:
                    raise ValueError(f"时间格式错误: {str(e)}")
            
            elif schedule_type == "工作日":
                time_parts = time_str.split(":")
                if len(time_parts) != 2:
                    raise ValueError("时间格式错误，应为 HH:MM")
                hour, minute = map(int, time_parts)
                next_run = now.replace(hour=hour, minute=minute)
                while next_run.weekday() > 4 or next_run <= now:  # 0-4 表示周一至周五
                    next_run += timedelta(days=1)
                return "workday", next_run
            
            elif schedule_type == "每周":
                weekday, time = time_str.split()
                weekdays = {
                    "Monday": 0, "Tuesday": 1, "Wednesday": 2,
                    "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
                }
                if weekday not in weekdays:
                    raise ValueError("无效的星期值")
                time_parts = time.split(":")
                if len(time_parts) != 2:
                    raise ValueError("时间格式错误，应为 HH:MM")
                hour, minute = map(int, time_parts)
                current_weekday = now.weekday()
                days_ahead = weekdays[weekday] - current_weekday
                if days_ahead <= 0:
                    days_ahead += 7
                next_run = now.replace(hour=hour, minute=minute) + timedelta(days=days_ahead)
                return "weekly", next_run
            
            elif schedule_type == "具体日期":
                try:
                    next_run = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                    next_run = self.timezone.localize(next_run)
                    if next_run <= now:
                        raise ValueError("指定的时间已过期")
                    return "once", next_run
                except ValueError as e:
                    raise ValueError("日期格式错误，应为 YYYY-MM-DD HH:MM")
            
            elif schedule_type == "cron":
                try:
                    cron = croniter.croniter(time_str, now)
                    next_run = cron.get_next(datetime)
                    return "cron", next_run
                except Exception as e:
                    raise ValueError(f"无效的cron表达式: {str(e)}")
            
            else:
                raise ValueError("不支持的调度类型")
        except Exception as e:
            raise ValueError(f"解析时间失败: {str(e)}")

    def _handle_schedule_send(self, content: str) -> Reply:
        """处理定时群发命令"""
        try:
            # 解析命令格式：$定时群发 [标签名] [调度类型] [时间] [消息内容]
            parts = content.split(" ", 4)
            if len(parts) != 5:
                raise ValueError(
                    "格式错误，请使用以下格式之一：\n"
                    "1. $定时群发 [标签名] 每天 HH:MM [消息内容]\n"
                    "2. $定时群发 [标签名] 每周 Monday HH:MM [消息内容]\n"
                    "3. $定时群发 [标签名] 工作日 HH:MM [消息内容]\n"
                    "4. $定时群发 [标签名] 具体日期 YYYY-MM-DD HH:MM [消息内容]\n"
                    "5. $定时群发 [标签名] cron */5 * * * * [消息内容]"
                )
            
            _, tag, schedule_type, time_str, message = parts
            
            # 验证时间格式
            if schedule_type == "工作日":
                # 工作日需要时间
                try:
                    datetime.strptime(time_str, "%H:%M")
                except ValueError:
                    raise ValueError("时间格式错误，请使用 HH:MM 格式，例如: 08:30")
            else:
                # 其他调度类型的时间验证
                try:
                    datetime.strptime(time_str, "%H:%M")
                except ValueError:
                    raise ValueError("时间格式错误，请使用 HH:MM 格式，例如: 08:30")
            
            # 生成任务ID
            task_id = f"task_{int(time.time())}"
            # 获取当前时间
            created_at = datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S")
            
            # 创建新任务
            new_task = {
                "id": task_id,
                "tag": tag,
                "schedule_type": schedule_type,
                "time": time_str,
                "message": message,
                "created_at": created_at
            }
            
            # 检查任务数量限制
            max_tasks = self.config.get("schedule_settings", {}).get("max_tasks", 100)
            if len(self.config.get("scheduled_tasks", [])) >= max_tasks:
                raise ValueError(f"定时任务数量已达到上限 ({max_tasks})")
            
            # 添加到配置
            if "scheduled_tasks" not in self.config:
                self.config["scheduled_tasks"] = []
            self.config["scheduled_tasks"].append(new_task)
            
            # 保存配置
            self._save_config()
            
            # 添加到调度器
            self._add_schedule_job(tag, schedule_type, time_str, message, task_id)
            
            return Reply(ReplyType.TEXT, 
                f"✅ 定时任务创建成功\n"
                f"------------------------\n"
                f"任务ID: {task_id}\n"
                f"标签: {tag}\n"
                f"调度类型: {schedule_type}\n"
                f"时间: {time_str}\n"
                f"消息: {message}\n"
                f"------------------------\n"
                f"可使用「$查看任务」查看所有任务\n"
                f"使用「$删除任务 {task_id}」删除此任务"
            )
            
        except Exception as e:
            error_msg = f"创建任务失败: {str(e)}"
            logger.error(f"[TagManager] {error_msg}")
            logger.error(traceback.format_exc())
            return Reply(ReplyType.ERROR, error_msg)

    def _handle_list_tasks(self, content: str) -> Reply:
        """处理查看任务命令"""
        try:
            tasks = self.config.get("scheduled_tasks", [])
            if not tasks:
                return Reply(ReplyType.TEXT, "当前没有定时任务")
            
            task_list = []
            for task in tasks:
                created_at = task.get('created_at', '未知')
                schedule_type = task.get('schedule_type', '每天')  # 兼容旧版本任务
                task_info = (
                    f"任务ID: {task['id']}\n"
                    f"标签: {task['tag']}\n"
                    f"调度类型: {schedule_type}\n"
                    f"时间: {task['time']}\n"
                    f"消息: {task['message']}\n"
                    f"创建时间: {created_at}\n"
                    f"------------------------"
                )
                task_list.append(task_info)
            
            return Reply(ReplyType.TEXT, "\n".join(task_list))
            
        except Exception as e:
            error_msg = f"查看任务失败: {str(e)}"
            logger.error(f"[TagManager] {error_msg}")
            return Reply(ReplyType.ERROR, error_msg)

    def on_handle_context(self, e_context: EventContext):
        """
        处理消息
        :param e_context: 消息上下文
        """
        try:
            # 获取 context 对象
            context = e_context.econtext.get('context')
            if not context:
                logger.debug("[TagManager] Context not found in econtext")
                return
                
            # 检查消息类型
            if not hasattr(context, 'type') or context.type != ContextType.TEXT:
                logger.debug("[TagManager] Not a text message")
                return
                
            # 获取消息内容
            content = context.content.strip() if context.content else ""
            
            # 获取消息对象
            msg = context.kwargs.get("msg")
            if not msg:
                logger.debug("[TagManager] No message object found")
                return
                
            # 获取发送者昵称
            from_user_name = msg.from_user_nickname
            logger.debug(f"[TagManager] 收到消息: {content} from {from_user_name}")

            # 检查命令
            command = content.split()[0] if content.split() else ""
            if not command in self.commands:
                logger.debug(f"[TagManager] Not a command: {command}")
                return
                
            # 检查权限
            if from_user_name not in self.config["admin_users"]:
                logger.debug(f"[TagManager] 用户 {from_user_name} 不是管理员")
                e_context.action = EventAction.CONTINUE
                return

            # 执行命令
            logger.info(f"[TagManager] 执行命令: {command} 参数: {content}")
            reply = self.commands[command](content)
            
            # 处理回复
            if reply:
                logger.debug(f"[TagManager] Reply generated: {reply.type}, {reply.content}")
                e_context.econtext['reply'] = reply
            else:
                e_context.econtext['reply'] = Reply(ReplyType.TEXT, "命令执行成功，但没有返回信息。")
                
            e_context.action = EventAction.BREAK_PASS
            
        except Exception as e:
            logger.error(f"[TagManager] 处理消息失败: {e}")
            logger.error(traceback.format_exc())
            e_context.econtext['reply'] = Reply(ReplyType.ERROR, f"处理消息失败: {str(e)}")
            e_context.action = EventAction.BREAK_PASS

    def _handle_mass_send(self, content: str) -> Reply:
        """处理群发命令"""
        try:
            parts = content.split(" ", 2)
            if len(parts) != 3:
                raise ValueError("格式错误，请使用: $群发 [标签名] [消息内容]")
            
            _, tag, message = parts
            result = self._mass_send_message(tag, message)
            return Reply(ReplyType.TEXT, f"群发执行结果: {result}")
            
        except Exception as e:
            return Reply(ReplyType.ERROR, f"群发失败: {str(e)}")
            # todo  错误处理

    def _handle_label_management(self, content: str) -> Reply:
        """处理标签管理命令"""
        try:
            parts = content.split(" ", 2)
            logger.debug(f"[TagManager] 处理标签管理命令: {parts}")
            
            if not os.path.exists(self.tag_config_path):
                tag_config = {
                    "tag_list": [],
                    "tag_members": {
                        "标签1": ["用户昵称", "用户昵称2"],
                        "标签2": ["用户昵称3", "用户昵称4"]
                    }
                }
                
                with open(self.tag_config_path, "w", encoding="utf-8") as f:
                    json.dump(tag_config, f, indent=4, ensure_ascii=False)
                    logger.info("[TagManager] 创建默认标签文件")

            with open(self.tag_config_path, "r", encoding="utf-8") as f:
                self.tag_config = json.load(f)
                logger.info(f"[TagManager] 标签文件: {self.tag_config}")
            
            if parts[1] == "标签列表":
                tag_list = self.tag_config["tag_list"]
                return Reply(ReplyType.TEXT, f"标签列表: {tag_list}")
                
        except Exception as e:
            logger.error(f"[TagManager] 标签管理失败: {e}")
            return Reply(ReplyType.ERROR, f"标签管理失败: {str(e)}")

    def _handle_delete_task(self, content: str) -> Reply:
        """处理删除任务命令"""
        try:
            logger.info(f"[TagManager] 开始处理删除任务命令: {content}")
            parts = content.split(" ", 1)
            if len(parts) != 2:
                raise ValueError("格式错误，请使用: $删除任务 [任务ID]")
            
            _, task_id = parts
            task_id = task_id.strip()  # 去除可能的空格
            logger.info(f"[TagManager] 准备删除任务: {task_id}")
            
            # 检查任务是否存在
            tasks = self.config.get("scheduled_tasks", [])
            task_info = None
            for task in tasks:
                if task["id"] == task_id:
                    task_info = task
                    break
                
            if not task_info:
                logger.warning(f"[TagManager] 未找到任务: {task_id}")
                return Reply(ReplyType.TEXT, f"❌ 未找到任务 {task_id}\n请使用「$查看任务」确认任务ID")
            
            try:
                # 从调度器中删除任务
                schedule.clear(task_id)
                logger.info(f"[TagManager] 已从调度器中删除任务: {task_id}")
            except Exception as e:
                logger.error(f"[TagManager] 从调度器删除任务失败: {e}")
                # 继续执行，因为配置中的任务仍然需要删除
            
            # 从配置中删除任务
            self.config["scheduled_tasks"] = [
                task for task in tasks
                if task["id"] != task_id
            ]
            
            # 保存配置
            try:
                self._save_config()
                logger.info(f"[TagManager] 已从配置文件中删除任务: {task_id}")
            except Exception as e:
                logger.error(f"[TagManager] 保存配置失败: {e}")
                raise ValueError("保存配置失败，请重试")
            
            # 构建成功提示消息
            reply_text = (
                f"✅ 任务删除成功\n"
                f"------------------------\n"
                f"任务ID: {task_info['id']}\n"
                f"标签: {task_info['tag']}\n"
                f"调度类型: {task_info.get('schedule_type', '每天')}\n"
                f"时间: {task_info['time']}\n"
                f"消息: {task_info['message']}\n"
                f"------------------------\n"
                f"可使用「$查看任务」查看剩余任务"
            )
            logger.info(f"[TagManager] {reply_text}")
            return Reply(ReplyType.TEXT, reply_text)
            
        except Exception as e:
            error_msg = f"删除任务失败: {str(e)}"
            logger.error(f"[TagManager] {error_msg}")
            logger.error(traceback.format_exc())
            return Reply(ReplyType.ERROR, error_msg)

    def _mass_send_message(self, tag: str, message: str) -> str:
        """群发消息到指定标签的好友"""
        try:
            # 获取该标签的所有好友
            members = self._get_tagged_friends(tag)

            success_count = 0
            fail_count = 0
            
            # 遍历发送私信
            for friend in members:
                try:
                    user_id = friend['UserName']  # 微信用户ID
                    itchat.send_msg(message, toUserName=user_id)
                    success_count += 1
                    logger.info(f"[TagManager] 已向好友 {friend.get('NickName', user_id)} 发送消息")
                except Exception as e:
                    fail_count += 1
                    error_stack = traceback.format_exc()  # 获取完整的错误栈信息
                    logger.error(f"[TagManager] 获取标签好友失败: {e}\n错误栈:\n{error_stack}")
                    logger.error(f"[TagManager] 向好友发送消息失败: {e}")

            result = f"群发完成 - 成功: {success_count}, 失败: {fail_count}"
            logger.info(f"[TagManager] {result}")
            return result    
            # TODO: 实现实际的消息发送逻辑
            # 这里需要根据您的微信API实现具体的发送逻辑
            
            # return f"消息已发送给标签 '{tag}' 下的 {len(members)} 个成员"
            
        except Exception as e:
            logger.error(f"[TagManager] 群发消息失败: {e}")
            return f"群发失败: {str(e)}"

    def _get_tagged_friends(self, tag_name: str):
        """
        获取指定标签的所有好友
        返回 [ "userName"]
        
        """
        try:

            friends = itchat.get_friends()    

            logger.debug(f"[TagManager] _get_tagged_friends  friends size{friends}")
            
            tagged_friends = self.config["tags_friends"][tag_name]
            result = []
            for friend in friends:
                if friend['NickName'] in tagged_friends:
                    result.append(friend)
                    
            logger.info(f"[TagManager] 标签 {tag_name} 下有 {len(tagged_friends)} ; result {result} ;个好友")
            return result
            
        except Exception as e:
            error_stack = traceback.format_exc()  # 获取完整的错误栈信息
            logger.error(f"[TagManager] 获取标签好友失败: {e}\n错误栈:\n{error_stack}")
            return []

    def _get_user_tags(self, user_name: str):
        """获取用户的标签列表"""
        # TODO: 实现实际的标签获取逻辑
        return self.config["enabled_tags"]

    def _save_config(self):
        """保存配置到文件"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            logger.info("[TagManager] 配置已保存")
        except Exception as e:
            logger.error(f"[TagManager] 保存配置失败: {e}")
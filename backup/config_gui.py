from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from plugins import *
from config import conf
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame
from ttkbootstrap.tooltip import ToolTip
import json
import os
from datetime import datetime
import shutil
from pathlib import Path
from lib import itchat
import random
import traceback
import time
import threading
import schedule
from plugins import register, Plugin
import platform
import glob
import signal
import subprocess

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

logger.info("[ConfigGUI] 开始注册插件...")
@register(
    name="ConfigGUI",
    desc="A GUI tool for managing ChatGPT-WeChat configurations",
    version="1.0",
    author="lanvent",
    desire_priority=0
)
class ConfigGUIPlugin(Plugin):
    def __init__(self):
        super().__init__()
        self.xvfb_process = None
        self.is_windows = platform.system().lower() == 'windows'
        self.linux_distro = None if self.is_windows else get_linux_distro()
        logger.info(f"[ConfigGUI] 系统类型: {'Windows' if self.is_windows else self.linux_distro}")
        
        # 配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        
        # 加载配置文件
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            raise FileNotFoundError(f"配置文件未找到: {config_path}")
        
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        logger.info("[ConfigGUI] inited")
        self.config_window = None
        
        # 移除初始化时的调度器启动
        self.schedule_thread = None
        
    def init_scheduler(self):
        """初始化调度器，仅在需要时调用"""
        if self.schedule_thread is None:
            # 初始化调度器
            schedule.clear()  # 清除所有现有任务
            
            # 加载现有定时任务
            self.load_scheduled_tasks()
            
            # 启动定时任务线程
            self.schedule_thread = threading.Thread(target=self.run_schedule, daemon=True)
            self.schedule_thread.start()
            logger.info("[ConfigGUI] 调度器已启动")

    def on_handle_context(self, e_context: EventContext):
        """处理消息"""
        context = e_context['context']
        logger.info("[ConfigGUI] 开始处理消息...")

        if context.type != ContextType.TEXT:
            return
            
        content = context.content.strip()
        
        if content == "#config":  # 触发配置GUI的命令
            # 检查是否是管理员
            if not context['isgroup']:  # 私聊消息
                if context['msg'].from_user_nickname not in self.config["admin_users"]:
                    reply = Reply(ReplyType.ERROR, "抱歉,只有管理员才能使用配置工具")
                    e_context['reply'] = reply
                    e_context.action = EventAction.BREAK_PASS
                    return
                
                # 在首次打开配置界面时初始化调度器
                if self.schedule_thread is None:
                    self.init_scheduler()
                                 
                # 启动配置GUI
                self.show_config_gui()
                
                reply = Reply(ReplyType.INFO, "配置工具已关闭")
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
        e_context.action = EventAction.CONTINUE

    def show_config_gui(self):
        """显示配置界面"""
        if getattr(self, '_gui_running', False):
            logger.info("[ConfigGUI] GUI已在运行")
            return
        
        try:
            self._gui_running = True
            
            if not self.is_windows:
                if not self.setup_display():
                    raise Exception("无法设置显示环境")
            
            logger.info(f"[ConfigGUI] 使用显示环境: {os.environ['DISPLAY']}")
            
            # 创建GUI窗口
            try:
                import ttkbootstrap as ttk
                
                # 创建根窗口并立即设置主题
                root = ttk.Window(
                    title="ChatGPT-WeChat 配置工具",
                    size=(800, 600),
                    themename="litera",  # 设置默认主题
                    resizable=(True, True),  # 允许调整大小
                    iconphoto=False  # 禁用图标
                )
                
                # 设置窗口位置
                screen_width = root.winfo_screenwidth()
                screen_height = root.winfo_screenheight()
                x = (screen_width - 800) // 2
                y = (screen_height - 600) // 2
                root.geometry(f"800x600+{x}+{y}")
                
                # 禁用主题切换事件
                def dummy_event(*args, **kwargs):
                    pass
                root.bind("<<ThemeChanged>>", dummy_event)
                
                logger.info("[ConfigGUI] GUI窗口创建成功")
                
                # 创建应用实例
                app = ModernConfigGUI(root, self)
                
                def on_closing():
                    logger.info("[ConfigGUI] 关闭GUI窗口")
                    root.unbind("<<ThemeChanged>>")  # 解绑事件
                    self.cleanup_display()
                    root.destroy()
                    self._gui_running = False
                    
                root.protocol("WM_DELETE_WINDOW", on_closing)
                
                logger.info("[ConfigGUI] 开始GUI主循环")
                root.mainloop()
                
            except Exception as e:
                logger.error(f"[ConfigGUI] 创建GUI窗口失败: {str(e)}")
                raise
            
        except Exception as e:
            logger.error(f"[ConfigGUI] GUI运行出错: {str(e)}")
            self.cleanup_display()
            self._gui_running = False

    def cleanup_display(self):
        """清理显示环境"""
        try:
            # 1. 终止所有Xvfb进程
            try:
                subprocess.run(['pkill', '-9', 'Xvfb'], 
                             stdout=subprocess.DEVNULL, 
                             stderr=subprocess.DEVNULL)
            except:
                pass
            
            # 2. 等待进程完全终止
            time.sleep(1)
            
            # 3. 清理所有锁文件和套接字
            files_to_remove = [
                '/tmp/.X99-lock',
                '/tmp/.X11-unix/X99',
                '/tmp/.X*',
                '/tmp/.X11-unix/*'
            ]
            
            for pattern in files_to_remove:
                try:
                    for f in glob.glob(pattern):
                        if os.path.exists(f):
                            if os.path.isfile(f):
                                os.unlink(f)
                            elif os.path.isdir(f):
                                shutil.rmtree(f)
                except Exception as e:
                    logger.warning(f"[ConfigGUI] 清理文件失败 {pattern}: {str(e)}")
                
            # 4. 重新创建目录
            os.makedirs('/tmp/.X11-unix', exist_ok=True)
            os.chmod('/tmp/.X11-unix', 0o1777)
            os.chmod('/tmp', 0o1777)
            
            # 5. 清理环境变量
            if 'DISPLAY' in os.environ:
                del os.environ['DISPLAY']
            
            # 6. 清理进程引用
            if hasattr(self, 'xvfb_process') and self.xvfb_process:
                try:
                    os.killpg(os.getpgid(self.xvfb_process.pid), signal.SIGKILL)
                except:
                    pass
                self.xvfb_process = None
            
            logger.info("[ConfigGUI] 显示环境已清理")
            
        except Exception as e:
            logger.error(f"[ConfigGUI] 清理显示环境失败: {str(e)}")

    def load_scheduled_tasks(self):
        """加载现有定时任务到调度器"""
        try:
            plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, 'r', encoding='utf-8') as f:
                    tag_config = json.load(f)
                    tasks = tag_config.get("scheduled_tasks", [])
                    for task in tasks:
                        self.schedule_task(
                            task["id"],
                            task["tag"],
                            task["time"],
                            task["message"]
                        )
                    logger.info(f"[ConfigGUI] 已加载 {len(tasks)} 个定时任务")
        except Exception as e:
            logger.error(f"[ConfigGUI] 加载定时任务失败: {e}")
            
    def schedule_task(self, task_id, tag, time_str, message):
        """调度定时任务"""
        try:
            # 先清除所有相关的任务
            schedule.clear(tag=task_id)
            
            # 创建一个任务执行状态记录
            task_status = {
                'last_execution': None,
                'is_running': False
            }
            
            def job():
                # 检查是否已经执行过
                current_time = datetime.now()
                if (task_status['last_execution'] and 
                    current_time.date() == task_status['last_execution'].date()):
                    logger.debug(f"[ConfigGUI] 任务 {task_id} 今天已执行，跳过")
                    return
                    
                # 检查任务是否正在执行
                if task_status['is_running']:
                    logger.debug(f"[ConfigGUI] 任务 {task_id} 正在执行中，跳过")
                    return
                    
                task_status['is_running'] = True
                try:
                    # 检查微信登录状态
                    if not itchat.check_login():
                        itchat.auto_login(hotReload=True)
                        time.sleep(1)
                    
                    # 获取标签下的好友
                    plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
                    with open(plugin_config_path, 'r', encoding='utf-8') as f:
                        tag_config = json.load(f)
                        tags_friends = tag_config.get("tags_friends", {})
                    
                    if tag not in tags_friends:
                        logger.error(f"[ConfigGUI] 标签 '{tag}' 不存在")
                        return
                        
                    friends = tags_friends[tag]
                    if not friends:
                        logger.error(f"[ConfigGUI] 标签 '{tag}' 下没有好友")
                        return
                    
                    # 获取所有微信好友
                    wx_friends = itchat.get_friends(update=True)
                    friend_map = {f['NickName']: f for f in wx_friends if f.get('NickName')}
                    
                    # 发送消息
                    for friend_name in friends:
                        if friend_name in friend_map:
                            friend = friend_map[friend_name]
                            user_id = friend['UserName']
                            time.sleep(random.uniform(1, 2))
                            itchat.send(msg=message, toUserName=user_id)
                            logger.info(f"[ConfigGUI] 定时任务 {task_id} 已向好友 {friend_name} 发送消息")
                    
                    # 更新最后执行时间
                    task_status['last_execution'] = current_time
                    
                except Exception as e:
                    logger.error(f"[ConfigGUI] 定时任务 {task_id} 执行失败: {e}")
                finally:
                    task_status['is_running'] = False
            
            # 设置定时任务，使用唯一标识符
            schedule.every().day.at(time_str).do(job).tag(task_id)
            logger.info(f"[ConfigGUI] 已设置定时任务 {task_id}, 时间: {time_str}")
            
        except Exception as e:
            logger.error(f"[ConfigGUI] 设置定时任务 {task_id} 失败: {e}")
            
    def run_schedule(self):
        """运行调度器"""
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                logger.error(f"[ConfigGUI] 调度器运行错误: {e}")
                time.sleep(5)  # 发生错误时等待较长时间再重试

    def setup_display(self):
        """配置显示环境"""
        if self.is_windows:
            return True
        
        try:
            import subprocess
            import os
            import time
            import signal
            import tkinter as tk
            
            logger.info("[ConfigGUI] 开始配置显示环境...")
            
            # 1. 确保环境干净
            self.cleanup_display()
            
            # 2. 验证环境清理完成
            if os.path.exists('/tmp/.X99-lock'):
                raise Exception("无法清理显示环境锁文件")
            
            # 3. 设置显示号
            display_num = 99
            display = f":{display_num}"
            
            # 4. 设置环境变量
            os.environ['DISPLAY'] = display
            
            # 5. 启动Xvfb
            xvfb_cmd = [
                '/usr/bin/Xvfb',
                display,
                '-screen', '0', '1024x768x24',
                '-ac',
                '+extension', 'GLX',
                '+render',
                '-noreset',
                '-nolisten', 'tcp'
            ]
            
            logger.info(f"[ConfigGUI] 启动命令: {' '.join(xvfb_cmd)}")
            
            # 启动进程
            self.xvfb_process = subprocess.Popen(
                xvfb_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid
            )
            
            # 等待启动
            time.sleep(3)
            
            # 检查进程状态
            if self.xvfb_process.poll() is not None:
                out, err = self.xvfb_process.communicate()
                logger.error(f"[ConfigGUI] Xvfb启动失败: {err.decode()}")
                return False
            
            # 只测试基本的tkinter
            try:
                logger.info(f"[ConfigGUI] 测试显示环境 DISPLAY={os.environ['DISPLAY']}")
                
                test_window = tk.Tk()
                test_window.withdraw()
                screen_width = test_window.winfo_screenwidth()
                screen_height = test_window.winfo_screenheight()
                test_window.destroy()
                
                logger.info(f"[ConfigGUI] 显示测试成功: {screen_width}x{screen_height}")
                return True
                
            except Exception as e:
                logger.error(f"[ConfigGUI] 显示环境测试失败: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"[ConfigGUI] 配置显示环境失败: {str(e)}")
            return False

    def load_config(self):
        """加载配置文件"""
        try:
            # 加载主配置文件
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    # 加载名单配置
                    self.set_text_content(self.nick_name_white_list, config.get('nick_name_white_list', []))
                    self.set_text_content(self.nick_name_black_list, config.get('nick_name_black_list', []))
                    
                    # 加载延时配置
                    self.random_reply_delay_min_var.set(str(config.get('random_reply_delay_min', 2)))
                    self.random_reply_delay_max_var.set(str(config.get('random_reply_delay_max', 4)))
                    
            # 单独加载标签插件配置
            self.load_tag_config()
                
        except FileNotFoundError:
            messagebox.showwarning("警告", "配置文件不存在，将使用默认配置")
        except Exception as e:
            messagebox.showerror("错误", f"加载配置时出错：\n{str(e)}")

    def save_config(self):
        """保存配置"""
        try:
            # 获取主配置
            config = self.get_current_config()
            if not config:
                return False
            
            # 确保配置目录存在
            os.makedirs("configs", exist_ok=True)
            
            # 备份当前主配置
            if os.path.exists("config.json"):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = os.path.join("configs", f"config_backup_{timestamp}.json")
                shutil.copy2("config.json", backup_file)
            
            # 保存主配置文件（不包含标签插件配置）
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            
            # 单独保存标签插件配置
            tag_saved = self.save_tag_config()
            
            if tag_saved:
                messagebox.showinfo("成功", "所有配置已保存")
                logger.info("[ConfigGUI] 配置保存成功")
                return True
            else:
                messagebox.showwarning("部分成功", "主配置已保存，但标签配置保存失败")
                return False
            
        except Exception as e:
            error_msg = f"保存配置时出错：{str(e)}"
            logger.error(f"[ConfigGUI] {error_msg}")
            messagebox.showerror("错误", error_msg)
            return False

    def reset_config(self):
        """重置配置到默认值"""
        if messagebox.askyesno("确认", "确定要重置所有配置为默认值吗？\n注意：重置后需要手动保存才会生效。"):
            try:
                # 名单配置重置
                self.reset_list_settings()
                
                # 延时配置重置
                self.reset_delay_settings()
                
                # 标签插件配置重置
                self.reset_tag_settings()
                
                messagebox.showinfo("成功", "配置已重置为默认值\n如需保存更改，请点击「保存配置」按钮")
                
            except Exception as e:
                error_msg = f"重置配置时出错：{str(e)}"
                logger.error(f"[ConfigGUI] {error_msg}")
                messagebox.showerror("错误", error_msg)

    def reset_list_settings(self):
        """重置名单配置"""
        # 清空白名单
        self.nick_name_white_list.delete('1.0', tk.END)
        # 清空黑名单
        self.nick_name_black_list.delete('1.0', tk.END)

    def reset_delay_settings(self):
        """重置延时配置为初始默认值"""
        try:
            # 使用与create_delay_settings中相同的默认值
            self.random_reply_delay_min_var.set("2")  # 与创建时的默认值保持一致
            self.random_reply_delay_max_var.set("4")  # 与创建时的默认值保持一致
            
            # 验证设置是否成功
            if (self.random_reply_delay_min_var.get() != "2" or 
                self.random_reply_delay_max_var.get() != "4"):
                raise ValueError("延时配置重置失败")
                
            logger.debug("[ConfigGUI] 延时配置已重置为默认值")
            
        except Exception as e:
            logger.error(f"[ConfigGUI] 重置延时配置时出错: {e}")
            raise

    def reset_tag_settings(self):
        """重置标签插件配置"""
        try:
            # 重置基本设置
            self.enable_tag_var.set(False)
            self.tag_prefix_var.set("#")
            self.allow_all_add_tag_var.set(False)
            self.allow_all_remove_tag_var.set(False)
            self.allow_all_view_tag_var.set(False)
            self.allow_all_list_tag_var.set(False)
            
            # 清空标签和管理员列表
            if hasattr(self, 'enabled_tags'):
                self.enabled_tags.delete('1.0', tk.END)
            if hasattr(self, 'admin_users'):
                self.admin_users.delete('1.0', tk.END)
            
            # 重置标签好友关系
            self.tags_friends.clear()
            self.refresh_aliases_table()
            
            # 重置自动回复配置
            for row in self.auto_reply_rows:
                if isinstance(row, dict) and "frame" in row:
                    row["frame"].destroy()
            self.auto_reply_rows.clear()
            
            # 重置定时任务配置
            for task in self.scheduled_tasks:
                if isinstance(task, dict) and "frame" in task:
                    task["frame"].destroy()
            self.scheduled_tasks.clear()
            
            # 清空群发消息和定时任务的输入框
            if hasattr(self, 'broadcast_message_var'):
                self.broadcast_message_var.set('')
            if hasattr(self, 'task_time_var'):
                self.task_time_var.set('')
            if hasattr(self, 'task_message_var'):
                self.task_message_var.set('')
            
            # 清空群发消息和定时任务的标签选择
            if hasattr(self, 'broadcast_tag_combo'):
                self.broadcast_tag_combo.set('')
            if hasattr(self, 'task_tag_combo'):
                self.task_tag_combo.set('')
            
        except Exception as e:
            logger.error(f"[ConfigGUI] 重置标签设置时出错: {e}")
            raise

    def create_import_export_buttons(self):
        """创建配置操作区域"""
        operation_frame = ttk.LabelFrame(
            self.main_container,
            text="配置操作",
            padding="10"
        )
        operation_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        # 创建按钮区域（居中）
        button_frame = ttk.Frame(operation_frame)
        button_frame.pack(expand=True)
        
        # 导入配置按钮
        import_btn = ttk.Button(
            button_frame,
            text="导入配置",
            command=self.import_config,
            style="primary.TButton",
            width=12
        )
        import_btn.pack(side=tk.LEFT, padx=5)
        
        # 导出配置按钮
        export_btn = ttk.Button(
            button_frame,
            text="导出配置",
            command=self.export_config,
            style="info.TButton",
            width=12
        )
        export_btn.pack(side=tk.LEFT, padx=5)
        
        # 保存配置按钮
        save_btn = ttk.Button(
            button_frame,
            text="保存配置",
            command=self.save_config,
            style="success.TButton",
            width=12
        )
        save_btn.pack(side=tk.LEFT, padx=5)
        
        # 重置配置按钮
        reset_btn = ttk.Button(
            button_frame,
            text="重置配置",
            command=self.reset_config,
            style="danger.TButton",
            width=12
        )
        reset_btn.pack(side=tk.LEFT, padx=5)
        
        # 添加工具提示
        ToolTip(import_btn, "从其他配置文件导入")
        ToolTip(export_btn, "将当前配置导出到新文件")
        ToolTip(save_btn, "保存当前配置")
        ToolTip(reset_btn, "重置为默认配置")

    def export_config(self):
        """导出配置文件"""
        try:
            # 让用户选择保存位置
            file_path = filedialog.asksaveasfilename(
                title="导出配置",
                initialfile="config_backup.json",
                defaultextension=".json",
                filetypes=[("JSON 配置文件", "*.json"), ("所有文件", "*.*")],
                initialdir="configs"
            )
            
            if not file_path:  # 用户取消选择
                return
                
            # 确保configs目录存在
            os.makedirs("configs", exist_ok=True)
            
            # 获取当前主配置
            main_config = self.get_current_config()
            if not main_config:
                return
            
            # 获取标签管理插件配置
            tag_config = {
                "enable": self.enable_tag_var.get(),
                "tag_prefix": self.tag_prefix_var.get(),
                "allow_all_add_tag": self.allow_all_add_tag_var.get(),
                "allow_all_remove_tag": self.allow_all_remove_tag_var.get(),
                "allow_all_view_tag": self.allow_all_view_tag_var.get(),
                "allow_all_list_tag": self.allow_all_list_tag_var.get(),
                "admin_users": self.get_list_from_text(self.admin_users),
                "enabled_tags": self.get_list_from_text(self.enabled_tags),
                "tags_friends": self.tags_friends,
                "auto_reply": self.get_auto_reply_config(),
                "scheduled_tasks": self.get_scheduled_tasks_config()
            }
            
            # 合并配置
            export_config = {
                **main_config,  # 主配置
                "tag_plugin": tag_config  # 标签插件配置
            }
            
            # 写入配置文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_config, f, indent=4, ensure_ascii=False)
            
            # 添加成功提示
            messagebox.showinfo(
                "导出成功",
                f"配置已成功导出到：\n{file_path}"
            )
            
            # 记录日志
            logger.info(f"[ConfigGUI] 配置已导出到: {file_path}")
            
        except Exception as e:
            error_msg = f"导出配置时出错：{str(e)}"
            logger.error(f"[ConfigGUI] {error_msg}")
            messagebox.showerror("错误", error_msg)

    def import_config(self):
        """导入配置文件"""
        try:
            # 使用现代风格的文件选择对话框
            file_path = filedialog.askopenfilename(
                title="选择配置文件",
                filetypes=[
                    ("JSON 配置文件", "*.json"),
                    ("所有文件", "*.*")
                ],
                initialdir="configs"
            )
            
            if not file_path:
                return
            
            # 备份当前配置
            if os.path.exists("config.json"):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = os.path.join("configs", f"config_backup_{timestamp}.json")
                shutil.copy2("config.json", backup_file)
            
            # 读取并验证新配置
            with open(file_path, 'r', encoding='utf-8') as f:
                new_config = json.load(f)
            
            self.validate_config(new_config)
            
            # 处理标签配置
            if "tag_plugin" in new_config:
                tag_config = new_config.pop("tag_plugin")  # 移除标签配置并保存
                plugin_dir = os.path.join("plugins", "tag_manager")
                os.makedirs(plugin_dir, exist_ok=True)
                plugin_config_path = os.path.join(plugin_dir, "config.json")
                
                # 备份现有标签配置
                if os.path.exists(plugin_config_path):
                    backup_tag_file = os.path.join(plugin_dir, f"config_backup_{timestamp}.json")
                    shutil.copy2(plugin_config_path, backup_tag_file)
                
                # 保存新的标签配置
                with open(plugin_config_path, 'w', encoding='utf-8') as f:
                    json.dump(tag_config, f, ensure_ascii=False, indent=4)
            
            # 保存主配置
            with open("config.json", 'w', encoding='utf-8') as f:
                json.dump(new_config, f, ensure_ascii=False, indent=4)
            
            # 重新加载所有配置
            self.load_config()  # 加载主配置
            self.load_tag_config()  # 加载标签配置
            
            # 重新加载定时任务
            if hasattr(self, 'plugin') and "tag_plugin" in new_config:
                schedule.clear()
                for task in tag_config.get("scheduled_tasks", []):
                    if all(k in task for k in ["id", "tag", "time", "message"]):
                        self.plugin.schedule_task(
                            task["id"],
                            task["tag"],
                            task["time"],
                            task["message"]
                        )
            
            # 成功消息框
            messagebox.showinfo(
                "导入成功",
                f"配置已成功导入！\n原配置已备份至：\n{backup_file}"
            )
            
        except Exception as e:
            # 错误消息框
            messagebox.showerror(
                "导入失败", 
                f"导入配置时出错：\n{str(e)}"
            )
            logger.error(f"[ConfigGUI] 导入配置失败: {e}")

    def validate_config(self, config):
        """验证配置文件格式"""
        try:
            required_fields = [
                "nick_name_white_list",
                "nick_name_black_list",
                "random_reply_delay_min",
                "random_reply_delay_max"
            ]
            
            # 检查需字段是否存在
            for field in required_fields:
                if field not in config:
                    config[field] = self.get_default_value(field)
            
            # 验证数值类型字段
            numeric_fields = {
                "random_reply_delay_min": 2,
                "random_reply_delay_max": 4
            }
            
            for field, default in numeric_fields.items():
                try:
                    if field in config:
                        config[field] = float(config[field]) if field == "temperature" else int(config[field])
                except (ValueError, TypeError):
                    config[field] = default
            
            # 验证布尔类型字段
            bool_fields = [
                "hot_reload", "speech_recognition", "group_speech_recognition",
                "voice_reply_voice", "always_reply_voice", "use_linkai",
                "group_at_off", "trigger_by_self"
            ]
            
            for field in bool_fields:
                if field in config:
                    config[field] = bool(config[field])
            
            return config
        except Exception as e:
            raise ValueError(f"配置验证失败: {str(e)}")

    def get_default_value(self, field):
        """获取配置项的默认值"""
        defaults = {
            "nick_name_white_list": [],
            "nick_name_black_list": [],
            "random_reply_delay_min": 2,
            "random_reply_delay_max": 4
        }
        return defaults.get(field, "")

    def get_list_from_text(self, text_widget):
        """安全地获取文本框内容并转换为列表"""
        try:
            content = text_widget.get('1.0', tk.END).strip()
            return [item.strip() for item in content.split('\n') if item.strip()]
        except Exception:
            return []

    def set_text_content(self, text_widget, content):
        """安全地设置文本框内容"""
        try:
            text_widget.delete('1.0', tk.END)
            if isinstance(content, list):
                text_widget.insert('1.0', '\n'.join(content))
            else:
                text_widget.insert('1.0', str(content))
        except Exception:
            text_widget.delete('1.0', tk.END)

    def get_current_config(self):
        """获取当前配置"""
        try:
            # 首先读取现有配置文件，如果存在的话
            current_config = {}
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    current_config = json.load(f)

            # 更新配置，而不是完全替换
            config_updates = {
                # 名单配置
                "nick_name_white_list": self.get_list_from_text(self.nick_name_white_list),
                "nick_name_black_list": self.get_list_from_text(self.nick_name_black_list),
                
                # 延时配置
                "random_reply_delay_min": safe_int(self.random_reply_delay_min_var.get(), 2),
                "random_reply_delay_max": safe_int(self.random_reply_delay_max_var.get(), 4),
                
                # 保留其他现有配置
                "hot_reload": current_config.get("hot_reload", True),
                "channel_type": current_config.get("channel_type", "wx"),
                "model": current_config.get("model", "coze"),
                "coze_api_base": current_config.get("coze_api_base", ""),
                "coze_api_key": current_config.get("coze_api_key", ""),
                "coze_bot_id": current_config.get("coze_bot_id", ""),
                "text_to_image": current_config.get("text_to_image", "dall-e-3"),
                "voice_to_text": current_config.get("voice_to_text", "xunfei"),
                "text_to_voice": current_config.get("text_to_voice", "xunfei"),
                "proxy": current_config.get("proxy", ""),
                "single_chat_prefix": current_config.get("single_chat_prefix", [""]),
                "single_chat_reply_prefix": current_config.get("single_chat_reply_prefix", ""),
                "group_chat_keyword": current_config.get("group_chat_keyword", []),
                "group_chat_prefix": current_config.get("group_chat_prefix", [""]),
                "group_chat_reply_prefix": current_config.get("group_chat_reply_prefix", ""),
                "group_chat_reply_suffix": current_config.get("group_chat_reply_suffix", ""),
                "group_at_off": current_config.get("group_at_off", True),
                "group_name_white_list": current_config.get("group_name_white_list", []),
                "group_name_keyword_white_list": current_config.get("group_name_keyword_white_list", []),
                "group_chat_in_one_session": current_config.get("group_chat_in_one_session", []),
                "concurrency_in_session": current_config.get("concurrency_in_session", 1),
                "group_welcome_msg": current_config.get("group_welcome_msg", ""),
                "speech_recognition": current_config.get("speech_recognition", True),
                "group_speech_recognition": current_config.get("group_speech_recognition", True),
                "voice_reply_voice": current_config.get("voice_reply_voice", False),
                "always_reply_voice": current_config.get("always_reply_voice", False),
                "conversation_max_tokens": current_config.get("conversation_max_tokens", 2000),
                "expires_in_seconds": current_config.get("expires_in_seconds", 3600),
                "character_desc": current_config.get("character_desc", ""),
                "temperature": current_config.get("temperature", 0.5),
                "subscribe_msg": current_config.get("subscribe_msg", ""),
                "debug": current_config.get("debug", False)
            }

            # 将更新合并到现有配置中
            current_config.update(config_updates)
            return current_config
            
        except Exception as e:
            messagebox.showerror("错误", f"获取配置时出错：\n{str(e)}")
            return None

    def get_auto_reply_config(self):
        """获取自动回复配置"""
        auto_reply = {}
        for row in self.auto_reply_rows:
            tag = row["tag"].get().strip()
            reply = row["reply"].get().strip()
            if tag and reply:
                auto_reply[tag] = reply
        return auto_reply

    def get_scheduled_tasks_config(self):
        """获取定时任务配置"""
        tasks = []
        for task in self.scheduled_tasks:
            tasks.append({
                "id": task["id"],
                "tag": task["tag_var"].get().strip(),  # 使用当前输入框的值
                "time": task["time_var"].get().strip(),
                "message": task["message_var"].get().strip()
            })
        return tasks

    def add_auto_reply_row(self, tag="", reply=""):
        """添加一行自动回复配置"""
        row = len(self.auto_reply_rows) + 1
        
        # 创建行容器
        row_frame = ttk.Frame(self.auto_reply_table)
        row_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=2)
        
        # 标签名称输入
        tag_var = tk.StringVar(value=tag)
        tag_entry = ttk.Entry(row_frame, textvariable=tag_var, width=20)
        tag_entry.grid(row=0, column=0, padx=5)
        
        # 回复内容输入
        reply_var = tk.StringVar(value=reply)
        reply_entry = ttk.Entry(row_frame, textvariable=reply_var, width=60)
        reply_entry.grid(row=0, column=1, padx=5)
        
        # 删除按钮
        del_btn = ttk.Button(
            row_frame,
            text="删除",
            style="danger.TButton",
            command=lambda: self.delete_auto_reply_row(row_frame)
        )
        del_btn.grid(row=0, column=2, padx=5)
        
        # 保存行信息
        self.auto_reply_rows.append({
            "frame": row_frame,
            "tag": tag_var,
            "reply": reply_var
        })

    def delete_auto_reply_row(self, row_frame):
        """删除一行自动回复配置"""
        # 从列表中移除
        self.auto_reply_rows = [
            row for row in self.auto_reply_rows 
            if row["frame"] != row_frame
        ]
        # 从界面中移除
        row_frame.destroy()

    def add_scheduled_task(self):
        """添加定时任务"""
        try:
            tag = self.task_tag_var.get().strip()
            time = self.task_time_var.get().strip()
            message = self.task_message_var.get().strip()
            
            # 验证输入
            if not all([tag, time, message]):
                messagebox.showerror("错误", "请填写完整的任务信息")
                return
            
            # 验证时间格式
            try:
                datetime.strptime(time, "%H:%M")
            except ValueError:
                messagebox.showerror("错误", "时间格式不正确，请使用HH:MM格式")
                return
            
            # 生成任务ID
            task_id = datetime.now().strftime("%Y%m%d%H%M%S")
            
            # 添加到任务列表
            self.add_task_row(task_id, tag, time, message)
            
            # 清空输入
            self.task_tag_var.set("")
            self.task_time_var.set("")
            self.task_message_var.set("")
            
        except Exception as e:
            messagebox.showerror("错误", f"添加任务失败：{str(e)}")

    def add_task_row(self, task_id, tag, time, message):
        """添加一行定时任务"""
        try:
            row = len(self.scheduled_tasks) + 1
            
            # 创建行容器
            row_frame = ttk.Frame(self.scheduled_tasks_table)
            row_frame.grid(row=row, column=0, columnspan=5, sticky="ew", pady=2)
            
            # 显示简化的任务ID（不可编辑）
            display_id = str(row).zfill(2)  # 将行号转换为两位数字，如 "01", "02"
            id_label = ttk.Label(row_frame, text=display_id, width=10)
            id_label.grid(row=0, column=0, padx=5)
            
            # 添加完整ID的提示框
            ToolTip(id_label, text=f"完整ID: {task_id}")
            
            # 标签选择（可编辑）
            tag_var = tk.StringVar(value=tag)
            tag_combo = ttk.Combobox(row_frame, textvariable=tag_var, width=15)
            if self.task_tag_combo and self.task_tag_combo["values"]:
                tag_combo["values"] = self.task_tag_combo["values"]
            tag_combo.grid(row=0, column=1, padx=5)
            
            # 时间输入（可编辑）
            time_var = tk.StringVar(value=time)
            time_entry = ttk.Entry(row_frame, textvariable=time_var, width=10)
            time_entry.grid(row=0, column=2, padx=5)
            
            # 消息内容（可编辑）
            message_var = tk.StringVar(value=message)
            message_entry = ttk.Entry(row_frame, textvariable=message_var, width=40)
            message_entry.grid(row=0, column=3, padx=5)
            
            # 操作按钮区域
            btn_frame = ttk.Frame(row_frame)
            btn_frame.grid(row=0, column=4, padx=5)
            
            # 保存按钮
            save_btn = ttk.Button(
                btn_frame,
                text="保存",
                style="success.TButton",
                command=lambda: self.save_task_row(task_id, tag_var, time_var, message_var)
            )
            save_btn.pack(side=tk.LEFT, padx=(0, 2))
            
            # 删除按钮
            del_btn = ttk.Button(
                btn_frame,
                text="删除",
                style="danger.TButton",
                command=lambda: self.delete_scheduled_task(task_id, row_frame)
            )
            del_btn.pack(side=tk.LEFT)
            
            # 保存任务信息
            self.scheduled_tasks.append({
                "id": task_id,
                "display_id": display_id,
                "frame": row_frame,
                "tag_var": tag_var,
                "time_var": time_var,
                "message_var": message_var,
                "tag": tag,
                "time": time,
                "message": message
            })
            
        except Exception as e:
            logger.error(f"[ConfigGUI] 添加任务行失败: {e}")
            messagebox.showerror("错误", f"添加任务行失败: {str(e)}")

    def save_task_row(self, task_id, tag_var, time_var, message_var):
        """保存定时任务的修改"""
        try:
            # 获取新的值
            new_tag = tag_var.get().strip()
            new_time = time_var.get().strip()
            new_message = message_var.get().strip()
            
            # 验证输入
            if not all([new_tag, new_time, new_message]):
                messagebox.showerror("错误", "请填写完整的任务信息")
                return
            
            # 验证时间格式
            try:
                datetime.strptime(new_time, "%H:%M")
            except ValueError:
                messagebox.showerror("错误", "时间格式不正确，请使用HH:MM格式")
                return
            
            # 更新任务信息
            task_updated = False
            for task in self.scheduled_tasks:
                if task["id"] == task_id:
                    # 先清除旧的定时任务
                    schedule.clear(tag=task_id)
                    
                    # 更新任务信息
                    task["tag"] = new_tag
                    task["time"] = new_time
                    task["message"] = new_message
                    task["tag_var"].set(new_tag)
                    task["time_var"].set(new_time)
                    task["message_var"].set(new_message)
                    
                    # 重新设置定时任务
                    if hasattr(self, 'plugin'):
                        self.plugin.schedule_task(task_id, new_tag, new_time, new_message)
                    task_updated = True
                    break
            
            if task_updated:
                messagebox.showinfo("成功", "任务已更新")
            else:
                messagebox.showerror("错误", "未找到要更新的任务")
            
        except Exception as e:
            error_msg = f"保存任务失败：{str(e)}"
            logger.error(f"[ConfigGUI] {error_msg}")
            messagebox.showerror("错误", error_msg)

    def delete_scheduled_task(self, task_id, row_frame):
        """删除定时任务"""
        # 从列表中移除
        self.scheduled_tasks = [
            task for task in self.scheduled_tasks 
            if task["id"] != task_id
        ]
        # 从界面中移除
        row_frame.destroy()

    def send_broadcast_message(self):
        """发送群发消息"""
        try:
            # 获取选中的标签和消息内容
            tag = self.broadcast_tag_var.get()
            message = self.broadcast_message_var.get().strip()
            
            # 验证输入
            if not tag:
                messagebox.showerror("错误", "请选择要发送的标签")
                return
            if not message:
                messagebox.showerror("错误", "请输入要发送的消息内容")
                return
            
            # 获取标签下的好友
            if tag not in self.tags_friends:
                messagebox.showerror("错误", f"标签 '{tag}' 不存在")
                return
            
            friends = self.tags_friends[tag]
            if not friends:
                messagebox.showerror("错误", f"标签 '{tag}' 下没有好友")
                return

            # 检查微信登录状态并重新初始化
            try:
                if not itchat.check_login():
                    itchat.auto_login(hotReload=True)
                    time.sleep(1)  # 等待登录完成
            except Exception as e:
                logger.error(f"[GUI] 微信登录失败: {e}")
                messagebox.showerror("错误", "微信登录失败，请重试")
                return
            
            success_count = 0
            fail_count = 0
            
            # 获取所有微信好友
            try:
                wx_friends = itchat.get_friends(update=True)
                friend_map = {}
                for friend in wx_friends:
                    if friend.get('NickName'):
                        print(f"mjh_test friend['NickName'] {friend['NickName']}; friends {friends}; friend {friend}")
                        if friend['NickName'] not in friends:
                            continue# 确保昵称存在
                        friend_map[friend['NickName']] = friend
            except Exception as e:
                error_trace = traceback.format_exc()  # 获取完整的堆栈跟踪
                logger.error(f"[GUI] 获取好友列表失败: {e}\n{error_trace}")
                messagebox.showerror("错误", "获取好友列表失败")
                return
            
            # 遍历发送消息
            print(f"mjh_test friends {friends}; friend_map {friend_map}")
            for friend_name in friends:
                try:
                    if friend_name in friend_map:
                        friend = friend_map[friend_name]
                        user_id = friend['UserName']
                        # 添加随机延时
                        time.sleep(random.uniform(1, 2))
                        
                        # 使用 send 方法替代 send_msg
                        ral = itchat.send(msg=message, toUserName=user_id)
                        print(f"mjh_test user_id {user_id}; message {message} friend_name{friend_name  }")

                        success_count += 1
                        logger.info(f"[GUI] 已向好友 {friend_name} 发送消息; {ral}")
                    else:
                        fail_count += 1
                        logger.warning(f"[GUI] 未找到好友: {friend_name}")
                except Exception as e:
                    fail_count += 1
                    logger.error(f"[GUI] 向好友 {friend_name} 发送消息失败: {e}")
                    continue  # 继续发送其他消息
            
            # 清空消息输入
            self.broadcast_message_var.set("")
            
            # 显示结果
            result_message = f"群发完成\n成功: {success_count}\n失败: {fail_count}"
            if fail_count > 0:
                result_message += "\n\n部分消息发送失败，请检查好友昵称是否正确"
            messagebox.showinfo("发送结果", result_message)
            
        except Exception as e:
            error_msg = f"发送消息失败：{str(e)}"
            logger.error(f"[GUI] {error_msg}")
            messagebox.showerror("错误", error_msg)

    def load_tag_config(self):
        """加载标签管理插件配置"""
        try:
            plugin_config_path = os.path.join("plugins", "tag_manager", "config.json")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, 'r', encoding='utf-8') as f:
                    tag_config = json.load(f)
                    
                    # 加载基本设置
                    self.enable_tag_var.set(tag_config.get("enable", False))
                    self.tag_prefix_var.set(tag_config.get("tag_prefix", "$"))
                    self.allow_all_add_tag_var.set(tag_config.get("allow_all_add_tag", False))
                    self.allow_all_remove_tag_var.set(tag_config.get("allow_all_remove_tag", False))
                    self.allow_all_view_tag_var.set(tag_config.get("allow_all_view_tag", True))
                    self.allow_all_list_tag_var.set(tag_config.get("allow_all_list_tag", True))
                    
                    # 加载管理员和标签列表
                    if self.admin_users and "admin_users" in tag_config:
                        self.admin_users.delete("1.0", tk.END)
                        self.admin_users.insert("1.0", "\n".join(tag_config["admin_users"]))
                    
                    if self.enabled_tags and "enabled_tags" in tag_config:
                        self.enabled_tags.delete("1.0", tk.END)
                        self.enabled_tags.insert("1.0", "\n".join(tag_config["enabled_tags"]))
                    
                    # 加载标签好友配置
                    self.tags_friends = tag_config.get("tags_friends", {})
                    self.refresh_aliases_table()
                    
                    # 加载自动回复配置
                    self.auto_reply_rows = []
                    for tag, message in tag_config.get("auto_reply", {}).items():
                        self.add_auto_reply_row(tag, message)
                    
                    # 加载定时任务配置
                    self.scheduled_tasks = []
                    for task in tag_config.get("scheduled_tasks", []):
                        if all(k in task for k in ["id", "tag", "time", "message"]):
                            self.add_task_row(
                                task["id"],
                                task["tag"],
                                task["time"],
                                task["message"]
                            )
                
            # 更新群发消息的标签下拉列表
            if hasattr(self, 'broadcast_tag_combo'):
                enabled_tags = self.get_list_from_text(self.enabled_tags)
                self.broadcast_tag_combo['values'] = enabled_tags
                if enabled_tags:
                    self.broadcast_tag_combo.set(enabled_tags[0])
                
        except Exception as e:
            messagebox.showerror("错误", f"加载标签插件配置时出错：\n{str(e)}")
            logger.error(f"[TagManager] 加载配置失败: {e}")

    def save_tag_config(self):
        """保存标签管理插件配置"""
        try:
            plugin_dir = os.path.join("plugins", "tag_manager")
            os.makedirs(plugin_dir, exist_ok=True)
            plugin_config_path = os.path.join(plugin_dir, "config.json")

            # 准备新的配置
            tag_config = {
                "enable": self.enable_tag_var.get(),
                "tag_prefix": self.tag_prefix_var.get(),
                "allow_all_add_tag": self.allow_all_add_tag_var.get(),
                "allow_all_remove_tag": self.allow_all_remove_tag_var.get(),
                "allow_all_view_tag": self.allow_all_view_tag_var.get(),
                "allow_all_list_tag": self.allow_all_list_tag_var.get(),
                "admin_users": self.get_list_from_text(self.admin_users),
                "enabled_tags": self.get_list_from_text(self.enabled_tags),
                "tags_friends": self.tags_friends,  # 确保使用正确的键名
                "auto_reply": {},  # 初始化自动回复配置
                "scheduled_tasks": []  # 初始化定时任务配置
            }

            # 添加自动回复配置
            for row in self.auto_reply_rows:
                if isinstance(row, dict) and "tag" in row and "message" in row:
                    tag_config["auto_reply"][row["tag"]] = row["message"]

            # 添加定时任务配置
            for task in self.scheduled_tasks:
                if isinstance(task, dict) and all(k in task for k in ["id", "tag", "time", "message"]):
                    task_data = {
                        "id": task["id"],
                        "tag": task["tag"],
                        "time": task["time"],
                        "message": task["message"]
                    }
                    tag_config["scheduled_tasks"].append(task_data)

            # 保存配置
            with open(plugin_config_path, 'w', encoding='utf-8') as f:
                json.dump(tag_config, f, ensure_ascii=False, indent=4)
            
            # 重新加载定时任务
            schedule.clear()  # 清除所有现有任务
            for task in tag_config["scheduled_tasks"]:
                self.plugin.schedule_task(
                    task["id"],
                    task["tag"],
                    task["time"],
                    task["message"]
                )
            
            return True
            
        except Exception as e:
            messagebox.showerror("错误", f"保存标签插件配置时出错：\n{str(e)}")
            logger.error(f"[TagManager] 保存配置失败: {e}")
            return False

    def load_example_config(self):
        """加载示例配置"""
        try:
            if messagebox.askyesno("确认", "加载示例配置将覆盖当前配置，是否继续？"):
                example_config = {
                    "nick_name_white_list": ["张三", "李四", "王五"],
                    "nick_name_black_list": ["广告机器人", "推销员"],
                    "random_reply_delay_min": 2,
                    "random_reply_delay_max": 4,
                    "tag_plugin": {
                        "enable": True,
                        "tag_prefix": "$",
                        "allow_all_add_tag": False,
                        "allow_all_remove_tag": False,
                        "allow_all_view_tag": True,
                        "allow_all_list_tag": True,
                        "enabled_tags": ["朋友", "同学", "同事", "家人"],
                        "admin_users": ["管理员1", "管理员2"],
                        "tags_friends": {
                            "朋友": ["张三", "李四", "王五"],
                            "同学": ["小明", "小红", "小李"],
                            "家人": ["爸爸", "妈妈", "妹妹"]
                        },
                        "auto_reply": {
                            "朋友": "你好，我的朋友！",
                            "同学": "好久不见，同学！",
                            "家人": "亲爱的家人，想你了！"
                        },
                        "scheduled_tasks": [
                            {
                                "id": "example_task_1",
                                "tag": "朋友",
                                "time": "09:00",
                                "message": "早上好，朋友们！"
                            },
                            {
                                "id": "example_task_2",
                                "tag": "同学",
                                "time": "12:00",
                                "message": "中午好，同学们！"
                            }
                        ]
                    }
                }
                
                # 保存示例配置
                with open('config.json', 'w', encoding='utf-8') as f:
                    json.dump(example_config, f, ensure_ascii=False, indent=4)
                
                # 重新加载配置
                self.load_config()
                
                messagebox.showinfo("成功", "示例配置已加载")
                
        except Exception as e:
            messagebox.showerror("错误", f"加载示例配置时出错：\n{str(e)}")

    def add_tag_alias(self):
        """添加或更新标签好友"""
        tag = self.alias_tag_var.get()
        friends = [f.strip() for f in self.alias_names_var.get().split(',') if f.strip()]
        
        if not tag or not friends:
            messagebox.showwarning("警告", "请输入标签名称和至少一个好友")
            return
        
        # 如果标签已存在，询问是否更新
        if tag in self.tags_friends:
            if messagebox.askyesno("确认", f"标签'{tag}'已存在好友列表，是否更新？\n" +
                                 f"当前好友：{', '.join(self.tags_friends[tag])}\n" +
                                 f"新好友：{', '.join(friends)}"):
                self.tags_friends[tag] = friends  # 完全替换现有好友列表
            else:
                return
        else:
            self.tags_friends[tag] = friends  # 新建标签好友列表
        
        # 清空输入
        self.alias_names_var.set("")
        
        # 刷新显示
        self.refresh_aliases_table()

    def refresh_aliases_table(self):
        """刷新好友列表表格"""
        # 清除现有行
        for widget in self.aliases_table.winfo_children():
            if widget.grid_info()["row"] > 0:  # 保留表头
                widget.destroy()
        
        # 重新添加所有好友列表
        row = 1
        for tag, friends in self.tags_friends.items():
            # 创建行框架
            row_frame = ttk.Frame(self.aliases_table)
            row_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=2)
            
            # 标签名称
            tag_var = tk.StringVar(value=tag)
            tag_combo = ttk.Combobox(row_frame, textvariable=tag_var, width=15)
            if hasattr(self, 'enabled_tags') and self.enabled_tags:
                enabled_tags = self.get_list_from_text(self.enabled_tags)
                tag_combo["values"] = enabled_tags
            tag_combo.grid(row=0, column=0, padx=5)
            
            # 好友列表输入框
            friends_var = tk.StringVar(value=", ".join(friends))
            friends_entry = ttk.Entry(row_frame, textvariable=friends_var, width=40)
            friends_entry.grid(row=0, column=1, padx=5)
            
            # 按钮框架
            btn_frame = ttk.Frame(row_frame)
            btn_frame.grid(row=0, column=2, padx=5)
            
            # 保存按钮
            save_btn = ttk.Button(
                btn_frame,
                text="保存",
                style="success.TButton",
                command=lambda t=tag, tv=tag_var, fv=friends_var: self.save_tag_friends(t, tv, fv)
            )
            save_btn.pack(side=tk.LEFT, padx=(0, 2))
            
            # 删除按钮
            delete_btn = ttk.Button(
                btn_frame,
                text="删除",
                style="danger.TButton",
                command=lambda t=tag: self.delete_tag_friends(t)
            )
            delete_btn.pack(side=tk.LEFT)
            
            row += 1

    def save_tag_friends(self, old_tag, tag_var, friends_var):
        """保存标签好友的修改"""
        try:
            # 获取新的值
            new_tag = tag_var.get().strip()
            friends = [f.strip() for f in friends_var.get().split(',') if f.strip()]
            
            # 验证输入
            if not new_tag or not friends:
                messagebox.showerror("错误", "请填写完整的标签和好友信息")
                return
            
            # 如果标签名变更了
            if old_tag != new_tag:
                # 检查新标签名是否已存在
                if new_tag in self.tags_friends and new_tag != old_tag:
                    if not messagebox.askyesno("确认", f"标签'{new_tag}'已存在，是否合并好友列表？"):
                        return
                    # 合并好友列表
                    existing_friends = set(self.tags_friends[new_tag])
                    existing_friends.update(friends)
                    friends = list(existing_friends)
                
                # 删除旧标签
                if old_tag in self.tags_friends:
                    del self.tags_friends[old_tag]
            
            # 更新好友列表
            self.tags_friends[new_tag] = friends
            
            # 刷新显示
            self.refresh_aliases_table()
            messagebox.showinfo("成功", "标签好友已更新")
            
        except Exception as e:
            messagebox.showerror("错误", f"保存标签好友失败：{str(e)}")

    def delete_tag_friends(self, tag):
        """删除标签的所有好友"""
        if tag in self.tags_friends:
            del self.tags_friends[tag]
            self.refresh_aliases_table()

    # 保持原有的ModernConfigGUI类代码不变
    # ... 

def get_linux_distro():
    """获取 Linux 发行版信息"""
    try:
        with open("/etc/os-release") as f:
            lines = f.readlines()
            info = {}
            for line in lines:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    info[key] = value.strip('"')
            
            # 获取发行版 ID 和相似发行版
            distro_id = info.get("ID", "").lower()
            distro_like = info.get("ID_LIKE", "").lower()
            
            # 对于 OpenCloudOS，使用 CentOS 的配置方式
            if "opencloudos" in (distro_id, distro_like):
                logger.info("[ConfigGUI] 检测到 OpenCloudOS 系统，使用 CentOS 配置")
                return "centos"
            
            return distro_id
    except Exception as e:
        logger.error(f"[ConfigGUI] 获取系统信息失败: {str(e)}")
        return "unknown"

class ConfigGUIPlugin(Plugin):
    def __init__(self):
        super().__init__()
        self.xvfb_process = None
        self.is_windows = platform.system().lower() == 'windows'
        self.linux_distro = None if self.is_windows else get_linux_distro()
        logger.info(f"[ConfigGUI] 系统类型: {'Windows' if self.is_windows else self.linux_distro}")
        
        # ... 其他初始化代码 ...

# 在文件开头添加 ModernConfigGUI 类的定义
class ModernConfigGUI:
    def __init__(self, root, plugin):
        self.root = root
        self.plugin = plugin
        self.setup_ui()
        
    def setup_ui(self):
        # 创建主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 创建标题标签
        title_label = ttk.Label(
            main_frame,
            text="ChatGPT-WeChat 配置工具",
            font=("Helvetica", 16, "bold")
        )
        title_label.pack(pady=(0, 20))
        
        # 创建选项卡控件
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # 基本设置选项卡
        basic_frame = ttk.Frame(notebook)
        notebook.add(basic_frame, text="基本设置")
        
        # 标签管理选项卡
        tag_frame = ttk.Frame(notebook)
        notebook.add(tag_frame, text="标签管理")
        
        # 定时任务选项卡
        schedule_frame = ttk.Frame(notebook)
        notebook.add(schedule_frame, text="定时任务")
        
        # 添加基本设置内容
        self.setup_basic_settings(basic_frame)
        
        # 添加标签管理内容
        self.setup_tag_management(tag_frame)
        
        # 添加定时任务内容
        self.setup_schedule_tasks(schedule_frame)
        
    def setup_basic_settings(self, parent):
        # 创建基本设置界面
        settings_frame = ttk.LabelFrame(parent, text="基本设置", padding=10)
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 添加设置项
        ttk.Label(settings_frame, text="示例设置项:").pack(anchor=tk.W)
        ttk.Entry(settings_frame).pack(fill=tk.X, pady=5)
        
    def setup_tag_management(self, parent):
        # 创建标签管理界面
        tag_frame = ttk.LabelFrame(parent, text="标签管理", padding=10)
        tag_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 添加标签管理功能
        ttk.Label(tag_frame, text="标签列表:").pack(anchor=tk.W)
        ttk.Entry(tag_frame).pack(fill=tk.X, pady=5)
        
    def setup_schedule_tasks(self, parent):
        # 创建定时任务界面
        schedule_frame = ttk.LabelFrame(parent, text="定时任务", padding=10)
        schedule_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 添加定时任务功能
        ttk.Label(schedule_frame, text="任务列表:").pack(anchor=tk.W)
        ttk.Entry(schedule_frame).pack(fill=tk.X, pady=5)
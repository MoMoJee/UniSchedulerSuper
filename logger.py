import logging
import logging.handlers
from concurrent_log_handler import ConcurrentRotatingFileHandler  # 新增
import os
import sys
import traceback
from pathlib import Path
import threading
import time
import psutil


class ProjectLogger:
    """项目日志器 - 支持多程序共享，按路径区分来源"""

    _instance = None
    _initialized = False
    _monitor_thread = None
    _monitor_stop_event = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, **kwargs):
        if not self._initialized:
            if kwargs.get('if_start_monitor_thread'):
                if isinstance(kwargs.get('if_start_monitor_thread'), bool):
                    self.if_start_monitor_thread = kwargs['if_start_monitor_thread']
            else:
                self.if_start_monitor_thread = False

            self._setup_logger()
            ProjectLogger._initialized = True

    def _setup_logger(self):
        """设置日志器配置"""
        # 获取项目根目录
        self.project_root = self._get_project_root()

        # 创建logs目录
        self.logs_dir = self.project_root / "logs"
        self.logs_dir.mkdir(exist_ok=True)

        # 设置日志文件路径
        self.log_file = self.logs_dir / "application.log"

        # 创建根日志器
        self.logger = logging.getLogger("ProjectLogger")
        self.logger.setLevel(logging.DEBUG)

        # 防止重复添加handler
        if not self.logger.handlers:
            self._add_handlers()

        # 设置日志格式
        self._setup_formatter()

        # 启动监控线程
        if self.if_start_monitor_thread:
            self._start_monitor_thread()

    @staticmethod
    def _get_project_root() -> Path:
        """获取项目根目录"""
        current_path = Path(os.getcwd())

        # 向上查找项目根目录的标志文件
        for path in [current_path] + list(current_path.parents):
            # 可以根据实际项目调整这些标志文件
            if any((path / marker).exists() for marker in
                   ['.git', 'requirements.txt', 'pyproject.toml', 'setup.py']):
                return path

        # 如果找不到标志文件，使用当前目录
        return current_path

    def _add_handlers(self):
        """添加日志处理器"""
        # 文件处理器 - 带日志截断功能
        file_handler = ConcurrentRotatingFileHandler(
            filename=str(self.log_file),
            maxBytes=5 * 512 * 1024,  #2.5MB
            backupCount=10,  # 保留10个备份文件
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        self.file_handler = file_handler
        self.console_handler = console_handler

    def _setup_formatter(self):
        """设置日志格式"""

        # 自定义formatter类来处理堆栈信息
        class StackFormatter(logging.Formatter):
            def format(self, record):
                formatted = super().format(record)
                # 使用 stack_info 而不是 sinfo（LogRecord 会自动将 sinfo 转换为 stack_info）
                if hasattr(record, 'stack_info') and record.stack_info:
                    formatted += f"\n堆栈信息:\n{record.stack_info}"
                return formatted

        # 文件日志格式 - 包含完整信息，使用自定义formatter
        file_formatter = StackFormatter(
            fmt='%(asctime)s | %(levelname)-8s | %(source_path)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 控制台日志格式 - 简化版本
        console_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(source_path)s | %(message)s',
            datefmt='%H:%M:%S'
        )

        self.file_handler.setFormatter(file_formatter)
        self.console_handler.setFormatter(console_formatter)

    def _get_caller_path(self) -> str:
        """获取调用者的相对路径"""
        frame = sys._getframe(3)  # 跳过当前方法和日志方法
        caller_file = frame.f_code.co_filename

        try:
            # 获取相对于项目根目录的路径
            relative_path = Path(caller_file).relative_to(self.project_root)
            return str(relative_path)
        except ValueError:
            # 如果无法获取相对路径，返回文件名
            return Path(caller_file).name

    def _log(self, level: int, message: str, *args, **kwargs):
        """内部日志记录方法"""
        source_path = self._get_caller_path()

        # 获取堆栈信息（如果需要）
        stack_info = None
        if kwargs.get('stack_info'):
            import traceback
            stack_info = ''.join(traceback.format_stack()[:-2])  # 排除当前方法和调用方法

        # 创建LogRecord并添加自定义字段
        record = self.logger.makeRecord(
            name=self.logger.name,
            level=level,
            fn="",  # 文件名，稍后会设置
            lno=0,  # 行号，稍后会设置
            msg=message,
            args=args,
            exc_info=kwargs.get('exc_info'),
            func=None,  # 函数名，稍后会设置
            extra={'source_path': source_path},
            sinfo=stack_info  # 使用 sinfo 而不是 stack_info
        )

        # 获取调用者信息
        frame = sys._getframe(2)
        record.filename = frame.f_code.co_filename  # 修正文件名
        record.lineno = frame.f_lineno
        record.funcName = frame.f_code.co_name
        record.pathname = frame.f_code.co_filename

        self.logger.handle(record)

    def _get_caller_stack(self, skip_frames=3):
        """获取调用者的堆栈信息"""
        return ''.join(traceback.format_stack()[:-skip_frames])

    def debug_with_stack(self, message: str, *args, **kwargs):
        """调试日志（包含完整调用栈）"""
        kwargs['stack_info'] = True
        self._log(logging.DEBUG, message, *args, **kwargs)

    def info_with_stack(self, message: str, *args, **kwargs):
        """信息日志（包含完整调用栈）"""
        kwargs['stack_info'] = True
        self._log(logging.INFO, message, *args, **kwargs)

    def warning_with_stack(self, message: str, *args, **kwargs):
        """警告日志（包含完整调用栈）"""
        kwargs['stack_info'] = True
        self._log(logging.WARNING, message, *args, **kwargs)

    def error_with_stack(self, message: str, *args, **kwargs):
        """错误日志（包含完整调用栈）"""
        kwargs['stack_info'] = True
        self._log(logging.ERROR, message, *args, **kwargs)

    def critical_with_stack(self, message: str, *args, **kwargs):
        """严重错误日志（包含完整调用栈）"""
        kwargs['stack_info'] = True
        self._log(logging.CRITICAL, message, *args, **kwargs)

    def log_call_chain(self, level: int, message: str, depth: int = 5):
        """记录调用链信息（指定深度）"""
        stack = traceback.extract_stack()[:-1]  # 排除当前方法
        call_chain = []

        # 获取指定深度的调用链
        for frame in stack[-depth:]:
            relative_path = self._get_relative_path(frame.filename)
            call_chain.append(f"{relative_path}:{frame.lineno} in {frame.name}()")

        chain_info = " -> ".join(call_chain)
        full_message = f"{message}\n调用链: {chain_info}"
        self._log(level, full_message)

    def _get_relative_path(self, file_path: str) -> str:
        """获取相对路径"""
        try:
            return str(Path(file_path).relative_to(self.project_root))
        except ValueError:
            return Path(file_path).name

    def debug(self, message: str, *args, **kwargs):
        """调试日志"""
        self._log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        """信息日志"""
        self._log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        """警告日志"""
        self._log(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        """错误日志"""
        self._log(logging.ERROR, message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs):
        """严重错误日志"""
        self._log(logging.CRITICAL, message, *args, **kwargs)

    def exception(self, message: str, *args, **kwargs):
        """异常日志（自动包含异常堆栈）"""
        kwargs['exc_info'] = True
        self._log(logging.ERROR, message, *args, **kwargs)

    def _start_monitor_thread(self):
        """启动监控线程"""
        if ProjectLogger._monitor_thread is None or not ProjectLogger._monitor_thread.is_alive():
            ProjectLogger._monitor_stop_event = threading.Event()
            ProjectLogger._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="LoggerMonitorThread"
            )
            ProjectLogger._monitor_thread.start()

    def _stop_monitor_thread(self):
        """停止监控线程"""
        if ProjectLogger._monitor_stop_event:
            ProjectLogger._monitor_stop_event.set()
        if ProjectLogger._monitor_thread:
            ProjectLogger._monitor_thread.join(timeout=1)

    def _monitor_loop(self):
        """监控循环 - 每5分钟检测一次"""
        while not ProjectLogger._monitor_stop_event.is_set():
            try:
                self._detect_caller_processes()
            except Exception as e:
                # 使用底层logger避免递归
                self.logger.debug(f"监控线程异常: {e}", extra={'source_path': 'logger.py'})

            # 等待5分钟或直到停止事件触发
            ProjectLogger._monitor_stop_event.wait(timeout=300)  # 300秒 = 5分钟

    def _detect_caller_processes(self):
        """检测正在调用日志器的进程"""
        current_pid = os.getpid()
        caller_processes = []

        try:
            current_process = psutil.Process(current_pid)
            log_file_path = str(self.log_file)

            # 收集当前进程信息
            process_info = {
                'pid': current_pid,
                'name': current_process.name(),
                'cmdline': ' '.join(current_process.cmdline()),
                'cwd': current_process.cwd(),
                'create_time': time.strftime('%Y-%m-%d %H:%M:%S', 
                                            time.localtime(current_process.create_time()))
            }
            caller_processes.append(process_info)

            # 检查是否有其他进程打开了日志文件
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
                try:
                    if proc.pid == current_pid:
                        continue

                    # 检查进程打开的文件
                    for file in proc.open_files():
                        if file.path == log_file_path:
                            proc_info = {
                                'pid': proc.pid,
                                'name': proc.info['name'],
                                'cmdline': ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else '',
                                'cwd': proc.info['cwd'] if proc.info['cwd'] else 'N/A',
                                'create_time': time.strftime('%Y-%m-%d %H:%M:%S',
                                                            time.localtime(proc.create_time()))
                            }
                            caller_processes.append(proc_info)
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            # 记录检测结果
            if caller_processes:
                report_lines = ["=== 日志器使用状态检测 ==="]
                report_lines.append(f"检测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                report_lines.append(f"发现 {len(caller_processes)} 个进程正在使用日志器:")

                for idx, proc in enumerate(caller_processes, 1):
                    report_lines.append(f"\n进程 #{idx}:")
                    report_lines.append(f"  PID: {proc['pid']}")
                    report_lines.append(f"  名称: {proc['name']}")
                    report_lines.append(f"  命令行: {proc['cmdline']}")
                    report_lines.append(f"  工作目录: {proc['cwd']}")
                    report_lines.append(f"  启动时间: {proc['create_time']}")

                report_lines.append("=" * 50)
                report = "\n".join(report_lines)

                # 直接使用底层logger记录,避免递归调用
                self.logger.debug(report, extra={'source_path': 'logger.py'})

        except Exception as e:
            self.logger.debug(f"检测进程时出错: {e}", extra={'source_path': 'logger.py'})

    def set_console_level(self, level: int):
        """设置控制台日志等级"""
        self.console_handler.setLevel(level)

    def set_file_level(self, level: int):
        """设置文件日志等级"""
        self.file_handler.setLevel(level)




# 创建全局日志器实例
logger = ProjectLogger()


# 便捷函数
def debug(message: str, *args, **kwargs):
    logger.debug(message, *args, **kwargs)


def info(message: str, *args, **kwargs):
    logger.info(message, *args, **kwargs)


def warning(message: str, *args, **kwargs):
    logger.warning(message, *args, **kwargs)


def error(message: str, *args, **kwargs):
    logger.error(message, *args, **kwargs)


def critical(message: str, *args, **kwargs):
    logger.critical(message, *args, **kwargs)


def exception(message: str, *args, **kwargs):
    logger.exception(message, *args, **kwargs)

# 便捷函数 - 带堆栈信息
def debug_with_stack(message: str, *args, **kwargs):
    logger.debug_with_stack(message, *args, **kwargs)

def info_with_stack(message: str, *args, **kwargs):
    logger.info_with_stack(message, *args, **kwargs)

def warning_with_stack(message: str, *args, **kwargs):
    logger.warning_with_stack(message, *args, **kwargs)

def error_with_stack(message: str, *args, **kwargs):
    logger.error_with_stack(message, *args, **kwargs)

def critical_with_stack(message: str, *args, **kwargs):
    logger.critical_with_stack(message, *args, **kwargs)

def log_call_chain(level: int, message: str, depth: int = 5):
    logger.log_call_chain(level, message, depth)



"""
BIND9 服务交互层
封装所有与 BIND9 named 进程的交互操作
使用命令白名单 + 超时控制 + 完整错误处理，禁止任意shell执行

权限说明:
- 直接运行named-checkconf/named-checkzone 通常不需要root
- systemctl/rndc 需要对应权限（建议通过sudoers配置无密码执行）
- named -v (版本查询) 不需要root
"""

import os
import subprocess
import json
import re
import logging
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger('dns.bind9_service')

# 命令白名单 - 仅允许执行以下命令（严禁shell注入）
ALLOWED_COMMANDS = {
    'systemctl', 'named-checkconf', 'named-checkzone',
    'rndc', 'named', 'cat', 'grep', 'head', 'tail', 'wc',
}

# 各命令默认超时(秒)
COMMAND_TIMEOUTS = {
    'systemctl': 15,
    'named-checkconf': 30,
    'named-checkzone': 30,
    'rndc': 20,
    'named': 10,
    'cat': 10,
    'grep': 10,
    'head': 5,
    'tail': 5,
    'wc': 5,
}


class Bind9ServiceError(Exception):
    """BIND9服务操作异常"""

    def __init__(self, message: str, command: str = '', output: str = ''):
        super().__init__(message)
        self.command = command
        self.output = output


class Bind9Service:
    """
    BIND9 DNS服务管理类
    封装状态查询、配置校验、服务控制等全部操作

    设计原则:
    - 所有命令经过白名单检查
    - 统一超时控制，防止单次调用阻塞
    - 结构化返回结果，便于上层消费
    - 详细日志记录，便于排查问题
    """

    def __init__(self, server_config=None):
        self.config_path = '/etc/named.conf'
        self.zone_dir = '/var/named'
        if server_config:
            self.config_path = getattr(server_config, 'named_conf_path', self.config_path)
            self.zone_dir = getattr(server_config, 'zone_dir', self.zone_dir)

    # ================================================================
    # 状态查询方法
    # ================================================================

    def get_service_status(self) -> Dict[str, Any]:
        """获取named服务状态信息

        Returns:
            dict: {
                'is_running': bool,
                'pid': int or None,
                'uptime': str,
                'bind_version': str,
                'listeners': list of {ip, port, protocol},
                'config_file': str,
                'zone_count': int,
                'stats': dict,
                'error': str or None,
            }
        """
        result = {
            'is_running': False,
            'pid': None,
            'uptime': '',
            'bind_version': '',
            'config_file': self.config_path,
            'zone_count': 0,
            'listeners': [],
            'error': None,
            'raw_output': '',
        }

        # 1) systemctl status named --no-pager
        try:
            output = self._run_command(['systemctl', 'status', 'named', '--no-pager'],
                                       timeout=COMMAND_TIMEOUTS.get('systemctl', 15))
            result['raw_output'] = output
            result['is_running'] = 'active (running)' in output

            # 解析PID
            pid_match = re.search(r'Main PID:\s*(\d+)', output)
            if pid_match:
                result['pid'] = int(pid_match.group(1))

            # 解析运行时间
            uptime_match = re.search(r'active.*since.*?(\d[\w\s]+?ago)', output, re.DOTALL)
            if uptime_match:
                result['uptime'] = uptime_match.group(1).strip()

            # 解析监听端口 (TCP)
            listener_matches = re.findall(r'(\S+):(\d+)\s+\(LISTEN\)', output) or []
            result['listeners'] = [
                {'ip': m[0], 'port': m[1], 'protocol': 'TCP'} for m in listener_matches
            ]

        except FileNotFoundError:
            result['error'] = 'systemctl 命令未找到，请确认系统支持systemd'
            logger.warning('get_service_status: systemctl not found')
        except Bind9ServiceError as e:
            result['error'] = str(e)
            logger.error(f'get_service_status error: {e}')
        except Exception as e:
            result['error'] = f'获取状态异常: {e}'
            logger.exception(f'get_service_status unexpected error: {e}')

        # 2) 获取BIND版本（独立调用，失败不影响整体状态）
        try:
            result['bind_version'] = self.get_bind_version() or ''
        except Exception:
            pass

        return result

    def get_bind_version(self) -> Optional[str]:
        """获取BIND9版本号 (通过 named -v)"""
        try:
            output = self._run_command(['named', '-v'],
                                       timeout=COMMAND_TIMEOUTS.get('named', 10))
            match = re.search(r'(\d+\.\d+(\.\d+)?)', output)
            return match.group(1) if match else None
        except FileNotFoundError:
            logger.warning('named command not found - BIND9 may not be installed')
            return None
        except Exception as e:
            logger.debug(f'get_bind_version failed: {e}')
            return None

    def rndc_status(self) -> Dict[str, Any]:
        """获取rndc status详细信息

        Returns:
            dict: {'success': bool, 'output': str, 'parsed': dict}
                   parsed包含: status, zone_count, debug_level, xfers_running,
                                soft_queries, boot_time, last_configured
        """
        result = {'success': False, 'output': '', 'parsed': {}}
        try:
            output = self._run_command(['rndc', 'status'],
                                       timeout=COMMAND_TIMEOUTS.get('rndc', 20))
            result['success'] = True
            result['output'] = output

            # 结构化解析 rndc status 输出
            parsed = {}

            # server is up and running / down
            if 'up and running' in output:
                parsed['status'] = 'running'
            elif 'is down' in output.lower() or 'not running' in output.lower():
                parsed['status'] = 'down'
            else:
                parsed['status'] = 'unknown'

            # number of zones: N
            z_match = re.search(r'number of zones:\s*(\d+)', output)
            if z_match:
                parsed['zone_count'] = int(z_match.group(1))

            # debug level: N
            dbg_match = re.search(r'debug level:\s*(\d+)', output)
            if dbg_match:
                parsed['debug_level'] = int(dbg_match.group(1))

            # xfers in progress: N
            xfer_match = re.search(r'xfers in progress:\s*(\d+)', output)
            if xfer_match:
                parsed['xfers_running'] = int(xfer_match.group(1))

            # soft queries in progress: N (或 "queries in progress")
            xferd_match = re.search(r'(?:soft )?queries in progress:\s*(\d+)', output)
            if xferd_match:
                parsed['soft_queries'] = int(xferd_match.group(1))

            # boot time: Wed Jan 1 00:00:00 2025
            boot_match = re.search(r'boot time:\s+(.+?)(?:\n|$)', output)
            if boot_match:
                parsed['boot_time'] = boot_match.group(1).strip()

            # last configured: Wed Jan 1 00:00:00 2025
            cfg_match = re.search(r'last configured:\s+(.+?)(?:\n|$)', output)
            if cfg_match:
                parsed['last_configured'] = cfg_match.group(1).strip()

            # servers: N failures: N (如有)
            srv_match = re.search(r'servers:\s*(\d+)\s+failures:\s*(\d+)', output)
            if srv_match:
                parsed['servers_total'] = int(srv_match.group(1))
                parsed['server_failures'] = int(srv_match.group(2))

            result['parsed'] = parsed
            logger.debug(f'rndc_status parsed: {parsed}')

        except subprocess.TimeoutExpired:
            result['output'] = 'rndc status 执行超时(20s)，DNS服务可能响应缓慢'
            logger.warning('rndc status timed out')
        except FileNotFoundError:
            result['output'] = 'rndc 命令未找到，请确认已安装BIND9工具包(bind9utils)'
            logger.warning('rndc command not found')
        except PermissionError:
            result['output'] = 'rndc 权限不足，请检查rndc.key文件权限或sudoers配置'
            logger.warning('rndc permission denied')
        except Bind9ServiceError as e:
            result['output'] = str(e)
            logger.error(f'rndc_status error: {e}')
        except Exception as e:
            result['output'] = f'rndc状态获取异常: {e}'
            logger.exception(f'rndc_status unexpected: {e}')

        return result

    # ================================================================
    # 配置校验方法
    # ================================================================

    def check_conf(self, config_content: str = None) -> Dict[str, Any]:
        """执行 named-checkconf 校验全局配置

        Args:
            config_content: 配置文件内容字符串，None则使用默认文件路径
                            注意：-z 选项需要从 stdin 读取，但 named-checkconf
                                  默认读取文件，这里我们传路径让checkconf直接读文件

        Returns:
            dict: {'passed': bool, 'output': str, 'error': str or None}
        """
        cmd = ['named-checkconf']
        # named-checkconf 不支持 -z 从stdin读，直接检查指定文件或默认文件
        cmd.append(self.config_path)

        result = {'passed': False, 'output': '', 'error': None}
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUTS.get('named-checkconf', 30),
            )
            result['passed'] = proc.returncode == 0
            result['output'] = (proc.stdout + proc.stderr).strip() or ('配置语法正确' if proc.returncode == 0 else '')
        except subprocess.TimeoutExpired:
            result['output'] = 'named-checkconf 执行超时(30s)'
            result['error'] = 'timeout'
            logger.error('check_conf timed out')
        except FileNotFoundError:
            result['output'] = 'named-checkconf 命令未找到，请安装bind9utils'
            result['error'] = 'not_found'
        except PermissionError:
            result['output'] = '权限不足，无法执行named-checkconf'
            result['error'] = 'permission'
        except Exception as e:
            result['output'] = f'checkconf 错误: {e}'
            result['error'] = str(e)
            logger.exception(f'check_conf error: {e}')
        return result

    def check_zone(self, zone_name: str, zone_file: str = None,
                   zone_content: str = None) -> Dict[str, Any]:
        """执行 named-checkzone 校验单个区域

        Args:
            zone_name: 区域名称（如 example.com）
            zone_file: 区域文件路径（优先使用）
            zone_content: 区域文件内容字符串（当zone_file为None时使用）

        Returns:
            dict: {'passed': bool, 'output': str, 'error': str or None}
        """
        if not zone_name:
            return {'passed': False, 'output': '区域名称不能为空', 'error': 'invalid_args'}

        result = {'passed': False, 'output': '', 'error': None}
        temp_path = None

        try:
            # 如果没有指定文件路径但有内容，先写入临时文件
            if not zone_file and zone_content:
                import tempfile as _tf
                fd, temp_path = _tf.mkstemp(suffix='.zone', prefix=f'check_{zone_name.replace(".", "_")}_')
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(zone_content)
                zone_file = temp_path

            cmd = ['named-checkzone', '-i', 'none', zone_name]
            if zone_file:
                cmd.append(zone_file)

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUTS.get('named-checkzone', 30),
            )
            result['passed'] = proc.returncode == 0
            output_text = (proc.stdout + proc.stderr).strip()
            result['output'] = output_text or ('OK' if proc.returncode == 0 else '')
        except subprocess.TimeoutExpired:
            result['output'] = f'checkzone [{zone_name}] 超时(30s)'
            result['error'] = 'timeout'
        except FileNotFoundError:
            result['output'] = f'named-checkzone 未找到，请安装bind9utils'
            result['error'] = 'not_found'
        except Exception as e:
            result['output'] = f'checkzone [{zone_name}] 错误: {e}'
            result['error'] = str(e)
            logger.warning(f'check_zone [{zone_name}] error: {e}')
        finally:
            # 清理临时文件
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        return result

    # ================================================================
    # 服务控制方法
    # ================================================================

    def service_start(self) -> Dict[str, Any]:
        """启动named服务"""
        return self._service_control('start')

    def service_stop(self) -> Dict[str, Any]:
        """停止named服务"""
        return self._service_control('stop')

    def service_restart(self) -> Dict[str, Any]:
        """重启named服务"""
        return self._service_control('restart')

    def service_reload(self) -> Dict[str, Any]:
        """重新加载配置(reload) - 不中断现有连接"""
        return self._service_control('reload')

    def service_reconfig(self) -> Dict[str, Any]:
        """重读配置文件并加载新区域(reconfig) - 通过rndc实现"""
        return self.rndc_command('reconfig')

    def flush_cache(self, view=None, domain=None) -> Dict[str, Any]:
        """清理DNS缓存

        Args:
            view: 指定view名称（可选）
            domain: 指定域名清理该域名的缓存（可选，不填则清理全部）
        """
        args = ['flush']
        if view:
            args.extend(['-view', view])
        if domain:
            args.append(domain)
        else:
            args.append('all')
        return self.rndc_command(' '.join(args))

    def rndc_reload_zone(self, zone_name: str, view: str = None) -> Dict[str, Any]:
        """reload单个区域 (通过 rndc reload <zone> [view])

        Args:
            zone_name: 区域名称
            view: View名称（可选）
        """
        args = ['reload', zone_name]
        if view:
            args.append(view)
        return self.rndc_command(' '.join(args))

    def rndc_notify(self, zone_name: str, target_ip: str = None) -> Dict[str, Any]:
        """发送 NOTIFY 通知给从服务器（用于触发增量传输）

        Args:
            zone_name: 区域名称
            target_ip: 目标从服务器IP（可选，不填则通知所有also-notify）
        """
        args = ['notify', zone_name]
        if target_ip:
            args.append(target_ip)
        return self.rndc_command(' '.join(args))

    def rndc_freeze(self, zone_name: str) -> Dict[str, Any]:
        """冻结区域（暂停动态更新，便于备份）"""
        return self.rndc_command(f'freeze {zone_name}')

    def rndc_thaw(self, zone_name: str) -> Dict[str, Any]:
        """解冻区域（恢复动态更新，同时递增serial并写盘）"""
        return self.rndc_command(f'thaw {zone_name}')

    def rndc_retransfer(self, zone_name: str) -> Dict[str, Any]:
        """强制重新传输区域（忽略SOA serial比较）"""
        return self.rndc_command(f'retransfer {zone_name}')

    def get_statistics(self) -> Dict[str, Any]:
        """获取DNS统计信息（通过rndc stats）"""
        ret = self.rndc_command('stats')
        if ret.get('success'):
            stats_file = '/var/named/data/named_stats.txt'  # BIND9默认路径
            try:
                with open(stats_file, 'r') as f:
                    ret['stats_content'] = f.read()
            except FileNotFoundError:
                ret['stats_content'] = ''
                ret['note'] = f'统计文件未找到: {stats_file}，请确认options中statistics-file设置'
        return ret

    # ================================================================
    # 内部方法
    # ================================================================

    def _service_control(self, action: str) -> Dict[str, Any]:
        """通用服务控制方法 (systemctl start|stop|restart|reload named)

        Args:
            action: 操作名称 (start/stop/restart/reload)

        Returns:
            dict: {'success': bool, 'output': str}
        """
        allowed_actions = ['start', 'stop', 'restart', 'reload', 'status']
        if action not in allowed_actions:
            logger.warning(f'_service_control blocked: {action}')
            return {
                'success': False,
                'output': f'不允许的操作: {action}，允许: {allowed_actions}',
            }

        try:
            output = self._run_command(
                ['systemctl', action, 'named'],
                timeout=COMMAND_TIMEOUTS.get('systemctl', 30),
            )
            # 判断成功: systemctl 输出首行不含 "Failed"
            first_line = output.split('\n')[0].strip() if output else ''
            success = 'Failed' not in first_line and 'Unit named.service could not be found' not in output
            return {
                'success': success,
                'output': output.strip() or f'systemctl {action} named 已提交',
            }
        except subprocess.TimeoutExpired:
            msg = f'systemctl {action} named 超时({COMMAND_TIMEOUTS.get("systemctl", 30)}s)'
            logger.error(msg)
            return {'success': False, 'output': msg}
        except Bind9ServiceError as e:
            return {'success': False, 'output': str(e)}
        except Exception as e:
            msg = f'systemctl {action} named 异常: {e}'
            logger.exception(msg)
            return {'success': False, 'output': msg}

    def rndc_command(self, args_str: str) -> Dict[str, Any]:
        """执行rndc子命令

        Args:
            args_str: rndc子命令及参数，如 'status', 'reconfig', 'flush all',
                      'reload example.com', 'freeze example.com'

        Returns:
            dict: {'success': bool, 'output': str}
        """
        # 安全拆分参数（简单按空格分割，避免shell注入）
        parts = ['rndc'] + args_str.split()

        # 二次验证：禁止危险的 rndc 子命令组合
        dangerous_patterns = [';', '|', '&&', '||', '$(', '`', '..']
        for arg in parts[1:]:
            for pattern in dangerous_patterns:
                if pattern in arg:
                    logger.critical(f'rndc_command blocked dangerous pattern: {args_str}')
                    return {
                        'success': False,
                        'output': f'命令包含危险字符: {pattern}',
                    }

        try:
            output = self._run_command(
                parts,
                timeout=COMMAND_TIMEOUTS.get('rndc', 20),
            )
            return {
                'success': True,
                'output': output.strip() or '(无输出)',
            }
        except subprocess.TimeoutExpired:
            msg = f'rndc {args_str} 超时({COMMAND_TIMEOUTS.get("rndc", 20)}s)'
            logger.warning(msg)
            return {'success': False, 'output': msg}
        except FileNotFoundError:
            msg = 'rndc 命令未找到，请确认已安装BIND9 (apt install bind9utils / yum install bind-utils)'
            logger.warning('rndc command not found')
            return {'success': False, 'output': msg}
        except PermissionError:
            msg = 'rndc 权限不足，请检查: 1) rndc.key 文件权限 2) sudoers配置 3) 是否在named组'
            return {'success': False, 'output': msg}
        except Bind9ServiceError as e:
            return {'success': False, 'output': str(e)}
        except Exception as e:
            msg = f'rndc {args_str} 异常: {e}'
            logger.exception(f'rndc_command unexpected: {e}')
            return {'success': False, 'output': msg}

    @staticmethod
    def _run_command(cmd_args: list, timeout: int = 30, input_data: str = None) -> str:
        """
        安全执行命令（白名单检查 + 超时控制）

        Args:
            cmd_args: 命令参数列表，如 ['systemctl', 'status', 'named']
            timeout: 超时秒数
            input_data: 通过stdin传入的数据（可选）

        Returns:
            str: stdout + stderr 合并输出（已strip）

        Raises:
            ValueError: 非白名单命令
            subprocess.TimeoutExpired: 命令超时
            FileNotFoundError: 命令不存在
            Bind9ServiceError: 其他执行错误
        """
        base_cmd = cmd_args[0] if cmd_args else ''

        # 1) 白名单检查
        if base_cmd not in ALLOWED_COMMANDS:
            logger.critical(f'Command blocked by whitelist: {base_cmd}, allowed={ALLOWED_COMMANDS}')
            raise Bind9ServiceError(
                f'命令不在白名单中: {base_cmd}，允许的命令: {", ".join(sorted(ALLOWED_COMMANDS))}',
                command=base_cmd,
            )

        # 2) 参数安全检查（防止注入）
        for i, arg in enumerate(cmd_args[1:], 1):
            if any(c in arg for c in [';', '|', '&', '$', '`', '\n', '\r']):
                raise Bind9ServiceError(
                    f'命令参数包含危险字符 (arg#{i}): {arg!r}',
                    command=base_cmd,
                )

        # 3) 执行命令
        try:
            proc = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input_data,
            )

            # 合并stdout和stderr（BIND9工具常把错误信息输出到stderr）
            combined = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')

            # 记录非零退出码
            if proc.returncode != 0:
                logger.debug(
                    f'Command {" ".join(cmd_args)} exited={proc.returncode}: '
                    f'{combined[:300]}'
                )

            return combined.strip()

        except subprocess.TimeoutExpired:
            logger.error(f'Command timed out: {" ".join(cmd_args)} ({timeout}s)')
            raise


# 单例便捷函数
def get_bind9_service():
    """获取Bind9Service实例（使用数据库中的本地服务器配置）"""
    from ..models import DnsServer
    server = DnsServer.get_local_server()
    return Bind9Service(server)

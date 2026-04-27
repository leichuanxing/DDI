#!/usr/bin/env python
"""
DDI管理系统 - Django管理命令入口

用法:
    python manage.py runserver          # 启动开发服务器
    python manage.py migrate             # 执行数据库迁移
    python manage.py init                # 初始化数据（角色/管理员/DNS配置/IPAM示例）
    python manage.py init --minimal      # 最小化初始化（仅基础配置，无示例数据）
    python manage.py shell               # 进入Django Shell
    python manage.py createsuperuser     # 创建管理员
    python manage.py collectstatic       # 收集静态文件

环境变量:
    DJANGO_SETTINGS_MODULE   覆盖默认设置模块 (默认: ddi_system.settings)
    DD_BIND_VERSION          BIND9版本号 (用于安装脚本引用)
    DD_DEBUG                 覆盖DEBUG模式 (0/1)
"""

import os
import sys


# ============================================================
# 路径处理 — 确保无论从哪个目录运行都能正确找到项目根目录
# ============================================================
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 默认设置模块
_DEFAULT_SETTINGS = 'ddi_system.settings'


def setup_environment():
    """配置Django运行环境"""
    settings_module = (
        os.environ.get('DJANGO_SETTINGS_MODULE')
        or _DEFAULT_SETTINGS
    )
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)


def run_init_data(extra_args=None):
    """执行数据初始化脚本"""
    import subprocess

    init_script = os.path.join(_PROJECT_ROOT, 'init_data.py')
    if not os.path.exists(init_script):
        print("❌ 初始化脚本不存在: init_data.py")
        return False

    cmd = [sys.executable, init_script]
    if extra_args:
        cmd.extend(extra_args)

    print("🚀 执行数据初始化...\n")
    result = subprocess.run(cmd, cwd=_PROJECT_ROOT)
    return result.returncode == 0


def run_dev_server(addr='0.0.0.0', port=8000):
    """启动开发服务器（带常用默认参数）"""
    from django.core.management import call_command

    # 自动创建必要的表（首次运行时）
    try:
        from django.core.management import execute_from_command_line
        execute_from_command_line(['manage.py', 'migrate', '--run-syncdb', '--noinput'])
    except Exception:
        pass  # 迁移失败不阻塞启动

    print(f"\n{'='*60}")
    print(f"  🌐 DDI管理系统 开发服务器")
    print(f"  地址: http://{addr}:{port}/")
    print(f"{'='*60}\n")

    call_command(
        'runserver',
        f'{addr}:{port}',
        use_reloader=True,
        verbosity=1,
    )


def main():
    """主入口"""
    setup_environment()

    # ---- 自定义快捷命令 ----
    args = sys.argv[1:] if len(sys.argv) > 1 else []

    # python manage.py init [args...]
    if args and args[0] == 'init':
        return run_init_data(args[1:])

    # python manage.py dev [--addr] [--port]
    if args and args[0] == 'dev':
        addr = '0.0.0.0'
        port = 8000
        i = 1
        while i < len(args):
            if args[i] in ('-a', '--addr') and i + 1 < len(args):
                addr = args[i + 1]; i += 2
            elif args[i] in ('-p', '--port') and i + 1 < len(args):
                port = int(args[i + 1]); i += 2
            else:
                i += 1
        try:
            run_dev_server(addr, port)
            return
        except KeyboardInterrupt:
            print("\n🛑 开发服务器已停止")
            return

    # ---- 标准 Django 命令 ----
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "无法导入 Django。请确认：\n"
            "  1) Django 已安装: pip install django\n"
            "  2) 已激活虚拟环境 (如有)\n"
            "  3) PYTHONPATH 包含项目目录\n"
            f"\n  当前 Python: {sys.executable}\n"
            f"  项目路径: {_PROJECT_ROOT}"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()

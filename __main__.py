"""
DDI管理系统 — 包入口

允许通过以下方式运行:
    python -m ddi_system runserver
    python -m ddi_system migrate
    python -m ddi_system init
"""

from manage import main

if __name__ == '__main__':
    main()

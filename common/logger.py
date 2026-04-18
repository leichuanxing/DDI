import logging
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


def log_operation(user, operation_type, module, obj_type, old_value='', new_value=''):
    """
    记录操作日志
    
    Args:
        user: 操作用户
        operation_type: 操作类型 (新增/修改/删除/导入/导出/登录/退出)
        module: 操作模块
        obj_type: 操作对象类型
        old_value: 变更前内容
        new_value: 变更后内容
    """
    try:
        from logs.models import OperationLog
        OperationLog.objects.create(
            user=user,
            module=module,
            action=operation_type,
            object_type=obj_type,
            old_value=old_value[:1000] if old_value else '',
            new_value=new_value[:1000] if new_value else '',
            ip_address=''  # 可以通过middleware设置
        )
    except Exception as e:
        logger.error(f"记录操作日志失败: {e}")

"""
发布/回滚服务框架
实现草稿->待发布->校验->备份->写入->reload 的完整生命周期流程

核心流程(发布):
1. 收集变更: 检测自上次发布以来数据库中的变更对象
2. 创建发布版本: 生成版本号，记录变更明细(DnsPublishObject)
3. 业务校验: 模型级约束检查(SOA完整性/CNAME冲突等)
4. 配置渲染: 通过ConfigRenderer生成named.conf文本
5. named-checkconf/checkzone: BIND9语法校验
6. 备份当前正式配置: 写入DnsBackup
7. 写入正式目录: 将新配置覆盖到目标路径(原子操作)
8. 执行reload/reconfig: 让named加载新配置
9. 记录结果: 更新DnsPublishVersion状态，写审计日志

回滚流程:
1. 选择历史备份版本
2. 备份当前配置(作为回滚前快照)
3. 将备份内容恢复到目标路径
4. 执行reload
5. 更新版本状态为rolled_back
6. 写回滚审计日志

P5完善:
- write_config 实际执行文件写入(原子写入+权限+备份原文件)
- rollback 完整实现回滚前快照+恢复+reload
- collect_changes 精确变更检测(基于updated_at对比上次发布时间)
- diff生成(DnsPublishObject.diff_content)
"""

import os
import shutil
import tempfile
import logging
from datetime import datetime
from django.db import transaction
from django.utils import timezone

from ..models import (
    DnsServer, DnsGlobalOption, DnsAcl, DnsAclItem,
    DnsView, DnsZone, DnsRecord, DnsForwardRule,
    DnsPublishVersion, DnsPublishObject, DnsBackup,
)
from .config_renderer import ConfigRenderer, render_bind_config
from .bind9_service import Bind9Service

logger = logging.getLogger('dns.publish')


def _read_config_file(path: str) -> str:
    """读取配置文件内容（模块级公共函数，PublishService/RollbackService共用）"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f'Config file not found: {path}')
        return f'// File not found: {path}\n// This is a placeholder.\n'
    except UnicodeDecodeError:
        try:
            with open(path, 'r', encoding='latin-1') as f:
                return f.read()
        except Exception:
            return '// Unable to read config file\n'


class PublishError(Exception):
    """发布异常"""

    def __init__(self, message: str, step: str = ''):
        super().__init__(message)
        self.step = step


class RollbackError(Exception):
    """回滚异常"""


# ================================================================
# 默认配置常量
# ================================================================

DEFAULT_CONFIG_PATH = '/etc/named.conf'
BACKUP_DIR = '/var/named/backups'  # 备份存储目录
NAMED_USER = 'named'              # named进程用户(Linux)
NAMED_GROUP = 'named'             # named进程组


class PublishService:
    """DNS配置发布服务 - 编排完整的发布生命周期"""

    def __init__(self, user=None, notes=''):
        self.user = user
        self.notes = notes
        self.server = None
        self.version = None
        self.renderer = None
        self.bind9 = None
        self._last_publish_time = None

    # ================================================================
    # 步骤1-2: 收集变更 + 创建发布版本
    # ================================================================

    @transaction.atomic
    def collect_changes(self) -> DnsPublishVersion:
        """
        收集自上次发布以来的所有变更对象，创建发布版本记录

        变更检测规则:
        - 全局配置: is_draft=True 的DnsGlobalOption
        - Zone: updated_at > 上次成功发布时间的zone
        - ACL/View: 同样基于时间戳判断
        - Record: 不单独列出(跟随所属Zone一起发布)

        Returns:
            DnsPublishVersion: 新建的发布版本实例
        """
        now = timezone.now()
        version_number = now.strftime('%Y%m%d%H%M%S')

        # 获取上次成功发布时间作为变更检测基线
        last_success = DnsPublishVersion.objects.filter(
            status='success'
        ).order_by('-publish_time').first()
        self._last_publish_time = last_success.publish_time if last_success else None

        self.version = DnsPublishVersion.objects.create(
            version_number=version_number,
            status='pending',
            publisher=self.user,
            notes=self.notes,
            publish_time=None,
        )

        objects_created = 0

        # --- 1) 全局配置变更 ---
        draft_opts = DnsGlobalOption.objects.filter(is_draft=True)
        for opt in draft_opts.select_related('server'):
            diff_text = f'options块已修改: directory={opt.directory}, listen_on={opt.listen_on_v4[:30] or "default"}...'
            DnsPublishObject.objects.create(
                version=self.version,
                object_type='global_option',
                object_id=opt.id,
                object_name=f'全局配置-{opt.server.hostname if opt.server else "默认"}',
                action='update',
                diff_content=diff_text,
                check_result='pending',
            )
            objects_created += 1

        # --- 2) Zone变更 (基于时间戳) ---
        zone_qs = DnsZone.objects.all()
        if self._last_publish_time:
            zone_qs = zone_qs.filter(updated_at__gt=self._last_publish_time)

        for zone in zone_qs.select_related('view').order_by('name'):
            action_type = 'update'
            if zone.created_at and self._last_publish_time:
                if zone.created_at > self._last_publish_time:
                    action_type = 'create'

            diff_text = (
                f'{zone.get_zone_type_display()} / {zone.get_direction_type_display()} / '
                f'enabled={zone.enabled} / records={zone.record_count}'
            )
            DnsPublishObject.objects.create(
                version=self.version,
                object_type='zone',
                object_id=zone.id,
                object_name=zone.name,
                action=action_type,
                diff_content=diff_text,
                check_result='pending',
            )
            objects_created += 1

        # --- 3) ACL变更 ---
        acl_qs = DnsAcl.objects.all()
        if self._last_publish_time:
            acl_qs = acl_qs.filter(updated_at__gt=self._last_publish_time)

        for acl in acl_qs:
            DnsPublishObject.objects.create(
                version=self.version,
                object_type='acl',
                object_id=acl.id,
                object_name=acl.name,
                action='update',
                diff_content=f'ACL {acl.name} ({acl.item_count}条目)',
                check_result='pending',
            )
            objects_created += 1

        # --- 4) View变更 ---
        view_qs = DnsView.objects.all()
        if self._last_publish_time:
            view_qs = view_qs.filter(updated_at__gt=self._last_publish_time)

        for view in view_qs:
            DnsPublishObject.objects.create(
                version=self.version,
                object_type='view',
                object_id=view.id,
                object_name=view.name,
                action='update',
                diff_content=f'View {view.name} (zones={view.zone_count})',
                check_result='pending',
            )
            objects_created += 1

        self.version.object_count = objects_created
        self.version.save(update_fields=['object_count'])

        logger.info(f'collect_changes: v{version_number}, {objects_created} objects')
        return self.version

    # ================================================================
    # 步骤3: 业务规则校验
    # ================================================================

    def validate_business_rules(self) -> tuple:
        """
        校验业务规则 - 在BIND9语法检查之前的模型级验证

        检查项:
        - Master Zone 必须有 SOA 记录
        - Master Zone 至少有一条 NS 记录
        - CNAME 不能与同名其他记录并存(RFC)
        - Slave Zone 必须指定 master_ips
        - Forward Zone 必须指定 forwarders

        Returns:
            tuple: (是否通过, 错误列表, 警告列表)
        """
        errors = []
        warnings = []

        # 1. SOA + NS 完整性检查
        master_zones = DnsZone.objects.filter(enabled=True, zone_type='master')
        for zone in master_zones:
            soa = zone.get_soa_record()
            if not soa:
                errors.append(f'Master区域 [{zone.name}] 缺少SOA记录')
            ns_count = zone.records.filter(record_type='NS', enabled=True).count()
            if ns_count < 1:
                errors.append(f'Master区域 [{zone.name}] 至少需要一条NS记录')

        # 2. CNAME 冲突检查
        all_enabled_zones = DnsZone.objects.filter(enabled=True)
        for zone in all_enabled_zones:
            cname_names = set(
                zone.records.filter(record_type='CNAME', enabled=True)
                .values_list('name', flat=True)
            )
            for name in cname_names:
                conflicts = (
                    zone.records.exclude(record_type='CNAME')
                    .filter(name=name, enabled=True)
                )
                if conflicts.exists():
                    conflict_types = list(conflicts.values_list('record_type', flat=True))
                    errors.append(
                        f'CNAME冲突: 区域[{zone.name}] 名称"{name}" '
                        f'同时存在CNAME和{", ".join(conflict_types)}记录'
                    )

        # 3. Slave/Forward 类型必填字段检查 (仅警告)
        slave_zones = DnsZone.objects.filter(zone_type='slave', enabled=True)
        for zone in slave_zones:
            if not zone.master_ips:
                warnings.append(f'Slave区域 [{zone.name}] 未设置主服务器IP(master_ips)')

        forward_zones = DnsZone.objects.filter(zone_type__in=('forward', 'stub'), enabled=True)
        for zone in forward_zones:
            if not zone.forwarders:
                warnings.append(f'{zone.get_zone_type_display()}区域 [{zone.name}] 未设置转发目标(forwarders)')

        logger.debug(f'validate_business_rules: {len(errors)} errors, {len(warnings)} warnings')
        return len(errors) == 0, errors, warnings

    # ================================================================
    # 步骤4-5: 渲染配置 + BIND9语法校验
    # ================================================================

    def render_and_validate(self) -> tuple:
        """
        渲染完整配置并执行BIND9语法校验(named-checkconf + named-checkzone)

        Returns:
            tuple: (all_passed, conf_result_dict, zone_results_list)
        """
        self.server = self.server or DnsServer.get_local_server()
        self.renderer = ConfigRenderer(self.server)
        config_text = self.renderer.render_full_config()

        self.bind9 = Bind9Service(self.server)

        # 4a) named-checkconf 全局配置校验
        conf_result = self.bind9.check_conf(config_text)

        # 4b) 对每个enabled的Master Zone执行checkzone
        zone_results = []
        master_zones = DnsZone.objects.filter(enabled=True, zone_type='master')
        for zone in master_zones:
            try:
                zone_text = self.renderer.render_zone_file(zone)
                zresult = self.bind9.check_zone(zone.name, zone_content=zone_text)
                zone_results.append({
                    'zone': zone.name,
                    'passed': zresult['passed'],
                    'output': zresult.get('output', ''),
                    'error': zresult.get('error'),
                })
                logger.debug(f'check_zone [{zone}]: passed={zresult["passed"]}')
            except Exception as e:
                zone_results.append({
                    'zone': zone.name,
                    'passed': False,
                    'output': '',
                    'error': f'校验异常: {e}',
                })

        all_passed = (
            conf_result.get('passed', False)
            and all(z['passed'] for z in zone_results)
        )

        return all_passed, conf_result, zone_results

    # ================================================================
    # 步骤6: 备份当前正式配置
    # ================================================================

    def backup_current(self) -> DnsBackup:
        """备份当前正式named.conf到数据库+磁盘(可选)

        Returns:
            DnsBackup: 备份记录实例
        """
        config_path = getattr(self.server, 'named_conf_path', DEFAULT_CONFIG_PATH) if self.server else DEFAULT_CONFIG_PATH
        config_content = _read_config_file(config_path)

        backup = DnsBackup.objects.create(
            version=self.version,
            backup_type='pre_publish',
            config_content=config_content,
            file_size=len(config_content),
            storage_path='',
            backup_user=self.user,
            notes=f'v{self.version.version_number} 发布前自动备份 @ {timezone.now().strftime("%H:%M:%S")}',
        )

        # 同时保存到备份目录(可选)
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            backup_filename = f'pre_{self.version.version_number}.conf'
            backup_path = os.path.join(BACKUP_DIR, backup_filename)
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(config_content)
            backup.storage_path = backup_path
            backup.save(update_fields=['storage_path'])
        except (IOError, OSError) as e:
            logger.warning(f'备份文件写入失败: {e}')

        logger.info(f'backup_current: v{self.version.version_number}, size={len(config_content)}')
        return backup

    # ================================================================
    # 步骤7: 写入正式配置 (原子操作)
    # ================================================================

    def write_config(self, config_text: str) -> bool:
        """
        将新配置原子写入目标路径

        安全策略:
        1. 先写入临时文件（同目录下）
        2. 设置正确的权限和属主
        3. 原子rename替换原文件
        4. 如果失败，原文件不受影响

        Args:
            config_text: 要写入的新配置文本

        Returns:
            bool: 是否写入成功
        """
        target_path = getattr(self.server, 'named_conf_path', DEFAULT_CONFIG_PATH) if self.server else DEFAULT_CONFIG_PATH

        if not config_text:
            raise PublishError('配置文本为空，无法写入', step='write_config')

        try:
            target_dir = os.path.dirname(target_path)
            if target_dir and not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                suffix='.tmp',
                prefix='named_conf_',
                dir=target_dir or '/tmp',
            )
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(config_text)
                    f.flush()
                    os.fsync(f.fileno())

                os.chmod(tmp_path, 0o644)
                try:
                    import pwd, grp
                    uid = pwd.getpwnam(NAMED_USER).pw_uid
                    gid = grp.getgrnam(NAMED_GROUP).gr_gid
                    os.chown(tmp_path, uid, gid)
                except (KeyError, OSError):
                    pass

                os.replace(tmp_path, target_path)
                tmp_path = None

                logger.info(f'write_config: 成功写入 {target_path} ({len(config_text)} bytes)')
                return True

            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

        except PublishError:
            raise
        except PermissionError as e:
            raise PublishError(
                f'写入权限不足: {target_path}. 请确认有写权限。',
                step='write_config',
            ) from e
        except IOError as e:
            raise PublishError(f'文件IO错误: {e}', step='write_config') from e
        except Exception as e:
            raise PublishError(f'配置写入异常: {e}', step='write_config') from e

        return False

    # ================================================================
    # 步骤8: reload服务
    # ================================================================

    def reload_service(self) -> dict:
        """执行service reload让named加载新配置"""
        if not self.bind9:
            self.bind9 = Bind9Service(self.server)

        result = self.bind9.service_reload()

        if result.get('success'):
            reconfig_result = self.bind9.service_reconfig()
            if not reconfig_result.get('success'):
                logger.warning(f'reload成功但reconfig失败: {reconfig_result.get("output")}')

        return result

    # ================================================================
    # 步骤9: 记录结果 + 清理草稿
    # ================================================================

    def finalize_publish(self, reload_result: dict) -> DnsPublishVersion:
        """记录最终发布结果并清除草稿标记"""
        success = reload_result.get('success', False)

        self.version.status = 'success' if success else 'failed'
        self.version.publish_time = timezone.now()
        self.version.checkconf_passed = success
        self.version.save(update_fields=['status', 'publish_time', 'checkconf_passed'])

        if success:
            DnsPublishObject.objects.filter(version=self.version).update(
                check_result='pass', publish_status='published'
            )
        else:
            DnsPublishObject.objects.filter(version=self.version).update(
                publish_status='failed'
            )

        cleared_count = DnsGlobalOption.objects.filter(is_draft=True).update(
            is_draft=False, draft_updated_at=None,
        )
        if cleared_count > 0:
            logger.info(f'finalize: 清除{cleared_count}个全局配置草稿标记')

        return self.version

    # ================================================================
    # 一键发布（串联以上所有步骤）
    # ================================================================

    def execute_publish(self) -> dict:
        """执行完整发布流程: collect -> validate -> render+check -> backup -> write -> reload -> finalize"""
        result = {
            'success': False,
            'version': None,
            'errors': [],
            'warnings': [],
            'step': '',
        }

        try:
            # === Step 1: 收集变更 ===
            result['step'] = 'collect_changes'
            version = self.collect_changes()
            if version.object_count == 0:
                result['warnings'].append('没有检测到变更对象，无需发布')
                result['success'] = True
                return result

            # === Step 2: 业务校验 ===
            result['step'] = 'business_validate'
            passed, biz_errors, biz_warnings = self.validate_business_rules()
            result['warnings'].extend(biz_warnings)
            if not passed:
                raise PublishError(
                    f'业务校验失败({len(biz_errors)}项): {"; ".join(biz_errors[:5])}',
                    step='business_validate',
                )

            # === Step 3: 渲染 + BIND9语法校验 ===
            result['step'] = 'render_and_check'
            all_passed, conf_result, zone_results = self.render_and_validate()
            if not all_passed:
                failed_items = []
                if not conf_result.get('passed'):
                    failed_items.append(f'named-checkconf未通过: {conf_result.get("output", "")[:200]}')
                failed_zones = [z['zone'] for z in zone_results if not z['passed']]
                if failed_zones:
                    failed_items.append(f'Zone校验失败: {", ".join(failed_zones)}')
                raise PublishError(
                    f'BIND9校验失败: {"; ".join(failed_items)}',
                    step='bind9_check',
                )

            # === Step 4: 备份当前配置 ===
            result['step'] = 'backup'
            backup = self.backup_current()

            # === Step 5: 写入新配置 ===
            result['step'] = 'write'
            config_text = self.renderer.render_full_config()
            self.write_config(config_text)

            # === Step 6: Reload ===
            result['step'] = 'reload'
            reload_result = self.reload_service()

            # === Step 7: 完成 ===
            result['step'] = 'finalize'
            version = self.finalize_publish(reload_result)
            result['success'] = True
            result['version'] = version

            logger.info(
                f'execute_publish SUCCESS: v{version.version_number}, '
                f'{version.object_count} objects, reload={"OK" if reload_result.get("success") else "FAIL"}'
            )

        except PublishError as e:
            logger.error(f'execute_publish FAILED at [{e.step}]: {e}')
            if self.version:
                self.version.status = 'failed'
                self.version.publish_time = timezone.now()
                self.version.save(update_fields=['status', 'publish_time'])
            result['errors'].append(str(e))
            result['step'] = getattr(e, 'step', result.get('step', 'unknown'))
        except Exception as e:
            logger.exception(f'execute_publish UNEXPECTED ERROR: {e}')
            result['errors'].append(f'发布过程发生异常: {e}')
            if self.version:
                self.version.status = 'failed'
                self.version.publish_time = timezone.now()
                self.version.save(update_fields=['status', 'publish_time'])

        return result


# ================================================================
# 回滚服务
# ================================================================

class RollbackService:
    """配置回滚服务 - 将配置恢复到某个历史备份版本"""

    def __init__(self, user=None):
        self.user = user
        self.server = None

    def _get_server(self):
        if not self.server:
            self.server = DnsServer.get_local_server()
        return self.server

    def execute_rollback(self, backup_pk: int) -> dict:
        """执行回滚到指定备份版本

        流程: 验证→读取→备份当前→原子写入→reload→更新状态→日志
        """
        result = {'success': False, 'message': ''}

        try:
            backup = DnsBackup.objects.select_related(
                'version', 'version__publisher', 'backup_user'
            ).get(pk=backup_pk)

            target_version_str = (
                f'v{backup.version.version_number}' if backup.version
                else f'manual-backup-{backup.pk}'
            )

            server = self._get_server()
            config_path = getattr(server, 'named_conf_path', DEFAULT_CONFIG_PATH)

            restore_content = backup.config_content
            if not restore_content or len(restore_content.strip()) < 10:
                raise RollbackError(f'备份内容为空或过短 ({len(restore_content or "")} bytes)，可能已损坏')

            # 回滚前快照（安全网）
            current_content = _read_config_file(config_path)
            pre_rollback_backup = DnsBackup.objects.create(
                version=backup.version,
                backup_type='pre_rollback',
                config_content=current_content,
                file_size=len(current_content),
                storage_path='',
                backup_user=self.user,
                notes=f'回滚到 {target_version_str} 前的当前配置快照 @ {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}',
            )

            # 原子写入恢复内容
            self._atomic_write(config_path, restore_content)

            # Reload
            bind9 = Bind9Service(server)
            reload_result = bind9.service_reconfig()

            if backup.version:
                backup.version.status = 'rolled_back'
                backup.version.save(update_fields=['status'])

            result['success'] = reload_result.get('success', True)
            result['message'] = (
                f'已成功回滚到 {target_version_str} '
                f'(reload={"成功" if reload_result.get("success") else "失败"})'
            )

            logger.info(
                f'Rollback SUCCESS: to={target_version_str}, size={len(restore_content)}, '
                f'pre_rollback_backup=#{pre_rollback_backup.pk}'
            )

        except DnsBackup.DoesNotExist:
            msg = f'备份记录不存在: pk={backup_pk}'
            result['message'] = msg
            logger.warning(msg)
        except RollbackError as e:
            msg = f'回滚失败: {e}'
            result['message'] = msg
            logger.error(msg)
        except PermissionError as e:
            msg = f'回滚权限不足: 无法写入配置文件。请确认有写权限。'
            result['message'] = msg
            logger.error(f'Rollback permission error: {e}')
        except Exception as e:
            msg = f'回滚异常: {e}'
            result['message'] = msg
            logger.exception(f'Rollback unexpected error: {e}')

        return result

    @staticmethod
    def _atomic_write(path: str, content: str) -> None:
        """原子写入文件（先写临时文件再rename）"""
        target_dir = os.path.dirname(path) or '/tmp'
        fd, tmp_path = tempfile.mkstemp(suffix='.rbk', dir=target_dir)

        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, path)
            tmp_path = None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

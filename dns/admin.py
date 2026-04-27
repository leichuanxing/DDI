"""DNS模块 - Django Admin 注册"""

from django.contrib import admin
from .models import (
    DnsServer, DnsGlobalOption, DnsAcl, DnsAclItem,
    DnsView, DnsZone, DnsRecord, DnsForwardRule,
    DnsSyncStatus, DnsPublishVersion, DnsPublishObject,
    DnsBackup, DnsAuditLog,
)


@admin.register(DnsServer)
class DnsServerAdmin(admin.ModelAdmin):
    list_display = ('hostname', 'ip_address', 'bind_version', 'is_local', 'enabled')
    search_fields = ('hostname', 'ip_address')


@admin.register(DnsAcl)
class DnsAclAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'item_count', 'created_at')
    search_fields = ('name',)

    def item_count(self, obj):
        return obj.items.count()


class DnsAclItemInline(admin.TabularInline):
    model = DnsAclItem
    extra = 1


@admin.register(DnsView)
class DnsViewAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'order_index')
    filter_horizontal = ('match_clients', 'match_destinations')


@admin.register(DnsZone)
class DnsZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'zone_type', 'direction_type', 'view', 'enabled', 'record_count')
    list_filter = ('zone_type', 'direction_type', 'enabled')
    search_fields = ('name',)

    def record_count(self, obj):
        return obj.records.count()


@admin.register(DnsRecord)
class DnsRecordAdmin(admin.ModelAdmin):
    list_display = ('zone', 'record_type', 'name', 'value', 'ttl', 'enabled')
    list_filter = ('record_type', 'enabled', 'zone')
    search_fields = ('name', 'value')


@admin.register(DnsForwardRule)
class DnsForwardRuleAdmin(admin.ModelAdmin):
    list_display = ('rule_type', 'zone', 'policy')


@admin.register(DnsAuditLog)
class DnsAuditLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'category', 'object_name', 'result', 'operation_time')
    list_filter = ('category', 'action', 'result')
    search_fields = ('object_name', 'detail')
    date_hierarchy = 'operation_time'


admin.site.register(DnsGlobalOption)
admin.site.register(DnsSyncStatus)
admin.site.register(DnsPublishVersion)
admin.site.register(DnsPublishObject)
admin.site.register(DnsBackup)

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from usermodel.models import ApiAccessLog, PersonalAccessToken, User
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin


@admin.register(User)
class UserAdmin(DefaultUserAdmin):
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'email', 'password',
                    'first_name', 'last_name',
                )
            }
        ),
        (
            _('Permissions'),
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                ),
            }
        ),
        (
            _('Important dates'),
            {
                'fields': (
                    'last_login',
                    'date_joined',
                )
            }
        ),
        (
            _('User data'),
            {
                'fields': (
                    ('is_email_confirmed',),
                )
            }
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'password1', 'password2'),
            }
        ),
    )
    list_display = ('email', 'first_name', 'last_name', 'is_staff')
    search_fields = ('first_name', 'last_name', 'email')
    ordering = ('email',)


@admin.register(PersonalAccessToken)
class PersonalAccessTokenAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at', 'last_used_at', 'expires_at', 'is_revoked')
    list_filter = ('is_revoked',)
    search_fields = ('name', 'user__email')
    raw_id_fields = ('user',)
    readonly_fields = ('token_hash', 'created_at', 'last_used_at')


@admin.register(ApiAccessLog)
class ApiAccessLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'method', 'path', 'status_code', 'token_type', 'ip_truncated')
    list_filter = ('method', 'token_type', 'status_code', 'user')
    search_fields = ('user__email', 'path', 'token_id', 'request_id', 'ip_truncated')
    raw_id_fields = ('user',)
    readonly_fields = (
        'timestamp', 'user', 'token_type', 'token_id', 'scopes',
        'method', 'path', 'status_code', 'ip_truncated', 'request_id', 'user_agent',
    )
    date_hierarchy = 'timestamp'
    list_per_page = 100

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

from django.contrib import admin

from .models import EmailConfiguration, SefazConfiguration


@admin.register(SefazConfiguration)
class SefazConfigurationAdmin(admin.ModelAdmin):
	list_display = ('base_url', 'environment', 'timeout', 'certificate_uploaded_at', 'updated_at', 'updated_by')
	readonly_fields = (
		'updated_at',
		'updated_by',
		'certificate_uploaded_at',
		'certificate_subject',
		'certificate_serial_number',
		'certificate_valid_from',
		'certificate_valid_until',
	)
	search_fields = ('base_url', 'token')


@admin.register(EmailConfiguration)
class EmailConfigurationAdmin(admin.ModelAdmin):
	list_display = (
		'smtp_host',
		'smtp_port',
		'incoming_protocol',
		'incoming_host',
		'updated_at',
		'updated_by',
	)
	readonly_fields = ('updated_at', 'updated_by')
	search_fields = ('smtp_host', 'incoming_host', 'default_from_email', 'smtp_username', 'incoming_username')

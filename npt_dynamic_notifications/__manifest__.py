{
    "name": "Dynamic Notifications",
    "summary": "Configurable event-based chatter and WhatsApp notifications",
    "version": "1.2.0",
    "category": "Tools",
    "license": "LGPL-3",
    "author": "Custom",
    # Requires stock for operation types; base/mail for messaging.
    "depends": ["base", "mail", "stock", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/notification_channel_data.xml",
        "data/init_user_channels.xml",
        "views/mail_notification_layouts.xml",
        "views/notification_settings_import_wizard_views.xml",
        "views/notification_config_views.xml",
        "views/res_users_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "dynamic_notifications/static/src/js/notification_config_export_defaults.js",
        ],
    },
    "application": False,
    "installable": True,
}

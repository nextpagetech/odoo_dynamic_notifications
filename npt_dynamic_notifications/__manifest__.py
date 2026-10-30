{
    "name": "Dynamic Notifications",
    "summary": "Configurable event-based alerts for email, inbox and optional WhatsApp",
    "version": "18.0.1.2.0",
    "category": "Tools",
    "license": "LGPL-3",
    "author": "Next Page Technologies Pvt Ltd",
    "website": "https://nextpagetechnologies.com",
    "support": "hello@nextpagetechnologies.com",
    "price": 10.0,
    "currency": "USD",
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
            "npt_dynamic_notifications/static/src/js/notification_config_export_defaults.js",
        ],
    },
    "images": [
        "static/description/banner.png",
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
}

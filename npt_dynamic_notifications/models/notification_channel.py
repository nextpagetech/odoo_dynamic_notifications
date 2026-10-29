from odoo import api, fields, models


class DynamicNotificationChannel(models.Model):
    _name = "dynamic.notification.channel"
    _description = "Dynamic Notification Channel"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Selection(
        [
            ("email", "Email"),
            ("inbox", "Inbox"),
            ("whatsapp", "WhatsApp"),
        ],
        required=True,
    )
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        (
            "dynamic_notification_channel_code_uniq",
            "unique(code)",
            "Notification channel code must be unique.",
        ),
    ]

    @api.model
    def _sync_default_channel_names(self):
        defaults = {
            "email": "Handle by Emails",
            "inbox": "Handle by App Notification",
            "whatsapp": "Handle by WhatsApp",
        }
        for channel in self.sudo().search([]):
            target_name = defaults.get(channel.code)
            if target_name and channel.name != target_name:
                channel.write({"name": target_name})

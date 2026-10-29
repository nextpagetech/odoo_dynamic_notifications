from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    notification_type = fields.Selection(
        selection_add=[("whatsapp", "Handle by WhatsApp")],
        ondelete={"whatsapp": "set default"},
    )

    dynamic_notification_channel_ids = fields.Many2many(
        "dynamic.notification.channel",
        "res_users_dynamic_notification_channel_rel",
        "user_id",
        "channel_id",
        string="Notification Channels",
        default=lambda self: self._default_dynamic_notification_channel_ids(),
        help="Dynamic notification delivery channels for this user.",
    )

    @api.model
    def _default_dynamic_notification_channel_ids(self):
        email_channel = self.env.ref(
            "npt_dynamic_notifications.dynamic_notification_channel_email",
            raise_if_not_found=False,
        )
        return [(6, 0, email_channel.ids)] if email_channel else []

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ["dynamic_notification_channel_ids"]

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ["dynamic_notification_channel_ids"]

    @api.model
    def _channels_from_notification_type(self, notification_type):
        mapping = {
            "email": {"email"},
            "inbox": {"inbox"},
            "email_inbox": {"email", "inbox"},
            "whatsapp": {"whatsapp"},
        }
        return set(mapping.get(notification_type or "", {"email"}))

    def _get_dynamic_notification_channels(self):
        self.ensure_one()
        selected_codes = set(self.dynamic_notification_channel_ids.mapped("code"))
        if selected_codes:
            return selected_codes
        return {"email"}

    @api.model
    def _init_dynamic_notification_channels(self):
        channel_model = self.env["dynamic.notification.channel"].sudo()
        channel_by_code = {ch.code: ch.id for ch in channel_model.search([])}
        users = self.with_context(active_test=False).sudo().search(
            [("dynamic_notification_channel_ids", "=", False)]
        )
        for user in users:
            channel_codes = self._channels_from_notification_type(user.notification_type)
            channel_ids = [channel_by_code[code] for code in channel_codes if code in channel_by_code]
            if channel_ids:
                user.write({"dynamic_notification_channel_ids": [(6, 0, channel_ids)]})

    def _notification_type_values(self):
        selection = self._fields["notification_type"]._description_selection(self.env)
        return {value for value, _label in selection}

    def _sync_notification_type_from_dynamic_channels(self):
        available_values = self._notification_type_values()
        for user in self:
            selected_codes = set(user.dynamic_notification_channel_ids.mapped("code"))
            if not selected_codes:
                continue

            target_value = False
            if "email" in selected_codes and "inbox" in selected_codes:
                target_value = "email_inbox" if "email_inbox" in available_values else "email"
            elif "email" in selected_codes:
                target_value = "email"
            elif "inbox" in selected_codes:
                target_value = "inbox"
            elif "whatsapp" in selected_codes and "whatsapp" in available_values:
                target_value = "whatsapp"

            if target_value and user.notification_type != target_value:
                user.with_context(skip_dynamic_channel_sync=True).write(
                    {"notification_type": target_value}
                )

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        if not self.env.context.get("skip_dynamic_channel_sync"):
            users.filtered("dynamic_notification_channel_ids")._sync_notification_type_from_dynamic_channels()
        return users

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("skip_dynamic_channel_sync") and "dynamic_notification_channel_ids" in vals:
            self._sync_notification_type_from_dynamic_channels()
        return result

    @api.model
    def _resync_all_notification_types_from_dynamic_channels(self):
        users = self.with_context(active_test=False).sudo().search(
            [("dynamic_notification_channel_ids", "!=", False)]
        )
        users._sync_notification_type_from_dynamic_channels()

    @api.model
    def _normalize_notification_type_without_notify_email_inbox(self):
        if "email_inbox" in self._notification_type_values():
            return

        users = self.with_context(active_test=False).sudo().search(
            [("notification_type", "=", "email_inbox")]
        )
        if users:
            users.with_context(skip_dynamic_channel_sync=True).write({"notification_type": "email"})

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _notify_thread(self, message, msg_vals=False, **kwargs):
        recipients_data = super()._notify_thread(message, msg_vals=msg_vals, **kwargs)
        self = self._fallback_lang()
        if self.env["ir.module.module"].sudo().search_count(
            [("name", "=", "notify_email_inbox"), ("state", "=", "installed")]
        ):
            return recipients_data

        inbox_recipients = []
        email_recipients = []
        for partner_data in recipients_data:
            if partner_data.get("notif") == "email_inbox":
                inbox_partner = partner_data.copy()
                inbox_partner["notif"] = "inbox"
                inbox_recipients.append(inbox_partner)

                email_partner = partner_data.copy()
                email_partner["notif"] = "email"
                email_recipients.append(email_partner)

        if inbox_recipients:
            self._notify_thread_by_inbox(message, inbox_recipients, msg_vals=msg_vals, **kwargs)
        if email_recipients:
            try:
                self._notify_thread_by_email(message.copy(), email_recipients, msg_vals=msg_vals, **kwargs)
            except Exception:
                _logger.exception("Dynamic notification: failed email_inbox email fan-out.")

        return recipients_data

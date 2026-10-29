import base64
import json

from odoo import _, fields, models
from odoo.exceptions import UserError


class DynamicNotificationSettingsImportWizard(models.TransientModel):
    _name = "dynamic.notification.settings.import.wizard"
    _description = "Import Dynamic Notification Settings"

    file_data = fields.Binary(string="Settings File", required=True)
    file_name = fields.Char(string="Filename")
    replace_existing = fields.Boolean(
        string="Replace Existing Rules",
        default=False,
        help="If enabled, all existing dynamic notification rules are removed before import.",
    )
    update_existing = fields.Boolean(
        string="Update Matching Rules",
        default=True,
        help="When enabled, matching rules are updated instead of creating duplicates.",
    )
    result_log = fields.Text(string="Result", readonly=True)

    def action_import(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please upload a JSON settings file."))

        try:
            raw = base64.b64decode(self.file_data)
        except Exception as exc:
            raise UserError(_("Unable to decode uploaded file: %s") % exc) from exc

        if not raw:
            raise UserError(_("The uploaded file is empty."))

        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise UserError(_("Invalid JSON file: %s") % exc) from exc

        summary = self.env["notification.config"].sudo().import_settings_payload(
            payload=payload,
            replace_existing=self.replace_existing,
            update_existing=self.update_existing and not self.replace_existing,
        )

        log_lines = [
            _("Created: %s") % summary.get("created", 0),
            _("Updated: %s") % summary.get("updated", 0),
            _("Skipped: %s") % summary.get("skipped", 0),
        ]
        warnings = summary.get("warnings") or []
        if warnings:
            log_lines.append("")
            log_lines.append(_("Warnings:"))
            log_lines.extend("- %s" % warning for warning in warnings)
        self.result_log = "\n".join(log_lines)

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

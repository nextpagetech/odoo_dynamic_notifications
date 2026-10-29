import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class BaseModelExtension(models.AbstractModel):
    _inherit = "base"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            self.env["notification.config"].process_event(self._name, records, "create")
        except Exception:
            _logger.exception("Dynamic notification (create) failed for %s", self._name)
        # Also evaluate state-change rules for fields present in each create payload
        try:
            for rec, vals in zip(records, vals_list):
                self.env["notification.config"].process_event(self._name, rec, "state_change", vals=vals)
        except Exception:
            _logger.exception("Dynamic notification (state_change on create) failed for %s", self._name)
        return records

    def write(self, vals):
        res = super().write(vals)
        try:
            self.env["notification.config"].process_event(self._name, self, "write", vals=vals)
        except Exception:
            _logger.exception("Dynamic notification (write) failed for %s", self._name)
        try:
            self.env["notification.config"].process_event(self._name, self, "state_change", vals=vals)
        except Exception:
            _logger.exception("Dynamic notification (state_change) failed for %s", self._name)
        return res

    def _notify_custom_event(self, event_type="custom", vals=None):
        """Helper to trigger custom events from buttons/overrides."""
        vals = vals or {}
        try:
            self.env["notification.config"].process_event(self._name, self, event_type, vals=vals)
        except Exception:
            _logger.exception("Dynamic notification (custom %s) failed for %s", event_type, self._name)
        return True

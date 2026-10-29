import base64
import json
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext, html_escape, sql
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class NotificationConfig(models.Model):
    _name = "notification.config"
    _description = "Dynamic Notification Rule"
    _SETTINGS_EXPORT_VERSION = 1

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        required=True,
        ondelete="cascade",
    )
    event_type = fields.Selection(
        [
            ("create", "Create"),
            ("write", "Write"),
            ("state_change", "State Change"),
            ("custom", "Custom"),
        ],
        required=True,
        default="write",
    )
    apply_to_children = fields.Boolean(
        string="Apply to Inherited Models",
        help="If enabled, models that delegate/extend this model via _inherits or _inherit can also trigger this rule.",
        default=False,
    )
    field_name = fields.Char(
        string="Field (for State Change)",
        help="Only used for state_change events; if the field is not among changed values, the rule is skipped.",
    )
    domain = fields.Text(
        help="Optional domain to select which records trigger this rule. "
        "Use the same syntax as on record rules, e.g. [('state', '=', 'done')]."
    )
    recipient_type = fields.Selection(
        [
            ("fixed_partners", "Fixed Partners"),
            ("record_user", "Record User"),
            ("record_field_partner", "Partner from Record Field"),
            ("group_users", "Users from Groups"),
        ],
        required=True,
        default="record_user",
    )
    partner_ids = fields.Many2many(
        "res.partner",
        string="Partners",
        domain=[("user_ids", "!=", False), ("user_ids.share", "=", False)],
    )
    group_ids = fields.Many2many("res.groups", string="Groups")
    record_field_name = fields.Char(
        string="Partner/User Field",
        help="Field on the record that points to a partner or user (e.g., partner_id, user_id, salesperson_id).",
    )
    operation_type_ids = fields.Many2many(
        "stock.picking.type",
        string="Operation Types",
        help="Optional filter: only trigger when the record is linked to these operation types (picking_type_id).",
    )
    subject_template = fields.Char(
        string="Subject Template",
        required=True,
        default="",
        help="Python str.format template. Available keys: object (record), user (current user), event (event type).",
    )
    message_template = fields.Html(
        string="Message Template",
        required=True,
        sanitize=False,
        help="Python str.format template. Available keys: object (record), user (current user), event (event type).",
    )

    @api.model
    def _evaluate_domain(self, model_name, records, domain_text):
        """Safely evaluate and filter by domain text; return a recordset."""
        if not domain_text:
            return records
        try:
            dom = safe_eval(domain_text, {})
            return records.filtered_domain(dom)
        except Exception as exc:
            _logger.warning("Dynamic notification: invalid domain on %s: %s", model_name, exc)
            return records.browse()

    def _get_recipients(self, record):
        """Return res.partner recordset for this config and record."""
        self.ensure_one()
        partners = self.env["res.partner"]
        if self.recipient_type == "fixed_partners":
            partners = self.partner_ids
        elif self.recipient_type == "record_user":
            user = getattr(record, "user_id", False)
            partners = user.partner_id if user else partners
        elif self.recipient_type == "record_field_partner":
            field_name = (self.record_field_name or "").strip()
            if field_name:
                target = getattr(record, field_name, False)
                if target and target._name == "res.users":
                    partners = target.partner_id
                elif target and target._name == "res.partner":
                    partners = target
        elif self.recipient_type == "group_users":
            partners = self.group_ids.mapped("users").mapped("partner_id")
        return partners.filtered(lambda p: p.id)

    def _render_message(self, record, event_type):
        self.ensure_one()
        template = self.message_template or ""
        try:
            body = template.format(object=record, user=self.env.user, event=event_type)
        except Exception as exc:
            _logger.warning("Dynamic notification: template error on %s: %s", self.display_name, exc)
            body = template
        if template and "<" in template and ">" in template:
            return body
        body = html_escape(body or "")
        body = body.replace("\r\n", "\n").replace("\r", "\n")
        return body.replace("\n", "<br/>")

    def _render_subject(self, record, event_type):
        self.ensure_one()
        template = self.subject_template or ""
        try:
            subject = template.format(object=record, user=self.env.user, event=event_type)
        except Exception as exc:
            _logger.warning("Dynamic notification: subject template error on %s: %s", self.display_name, exc)
            subject = template
        return subject

    def _split_recipients_by_channel(self, recipients):
        """Split recipients based on linked users notification preference."""
        mail_partners = self.env["res.partner"]
        whatsapp_partners = self.env["res.partner"]
        for partner in recipients:
            users = partner.user_ids.filtered(lambda u: u.active and not u.share)
            if not users:
                mail_partners |= partner
                continue

            partner_channels = set()
            for user in users:
                if hasattr(user, "_get_dynamic_notification_channels"):
                    partner_channels |= user._get_dynamic_notification_channels()
                    continue
                partner_channels.add("email")

            if {"email", "inbox"} & partner_channels:
                mail_partners |= partner
            if "whatsapp" in partner_channels:
                whatsapp_partners |= partner
            if not partner_channels:
                mail_partners |= partner

        return mail_partners, whatsapp_partners

    def _compose_whatsapp_message(self, subject, body_html):
        """Build plain text body suitable for WhatsApp."""
        clean_subject = (subject or "").strip()
        clean_body = html2plaintext(body_html or "", include_references=False).strip()
        if clean_subject and clean_body:
            return f"{clean_subject}\n\n{clean_body}"
        return clean_subject or clean_body

    def _is_success_whatsapp_response(self, response):
        return bool(
            isinstance(response, dict)
            and not response.get("error")
            and response.get("messages")
        )

    def _extract_whatsapp_error(self, response):
        if not isinstance(response, dict):
            return "Unknown API error."
        error = response.get("error")
        if isinstance(error, dict):
            return error.get("message") or str(error)
        if error:
            return str(error)
        return "Unknown API error."

    def _extract_whatsapp_message_id(self, response):
        if not isinstance(response, dict):
            return False
        messages = response.get("messages") or []
        if messages and isinstance(messages[0], dict):
            return messages[0].get("id")
        return False

    @api.model
    def _field_selection_values(self, field_name):
        selection = self._fields[field_name]._description_selection(self.env)
        return {value for value, _label in selection}

    @api.model
    def _build_rule_signature(
        self,
        *,
        name,
        model,
        event_type,
        recipient_type,
        field_name="",
        record_field_name="",
    ):
        parts = [
            (name or "").strip().lower(),
            (model or "").strip().lower(),
            (event_type or "").strip().lower(),
            (recipient_type or "").strip().lower(),
            (field_name or "").strip().lower(),
            (record_field_name or "").strip().lower(),
        ]
        return "|".join(parts)

    @api.model
    def _serialize_partner_refs(self, partners):
        external_ids = partners.get_external_id() if partners else {}
        refs = []
        for partner in partners.sorted(key=lambda p: p.id):
            refs.append(
                {
                    "xmlid": external_ids.get(partner.id) or False,
                    "email": partner.email or False,
                    "name": partner.name or False,
                }
            )
        return refs

    @api.model
    def _serialize_group_refs(self, groups):
        external_ids = groups.get_external_id() if groups else {}
        refs = []
        for group in groups.sorted(key=lambda g: g.id):
            refs.append(
                {
                    "xmlid": external_ids.get(group.id) or False,
                    "name": group.name or False,
                }
            )
        return refs

    @api.model
    def _serialize_operation_type_refs(self, operation_types):
        external_ids = operation_types.get_external_id() if operation_types else {}
        refs = []
        for operation_type in operation_types.sorted(key=lambda op: op.id):
            refs.append(
                {
                    "xmlid": external_ids.get(operation_type.id) or False,
                    "name": operation_type.name or False,
                    "code": operation_type.code or False,
                    "warehouse_code": operation_type.warehouse_id.code or False,
                }
            )
        return refs

    @api.model
    def _serialize_rule_for_export(self, config):
        return {
            "name": config.name,
            "active": config.active,
            "model": config.model_id.model,
            "event_type": config.event_type,
            "apply_to_children": config.apply_to_children,
            "field_name": config.field_name or False,
            "domain": config.domain or False,
            "recipient_type": config.recipient_type,
            "record_field_name": config.record_field_name or False,
            "subject_template": config.subject_template or "",
            "message_template": config.message_template or "",
            "partner_refs": self._serialize_partner_refs(config.partner_ids),
            "group_refs": self._serialize_group_refs(config.group_ids),
            "operation_type_refs": self._serialize_operation_type_refs(config.operation_type_ids),
        }

    @api.model
    def _get_configs_for_export(self, include_inactive=True, config_ids=None):
        if config_ids:
            configs = self.sudo().browse(config_ids).exists().sorted(key=lambda c: c.id)
            if not include_inactive:
                configs = configs.filtered("active")
            return configs

        domain = []
        if not include_inactive:
            domain.append(("active", "=", True))
        return self.sudo().search(domain, order="id")

    @api.model
    def export_settings_payload(self, include_inactive=True, config_ids=None):
        configs = self._get_configs_for_export(
            include_inactive=include_inactive,
            config_ids=config_ids,
        )
        return {
            "meta": {
                "module": "npt_dynamic_notifications",
                "format_version": self._SETTINGS_EXPORT_VERSION,
                "exported_at": fields.Datetime.to_string(fields.Datetime.now()),
                "exported_by": self.env.user.login,
                "rule_count": len(configs),
            },
            "notification_rules": [self._serialize_rule_for_export(config) for config in configs],
        }

    def action_export_settings(self):
        params = self.env.context.get("params") or {}
        candidate_lists = []
        for candidate in (
            self.ids,
            self.env.context.get("active_ids"),
            params.get("selected_ids"),
            params.get("ids"),
        ):
            if isinstance(candidate, list):
                cleaned = [rid for rid in candidate if isinstance(rid, int) and rid > 0]
                if cleaned:
                    candidate_lists.append(cleaned)

        if candidate_lists:
            selected_ids = min(candidate_lists, key=len)
        else:
            raise UserError(_("Please select at least one notification rule to export."))

        payload = self.export_settings_payload(include_inactive=True, config_ids=selected_ids)
        payload = {"notification_rules": payload.get("notification_rules", [])}
        content = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True).encode("utf-8")
        filename = "dynamic_notification_settings_%s.json" % fields.Datetime.now().strftime("%Y%m%d_%H%M%S")
        attachment_res_id = self[:1].id or (selected_ids[0] if selected_ids else 0)
        attachment = self.env["ir.attachment"].sudo().create(
            {
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(content),
                "res_model": self._name,
                "res_id": attachment_res_id,
                "mimetype": "application/json",
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    @api.model
    def _extract_refs(self, data, structured_key, xmlid_key):
        refs = data.get(structured_key)
        if isinstance(refs, list):
            if all(isinstance(item, dict) for item in refs):
                return refs
            if all(isinstance(item, str) for item in refs):
                return [{"xmlid": item} for item in refs if item]

        xmlids = data.get(xmlid_key)
        if isinstance(xmlids, list):
            return [{"xmlid": item} for item in xmlids if isinstance(item, str) and item]
        return []

    @api.model
    def _resolve_partner_refs(self, refs):
        partner_model = self.env["res.partner"].with_context(active_test=False)
        partners = partner_model.browse()
        unresolved = []
        for ref in refs:
            if not isinstance(ref, dict):
                unresolved.append(ref)
                continue

            partner = partner_model.browse()
            xmlid = (ref.get("xmlid") or "").strip()
            if xmlid:
                partner = self.env.ref(xmlid, raise_if_not_found=False)
                if not partner or partner._name != "res.partner":
                    partner = partner_model.browse()

            email = (ref.get("email") or "").strip()
            if not partner and email:
                partner = partner_model.search([("email", "=", email)], limit=1)

            name = (ref.get("name") or "").strip()
            if not partner and name:
                partner = partner_model.search([("name", "=", name)], limit=1)

            if partner:
                partners |= partner
            else:
                unresolved.append(ref)
        return partners, unresolved

    @api.model
    def _resolve_group_refs(self, refs):
        group_model = self.env["res.groups"]
        groups = group_model.browse()
        unresolved = []
        for ref in refs:
            if not isinstance(ref, dict):
                unresolved.append(ref)
                continue

            group = group_model.browse()
            xmlid = (ref.get("xmlid") or "").strip()
            if xmlid:
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if not group or group._name != "res.groups":
                    group = group_model.browse()

            name = (ref.get("name") or "").strip()
            if not group and name:
                group = group_model.search([("name", "=", name)], limit=1)

            if group:
                groups |= group
            else:
                unresolved.append(ref)
        return groups, unresolved

    @api.model
    def _resolve_operation_type_refs(self, refs):
        operation_type_model = self.env["stock.picking.type"].with_context(active_test=False)
        operation_types = operation_type_model.browse()
        unresolved = []
        for ref in refs:
            if not isinstance(ref, dict):
                unresolved.append(ref)
                continue

            operation_type = operation_type_model.browse()
            xmlid = (ref.get("xmlid") or "").strip()
            if xmlid:
                operation_type = self.env.ref(xmlid, raise_if_not_found=False)
                if not operation_type or operation_type._name != "stock.picking.type":
                    operation_type = operation_type_model.browse()

            if not operation_type:
                domain = []
                code = (ref.get("code") or "").strip()
                name = (ref.get("name") or "").strip()
                warehouse_code = (ref.get("warehouse_code") or "").strip()
                if code:
                    domain.append(("code", "=", code))
                if name:
                    domain.append(("name", "=", name))
                if warehouse_code:
                    domain.append(("warehouse_id.code", "=", warehouse_code))
                if domain:
                    operation_type = operation_type_model.search(domain, limit=1)

            if operation_type:
                operation_types |= operation_type
            else:
                unresolved.append(ref)
        return operation_types, unresolved

    @api.model
    def import_settings_payload(self, payload, replace_existing=False, update_existing=True):
        if not isinstance(payload, dict):
            raise UserError(_("Invalid settings file format."))

        rules_data = payload.get("notification_rules")
        if not isinstance(rules_data, list):
            raise UserError(_("Invalid settings file: 'notification_rules' must be a list."))

        config_model = self.sudo()
        if replace_existing:
            config_model.search([]).unlink()

        event_values = self._field_selection_values("event_type")
        recipient_values = self._field_selection_values("recipient_type")
        ir_model = self.env["ir.model"]
        existing_by_signature = {}

        if update_existing and not replace_existing:
            for config in config_model.search([]):
                signature = self._build_rule_signature(
                    name=config.name,
                    model=config.model_id.model,
                    event_type=config.event_type,
                    recipient_type=config.recipient_type,
                    field_name=config.field_name,
                    record_field_name=config.record_field_name,
                )
                existing_by_signature.setdefault(signature, config)

        summary = {"created": 0, "updated": 0, "skipped": 0, "warnings": []}

        for index, rule_data in enumerate(rules_data, start=1):
            if not isinstance(rule_data, dict):
                summary["skipped"] += 1
                summary["warnings"].append(_("Rule %s skipped: invalid object format.") % index)
                continue

            model_name = (rule_data.get("model") or "").strip()
            if not model_name:
                summary["skipped"] += 1
                summary["warnings"].append(_("Rule %s skipped: model is missing.") % index)
                continue

            try:
                model_ref = ir_model._get(model_name)
            except Exception:
                model_ref = False
            if not model_ref:
                summary["skipped"] += 1
                summary["warnings"].append(
                    _("Rule '%s' skipped: model '%s' not found.") % (rule_data.get("name") or index, model_name)
                )
                continue

            event_type = (rule_data.get("event_type") or "write").strip()
            if event_type not in event_values:
                summary["warnings"].append(
                    _("Rule '%s': invalid event type '%s'. Using 'write'.")
                    % (rule_data.get("name") or index, event_type)
                )
                event_type = "write"

            recipient_type = (rule_data.get("recipient_type") or "record_user").strip()
            if recipient_type not in recipient_values:
                summary["warnings"].append(
                    _("Rule '%s': invalid recipient type '%s'. Using 'record_user'.")
                    % (rule_data.get("name") or index, recipient_type)
                )
                recipient_type = "record_user"

            name = (rule_data.get("name") or "").strip() or (_("Imported Rule %s") % index)
            partner_refs = self._extract_refs(rule_data, "partner_refs", "partner_xmlids")
            group_refs = self._extract_refs(rule_data, "group_refs", "group_xmlids")
            operation_type_refs = self._extract_refs(
                rule_data, "operation_type_refs", "operation_type_xmlids"
            )

            partners, unresolved_partners = self._resolve_partner_refs(partner_refs)
            groups, unresolved_groups = self._resolve_group_refs(group_refs)
            operation_types, unresolved_operation_types = self._resolve_operation_type_refs(operation_type_refs)

            vals = {
                "name": name,
                "active": bool(rule_data.get("active", True)),
                "model_id": model_ref.id,
                "event_type": event_type,
                "apply_to_children": bool(rule_data.get("apply_to_children", False)),
                "field_name": (rule_data.get("field_name") or "").strip() or False,
                "domain": (rule_data.get("domain") or "").strip() or False,
                "recipient_type": recipient_type,
                "record_field_name": (rule_data.get("record_field_name") or "").strip() or False,
                "subject_template": (rule_data.get("subject_template") or ""),
                "message_template": (rule_data.get("message_template") or ""),
                "partner_ids": [(6, 0, partners.ids)],
                "group_ids": [(6, 0, groups.ids)],
                "operation_type_ids": [(6, 0, operation_types.ids)],
            }

            signature = self._build_rule_signature(
                name=name,
                model=model_name,
                event_type=event_type,
                recipient_type=recipient_type,
                field_name=vals["field_name"],
                record_field_name=vals["record_field_name"],
            )
            target_config = config_model.browse()
            if update_existing and not replace_existing:
                target_config = existing_by_signature.get(signature, config_model.browse())

            try:
                if target_config:
                    target_config.write(vals)
                    summary["updated"] += 1
                else:
                    created = config_model.create(vals)
                    summary["created"] += 1
                    if update_existing and not replace_existing:
                        existing_by_signature[signature] = created
            except Exception as exc:
                summary["skipped"] += 1
                summary["warnings"].append(
                    _("Rule '%s' skipped due to error: %s") % (name, str(exc))
                )
                continue

            if unresolved_partners:
                summary["warnings"].append(
                    _("Rule '%s': %s partner(s) could not be resolved.")
                    % (name, len(unresolved_partners))
                )
            if unresolved_groups:
                summary["warnings"].append(
                    _("Rule '%s': %s group(s) could not be resolved.")
                    % (name, len(unresolved_groups))
                )
            if unresolved_operation_types:
                summary["warnings"].append(
                    _("Rule '%s': %s operation type(s) could not be resolved.")
                    % (name, len(unresolved_operation_types))
                )

        return summary
    def _is_whatsapp_module_installed(self):
        return bool(
            self.env["ir.module.module"]
            .sudo()
            .search_count([("name", "=", "odoo_whatsapp_meta"), ("state", "=", "installed")])
        )

    def _normalize_whatsapp_phone(self, number, default_country_code="91"):
        if not number:
            return False

        normalized = str(number).strip()
        normalized = re.sub(r"\D", "", normalized)
        if not normalized:
            return False

        country_code = re.sub(r"\D", "", str(default_country_code or "91")) or "91"

        if normalized.startswith(country_code) and len(normalized) >= (len(country_code) + 10):
            return normalized

        if normalized.startswith("0"):
            normalized = normalized[1:]

        if len(normalized) == 10:
            return f"{country_code}{normalized}"

        return normalized

    def _send_whatsapp_notifications(self, record, partners, subject, body_html):
        """Send WhatsApp messages immediately for routed recipients."""
        if not partners:
            return
        if not self._is_whatsapp_module_installed():
            return
        if "whatsapp.message" not in self.env or "whatsapp.api.service" not in self.env:
            _logger.warning(
                "Dynamic notification: recipient prefers WhatsApp but model "
                "'whatsapp.message' or service 'whatsapp.api.service' is unavailable. "
                "Install odoo_whatsapp_meta."
            )
            return

        text = self._compose_whatsapp_message(subject, body_html)
        if not text:
            return

        message_model = self.env["whatsapp.message"].sudo()
        api_service = self.env["whatsapp.api.service"].sudo()
        partner_model = self.env["res.partner"].sudo()
        for partner in partners:
            raw_phone = getattr(partner, "whatsapp_number", False) or partner.mobile or partner.phone
            phone = self._normalize_whatsapp_phone(raw_phone)
            if not phone:
                _logger.warning(
                    "Dynamic notification: missing WhatsApp number/mobile for partner %s (%s)",
                    partner.display_name,
                    partner.id,
                )
                continue

            vals = {
                "partner_id": partner.id,
                "phone": phone,
                "message": text,
                "state": "draft",
                "direction": "outbound",
            }
            if record._name == "sale.order":
                vals["sale_order_id"] = record.id

            try:
                wa_message = message_model.create(vals)
                session_partner = partner.commercial_partner_id or partner
                can_send_text = bool(
                    hasattr(session_partner, "can_send_whatsapp")
                    and session_partner.can_send_whatsapp(message_type="text")
                )

                if not can_send_text and hasattr(partner_model, "_find_whatsapp_partner"):
                    phone_partner = partner_model._find_whatsapp_partner(phone)
                    phone_session_partner = (
                        phone_partner.commercial_partner_id or phone_partner
                        if phone_partner
                        else self.env["res.partner"]
                    )
                    can_send_text = bool(
                        phone_session_partner
                        and hasattr(phone_session_partner, "can_send_whatsapp")
                        and phone_session_partner.can_send_whatsapp(message_type="text")
                    )
                if not can_send_text:
                    error_message = "User not in 24h session window. Send an approved template."
                    wa_message.write({"state": "failed"})
                    wa_message._append_response(
                        {
                            "status": "failed",
                            "error": error_message,
                            "response": {"blocked": True},
                        }
                    )
                    _logger.warning(
                        "Dynamic notification: WhatsApp blocked for partner %s (%s): %s",
                        partner.display_name,
                        partner.id,
                        error_message,
                    )
                    continue

                response = api_service.send_text(phone=phone, message=text)
                if self._is_success_whatsapp_response(response):
                    wa_message.write(
                        {
                            "state": "sent",
                            "meta_message_id": self._extract_whatsapp_message_id(response)
                            or wa_message.meta_message_id,
                        }
                    )
                    wa_message._append_response(
                        {
                            "status": "sent",
                            "response": response,
                        }
                    )
                else:
                    error_message = self._extract_whatsapp_error(response)
                    wa_message.write({"state": "failed"})
                    wa_message._append_response(
                        {
                            "status": "failed",
                            "error": error_message,
                            "response": response,
                        }
                    )
                    _logger.warning(
                        "Dynamic notification: WhatsApp send failed for partner %s (%s): %s",
                        partner.display_name,
                        partner.id,
                        error_message,
                    )
            except Exception as exc:
                _logger.warning(
                    "Dynamic notification: failed to send WhatsApp for partner %s (%s): %s",
                    partner.display_name,
                    partner.id,
                    exc,
                )

    @api.model
    def process_event(self, model_name, records, event_type, vals=None):
        """Main dispatcher: process configs for given model/event."""
        if not records:
            return
        if self.env.context.get("module_install") or self.env.context.get("module_uninstall"):
            return
        if not sql.table_exists(self.env.cr, self._table):
            return
        try:
            model_ref = self.env["ir.model"]._get(model_name)
        except Exception:
            return

        # Always evaluate configs with sudo so access rules on notification.config
        # do not block runtime chatter hooks for regular users.
        self_sudo = self.sudo()
        configs = self_sudo.search(
            [
                ("active", "=", True),
                ("event_type", "=", event_type),
                "|",
                ("model_id", "=", model_ref.id),
                ("apply_to_children", "=", True),
            ]
        )
        if not configs:
            return
        whatsapp_enabled = self_sudo._is_whatsapp_module_installed()

        # Normalize records to a recordset
        if not isinstance(records, models.Model):
            return

        vals = vals or {}
        model_obj = self.env[model_name]
        # Collect inheritance chain for child handling
        inheritance_models = set()
        try:
            inheritance_models.add(model_obj._name)
            parent_inherits = model_obj._inherits if hasattr(model_obj, "_inherits") else {}
            for parent in parent_inherits.keys():
                inheritance_models.add(parent)
            raw_inherit = getattr(model_obj, "_inherit", None)
            if raw_inherit:
                if isinstance(raw_inherit, (list, tuple, set)):
                    inheritance_models.update(raw_inherit)
                elif isinstance(raw_inherit, str):
                    inheritance_models.add(raw_inherit)
        except Exception:
            pass

        for config in configs:
            # Skip configs that rely on parent match when child support is enabled
            if config.model_id.model != model_name and not (
                config.apply_to_children and config.model_id.model in inheritance_models
            ):
                continue
            if event_type == "state_change" and config.field_name:
                field = config.field_name
                if isinstance(vals, dict):
                    if field not in vals:
                        continue
                else:
                    # if vals not a dict, skip field gate
                    pass

            candidates = config._evaluate_domain(model_name, records, config.domain)
            if not candidates:
                continue
            # Filter by operation type if configured and the record exposes picking_type_id
            if config.operation_type_ids:
                candidates = candidates.filtered(
                    lambda rec: hasattr(rec, "picking_type_id")
                    and rec.picking_type_id
                    and rec.picking_type_id.id in config.operation_type_ids.ids
                )
            if not candidates:
                continue
            for record in candidates:
                recipients = config._get_recipients(record)
                subject = config._render_subject(record, event_type)
                body = config._render_message(record, event_type)
                email_recipients, whatsapp_recipients = config._split_recipients_by_channel(recipients)

                if email_recipients:
                    try:
                        record.message_post(
                            body=body,
                            subject=subject,
                            partner_ids=email_recipients.ids,
                            subtype_xmlid="mail.mt_comment",
                            email_layout_xmlid="npt_dynamic_notifications.mail_notification_layout_plain",
                        )
                    except Exception as exc:
                        _logger.warning(
                            "Dynamic notification: failed to post on %s (%s): %s",
                            record._name,
                            record.id,
                            exc,
                        )

                if whatsapp_enabled:
                    config._send_whatsapp_notifications(
                        record=record,
                        partners=whatsapp_recipients,
                        subject=subject,
                        body_html=body,
                    )

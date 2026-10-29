/** @odoo-module **/

import { unique } from "@web/core/utils/arrays";
import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";

const EXPORT_DEFAULT_FIELDS = [
    "model_id",
    "name",
    "recipient_type",
    "subject_template",
    "domain",
    "display_name",
    "message_template",
];

function isNotificationConfig(controller) {
    return controller?.model?.root?.resModel === "notification.config";
}

patch(ListController.prototype, {
    get defaultExportList() {
        const baseFields = super.defaultExportList || [];
        if (!isNotificationConfig(this)) {
            return baseFields;
        }

        const extraFields = EXPORT_DEFAULT_FIELDS.map((fieldName) => this.props.fields?.[fieldName])
            .filter((field) => field && field.exportable !== false);

        return unique([...baseFields, ...extraFields]);
    },
});

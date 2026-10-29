# Dynamic Notifications — Odoo 18

Technical module: `npt_dynamic_notifications`

Publisher: **Next Page Technologies Pvt Ltd**

## Overview

Dynamic Notifications provides configurable event-based notification rules for Odoo records. Administrators can choose the target model, event type, optional conditions, recipient strategy and message templates.

Supported rule events include:

- Create
- Write
- State Change
- Custom event helper

Supported recipient strategies include:

- Fixed internal partners
- Record user
- Partner or user from a record field
- Users from selected groups

Users can select supported dynamic notification channels. Email and inbox delivery use Odoo's mail framework. WhatsApp delivery is optional and activates only when the separate `odoo_whatsapp_meta` module is installed and its service models are available.

Additional features include:

- Optional Odoo domain filtering
- Optional inherited-model handling
- Optional stock operation type filtering
- Subject and HTML message templates
- JSON export of selected rules
- JSON import with replace/update options

## Compatibility

- Odoo 18.0
- Standard dependencies: `base`, `mail`, `stock`, `web`

## Publisher

Next Page Technologies Pvt Ltd  
https://nextpagetechnologies.com

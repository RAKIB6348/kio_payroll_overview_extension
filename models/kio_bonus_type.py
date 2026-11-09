from odoo import fields, models


class KioBonusType(models.Model):
    _name = "kio.bonus.type"
    _description = "Bonus Type"
    _order = "sequence, id"

    name = fields.Char(string="Bonus Type Name", required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        help="Leave empty to share this bonus type across companies.",
    )

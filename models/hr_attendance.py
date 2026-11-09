from odoo import api, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    def _kio_overtime_pairs(self):
        pairs = []
        for att in self:
            if att.employee_id and att.check_in:
                tz = self.env["kio.overtime"]._get_tz(att.employee_id)
                day = self.env["kio.overtime"]._local_date(att.check_in, tz)
                if day:
                    pairs.append((att.employee_id, day))
            # if checkout moved across days, also sync checkout day
            if att.employee_id and att.check_out:
                tz = self.env["kio.overtime"]._get_tz(att.employee_id)
                day = self.env["kio.overtime"]._local_date(att.check_out, tz)
                if day:
                    pairs.append((att.employee_id, day))
        return list({(e.id, d): (e, d) for e, d in pairs}.values())

    def _sync_kio_overtime(self):
        if "kio.overtime" not in self.env.registry.models:
            return
        pairs = self._kio_overtime_pairs()
        if pairs:
            self.env["kio.overtime"].sudo().with_context(
                tracking_disable=True, mail_notrack=True
            )._sync_employee_dates(pairs)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_kio_overtime()
        return records

    def write(self, vals):
        # capture old pairs (e.g. employee/date changed)
        old_pairs = self._kio_overtime_pairs()
        res = super().write(vals)
        self._sync_kio_overtime()
        if old_pairs and "kio.overtime" in self.env.registry.models:
            self.env["kio.overtime"].sudo().with_context(
                tracking_disable=True, mail_notrack=True
            )._sync_employee_dates(old_pairs)
        return res

    def unlink(self):
        old_pairs = self._kio_overtime_pairs()
        res = super().unlink()
        if old_pairs and "kio.overtime" in self.env.registry.models:
            self.env["kio.overtime"].sudo().with_context(
                tracking_disable=True, mail_notrack=True
            )._sync_employee_dates(old_pairs)
        return res

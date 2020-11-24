from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round, float_is_zero

# This module only changes string to force translate
# The original definition is done in mrp/models/mrp_abstract_workorder.py !

class MrpAbstractWorkorderLine(models.AbstractModel):
    _inherit = "mrp.abstract.workorder.line"                                            # Inherit class to make changes (on translate)

    qty_done = fields.Float()                                                           # Overdefinition to remember type class
    lot_id = fields.Many2one()                                                          # (those memebers are defined on "mrp.abstract.workorder.line")
    move_id = fields.Many2one()                                                         # No changes here. Those members are here to remember
    product_id = fields.Many2one()                                                      # type of fields and avoud no member linting errors

    def _get_final_lots(self):                                                          # Overdefinition to remember function definition
        raise NotImplementedError('Method _get_final_lots() undefined on %s' % self)

    def _get_production(self):
        raise NotImplementedError('Method _get_production() undefined on %s' % self)    # Overdefinition to remember function definition

    def _get_produced_lots(self):                                                       # Overdefinition to remember function definition
        return self.move_id in self._get_production().move_raw_ids and self._get_final_lots() and [(4, lot.id) for lot in self._get_final_lots()]

    def _update_move_lines(self):                                                       # Overdefinition to force translate to ES_CO
        """ update a move line to save the workorder line data"""
        self.ensure_one()
        if self.lot_id:
            move_lines = self.move_id.move_line_ids.filtered(lambda ml: ml.lot_id == self.lot_id and not ml.lot_produced_ids)
        else:
            move_lines = self.move_id.move_line_ids.filtered(lambda ml: not ml.lot_id and not ml.lot_produced_ids)
        if self.product_id.tracking != 'none' and not self.lot_id:
            raise UserError(_('Por favor, ingrese un número de lote para %s.' % self.product_id.display_name))  # The first translation is done here
        if self.lot_id and self.product_id.tracking == 'serial' and self.lot_id in self.move_id.move_line_ids.filtered(lambda ml: ml.qty_done).mapped('lot_id'):
            raise UserError(_('No puedes utilizar el mismo número de lote dos veces.'))                         # The second translation is done here
        for ml in move_lines:
            rounding = ml.product_uom_id.rounding
            if float_compare(self.qty_done, 0, precision_rounding=rounding) <= 0:
                break
            quantity_to_process = min(self.qty_done, ml.product_uom_qty - ml.qty_done)
            self.qty_done -= quantity_to_process

            new_quantity_done = (ml.qty_done + quantity_to_process)
            if float_compare(new_quantity_done, ml.product_uom_qty, precision_rounding=rounding) >= 0:
                ml.write({
                    'qty_done': new_quantity_done,
                    'lot_produced_ids': self._get_produced_lots(),
                })
            else:
                new_qty_reserved = ml.product_uom_qty - new_quantity_done
                default = {
                    'product_uom_qty': new_quantity_done,
                    'qty_done': new_quantity_done,
                    'lot_produced_ids': self._get_produced_lots(),
                }
                ml.copy(default=default)
                ml.with_context(bypass_reservation_update=True).write({
                    'product_uom_qty': new_qty_reserved,
                    'qty_done': 0
                })
import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from odoo.tools import float_compare, float_is_zero
from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG
from odoo.tools.float_utils import float_round, float_compare, float_is_zero


class Inventory(models.Model):
    _name = 'stock.inventory'
    _inherit = ['stock.inventory', 'mail.thread']


class Inventory(models.Model):
    _inherit = "stock.inventory"

    AJUSTES = [('conteo', 'Por conteo'), ('diferencia',
                                          'Por diferencia'), ('baja', 'Baja de inventario')]
    location_dest_id = fields.Many2one('stock.location', 'Location destiny', check_company=True,
                                       domain="[['scrap_location', '=', True]]",
                                       index=True)
    ajuste = fields.Selection(AJUSTES,
                              string='Tipo de ajuste',
                              readonly=True,
                              states={'draft': [('readonly', False)]},
                              help="Tipo de ajuste del inventario.")

    def action_open_inventory_lines(self):
        self.ensure_one()
        if self.ajuste == 'conteo':
            action = {
                'type': 'ir.actions.act_window',
                'views': [(self.env.ref('overwrite_inventory.stock_inventory_line_tree3').id, 'tree')],
                'view_mode': 'tree',
                'name': _('Por conteo'),
                'res_model': 'stock.inventory.line',
            }
        elif self.ajuste == 'baja':
            action = {
                'type': 'ir.actions.act_window',
                'views': [(self.env.ref('overwrite_inventory.stock_inventory_line_tree5').id, 'tree')],
                'view_mode': 'tree',
                'name': _('Baja de inventario'),
                'res_model': 'stock.inventory.line',
            }
        else:
            action = {
                'type': 'ir.actions.act_window',
                'views': [(self.env.ref('overwrite_inventory.stock_inventory_line_tree4').id, 'tree')],
                'view_mode': 'tree',
                'name': _('por Diferencia'),
                'res_model': 'stock.inventory.line',
            }
        context = {
            'default_is_editable': True,
            'default_inventory_id': self.id,
            'default_company_id': self.company_id.id,
        }
        # Define domains and context
        domain = [
            ('inventory_id', '=', self.id),
            ('location_id.usage', 'in', ['internal', 'transit'])
        ]
        if self.location_ids:
            context['default_location_id'] = self.location_ids[0].id
            if len(self.location_ids) == 1:
                if not self.location_ids[0].child_ids:
                    context['readonly_location_id'] = True

        if self.product_ids:
            if len(self.product_ids) == 1:
                context['default_product_id'] = self.product_ids[0].id

        action['context'] = context
        action['domain'] = domain
        return action

    def _get_inventory_lines_values(self):
        # TDE CLEANME: is sql really necessary ? I don't think so
        locations = self.env['stock.location']
        if self.location_ids:
            locations = self.env['stock.location'].search(
                [('id', 'child_of', self.location_ids.ids)])
        else:
            locations = self.env['stock.location'].search(
                [('company_id', '=', self.company_id.id), ('usage', 'in', ['internal', 'transit'])])
        domain = ' sq.location_id in %s AND pp.active'
        args = (tuple(locations.ids),)

        vals = []
        Product = self.env['product.product']
        # Empty recordset of products available in stock_quants
        quant_products = self.env['product.product']

        # If inventory by company
        if self.company_id:
            domain += ' AND sq.company_id = %s'
            args += (self.company_id.id,)
        if self.product_ids:
            domain += ' AND sq.product_id in %s'
            args += (tuple(self.product_ids.ids),)
            for product in self.product_ids:
                stock_quants = self.env['stock.quant'].search(
                    ['&', ['product_id', '=', product.id], ['location_id', 'in', locations.ids]])
                if len(stock_quants) < 1 and product.x_studio_perecedero:
                    for location in locations.ids:
                        self.env['stock.quant'].create({
                            'product_id': product.id,
                            'location_id': location,
                            'company_id': self.company_id.id
                        })

        self.env['stock.quant'].flush(
            ['company_id', 'product_id', 'quantity', 'location_id', 'lot_id', 'package_id', 'owner_id'])
        self.env['product.product'].flush(['active'])
        self.env.cr.execute("""SELECT sq.product_id, sum(sq.quantity) as product_qty, sq.location_id, sq.lot_id as prod_lot_id, sq.package_id, sq.owner_id as partner_id
            FROM stock_quant sq
            LEFT JOIN product_product pp
            ON pp.id = sq.product_id
            WHERE %s
            GROUP BY sq.product_id, sq.location_id, sq.lot_id, sq.package_id, sq.owner_id """ % domain, args)

        for product_data in self.env.cr.dictfetchall():
            product_data['company_id'] = self.company_id.id
            product_data['inventory_id'] = self.id
            product_data['revisado'] = False
            # replace the None the dictionary by False, because falsy values are tested later on
            for void_field in [item[0] for item in product_data.items() if item[1] is None]:
                product_data[void_field] = False
            product_data['theoretical_qty'] = product_data['product_qty']
            if self.prefill_counted_quantity == 'zero':
                if 'difference_qty_2' in product_data.keys():
                    product_data['product_qty'] = 0 + \
                        product_data['difference_qty_2']
                else:
                    product_data['product_qty'] = 0
            if product_data['product_id']:
                product_data['product_uom_id'] = Product.browse(
                    product_data['product_id']).uom_id.id
                quant_products |= Product.browse(product_data['product_id'])
            vals.append(product_data)
        return vals

    def action_validate(self):
        if not self.exists():
            return
        self.ensure_one()
        if not (self.user_has_groups('overwrite_inventory.inventory_adjustment_user') or self.user_has_groups('stock.group_stock_manager')):
            raise UserError(_("Only a stock manager can validate an inventory adjustment."))
        if self.state != 'confirm':
            raise UserError(_(
                "You can't validate the inventory '%s', maybe this inventory " +
                "has been already validated or isn't ready.") % (self.name))
        inventory_lines = self.line_ids.filtered(lambda l: l.product_id.tracking in ['lot', 'serial'] and not l.prod_lot_id and l.theoretical_qty != l.product_qty)
        lines = self.line_ids.filtered(lambda l: float_compare(l.product_qty, 1, precision_rounding=l.product_uom_id.rounding) > 0 and l.product_id.tracking == 'serial' and l.prod_lot_id)
        if inventory_lines and not lines:
            wiz_lines = [(0, 0, {'product_id': product.id, 'tracking': product.tracking}) for product in inventory_lines.mapped('product_id')]
            wiz = self.env['stock.track.confirmation'].create({'inventory_id': self.id, 'tracking_line_ids': wiz_lines})
            return {
                'name': _('Tracked Products in Inventory Adjustment'),
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_model': 'stock.track.confirmation',
                'target': 'new',
                'res_id': wiz.id,
            }
        self._action_done()
        self.line_ids._check_company()
        self._check_company()
        return True

    def _action_done(self):
        negative = next((line for line in self.mapped(
            'line_ids') if line.product_qty < 0 and line.product_qty != line.theoretical_qty), False)
        not_checked = next((line for line in self.mapped(
            'line_ids') if not line.revisado), False)
        negative_lost = next((line for line in self.mapped(
            'line_ids') if line.perdida < 0), False)
        print(not_checked)
        if negative:
            raise UserError(_('You cannot set a negative product quantity in an inventory line:\n\t%s - qty: %s') %
                            (negative.product_id.name, negative.product_qty))
        if not_checked:
            raise UserError(_('No se ha revisado algún producto.'))
        if negative_lost:
            raise UserError(_('Algún producto tiene pérdida negativa.'))
        self.action_check()
        self.write({'state': 'done'})
        self.post_inventory()
        return True


class InventoryLine(models.Model):
    _inherit = "stock.inventory.line"

    revisado = fields.Boolean('Revisado', required=True)
    motivo_de_baja = fields.Selection([
        ('obs', 'Obsolecencia de Bien'),
        ('da', 'Daño'),
        ('fec', 'Fecha de Vencimiento'),
        ('hur',	'Hurto')],
        string='Motivo de Baja')

    showed_qty = fields.Float('Contado',
                              help="Campo que muestra la cantidad contada.",
                              compute="update_showed_quantity",
                              digits='Product Unit of Measure', default=0)

    difference_qty_2 = fields.Float('Diferencia',
                                    help="Diferencia ingresada para el cálculo de la cantidad contada.",
                                    digits='Product Unit of Measure', default=0)

    perdida = fields.Float('Pérdida',
                           help="Productos perdidos.",
                           digits='Product Unit of Measure', default=0)

    prueba = fields.Image('Evidencia')
    costo = fields.Float(related='product_id.standard_price')
    total_perdida = fields.Float(compute='_compute_lost')
    disposicion_final = fields.Char()
    fecha_disposicion_final = fields.Date()

    @ api.depends('costo', 'perdida')
    def _compute_lost(self):
        for line in self:
            line.total_perdida = line.costo * line.perdida

    @ api.onchange('perdida')
    def update_quantity_by_perdida(self):
        for line in self:
            line.product_qty = line.theoretical_qty - line.perdida

    @ api.onchange('difference_qty_2')
    def update_quantity_by_difference(self):
        for line in self:
            line.product_qty = line.theoretical_qty + line.difference_qty_2

    @ api.onchange('product_qty')
    def update_showed_quantity(self):
        for line in self:
            line.showed_qty = line.product_qty

    @ api.onchange('product_id', 'location_id', 'product_uom_id', 'prod_lot_id', 'partner_id', 'package_id')
    def _onchange_quantity_context(self):
        product_qty = False
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
        # TDE FIXME: last part added because crash
        if self.product_id and self.location_id and self.product_id.uom_id.category_id == self.product_uom_id.category_id:
            theoretical_qty = self.product_id.get_theoretical_quantity(
                self.product_id.id,
                self.location_id.id,
                lot_id=self.prod_lot_id.id,
                package_id=self.package_id.id,
                owner_id=self.partner_id.id,
                to_uom=self.product_uom_id.id,
            )
        else:
            theoretical_qty = 0
        # Sanity check on the lot.
        if self.prod_lot_id:
            if self.product_id.tracking == 'none' or self.product_id != self.prod_lot_id.product_id:
                self.prod_lot_id = False

        if self.prod_lot_id and self.product_id.tracking == 'serial':
            # We force `product_qty` to 1 for SN tracked product because it's
            # the only relevant value aside 0 for this kind of product.
            self.product_qty = 1
        elif self.product_id and float_compare(self.product_qty, self.theoretical_qty, precision_rounding=self.product_uom_id.rounding) == 0:
            # We update `product_qty` only if it equals to `theoretical_qty` to
            # avoid to reset quantity when user manually set it.
            self.product_qty = theoretical_qty + self.difference_qty_2
        self.theoretical_qty = theoretical_qty

    def _get_virtual_location(self):
        if self.inventory_id.ajuste == 'baja':
            return self.inventory_id.location_dest_id
        else:
            return self.product_id.with_context(force_company=self.company_id.id).property_stock_inventory


class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    state = fields.Selection([
        ('draft', 'Elaboración'),
        ('review', 'Revisión'),
        ('auth', 'Autorización'),
        ('approv', 'Aprobación'),
        ('done', 'Done')],
        string='Status', default="draft", readonly=True, tracking=True)

    rule = {
        'review': [('readonly', True)],
        'auth': [('readonly', True)],
        'approv': [('readonly', True)],
        'done': [('readonly', True)],
    }

    company_id = fields.Many2one(states=rule, tracking=1)
    product_id = fields.Many2one(states=rule, tracking=1)
    origin = fields.Char(states=rule)
    product_uom_id = fields.Many2one(states=rule, tracking=1)
    lot_id = fields.Many2one(states=rule, tracking=1)
    package_id = fields.Many2one(states=rule, tracking=1)
    owner_id = fields.Many2one(states=rule, tracking=1)
    picking_id = fields.Many2one(states=rule, tracking=1)
    location_id = fields.Many2one(states=rule, tracking=1)
    scrap_location_id = fields.Many2one(states=rule, tracking=1)
    scrap_qty = fields.Float(states=rule, tracking=1)

    user_rev = fields.Many2one('res.users', string='Revisó', required=False)
    user_aut = fields.Many2one('res.users', string='Autorizó', required=False)
    user_apr = fields.Many2one('res.users', string='Aprobó', required=False)

    date_rev = fields.Datetime(string='Fecha revisó')
    date_aut = fields.Datetime(string='Fecha autorizó')
    date_apr = fields.Datetime(string='Fecha aprobó')

    motivo_de_baja = fields.Selection([
        ('obs', 'Obsolecencia de Bien'),
        ('da', 'Daño'),
        ('fec', 'Fecha de Vencimiento'),
        ('hur',	'Hurto')],
        string='Motivo de Baja', states=rule, tracking=1)

    def to_review(self):
        self._check_company()
        for scrap in self:
            scrap.name = self.env['ir.sequence'].next_by_code(
                'stock.scrap') or _('New')
            scrap.date_done = fields.Datetime.now()
            scrap.write({'state': 'review'})
        if self.product_id.type != 'product':
            return True
        precision = self.env['decimal.precision'].precision_get(
            'Product Unit of Measure')
        location_id = self.location_id
        if self.picking_id and self.picking_id.picking_type_code == 'incoming':
            location_id = self.picking_id.location_dest_id
        available_qty = sum(self.env['stock.quant']._gather(self.product_id,
                                                            location_id,
                                                            self.lot_id,
                                                            self.package_id,
                                                            self.owner_id,
                                                            strict=True).mapped('quantity'))
        scrap_qty = self.product_uom_id._compute_quantity(
            self.scrap_qty, self.product_id.uom_id)
        if float_compare(available_qty, scrap_qty, precision_digits=precision) >= 0:
            return True
        else:
            ctx = dict(self.env.context)
            ctx.update({
                'default_product_id': self.product_id.id,
                'default_location_id': self.location_id.id,
                'default_scrap_id': self.id
            })
            return {
                'name': _('Insufficient Quantity'),
                'view_mode': 'form',
                'res_model': 'stock.warn.insufficient.qty.scrap',
                'view_id': self.env.ref('stock.stock_warn_insufficient_qty_scrap_form_view').id,
                'type': 'ir.actions.act_window',
                'context': ctx,
                'target': 'new'
            }

    def to_auth(self):
        self._check_company()
        for scrap in self:
            scrap.write({'state': 'auth'})
            scrap.write({'user_rev': self.env.uid})
            scrap.write({'date_rev': datetime.datetime.today()})
        return True

    def to_approv(self):
        self._check_company()
        for scrap in self:
            scrap.write({'state': 'approv'})
            scrap.write({'user_aut': self.env.uid})
            scrap.write({'date_aut': datetime.datetime.today()})
        return True

    def to_draft(self):
        self._check_company()
        for scrap in self:
            scrap.write({'state': 'draft'})
            scrap.write({'user_rev': False})
            scrap.write({'user_aut': False})
            scrap.write({'user_apr': False})
            scrap.write({'date_rev': False})
            scrap.write({'date_aut': False})
            scrap.write({'date_apr': False})
        return True

    def do_scrap(self):
        self._check_company()
        for scrap in self:
            move = self.env['stock.move'].create(scrap._prepare_move_values())
            # master: replace context by cancel_backorder
            move.with_context(is_scrap=True)._action_done()
            scrap.write({'move_id': move.id, 'state': 'done'})
            scrap.write({'user_apr': self.env.uid})
            scrap.write({'date_apr': datetime.datetime.today()})
        return True

    def _prepare_move_values(self):
        self.ensure_one()
        location_id = self.location_id.id
        if self.picking_id and self.picking_id.picking_type_code == 'incoming':
            location_id = self.picking_id.location_dest_id.id
        return {
            'name': self.name,
            'origin': self.origin or self.picking_id.name or self.name,
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'state': 'draft',
            'product_uom_qty': self.scrap_qty,
            'location_id': location_id,
            'scrapped': True,
            'location_dest_id': self.scrap_location_id.id,
            'move_line_ids': [(0, 0, {'product_id': self.product_id.id,
                                      'product_uom_id': self.product_uom_id.id,
                                      'qty_done': self.scrap_qty,
                                      'location_id': location_id,
                                      'location_dest_id': self.scrap_location_id.id,
                                      'package_id': self.package_id.id,
                                      'owner_id': self.owner_id.id,
                                      'lot_id': self.lot_id.id, })],
            #             'restrict_partner_id': self.owner_id.id,
            'picking_id': self.picking_id.id
        }

    def action_validate(self):
        self.ensure_one()
        if self.location_id.id == self._get_default_location_id():
            view = self.env.ref('overwrite_inventory.button_confirm_form')
            return {
                'type': 'ir.actions.act_window',
                'name': "Confirmar 'Ubicación Origen'",
                'res_model': 'overwrite_inventory.button.confirm',
                'views': [(view.id, 'form')],
                'target': 'new',
                'context': {'scrap': self.id}
            }
        else:
            return self.do_scrap()

    def action_validate_second_confirm(self):
        self.ensure_one()
        return self.do_scrap()


class StockWarnInsufficientQtyScrapOver(models.TransientModel):
    _inherit = 'stock.warn.insufficient.qty.scrap'

    def action_done(self):
        return True

    def action_cancel(self):
        return self.scrap_id.to_draft()


class Picking(models.Model):
    _inherit = 'stock.picking'

    parent_id = fields.Many2one(comodel_name='stock.picking')
    children_ids = fields.One2many(
        comodel_name='stock.picking', inverse_name='parent_id')

    warehouse_orig = fields.Many2one(comodel_name='stock.warehouse')
    warehouse_dest = fields.Many2one(comodel_name='stock.warehouse')

    def get_root_warehouse(self, location_id):
        stock_location = self.env['stock.location']
        #En sale.order estaba tomando dos warehouse, se estaba duplicando el warehouse
        #para varias compañias, por lo tanto se establece the current company para que 
        #tome unicamente un warehouse.
        company_ids = self.env.user.company_id.id
        current = stock_location.search([['id', '=', location_id and 'company_id' == company_ids]])
        while current.location_id and current.location_id.location_id:
            current = current.location_id
        warehouse = self.env['stock.warehouse'].search(
            [['code', '=', current.complete_name]])
        return warehouse

    def set_warehouse(self, vals):

        if vals.get('location_id', False):
            warehouse_orig = self.get_root_warehouse(vals['location_id'])
            if warehouse_orig:
                vals['warehouse_orig'] = warehouse_orig.id

        if vals.get('location_dest_id', False):
            warehouse_dest = self.get_root_warehouse(vals['location_dest_id'])
            if warehouse_dest:
                vals['warehouse_dest'] = warehouse_dest.id
        return vals

    def set_parent(self, vals):
        if vals.get('origin', False):
            parent = self.env['stock.picking'].search(['&', ['name', '=', vals['origin'].split(
                'Retorno de ')[-1]], ['company_id', '=', self.env.company.id]])
            if parent:
                vals['parent_id'] = parent.id
                vals['company_id'] = parent.company_id.id
        if not vals.get('origin', False):
            vals['parent_id'] = False

    @ api.model
    def write(self, vals):
        vals = self.set_warehouse(vals)
        self.set_parent(vals)
        self._check_intrawarehouse_moves(vals)
        return super(Picking, self).write(vals)

    @ api.model
    def create(self, vals):
        vals = self.set_warehouse(vals)
        self.set_parent(vals)
        self._check_intrawarehouse_moves(vals)
        return super(Picking, self).create(vals)

    def _check_different_lot_stock_moves(self):
        if self.group_id:
            pickings_on_group = self.env['stock.picking'].search(
                [['group_id', '=', self.group_id.id], ['state', '=', 'done']])
            if len(pickings_on_group) > 0 and self.backorder_id == False:
                move_lot_ids = []
                move_lot_ids_qty = {}
                for picking in pickings_on_group:
                    if 'Retorno' in picking.origin:
                        pass
                    for move in picking.move_line_ids_without_package:
                        move_lot_ids.append(move.lot_id.id)
                        key = str(move.product_id)+str(move.lot_id)
                        if move_lot_ids_qty.get(key, False):
                            if move.qty_done * move.product_uom_id.factor_inv < move_lot_ids_qty.get(key, False):
                                move_lot_ids_qty[key] = move.qty_done * \
                                    move.product_uom_id.factor_inv
                        else:
                            move_lot_ids_qty[key] = move.qty_done * \
                                move.product_uom_id.factor_inv
                for move in self.move_line_ids_without_package:
                    key = str(move.product_id)+str(move.lot_id)
                    if move.lot_id.id not in move_lot_ids:
                        raise UserError(_('No se puede agregar lotes no existentes en movimientos terminados anteriores. {}'.format(
                            move.product_id.name)))
                    print(move.qty_done * move.product_uom_id.factor_inv)
                    print()
                    if move_lot_ids_qty.get(key, False):
                        if move.qty_done * move.product_uom_id.factor_inv > move_lot_ids_qty.get(key, False):
                            raise UserError(_('No se puede realizar un movimiento con mayor cantidad de producto terminado que en los anteriores movimientos. {}'.format(
                                move.product_id.name)))


    def _check_intrawarehouse_moves(self, vals):
        if vals.get('warehouse_orig', False):
            current_user = self.env['res.users'].browse(self.env.uid)
            warehouse = self.env['stock.warehouse'].search(
                [['id', '=', vals.get('warehouse_orig')]])
            responsables = warehouse.user_ids
            if current_user not in responsables:
                raise UserError(
                    _('Los movimientos intraalmacen solo la puede realizar un usuario responsable del almacen destino'))


    def button_validate(self):
        if not self.partner_id:
            products = {}
            for line in self.move_line_ids:
                key = str(line.product_id.id) + '-' + \
                    str(line.lot_id.id) + '-' + str(line.location_id.id)
                if products.get(key, False):
                    products[key] += line.qty_done * \
                        line.product_uom_id.factor_inv
                else:
                    products[key] = line.qty_done * \
                        line.product_uom_id.factor_inv
            for key, qty_done in products.items():
                product, lot, dest = key.split('-')
                product = int(product)
                dest = int(dest)
                if lot == 'False':
                    lot = False
                else:
                    lot = int(lot)
                quant = self.env['stock.quant'].search(
                    [['product_id', '=', product], ['lot_id', '=', lot], ['location_id', '=', dest]])
                quant_sum = sum(map(lambda q: q.quantity *
                                    q.product_uom_id.factor_inv, quant))
                if quant_sum < qty_done:
                    view = self.env.ref(
                        'overwrite_inventory.button_confirm_form_generic')
                    wiz = self.env['overwrite_inventory.button.confirm.generic'].create(
                        {'message': 'Las cantidades en la ubicación origen no son suficientes para cubrir la demanda. Confirme para ignorar inventario negativo.'})
                    return {
                        'type': 'ir.actions.act_window',
                        'name': "Confirmar",
                        'res_model': 'overwrite_inventory.button.confirm.generic',
                        'views': [(view.id, 'form')],
                        'target': 'new',
                        'res_id': wiz.id,
                        'context': {'model': 'stock.picking', 'id': self.id}
                    }
        return self.button_validate_confirm()

    def button_validate_confirm(self):
        self.ensure_one()

        if not self.env['mrp.production'].search([['name', '=', self.origin]]):
            self._check_different_lot_stock_moves()

        if self.state == 'waiting':
            raise UserError(
                _('Por favor completar las operaciones precondiciones'))

        if not self.move_lines and not self.move_line_ids:
            raise UserError(_('Please add some items to move.'))

        # Clean-up the context key at validation to avoid forcing the creation of immediate
        # transfers.
        ctx = dict(self.env.context)
        ctx.pop('default_immediate_transfer', None)
        self = self.with_context(ctx)

        # add user as a follower
        self.message_subscribe([self.env.user.partner_id.id])

        # If no lots when needed, raise error
        picking_type = self.picking_type_id
        precision_digits = self.env['decimal.precision'].precision_get(
            'Product Unit of Measure')
        no_quantities_done = all(float_is_zero(move_line.qty_done, precision_digits=precision_digits)
                                 for move_line in self.move_line_ids.filtered(lambda m: m.state not in ('done', 'cancel')))
        no_reserved_quantities = all(float_is_zero(
            move_line.product_qty, precision_rounding=move_line.product_uom_id.rounding) for move_line in self.move_line_ids)
        if no_reserved_quantities and no_quantities_done:
            raise UserError(
                _('You cannot validate a transfer if no quantites are reserved nor done. To force the transfer, switch in edit more and encode the done quantities.'))

        if picking_type.use_create_lots or picking_type.use_existing_lots:
            lines_to_check = self.move_line_ids
            if not no_quantities_done:
                lines_to_check = lines_to_check.filtered(
                    lambda line: float_compare(line.qty_done, 0,
                                               precision_rounding=line.product_uom_id.rounding)
                )

            for line in lines_to_check:
                product = line.product_id
                if product and product.tracking != 'none':
                    if not line.lot_name and not line.lot_id:
                        raise UserError(
                            _('You need to supply a Lot/Serial number for product %s.') % product.display_name)

        # Propose to use the sms mechanism the first time a delivery
        # picking is validated. Whatever the user's decision (use it or not),
        # the method button_validate is called again (except if it's cancel),
        # so the checks are made twice in that case, but the flow is not broken
        sms_confirmation = self._check_sms_confirmation_popup()
        if sms_confirmation:
            return sms_confirmation

        if no_quantities_done:
            view = self.env.ref('stock.view_immediate_transfer')
            wiz = self.env['stock.immediate.transfer'].create(
                {'pick_ids': [(4, self.id)]})
            return {
                'name': _('Immediate Transfer?'),
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'res_model': 'stock.immediate.transfer',
                'views': [(view.id, 'form')],
                'view_id': view.id,
                'target': 'new',
                'res_id': wiz.id,
                'context': self.env.context,
            }

        if self._get_overprocessed_stock_moves() and not self._context.get('skip_overprocessed_check'):
            view = self.env.ref('stock.view_overprocessed_transfer')
            wiz = self.env['stock.overprocessed.transfer'].create(
                {'picking_id': self.id})
            return {
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'res_model': 'stock.overprocessed.transfer',
                'views': [(view.id, 'form')],
                'view_id': view.id,
                'target': 'new',
                'res_id': wiz.id,
                'context': self.env.context,
            }

        # Check backorder should check for other barcodes
        if self._check_backorder():
            return self.action_generate_backorder_wizard()
        self.action_done()
        return


class Warehouse(models.Model):
    _inherit = "stock.warehouse"

    code = fields.Char(size=10)
    user_ids = fields.Many2many('res.users', string='Responsables')


class ProductCategory(models.Model):
    _inherit = 'product.category'

    company_id = fields.Many2one(
        'res.company',
        'Company',
        ondelete='cascade',
    )


class StockValuationLayer(models.Model):

    _inherit = 'stock.valuation.layer'
    categ_id = fields.Many2one(store=True)


class StockMoveLine(models.Model):

    _inherit = 'stock.move.line'

    exists_qty = fields.Float(
        'Exists Quantity', compute='_compute_exists_qty',
        store=True, help='Cantidad existente en inventario')

    @api.depends('qty_done')
    def _compute_exists_qty(self):
        for move in self:
            if move.location_dest_id.usage == 'internal':
                move.exists_qty = move.qty_done
            else:
                move.exists_qty = -1 * move.qty_done

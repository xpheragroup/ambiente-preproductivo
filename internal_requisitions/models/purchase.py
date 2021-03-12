


from odoo import models, fields, api


class InternalPurchase(models.Model):

     _inherit = "purchase.order"

     requisicion_interna_purchase = fields.Boolean("Requisición Interna de Compra", default=False, required=True)
     requisicion_interna_production = fields.Boolean("Requisición Interna de Faltantes Fabricación", default=False, required=True)
     requisicion_interna_inventory = fields.Boolean("Requisición Interna de Requerimiento de Inventario", default=False, required=True)
     mrp_production_ids = fields.Many2many('stock.move', string='Órdenes de Producción')
     stock_picking_ids = fields.Many2many('stock.move.line', string='Transferencias')
     show_internal_purchase = fields.Boolean("Ocultar Lista", default=False, required=True)
     state = fields.Selection([
        ('borrador compra', 'Borrador'),
        ('Borrador Requisición', 'Requisición'),
        ('draft', 'RFQ'),
        ('sent', 'RFQ Sent'),
        ('to approve', 'To Approve'),
        ('purchase', 'Purchase Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled')
     ], string='Status', readonly=True, index=True, copy=False, default='borrador compra', tracking=True)

     def _default_partner_id(self):
          company_ids = self.env.user.company_id.id
          return self.env['res.partner'].search([('name', '=', 'Proveedor Default'),('company_id','=',company_ids)], limit=1).id

     partner_id = fields.Many2one('res.partner', string='Proveedor', required=True, default=_default_partner_id , tracking=True, domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]", help="You can find a vendor by its Name, TIN, Email or Internal Reference.")

     @api.depends('purchase.order')
     def button_continue(self):
          if self.requisicion_interna_purchase:
               self.state = 'Borrador Requisición'
          if not self.requisicion_interna_purchase:
               self.state = 'draft'
          return self.state
     
     @api.depends('purchase.order')
     def button_quote(self):
          self.state = 'draft'
          return self.state
     
     @api.depends('purchase.order')
     def button_draft(self):
          if self.state == 'draft':
               self.state = 'Borrador Requisición'
          if self.state == 'Borrador Requisición':
               self.state = 'borrador compra'
          return self.state







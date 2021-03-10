


from odoo import models, fields, api


class InternalPurchase(models.Model):

     _inherit = "purchase.order"

     requisicion_interna_purchase = fields.Boolean("Requisición Interna de Compra", default=False, required=True)
     
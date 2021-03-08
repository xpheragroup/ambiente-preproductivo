

from odoo import models, fields, api


class InternalOrder(models.Model):

     _inherit = "sale.order"

     requisicion_interna_sale = fields.Boolean("Requisición Interna de Orden", default=False, required=True)
     
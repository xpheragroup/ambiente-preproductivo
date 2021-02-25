# -*- coding: utf-8 -*-

from odoo import models, fields, api


class overwrite_user(models.Model):
     _inherit = 'res.users'

     warehouse_ids = fields.Many2many('stock.warehouse',string='Almacen')

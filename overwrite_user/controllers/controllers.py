# -*- coding: utf-8 -*-
# from odoo import http


# class OverwriteUser(http.Controller):
#     @http.route('/overwrite_user/overwrite_user/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/overwrite_user/overwrite_user/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('overwrite_user.listing', {
#             'root': '/overwrite_user/overwrite_user',
#             'objects': http.request.env['overwrite_user.overwrite_user'].search([]),
#         })

#     @http.route('/overwrite_user/overwrite_user/objects/<model("overwrite_user.overwrite_user"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('overwrite_user.object', {
#             'object': obj
#         })

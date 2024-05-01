from flask.views import MethodView
from flask import jsonify, request, current_app

from app.services.authentication import authenticate_request
from app.services.admin import log_request


class AllBuyersView(MethodView):

    def get(self):
        log_request(request)
        if authenticate_request(request):
            # Filter only sellers
            users = list(current_app.db.users.find({'role': 'buyer'}, {'_id': 0}))
            return jsonify(users), 200
        else:
            return jsonify({'error': 'Unauthorized'}), 200


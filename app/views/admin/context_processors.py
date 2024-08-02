from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify
from flask import current_app
from flask_jwt_extended import get_jwt_identity

from app.services.authentication import custom_jwt_required
from app.services.admin import log_request


class ContextProcessorsDataView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Get all users
        users = list(current_app.db.users.find({}, {'_id': 0, 'otp': 0}))

        # Get all properties
        properties = current_app.db.properties.find()

        property_list = []
        for prop in properties:
            lookup_info = current_app.db.property_seller_transaction.find_one({'property_id': str(prop['_id'])})
            if lookup_info: 
                property_id = str(prop.pop('_id', None))
                prop['property_id'] = property_id
                seller = current_app.db.users.find_one({'uuid': lookup_info['seller_id']})
                if seller:
                    owner_info = {
                        'name': seller.get('first_name') + " " + seller.get('last_name'),
                        'phone': seller.get('phone'),
                        'email': seller.get('email'),
                        'profile': seller.get('profile_pic'),
                        'user_id': seller.get('uuid')
                    }
                    prop['owner_info'] = owner_info
                else:
                    prop['owner_info'] = {
                        'name': "Customer-Service",
                        'phone': None,
                        'email': None,
                        'profile': None,
                        'user_id': None
                    }                          # External properties
                
                property_list.append(prop)
            else:
                continue  # Invalid/Incomplete transaction properties
          

        # Combine users and properties data
        context_processors_data = {
            'users': users,
            'properties': property_list
        }

        return jsonify(context_processors_data), 200

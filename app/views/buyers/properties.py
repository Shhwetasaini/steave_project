
import os
import json
import werkzeug
from datetime import datetime

from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify, request, current_app, url_for
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename

from app.services.admin import log_request
from app.services.authentication import custom_jwt_required
from bson import ObjectId


class AddBuyerView(MethodView):
    decorators = [custom_jwt_required()]

    def post(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        data = request.json
        property_id = data.get('property_id')
        seller_id = data.get('seller_id')

        if not user:
            return jsonify({'error': 'User not found'}), 200
        
        user_role = user.get('role')
        if not user_role or user_role != 'buyer':
            return jsonify({'error':'Unauthorized access'}), 200
        
        # Check if the seller exists
        seller = current_app.db.users.find_one({'uuid': seller_id, 'role': 'seller'})
        if not seller:
            return jsonify({'error': 'Seller not found'}), 200
        
        # Check if the property exists and belongs to the specified seller
        property_doc = current_app.db.properties.find_one({'_id': ObjectId(property_id), 'seller_id': seller_id})
        if not property_doc:
            return jsonify({'error': 'Property not found or does not belong to the specified seller'}), 200
        
        # Update the property to add the buyer
        current_app.db.properties.update_one(
            {'_id': ObjectId(property_id)},
            {'$addToSet': {'buyers': user['email']}}
        )
        
        return jsonify({'message': 'Buyer added to property successfully'}), 200


class BuyerAllSellersView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 200
        
        user_role = user.get('role')
        if user_role != 'buyer':
            return jsonify({'error': 'Unauthorized access'}), 200
        
        # Retrieve properties associated with the buyer_id
        properties = current_app.db.properties.find({'buyers': {'$in': [user['uuid']]}})

        # Initialize a set to store unique seller_ids
        seller_ids = set()

        # Extract unique seller_ids from the properties
        for property in properties:
            seller_ids.add(property['seller_id'])

        # Convert the set of seller_ids to a list if needed
        seller_ids_list = list(seller_ids)

        return jsonify(seller_ids_list), 200

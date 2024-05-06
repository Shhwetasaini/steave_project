
import os
import random
import json
from datetime import datetime
from bson import ObjectId

from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify, request, current_app, url_for
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename

from app.services.admin import log_request
from app.services.authentication import custom_jwt_required
from app.views.notifications import store_notification


class SellerPropertyListView(MethodView):
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
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 200

        # Get properties associated with the seller
        property_transactions = current_app.db.property_seller_transaction.find({'seller_id': user['uuid']})

        # Construct response
        property_list = []
        for prop_transaction in property_transactions:
            property_id = prop_transaction.get('property_id')
            # Fetch property details from properties collection
            property_info = current_app.db.properties.find_one({'_id': ObjectId(property_id)}, {'_id': 0})
            if property_info:
                property_info['property_id'] = property_id
                owner_info = {
                    'name': user.get('first_name') + " " + user.get('last_name'),
                    'phone': user.get('phone'),
                    'email': user.get('email'),
                    'profile': user.get('profile_pic')
                }
                property_info['owner_info'] = owner_info
                property_list.append(property_info)
            else:
                property_list.append(None)

        return jsonify({'properties': property_list}), 200


class AllPropertyListView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request(request)
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
                        'profile': seller.get('profile_pic')
                    }
                    prop['owner_info'] = owner_info
                else:
                    prop['owner_info'] = None          # External properties
                
                property_list.append(prop)
            else:
                continue  # Invalid/Incomplete transaction properties
        return jsonify(property_list), 200


class SellerBuyersListView(MethodView):
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
        if not user_role or user_role != 'seller':
            return jsonify({'error': 'Unauthorized access'}), 200
        
        # Retrieve properties listed by the seller
        properties = current_app.db.properties.find({'seller_id': user['uuid']})
        
        # Extract buyers from properties
        buyers = set()
        for property in properties:
            buyers.update(property.get('buyers', []))
        
        return jsonify(list(buyers)), 200
    

class SellerSinglePropertyBuyersListView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self, property_id):
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
        if not user_role or user_role != 'seller':
            return jsonify({'error': 'Unauthorized access'}), 200
        
        # Check if the property exists and belongs to the seller
        property_doc = current_app.db.properties.find_one({'_id': ObjectId(property_id), 'seller_id': user['uuid']})
        if not property_doc:
            return jsonify({'error': 'Property not found or does not belong to the seller'}), 200
        
        # Retrieve the buyers associated with the property
        buyers = property_doc.get('buyers', [])
        
        return jsonify(buyers), 200


class PropertyUpdateView(MethodView):
    decorators = [custom_jwt_required()]
    def put(self, property_id):
        log_request(request)
        current_user = get_jwt_identity()
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        if user:
            if user.get('role') == 'realtor':
                return jsonify({'error': 'Unauthorized access'}), 200
            
            property_data = current_app.db.properties.find_one({'_id': ObjectId(property_id)})
            property_seller_data = current_app.db.property_seller_transaction.find_one({'property_id': property_id, 'seller_id': user['uuid']})

            if property_data is None or property_seller_data is None:
                return jsonify({'error': 'Property does not Exists or you are not allowed to update this property'}), 200
            
            # Update property data
            updatable_fields = [
                'description', 'price', 'size',
                'name', 'status', 'address', 'state', 'city',
                'latitude', 'longitude', 'beds', 'baths', 'kitchen', 'image',
            ]
            for key, value in request.form.items():
                if key in updatable_fields:
                    property_data[key] = value
            # Update property document in MongoDB
            current_app.db.properties.update_one({'_id': ObjectId(property_id)}, {'$set': property_data})
            # Add image if provided
            if 'image' in request.files:
                file = request.files['image']
                org_filename = secure_filename(file.filename)
                user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id))
                os.makedirs(user_media_dir, exist_ok=True)
                if os.path.exists(os.path.join(user_media_dir, org_filename)):
                    return jsonify({'error': 'File with the same name already exists in the folder'}), 200
                if any(image['name'] == org_filename for image in property_data.get('images', [])):
                    return jsonify({'error': 'File with the same name already exists in the database'}), 200
                image_path = os.path.join(user_media_dir, org_filename)
                file.save(image_path)
                image_url = url_for('serve_media', filename=os.path.join('user_properties', str(user['uuid']), str(property_id), org_filename))
                property_data.setdefault('images', []).append(image_url)
                current_app.db.properties.update_one(
                    {'_id': ObjectId(property_id)},
                    {'$set': {'images': property_data['images']}}
                )
                store_notification(
                    user_id=user['uuid'], 
                    title="Update Property",
                    message="image added successfully",
                    type="property"
                )
            return jsonify({'message': 'Property information updated successfully'}), 200
        else:
            return jsonify({'error': 'User not found'}), 200


class PropertyImageDeleteView(MethodView):  #not working
    decorators = [custom_jwt_required()]
    
    def delete(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if user:
            if user.get('role') == 'realtor':
                return jsonify({'error': 'Unauthorized access'}), 200
            
            data = request.json
            property_id = data.get('property_id')
            image_url = data.get('image_url')

            if not property_id or not image_url:
                return jsonify({'error': 'property_id or image_name is missing in the request body'}), 200

            
            property_data = current_app.db.properties.find_one({'_id': ObjectId(property_id)})
            property_seller_data = current_app.db.property_seller_transaction.find_one({'property_id': property_id, 'seller_id': user['uuid']})

            if property_data is None or property_seller_data is None:
                return jsonify({'error': 'Property does not Exists or you are not allowed to delete image to this property'}), 200

            if not property_data:
                return jsonify({'error': 'Property not found'}), 200

            # Remove the image URL from property_data's images list
            property_data['images'].remove(image_url)

            # Update the user's properties in the database to reflect the removed image
            result = current_app.db.properties.update_one(
                {'_id': ObjectId(property_id)},
                {'$set': {'images': property_data['images']}}
            )

            if result.modified_count == 0:
                return jsonify({'error': 'Failed to delete the image'}), 200

            # Delete the image from the folder
            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id))
            image_path = os.path.join(user_media_dir, image_url)
            if os.path.exists(image_path):
                os.remove(image_path)
            
            store_notification(
                user_id=user['uuid'], 
                title="Update Property",
                message="image deleted successfully",
                type="property"
            )

            return jsonify({'message': 'Image deleted successfully'}), 200
        else:
            return jsonify({'error': 'User not found'}), 200

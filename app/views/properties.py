
import os
import re
import json
from datetime import datetime
from bson import ObjectId
import logging

from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify, request, current_app, url_for
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename

from app.services.admin import log_request
from app.services.authentication import custom_jwt_required, log_action

from app.services.properties import validate_address


class SellerPropertyListView(MethodView):
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
                if property_info.get('status') == 'cancelled':
                    continue
                property_info['property_id'] = property_id
                owner_info = {
                    'name': user.get('first_name') + " " + user.get('last_name'),
                    'phone': user.get('phone'),
                    'email': user.get('email'),
                    'profile': user.get('profile_pic'),
                    'user_id': user['uuid']
                }
                property_info['owner_info'] = owner_info
                property_list.append(property_info)
            else:
                continue
      
        log_action(user['uuid'],user['role'], "viewed-properties", None)
        return jsonify(property_list), 200


class AllPropertyListView(MethodView):
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
            return jsonify({'error': 'User not found'}), 200
        
        properties = current_app.db.properties.find()

        property_list = []
        for prop in properties:
            lookup_info = current_app.db.property_seller_transaction.find_one({'property_id': str(prop['_id'])})
            if lookup_info: 
                if prop.get('status') == 'cancelled':
                    continue
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
        
        log_action(user['uuid'],user['role'], "viewed-all-properties", None)     
        return jsonify(property_list), 200


class ExternalPropertyAddView(MethodView):
    def post(self):
        log_request()
        try:
            data = request.json
            property_insert_result = current_app.db.properties.insert_one(data)
            inserted_property_id = str(property_insert_result.inserted_id)
            data['property_id'] =  inserted_property_id
            # Use the inserted property ID in the transaction
            data.pop('_id', None)
            transaction_result = current_app.db.transaction.insert_one({
                'property_data': data,
                'amount': "NA",
                'signed_property_contract': None
            })

            lookup_data = {
                "transaction_id": str(transaction_result.inserted_id),
                "property_id": inserted_property_id, 
                "seller_id": "Customer-Service",
                "realtors": []  
            }

            # Insert lookup data into the lookup table
            current_app.db.property_seller_transaction.insert_one(lookup_data)
            return jsonify({'message': 'Property added successfully.'})
        except Exception as e:
            logging.info("Externalproperty add error",  str(e))
            return jsonify({'error': str(e)})


class PropertyUpdateView(MethodView):
    decorators = [custom_jwt_required()]
    def put(self, property_id):
        log_request()
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
            updatable_fields = [
                'description', 'price', 'size',
                'name', 'status', 'address', 'state', 'city',
                'latitude', 'longitude', 'beds', 'baths', 'kitchen'
            ]

            data = request.form 
            files = request.files.get('image')
            
            if not data and not files:
                return jsonify({'error': 'No data in payload'})

            update_data  = {}
            for key, value in request.form.items():
                if key in updatable_fields:
                    if key == "address":
                        
                        if value.isdigit():
                            return jsonify({'error': 'seller_address and property_type field is required'})
                        
                        # Check if the address contains "US" or "United States" or "États-Unis"
                        if not re.search(r'\b(US|United States|USA|États-Unis|U\.S\.?)\b', value, flags=re.IGNORECASE):
                            return jsonify({'error': 'Please enter a valid address in the United States.'})
                        
                        # Check if seller_property_address is present in e_sign_data and contains mn, minnesota, fl, or florida
                        if not any(keyword in  value.lower() for keyword in ['mn', 'minnesota', 'fl', 'florida']):
                            return jsonify({'error': "The address must be located in Minnesota (MN) or Florida (FL)."})
                        
                        valid_address = validate_address(value)
                        if not valid_address:
                            return jsonify({'error': "Invalid Address. missing country, state or postal_code"})
                        
                        update_data[key] = value

                    elif key in ["price", "longitude", "latitude"]:
                        try:
                            update_data[key] = float(value)
                        except ValueError:
                            if value.strip() != '':
                                return jsonify({'error':'only float values are accepted for price, longitude, latitude'})
                            pass
                    
                    elif key in ["beds", "baths", "kitchen"]:
                        try:
                            update_data[key] = int(value)
                        except ValueError:
                            if value.strip() != '':
                                return jsonify({'error':'only integer values are accepted for beds, baths, kitchen'})
                            pass  
                    
                    else:
                        update_data[key] = value
                
            # Update property document in MongoDB
            current_app.db.properties.update_one({'_id': ObjectId(property_id)}, {'$set': update_data})
            # Add image if provided
            if 'image' in request.files:
                file = request.files['image']
                org_filename = secure_filename(file.filename)
                user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id))
                os.makedirs(user_media_dir, exist_ok=True)
                
                if os.path.exists(os.path.join(user_media_dir, org_filename)):
                    return jsonify({'error': 'File with the same name already exists in the folder'}), 200
                # Check if image with same name already exists in database
                if any(org_filename == image_name for image_name in [image.split('/')[-1] for image in property_data.get('images', [])]):
                    return jsonify({'error': 'File with the same name already exists in the database'}), 200
                
                image_path = os.path.join(user_media_dir, org_filename)
                file.save(image_path)
                image_url = url_for('serve_media', filename=os.path.join('user_properties', str(user['uuid']), str(property_id), org_filename))
                update_data.setdefault('images', []).append(image_url)
                current_app.db.properties.update_one(
                    {'_id': ObjectId(property_id)},
                    {'$push': {'images': update_data['images'][0]}}
                )
            
            property_data['property_id'] = property_id
            log_action(user['uuid'], user['role'], "updated-property", update_data)
            return jsonify({'message': 'Property information updated successfully'}), 200
        else:
            return jsonify({'error': 'User not found'}), 200


class PropertyImageDeleteView(MethodView): 
    decorators = [custom_jwt_required()]
    
    def delete(self):
        log_request()
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
            
            file_name = os.path.basename(image_url)
           
            # Delete the file from the server
            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id))
            file_path = os.path.join(user_media_dir, file_name)

            if not os.path.exists(file_path):
                return jsonify({"error":"file does not exits "})
            
            property_images = property_data.get('images')
            if image_url not in property_images:
                return jsonify({"error":"file does not exits "})
            
            os.remove(file_path)

           # Remove the image URL from property_data's images list
            property_data['images'].remove(image_url)

            # Update the user's properties in the database to reflect the removed image
            result = current_app.db.properties.update_one(
                {'_id': ObjectId(property_id)},
                {'$set': {'images': property_data['images']}}
            )

            if result.modified_count == 0:
                return jsonify({'error': 'Failed to delete the image'}), 200
            
           
            log_action(user['uuid'], user['role'],"deleted-property-image", data)
            return jsonify({'message': 'Image deleted successfully'}), 200
        else:
            return jsonify({'error': 'User not found'}), 200

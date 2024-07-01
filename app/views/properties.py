
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
from app.services.properties import validate_address, save_panoramic_image


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
      
        log_action(user['uuid'],user['role'], "viewed-properties", {})
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
        
        log_action(user['uuid'],user['role'], "viewed-all-properties", {})     
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
            label = data.get('label')
            
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
                if not label:
                    return jsonify({'error': 'Missing image label'})

                file = request.files['image']
                org_filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"{timestamp}_{org_filename}"
                user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id))
                os.makedirs(user_media_dir, exist_ok=True)
                
                if os.path.exists(os.path.join(user_media_dir, filename)):
                    return jsonify({'error': 'File with the same name already exists in the folder'}), 200
                # Check if image with same name already exists in database
                if any(org_filename == image_name for image_name in [image.get('name') for image in property_data.get('images', [])]):
                    return jsonify({'error': 'File with the same name already exists in the database'}), 200
                
                image_path = os.path.join(user_media_dir, filename)
                file.save(image_path)
                image_url = url_for('serve_media', filename=os.path.join('user_properties', str(user['uuid']), str(property_id), filename))
                image_data = {'label':label, 'name': filename, 'image_url':image_url}
                update_data.setdefault('images', []).append(image_data)
                current_app.db.properties.update_one(
                    {'_id': ObjectId(property_id)},
                    {'$push': {'images': update_data['images'][0]}}
                )
            
            property_data['property_id'] = property_id
            log_action(user['uuid'], user['role'], "updated-property", update_data)
            return jsonify({'message': 'Property information updated successfully'}), 200
        else:
            return jsonify({'error': 'User not found'}), 200


class PanoramicImageView(MethodView):
    decorators = [custom_jwt_required()]

    def post(self):
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


        if 'panoramic_image' not in request.files:
            return jsonify({"error": "No image part"}), 200

        panoramic_image = request.files.get('panoramic_image')
        property_id = request.form.get('property_id')
        property_version = request.form.get('property_version')
        order = request.form.get('order')
        room_label = request.form.get('room_label')
        latitude = request.form.get('geo_location_latitude')
        longitude = request.form.get('geo_location_longitude')

        missing_fields = [field for field, value in {'property_id': property_id,'property_version': property_version,'order': order,'room_label': room_label,'latitude': latitude,'longitude': longitude}.items() if not value]

        if missing_fields:
            return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 200

        try:
            property_version = int(property_version)
        except ValueError:
            return jsonify({"error": "Invalid property_version value, must be an integer"}), 200
        try:
            order = int(order)
        except ValueError:
            return jsonify({"error": "Invalid order value, must be an integer"}), 200
        try:
            latitude = float(latitude)
        except ValueError:
            return jsonify({"error": "Invalid latitude value, must be a float"}), 200
        try:
            longitude = float(longitude)
        except ValueError:
            return jsonify({"error": "Invalid longitude value, must be a float"}), 200

        user_property = current_app.db.properties.find_one({'_id': ObjectId(property_id)})
        seller_transaction_property = current_app.db.property_seller_transaction.find_one({'property_id': property_id, 'seller_id': user['uuid']})
        if not user_property or not seller_transaction_property:
            return jsonify({"error": "Property not found"}), 200

        panoramic_images = user_property.get('panoramic_images', [])
        existing_versions = [pano.get('property_version') for pano in panoramic_images]

        if not existing_versions and property_version != 1:
            return jsonify({'error': 'Invalid property_version. Start from 1.'}), 200

        if existing_versions:
            max_existing_version = max(existing_versions)
            if property_version not in existing_versions and property_version != max_existing_version + 1:
                return jsonify({'error': f'Invalid property_version. The next version should start from {max_existing_version + 1}.'}), 200

        property_version_images = next((pano for pano in panoramic_images if pano.get('property_version') == property_version), None)
        
        image_data = save_panoramic_image(panoramic_image=panoramic_image, user=user, property_id=property_id)
        if 'error' in image_data:
            return jsonify({'error': image_data.get('error')})
        if property_version_images:
            current_orders = [img['order'] for img in property_version_images.get('3d_images', [])]

            existing_image = next((img for img in property_version_images['3d_images'] if img['order'] == order), None)
            if existing_image:
                return jsonify({'error': "panoramic Image already exists for this order, delete it first"}), 200

            else:
                
                # Add new image to the existing property version
                if current_orders and order != max(current_orders) + 1:
                    return jsonify({"error": f"Wrong Order Value, Order value should start from {max(current_orders) + 1}"}), 200
                new_image = {
                    "order": order,
                    "room_label": room_label,
                    "name": image_data.get('filename'),
                    "url": image_data.get('image_url'),
                    "geo_location_latitude": latitude,
                    "geo_location_longitude": longitude,
                    "uploaded_at": datetime.now(),
                }
                current_app.db.properties.update_one(
                    {"_id": ObjectId(property_id), "panoramic_images.property_version": property_version},
                    {"$push": {"panoramic_images.$.3d_images": new_image}}
                )

                log_action(user['uuid'], user['role'], "uploaded-panoramic-images", new_image)
                return jsonify({'message': "panoramic Image details added successfully"}), 200

        else:
            # Creating a new property version
            if order != 1:
                return jsonify({'error': 'Wrong Order Value, Order value should start from 1'}), 200

            new_property_version_images = {
                'property_version': property_version,
                '3d_images': [{
                    "order": order,
                    "room_label": room_label,
                    "name": image_data.get('filename'),
                    "url": image_data.get('image_url'),
                    "geo_location_latitude": latitude,
                    "geo_location_longitude": longitude,
                    "uploaded_at": datetime.now(),
                }]
            }
            current_app.db.properties.update_one(
                {'_id': ObjectId(property_id)},
                {'$push': {'panoramic_images': new_property_version_images}}
            )
            
            log_action(user['uuid'], user['role'], "uploaded-panoramic-images", new_property_version_images)
            return jsonify({"message": "Panoramic Image uploaded successfully"}), 200

    def get(self, property_id):
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


        logging.info(f"Fetching all panoramic images for property ID: {property_id}")
        user_property = current_app.db.properties.find_one({'_id': ObjectId(property_id)})
        seller_transaction_property = current_app.db.property_seller_transaction.find_one({'property_id': property_id, 'seller_id': user['uuid']})
        if not user_property or not seller_transaction_property:
            return jsonify({"error": "Property not found"}), 200
        
        panoramas = user_property.get('panoramic_images', [])
        sorted_panoramas = []
        for panorama in panoramas:
            sorted_panoramas.append({
                'property_version': panorama['property_version'],
                '3d_images': sorted(panorama['3d_images'], key=lambda x: x['order'])
            })

        log_action(user['uuid'], user['role'], "viewed-panoramic-images", {})
        return jsonify(sorted_panoramas), 200
    
    def delete(self, property_id, property_version, order):
        log_request()
        current_user = get_jwt_identity()
        
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not user:
            return jsonify({'error': 'User not found'}), 200

        if user.get('role') == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 200
        
        property_version = int(property_version)
        order = int(order)

        user_property = current_app.db.properties.find_one({'_id': ObjectId(property_id)})
        seller_transaction_property = current_app.db.property_seller_transaction.find_one({'property_id': property_id, 'seller_id': user['uuid']})
        if not all([user_property, seller_transaction_property]):
            return jsonify({"error": "Property not found"}), 200
        
        panoramic_images = user_property.get('panoramic_images', [])
        
        property_version_exists = False
        order_exists = False
        updated_panoramic_images = []

        for panorama in panoramic_images:
            if panorama.get('property_version') == property_version:
                property_version_exists = True
                updated_3d_images = [img for img in panorama.get('3d_images', []) if img.get('order') != order]
                if len(updated_3d_images) < len(panorama.get('3d_images', [])):
                    order_exists = True
                if updated_3d_images:
                    panorama['3d_images'] = updated_3d_images
                    updated_panoramic_images.append(panorama)
                else:
                    current_app.db.properties.update_one(
                        {"_id": ObjectId(property_id)},
                        {"$pull": {"panoramic_images": {"property_version": property_version}}}
                    )
            else:
                updated_panoramic_images.append(panorama)

        if not property_version_exists:
            return jsonify({'error': "property_version does not exist"}), 200

        if not order_exists:
            return jsonify({'error': "order does not exist in the specified property_version"}), 200

        current_app.db.properties.update_one(
            {"_id": ObjectId(property_id)},
            {"$set": {"panoramic_images": updated_panoramic_images}}
        )

        log_action(user['uuid'], user['role'], "deleted-panoramic-images", {"property_id": property_id, "property_version": property_version, "order": order})
        return jsonify({"message": "Panoramic image deleted successfully"}), 200


class PropertyImageLabelUpdateView(MethodView):
    decorators = [custom_jwt_required()]

    def put(self):
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

        
        data = request.json
        property_id = data.get('property_id')
        image_name = data.get('image_name')
        url = data.get('url')
        new_label = data.get('new_label')

        if not property_id or not image_name or not new_label:
            return jsonify({'error': 'property_id, image_name, or new_label is missing in the request body'})

        property_data = current_app.db.properties.find_one({'_id': ObjectId(property_id)})
        property_seller_data = current_app.db.property_seller_transaction.find_one({'property_id': property_id, 'seller_id': user['uuid']})
        if property_data is None or property_seller_data is None:
            return jsonify({'error': 'Property does not Exists or you are not allowed to update this property'}), 200

        # Update the image URL and label in the database
        result = current_app.db.properties.update_one(
            {"_id": ObjectId(property_id), "images.name": image_name, "images.image_url": url},
            {"$set": {"images.$.label": new_label}}
        )

        # Check if the update was successful
        if result.modified_count > 0:
            return jsonify({"message": "Image updated successfully"})
        else:
            return jsonify({"error": "Image not found or update failed"})


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

        if not user:
            return jsonify({'error': 'User not found'})

        if user.get('role') == 'realtor':
            return jsonify({'error': 'Unauthorized access'})

        data = request.json
        property_id = data.get('property_id')
        image_url = data.get('image_url')
        label = data.get('label')

        if not property_id or not image_url or not label:
            return jsonify({'error': 'property_id, image_url, or label is missing in the request body'})

        property_data = current_app.db.properties.find_one({'_id': ObjectId(property_id)})
        property_seller_data = current_app.db.property_seller_transaction.find_one({'property_id': property_id, 'seller_id': user['uuid']})

        if not property_data or not property_seller_data:
            return jsonify({'error': 'Property does not exist or you are not allowed to delete image from this property'})

        file_name = os.path.basename(image_url)
        user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id))
        file_path = os.path.join(user_media_dir, file_name)

        print(file_path)

        if not os.path.exists(file_path):
            return jsonify({"error": "File does not exist"})

        os.remove(file_path)

        property_images = property_data.get('images', [])

        # Find the image object to be removed
        image_to_remove = next((image for image in property_images if image['image_url'] == image_url and image['label'] == label), None)

        if not image_to_remove:
            return jsonify({"error": "Image with the specified URL and label does not exist"})

        # Remove the image object from the property_data's images list
        property_images.remove(image_to_remove)

        # Update the user's properties in the database to reflect the removed image
        result = current_app.db.properties.update_one(
            {'_id': ObjectId(property_id)},
            {'$set': {'images': property_images}}
        )

        if result.modified_count == 0:
            return jsonify({'error': 'Failed to delete the image'})

        log_action(user['uuid'], user['role'], "deleted-property-image", data)
        return jsonify({'message': 'Image deleted successfully'})


class PropertySearchView(MethodView):
    decorators = [custom_jwt_required()]

    def post(self):
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 403

        data = request.json
        location = data.get('location_point', [])

        if len(location) != 4:
            return jsonify({'error': 'Invalid input data. Four coordinates are required.'}), 400
        
        # Extract bounding box coordinates
        min_lat = min(point["lat"] for point in location)
        max_lat = max(point["lat"] for point in location)
        min_lng = min(point["lng"] for point in location)
        max_lng = max(point["lng"] for point in location)

        # Query to find properties within the bounding box
        pipeline = [
            {
                '$match': {
                    'latitude': {'$gte': min_lat, '$lte': max_lat},
                    'longitude': {'$gte': min_lng, '$lte': max_lng},
                    'status': {'$ne': 'cancelled'}
                }
            }
        ]

        properties_collection = current_app.db.properties
        filtered_properties = list(properties_collection.aggregate(pipeline))
        
        # Fetch property IDs
        valid_properties = []
        for property in filtered_properties:
            property['_id'] = str(property.pop('_id'))
            valid_property = current_app.db.property_seller_transaction.find_one({'property_id': property['_id']})
            if valid_property:
                valid_properties.append(property)

        return jsonify(valid_properties), 200

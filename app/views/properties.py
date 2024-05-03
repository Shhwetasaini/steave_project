
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


#def property_dummy_data_insert():
#    properties_collection = current_app.db.properties
#    with open('app/properties.json', 'r') as file:
#        property_data = json.load(file)
#    properties_collection.insert_many(property_data)
#
#
#class SellersDummyPropertyListView(MethodView):
#    def get(self):
#        log_request(request)
#        current_user = get_jwt_identity()
#
#        try:
#            validate_email(current_user)
#            user = current_app.db.users.find_one({'email': current_user})
#        except EmailNotValidError:
#            user = current_app.db.users.find_one({'uuid': current_user})
#        
#        if not user:
#            return jsonify({'error': 'User not found'}), 200
#        
#        user_role = user.get('role')
#        if user_role != 'seller':
#            return jsonify({'error': 'Unauthorized access'}), 200
#        
#        unsold_properties = list(current_app.db.properties.find({'seller_id': {'$exists': False}}))
#
#        if unsold_properties:
#            for property in unsold_properties:
#                property['property_id'] = str(property['_id'])
#                property.pop('_id', None)
#            
#            return jsonify(unsold_properties), 200
#        else:
#            property_dummy_data_insert()
#            return jsonify({'message': 'Please check again!'}), 200
#
#
#class MobileAppSellersDummyPropertyAddView(MethodView):      #Temporary View- Only for mobile app sellers 
#    decorators = [custom_jwt_required()]
#
#    def get(self):
#        log_request(request)
#        current_user = get_jwt_identity()
#
#        unsold_properties = list(current_app.db.properties.find({'seller_id': {'$exists': False}}))
#        if not unsold_properties or len(unsold_properties) < 3:
#            property_dummy_data_insert()
#            unsold_properties = list(current_app.db.properties.find({'seller_id': {'$exists': False}}))
#        
#        # Select three random properties from unsold_properties
#        random_properties = random.sample(unsold_properties, 3)
#        property_ids = [property['_id'] for property in random_properties]
#       
#
#        try:
#            validate_email(current_user)
#            user = current_app.db.users.find_one({'email': current_user})
#        except EmailNotValidError:
#            user = current_app.db.users.find_one({'uuid': current_user})
#        
#        if not user:
#            return jsonify({'error': 'User not found'}), 200
#        
#        user_role = user.get('role')
#        if user_role != 'seller':
#            return jsonify({'error': 'Unauthorized access'}), 200
#        
#        for property_id in property_ids:
#            property_id = ObjectId(property_id)
#
#            # Check if the property is already assigned to a seller
#            existing_property = current_app.db.properties.find_one({'_id': property_id, 'seller_id': {'$exists': True}})
#            if existing_property:
#                continue
#            
#            # Update property document to add the seller's ID
#            current_app.db.properties.update_one(
#                {'_id': property_id},
#                {'$set': {'seller_id': user['uuid']}}
#            )
#        
#        store_notification(
#            user_id=user['uuid'], 
#            title="Add Property",
#            message="property added successfully",
#            type="property"
#        )
#        return jsonify({'message': 'properties added to the seller successfully'}), 200
#


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
        if user_role != 'realtor' and not current_app.db.property_seller_lookup.find_one({"seller_id": [user['uuid']]}):
            return jsonify({'error': 'Unauthorized access'}), 200

        # Get properties associated with the seller
        properties = current_app.db.properties.find({"_id": {"$in": current_app.db.property_seller_lookup.find_one({"seller_id": [user['uuid']]})['property_id']}})

        # Construct response
        property_list = []
        for prop in properties:
            prop["_id"] = str(prop["_id"])
            property_list.append(prop)

        return jsonify(property_list), 200
    

class PropertyListView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request(request)
        properties = current_app.db.properties.find()

        property_list = []
        for prop in properties:
            lookup_info = current_app.db.property_seller_lookup.find_one({"property_id": prop['_id']})
            seller_ids = lookup_info.get("seller_id", [])
            seller_info_list = []
            for seller_id in seller_ids:
                seller_info = current_app.db.users.find_one({'uuid': seller_id})
                if seller_info:
                    seller_info_list.append({
                        "name": seller_info.get("name"),
                        "email": seller_info.get("email"),
                        "phone": seller_info.get("phone"),
                        # Add any other seller information you want to include
                    })

            property_list.append({
                "_id": str(prop['_id']),
                "name": prop.get("name"),
                "status": prop.get("status"),
                "address": prop.get("address"),
                "city": prop.get("city"),
                "state": prop.get("state"),
                "latitude": prop.get("latitude"),
                "longitude": prop.get("longitude"),
                "beds": prop.get("beds"),
                "baths": prop.get("baths"),
                "kitchen": prop.get("kitchen"),
                "property_type": prop.get("property_type"),
                "description": prop.get("description"),
                "price": prop.get("price"),
                "size": prop.get("size"),
                "images": prop.get("images"),
                "seller_info": seller_info_list
            })

        return jsonify(property_list), 200


#class SellerPropertyListView(MethodView):
#    decorators = [custom_jwt_required()]
#
#    def get(self):
#        log_request(request)
#        current_user = get_jwt_identity()
#
#        try:
#            validate_email(current_user)
#            user = current_app.db.users.find_one({'email': current_user})
#        except EmailNotValidError:
#            user = current_app.db.users.find_one({'uuid': current_user})
#        
#        if not user:
#            return jsonify({'error': 'User not found'}), 200
#        
#        user_role = user.get('role')
#        if user_role != 'realtor':
#            return jsonify({'error': 'Unauthorized access'}), 200
#        
#        # Retrieve properties listed by the seller
#        properties = current_app.db.properties.find({'seller_id': user['uuid']})
#        
#        # Prepare response with property details
#        property_list = []
#        for property in properties:
#            property['property_id'] = str(property['_id'])
#            property.pop('_id', None)
#            property_list.append(property)
#        
#        return jsonify(property_list), 200


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

        updatable_fields = [
            'owner_bio', 'description', 'price', 'size', 
            'name', 'status', 'address', 'state', 'city', 
            'latitude', 'longitude', 'beds', 'baths', 'kitchen'
        ]
        
        if user:
            if user.get('role') != 'seller':
                return jsonify({'error': 'Unauthorized access'}), 200
            try:
            
                property_data = current_app.db.find_one({'_id': ObjectId(property_id), 'seller_id': user['uuid']})

                if property_data is None:
                    return jsonify({'error': 'Property not found'}), 200

                # Update only the fields that are included in the request JSON and are updatable
                for key, value in request.json.items():
                    if key in updatable_fields:
                        property_data[key] = value

                # Update the property document in MongoDB
                current_app.db.update_one({'_id': ObjectId(property_id)}, {'$set': property_data})

                return jsonify({'message': 'Property information updated successfully'}), 200
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        else:
            return jsonify({'error': 'User not found'}), 200


class PropertyImageAddView(MethodView):
    decorators = [custom_jwt_required()]

    def post(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if user:
            if user.get('role') != 'seller':
                return jsonify({'error': 'Unauthorized access'}), 200
            
            property_id = request.form.get('property_id')
            file = request.files.get('image')

            print(property_id, file)

            if not file or not property_id:
                return jsonify({'error': 'File or property_id is missing!'}), 200

            property_data = current_app.db.properties.find_one({'_id': ObjectId(property_id), 'seller_id': user['uuid']})

            if not property_data:
              return jsonify({'error': 'Property does not Exists'}), 200

            # Check if the file with the same name already exists in the folder
            org_filename = secure_filename(file.filename)
            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id))
            os.makedirs(user_media_dir, exist_ok=True)

            if os.path.exists(os.path.join(user_media_dir, org_filename)):
                return jsonify({'error': 'File with the same name already exists in the folder'}), 200

            # Check if the file with the same name already exists in the database
            if any(image['name'] == org_filename for image in property_data['images']):
              return jsonify({'error': 'File with the same name already exists in the database'}), 200

            image_path = os.path.join(user_media_dir, org_filename)
            file.save(image_path)

            # Generate URL for accessing the saved image
            image_url = url_for('serve_media', filename=os.path.join('user_properties', str(user['uuid']), str(property_id), org_filename))
    
            # Update property_data with image information
            property_data['images'].append(image_url)

            # Update the user's properties in the database
            result = current_app.db.properties.update_one(
                {'seller_id': user['uuid'], '_id': ObjectId(property_id)},
                {'$set': {'images': property_data['images']}}
            )

            if result.modified_count == 0:
                return jsonify({'error': 'Property not found in the database'}), 200

            store_notification(
                user_id=user['uuid'], 
                title="Update Property",
                message="image added successfully",
                type="property"
            )
            return jsonify({'message': 'Image added successfully'}), 200
        
        else:
          return jsonify({'error': 'User not found'}), 200


class PropertyImageDeleteView(MethodView):
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
            if user.get('role') != 'seller':
                return jsonify({'error': 'Unauthorized access'}), 200
            
            data = request.json
            property_id = data.get('property_id')
            image_name = data.get('image_name')

            if not property_id or not image_name:
                return jsonify({'error': 'property_id or image_name is missing in the request body'}), 200

            # Retrieve property data from the database
            property_data = current_app.db.properties.find_one(
                {'seller_id': user['uuid'], '_id': ObjectId(property_id)}
            )

            if not property_data:
                return jsonify({'error': 'Property not found'}), 200

            # Find the image to delete
            image_to_delete = None
            for image in property_data['images']:
                if image['name'] == image_name:
                    image_to_delete = image
                    break

            if not image_to_delete:
              return jsonify({'error': 'Image not found'}), 200

            # Update the user's properties in the database to remove the image
            result = current_app.db.properties.update_one(
                {'seller_id': user['uuid'], '_id': ObjectId(property_id)},
                {'$pull': {'images': {'name': image_name}}}
            )

            if result.modified_count == 0:
                return jsonify({'error': 'Image not found in the database'}), 200

            # Delete the image from the folder
            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id))
            image_path = os.path.join(user_media_dir, image_name)
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

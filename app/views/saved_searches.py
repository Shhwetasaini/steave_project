from bson import ObjectId
from datetime import datetime
from flask.views import MethodView
from geopy.geocoders import GoogleV3
from app.services.admin import log_request
from flask import jsonify, request, current_app
from flask_jwt_extended import get_jwt_identity
from app.services.authentication import custom_jwt_required
from email_validator import validate_email, EmailNotValidError


class SavedSearchView(MethodView):

    decorators=[custom_jwt_required()]
    def post(self):
        """Create a new saved search"""
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not user:
            return jsonify({'error': 'User not found'}), 404

        data = request.json
        description = data.get('description')
        longitude = data.get('longitude')
        latitude = data.get('latitude')

        # Fetch latitude and longitude using Google Maps if not provided
        if not longitude or not latitude:
            google_location_api_key = current_app.config['GOOGLE_LOCATION_API_KEY']
            geocoder = GoogleV3(api_key=google_location_api_key)
            location = geocoder.geocode(description)
            if location:
                latitude = location.latitude
                longitude = location.longitude
            else:
                return jsonify({'error': 'Could not retrieve location data from Google Maps'}), 400

        # Create the search entry to be added to the array with a unique ID
        search_entry = {
            '_id': str(ObjectId()),  
            'description': description,
            'longitude': longitude,
            'latitude': latitude,
            'timestamp': datetime.now()
        } 

        # Add the new search entry to the user's saved searches array
        result = current_app.db.saved_searches.update_one(
            {'user_id': str(user['_id'])},
            {'$push': {'searches': search_entry}},
            upsert=True 
        )

        return jsonify({'message': 'Saved search added successfully', 'search_saved_data': search_entry}), 201

    def get(self, search_id=None):
        """Retrieve all saved searches or a specific search by ID"""
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not user:
            return jsonify({'error': 'User not found'}), 404

        user_searches = current_app.db.saved_searches.find_one({'user_id': str(user['_id'])})

        if not user_searches:
            return jsonify({'error': 'No saved searches found for this user'}), 404

        if search_id:
            # Safely handle the case where '_id' might not exist in a search entry
            search = next((s for s in user_searches['searches'] if s.get('_id') == search_id), None)
            if search:
                return jsonify(search), 200
            else:
                return jsonify({'error': 'Search not found'}), 404
        else:
            return jsonify(user_searches['searches']), 200

    def put(self, search_id):
        """Update a saved search by ID"""
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not user:
            return jsonify({'error': 'User not found'}), 404

        data = request.json
        description = data.get('description')
        longitude = data.get('longitude')
        latitude = data.get('latitude')

        # Fetch latitude and longitude using Google Maps if not provided
        if not longitude or not latitude:
            google_location_api_key = current_app.config['GOOGLE_LOCATION_API_KEY']
            geocoder = GoogleV3(api_key=google_location_api_key)
            location = geocoder.geocode(description)
            if location:
                latitude = location.latitude
                longitude = location.longitude
            else:
                return jsonify({'error': 'Could not retrieve location data from Google Maps'}), 400

        # Find and update the specific search entry
        result = current_app.db.saved_searches.update_one(
            {'user_id': str(user['_id']), 'searches._id': search_id},
            {'$set': {
                'searches.$.description': description,
                'searches.$.longitude': longitude,
                'searches.$.latitude': latitude,
                'searches.$.timestamp': datetime.now()
            }}
        )

        if result.matched_count == 0:
            return jsonify({'error': 'Search not found'}), 404

        updated_search = current_app.db.saved_searches.find_one(
            {'user_id': str(user['_id']), 'searches._id': search_id},
            {'searches.$': 1}  
        )
        updated_search_data = updated_search['searches'][0] if updated_search else None

        return jsonify({
            'message': 'Saved search updated successfully',
            'matched_count': result.matched_count,
            'modified_count': result.modified_count,
            'updated_data': updated_search_data
        }), 200


    def delete(self, search_id):
        """Delete a saved search by ID"""
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Find and delete the specific search entry by ID
        result = current_app.db.saved_searches.update_one(
            {'user_id': str(user['_id'])},
            {'$pull': {'searches': {'_id': search_id}}}
        )

        if result.modified_count == 0:
            return jsonify({'error': 'Search not found or could not be deleted'}), 404

        return jsonify({'message': 'Saved search deleted successfully'}), 200

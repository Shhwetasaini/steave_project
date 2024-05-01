import os
import hashlib
from datetime import datetime 
from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify, request, url_for
from flask import current_app
from werkzeug.utils import secure_filename

from app.services.authentication import authenticate_request
from app.services.admin import log_request


class AllUserView(MethodView):
    def get(self):
        log_request(request)
        if authenticate_request(request):
            users = list(current_app.db.users.find({}, {'_id': 0, 'otp': 0}))
            return jsonify(users), 200
        else:
            return jsonify({'error': 'Unauthorized'}), 401
        

class AddUserView(MethodView):
    def post(self):
        log_request(request)

        if authenticate_request(request):

            # Determine content type and parse data accordingly
            if request.content_type.startswith('multipart/form-data'):
                data = request.form
            elif request.is_json:
                data = request.json
            else:
                return jsonify({"error": "Unsupported Content Type"}), 400
            

            uuid_val = data.get('uuid', None)
            first_name = data.get('first_name', None)
            last_name = data.get('last_name', None)
            email = data.get('email', None)
            phone = data.get('phone', None)
            facebook = data.get('facebook', None)
            gmail = data.get('gmail', None)
            role = data.get('role', 'seller')
            linkedin = data.get('linkedin', None)
            password = data.get('password', None)

            # Validate email using email_validator
            try:
                validate_email(email)
            except EmailNotValidError:
                return jsonify({"error": "Invalid email format!"}), 400

            new_user = {
                'uuid': uuid_val,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'role' : role,
                'phone':  phone,
                'facebook': facebook,
                'gmail': gmail,
                'linkedin': linkedin,
                'is_verified': True,
                'password': hashlib.sha256(password.encode("utf-8")).hexdigest()
            }

            query = {"$or": [{"uuid": uuid_val}, {"email": email}]}
            existing_user = current_app.db.users.find_one(query)

            if not existing_user:
                current_app.db.users.insert_one(new_user)
                return jsonify({'message': 'User registered successfully'}), 200
            else:
                return jsonify({'error': 'User already exists with this email'}), 400
            
        else:
            return jsonify({'error': 'Unauthorized'}), 401


class EditUsersView(MethodView):
    def put(self):
        log_request(request)
        update_doc = {}
        if authenticate_request(request):
            data = request.form
            email = data.get('email')
            user = current_app.db.users.find_one({'email' : email})
            
            profile_pic = request.files.get('profile_pic', None)

            if profile_pic and secure_filename(profile_pic.filename):
                filename = secure_filename(profile_pic.filename)
                user_profile_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'users_profile', str(user['uuid']))
                os.makedirs(user_profile_dir, exist_ok=True)
                # Delete old profile picture if it exists
                if 'profile_pic' in user:
                    old_profile_pic_path = os.path.join(user_profile_dir, user['profile_pic'].split('/')[-1])
                    if os.path.exists(old_profile_pic_path):
                        os.remove(old_profile_pic_path)
                profile_pic_path = os.path.join(user_profile_dir, filename)
                profile_pic.save(profile_pic_path)
                media_url = url_for('serve_media', filename=os.path.join('users_profile', str(user['uuid']), filename))
                update_doc['profile_pic'] = media_url

            first_name = data.get('first_name', None)
            last_name = data.get('last_name', None)
            phone = data.get('phone', None)
            password = data.get('password', None)
            facebook = data.get('facebook', None)
            gmail = data.get('gmail', None)
            linkedin = data.get('linkedin', None)

            if first_name:
                update_doc['first_name'] = first_name
            if last_name:
                update_doc['last_name'] = last_name
            if phone:
                update_doc['phone'] = phone
            if password:
                update_doc['password'] = hashlib.sha256(password.encode("utf-8")).hexdigest()
            if facebook:
                update_doc['facebook'] = facebook
            if gmail:
                update_doc['gmail'] = gmail
            if linkedin:
                update_doc['linkedin'] = linkedin

            if not update_doc:
                return jsonify({"message": "No fields to update!"}), 200

            updated_user = current_app.db.users.find_one_and_update(
                {"uuid": user['uuid']},
                {"$set": update_doc},
                return_document=True 
            )

            if updated_user:
                return jsonify({'message':"User updated Successfully!"}), 200
            else:
                return jsonify({'error': 'User not found or no fields to update!'}), 200 
        else:
            return jsonify({'error': 'Unauthorized'}), 401 
            

class DeleteUserView(MethodView):
    def delete(self):
        log_request(request)
        if authenticate_request(request):
            result = current_app.db.users.delete_one({'email': request.json.get('email')})
            if result.deleted_count == 1:
                return jsonify({'message': 'User deleted successfully'}), 200
            else:
                return jsonify({'error': 'User not found'}), 404
    
        return jsonify({'error': 'Unauthorized'}), 401 


class GetMediaView(MethodView):
    def get(self):
        log_request(request)
        if authenticate_request(request):
            all_media = list(current_app.db.media.find({}, {'_id': 0}))
            for media in all_media:
                user = current_app.db.users.find_one({'uuid':media['user_id']})
                try:
                    media['email'] = user['email']
                except TypeError:
                    continue
            return jsonify(all_media), 200
        else:
            return jsonify({'error': 'Unauthorized'}), 401 

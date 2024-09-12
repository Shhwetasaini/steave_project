from datetime import datetime
import hashlib
import logging
import uuid
import os
from jwt import DecodeError, InvalidTokenError
import phonenumbers

from email_validator import validate_email, EmailNotValidError
from flask.views import MethodView
from flask import jsonify, request, url_for
from flask import current_app
from flask_jwt_extended import (create_access_token,create_refresh_token, 
        get_jwt_identity, get_jwt, set_access_cookies, verify_jwt_in_request, jwt_required)
import hashlib
from datetime import timedelta

import requests
from werkzeug.utils import secure_filename

from app.services.admin import log_request
from app.services.authentication import (
    custom_jwt_required, 
    send_otp_via_email, 
    generate_otp ,log_action,
    insert_liked_properties
)


class RegisterUserView(MethodView):
    def post(self):
        log_request()

        # Determine content type and parse data accordingly
        if not request.is_json:
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type

        data = request.json
        uuid_val = str(uuid.uuid4())
        first_name = data.get('first_name', None)
        last_name = data.get('last_name', None)
        email = data.get('email', None)
        phone = data.get('phone', None)
        facebook = data.get('facebook', None)
        google = data.get('google', None)
        gmail = data.get('gmail', None)
        linkedin = data.get('linkedin', None)
        password = data.get('password', None)
        role = data.get('role', None) or None

        # Ensure essential fields are present
        if not all([uuid_val, email, first_name, last_name]):
            return jsonify({"error": "uuid, email, first_name, or last_name is missing!"}), 400  # Bad Request

        if role and role not in ['realtor']:
            return jsonify({"error": "Invalid user role!"}), 400  # Bad Request

        # Validate email
        try:
            validate_email(email)
        except EmailNotValidError:
            return jsonify({"error": "Invalid email format!"}), 400  # Bad Request

        # Validate phone number if provided
        formatted_phone = None
        if phone:
            try:
                parsed_number = phonenumbers.parse(phone, None)
                if not phonenumbers.is_valid_number(parsed_number):
                    return jsonify({"error": "Invalid phone number."}), 400  # Bad Request
                formatted_phone = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
            except (phonenumbers.phonenumberutil.NumberParseException, ValueError):
                return jsonify({"error": "Invalid phone number format."}), 400  # Bad Request

        # Check if user already exists
        query = {"$or": [{"uuid": uuid_val}, {"email": email}]}
        existing_user = current_app.db.users.find_one(query)

        if existing_user:
            return jsonify({'error': 'User already exists'}), 409  # Conflict

        # Prepare new user data
        new_user = {
            'uuid': uuid_val,
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone': formatted_phone,
            'role': role,
            'facebook': facebook,
            'google': google,
            'gmail': gmail,
            'linkedin': linkedin,
            'profile_pic': None,
            'password': hashlib.sha256(password.encode("utf-8")).hexdigest() if password else None,
            'is_verified': bool(facebook or google),  # Automatically verified for Facebook or Google logins
            'liked_properties': [],
            'device_token': None
        }

        # Insert new user into the database
        current_app.db.users.insert_one(new_user)

        # For non-social logins, generate and send OTP
        if not (facebook or google):
            otp = generate_otp()
            current_time = datetime.now()
            current_app.db.users.update_one(
                {'email': email},
                {'$set': {'otp': {'value': otp, 'time': current_time, 'is_used': False}}},
                upsert=True
            )
            send_otp_via_email(new_user['email'], otp, subject='OTP for user verification')

        new_user.pop('_id')
        log_action(new_user['uuid'], new_user['role'], "registration", new_user)

        return jsonify({
            'message': 'User registered successfully' + (
                ', OTP has been sent to email. Please verify it.' if not (facebook or google) else ''
            )
        }), 201  # Created

class LoginUserView(MethodView):
    def post(self):
        log_request()

        if not request.is_json:
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type
        data = request.json

        email = data.get('email')
        password = data.get('password')
        facebook = data.get('facebook')
        google = data.get('google')
        remember_me = data.get('remember_me', False)  # Defaults to False if not provided

        if not email:
            return jsonify({"error": "Email is missing!"}), 400  # Bad Request

        user = current_app.db.users.find_one({'email': email})

        if user:
            if not user['is_verified'] and not (facebook or google):
                return jsonify({'error': 'Verify user to login!'}), 403  # Forbidden
            if user['role'] == "superuser":
                return jsonify({"error": "You are not allowed to login here"}), 403  # Forbidden

            if facebook or google:
                # For Facebook or Google login, skip password check
                authenticated = True
            else:
                encrypted_password = hashlib.sha256(password.encode("utf-8")).hexdigest()
                authenticated = encrypted_password == user['password']

            if authenticated:
                expires_delta = timedelta(days=30) if remember_me else timedelta(hours=1)
                access_token = create_access_token(identity=email, expires_delta=expires_delta)
                refresh_token = create_refresh_token(identity=email)

                # Include user information in the response
                user_info = {
                    "uuid": user.get("uuid"),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "email": user.get("email"),
                    "phone": user.get("phone"),
                    "role": user.get("role"),
                }

                log_action(user['uuid'], user['role'], "social-login" if (facebook or google) else "email-login", data)

                response = jsonify({"message": "User logged in successfully!", "access_token": access_token, "refresh_token": refresh_token, "user_info": user_info})
                set_access_cookies(response, access_token)

                return response, 200  # OK
            else:
                return jsonify({'error': 'Email or password is incorrect!'}), 401  # Unauthorized

        return jsonify({'error': 'User does not exist, please register the user!'}), 404  # Not Found
    
    
class UserUuidLoginView(MethodView):
    def post(self):
        log_request()

        # Determine content type and parse data accordingly
        if not request.is_json:
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type
        
        data = request.json

        uuid = data.get('user_id')

        if not uuid:
            return jsonify({"error": "UUID is missing!"}), 400  # Bad Request
    
        user = current_app.db.users.find_one({'uuid': uuid})

        if user:
            if not user['is_verified']:
                return jsonify({'error': 'Verify user to login!'}), 403  # Forbidden
            
            access_token = create_access_token(identity=uuid)
            log_action(user['uuid'], user['role'], "uuid-login", data)
            return jsonify({"message": "User logged in successfully!", "access_token": access_token}), 200  # OK
        
        return jsonify({'error': 'User does not exist, please register the user'}), 404  # Not Found


class ProfileUserView(MethodView):
    decorators = [custom_jwt_required()]
    
    def get(self):
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if user:
            log_action(user['uuid'], user['role'], "viewed-profile", {'user': current_user})
            user.pop('_id', None)
            user.pop('password', None)
            
            return jsonify(user), 200
        else:
            return jsonify({'error': 'Profile not found'}), 404  # Not Found


class UserUUIDView(MethodView):
    def post(self):
        log_request()

        if not request.is_json:
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type
        data = request.json
        email = data.get('email')
        if not email:
            return jsonify({"error": "Email is missing!"}), 400  # Bad Request

        user = current_app.db.users.find_one({"email": email})
        if user:
            log_action(user['uuid'], user['role'], "viewed-uuid", data)
            return jsonify({'uuid': user.get('uuid', None)}), 200  # OK
        
        return jsonify({"error": "User does not exist"}), 404  # Not Found


class LogoutUserView(MethodView):
    decorators = [custom_jwt_required()]
    
    def get(self):
        log_request()
        current_user = get_jwt_identity()
        
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if user:
            jti = get_jwt()["jti"]
            now = datetime.now()
            current_app.db.user_token_blocklist.insert_one({
                "jti": jti,
                "created_at": now,
                'user_id': user['uuid']
            })
            log_action(user['uuid'], user['role'], "logout", {'user': current_user})
            return jsonify({"message": "Logout successfully"}), 200  # OK
        
        return jsonify({"error": "User not found"}), 404  # Not Found


class UpdateUsersView(MethodView):
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
            return jsonify({'error': 'User not found'}), 404
        
        update_doc = {}

        # Determine content type and parse data accordingly
        if not request.content_type.startswith('multipart/form-data'):
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type
            
        data = request.form
        profile_pic = request.files.get('profile_pic')
        if profile_pic and secure_filename(profile_pic.filename):
            filename = secure_filename(profile_pic.filename)
            user_profile_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'users_profile', str(user['uuid']))
            os.makedirs(user_profile_dir, exist_ok=True)
            
            # Delete old profile picture if it exists
            if user['profile_pic'] is not None:
                old_profile_pic_path = os.path.join(user_profile_dir, user['profile_pic'].split('/')[-1])
                if os.path.exists(old_profile_pic_path):
                    os.remove(old_profile_pic_path)
    
            profile_pic_path = os.path.join(user_profile_dir, filename)
            profile_pic.save(profile_pic_path)
            media_url = url_for('serve_media', filename=os.path.join('users_profile', str(user['uuid']), filename))
            update_doc['profile_pic'] = media_url
    
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        phone = data.get('phone')
        password = data.get('password')
        device_token = data.get('devicetoken')
        liked_properties = data.get('liked_properties')
        if device_token:
            update_doc['device_token'] = device_token.strip()
        if first_name and first_name.strip() != '':
            update_doc['first_name'] = first_name.strip()
        if last_name and last_name.strip() != '':
            update_doc['last_name'] = last_name.strip()
        if phone and phone.strip() != '':
            # Validate phone number
            try:
                parsed_number = phonenumbers.parse(phone, None)
                if not phonenumbers.is_valid_number(parsed_number):
                    return jsonify({"error": "Invalid phone number."}), 400  # Bad Request
            except phonenumbers.phonenumberutil.NumberParseException:
                return jsonify({"error": "Invalid phone number format."}), 400  # Bad Request
            except ValueError:
                return jsonify({"error": "Invalid phone number."}), 400  # Bad Request
            formatted_phone = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
            update_doc['phone'] = formatted_phone
        if password and password.strip() != '':
            update_doc['password'] = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if liked_properties:
            result = insert_liked_properties(user['uuid'], liked_properties)
            if result.get('error'):
                return jsonify(result), 400  # Bad Request
        # If the update document is empty, return an error
        if not update_doc:
            return jsonify({"error": "No fields to update!"}), 400  # Bad Request
        updated_user = current_app.db.users.find_one_and_update(
            {"uuid": user['uuid']},
            {"$set": update_doc},
            return_document=True 
        )
        if updated_user:
            log_action(user['uuid'], user['role'], "updated-profile", update_doc)
            return jsonify({'message': "User updated successfully!"}), 200  # OK
        else:
            return jsonify({'error': 'User not found or no fields to update!'}), 404  # Not Found
    

class ForgetPasswdView(MethodView):
    def post(self):
        if not request.is_json:
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type
        data = request.json

        email = data.get('email') or request.form.get('email')
        if not email:
            return jsonify({"error": "Email is missing!"}), 400  # Bad Request
        
        user = current_app.db.users.find_one({'email': email})

        if user:
            otp = generate_otp()
            current_time = datetime.now()
            current_app.db.users.update_one(
                {'email': email}, 
                {'$set': {'otp': {'value': otp, 'time': current_time, 'is_used': False}}}, 
                upsert=True
            )
            data['otp'] = otp
            data['time'] = current_time
            log_action(user['uuid'], user['role'], "forget-password", data)
            send_otp_via_email(user['email'], otp, subject='OTP for Password Reset')
            return jsonify({'message': 'OTP sent to your email'}), 200  # OK
        else:
            return jsonify({"error": "User does not exist"}), 404  # Not Found


class ResetPasswdView(MethodView):
    def post(self):
        if not request.is_json:
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type
        data = request.json

        email = data.get('email')
        otp_received = data.get('otp')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if not email or not otp_received or not new_password or not confirm_password:
            return jsonify({"error": "All fields are required"}), 400  # Bad Request
        
        if new_password != confirm_password:
            return jsonify({"error": "Both passwords must be the same"}), 400  # Bad Request

        user = current_app.db.users.find_one({'email': email})       

        if user and user['otp']['value'] == otp_received:
            otp_created_at = user['otp']['time']
            current_time = datetime.now()
            time_difference = current_time - otp_created_at
            if time_difference.total_seconds() <= 3600 and not user['otp']['is_used']:
                hashed_password = hashlib.sha256(new_password.encode("utf-8")).hexdigest()  
                current_app.db.users.update_one({'email': email}, {'$set': {'password': hashed_password, "otp.is_used": True}})
                data['new_password'] = hashed_password
                log_action(user['uuid'], user['role'], "reset-password",  data)
                return jsonify({'message': 'Password reset successfully'}), 200  # OK
            else:
                return jsonify({'error': 'OTP has been used or expired'}), 400  # Bad Request
        else:
            return jsonify({'error': 'Invalid OTP or Email'}), 400  # Bad Request


class VerifyOtpView(MethodView):
    def post(self):
        if not request.is_json:
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type
        data = request.json
        email = data.get('email')
        otp_received = data.get('otp')

        user = current_app.db.users.find_one({'email': email})

        if user and user['otp']['value'] == otp_received:
            otp_created_at = user['otp']['time']
            current_time = datetime.now()
            time_difference = current_time - otp_created_at
            if time_difference.total_seconds() <= 3600 and not user['otp']['is_used']:
                current_app.db.users.update_one({'email': email}, {'$set': {'is_verified': True,  "otp.is_used": True}})
                log_action(user['uuid'], user['role'], "otp-verification", data)
                return jsonify({'message': 'OTP verification successful'}), 200  # OK
            else:
                return jsonify({'error': 'OTP has expired or already used'}), 400  # Bad Request
        else:
            return jsonify({'error': 'Invalid OTP or Email'}), 400  # Bad Request

class ValidateTokenView(MethodView):
    
    def get(self):
        log_request()
        try:
            
            verify_jwt_in_request()
            current_user = get_jwt_identity()
            jwt_claims = get_jwt()

            
            token_info = {
                "valid": True,
                "message": "Token is valid",
                "user_identity": current_user,
                "token_claims": jwt_claims,  
                "expires_at": jwt_claims.get("exp", None),
                "issued_at": jwt_claims.get("iat", None),  
                "jti": jwt_claims.get("jti", None)  
            }

            return jsonify(token_info), 200

        except DecodeError:
            return jsonify({
                "valid": False,
                "error": "Invalid token format"
            }), 401  

        except InvalidTokenError:
            return jsonify({
                "valid": False,
                "error": "Token has expired or is invalid!"
            }), 401  

        except Exception as e:
            logging.error(f"Token validation error: {str(e)}")
            return jsonify({
                "valid": False,
                "error": str(e)
            }), 401  
         
class RefreshTokenView(MethodView):
    decorators = [jwt_required(refresh=True)]

    def get(self):
        log_request()
        try:
            current_user = get_jwt_identity()
            new_access_token = create_access_token(identity=current_user)
            new_refresh_token = create_refresh_token(identity=current_user)
            return jsonify({
                "access_token": new_access_token,
                "refresh_token": new_refresh_token
            }), 200
        except Exception as e:
            logging.error(f"Error during token refresh: {str(e)}")
            return jsonify({"error": str(e)}), 401
        
        
class SearchAddressAutoCompleteView(MethodView):
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

        # Extract individual query parameters from the request
        format_type = request.args.get('format', 'json')
        query = request.args.get('q')
        limit = request.args.get('limit', 5)

        # Validate required parameters
        if not query:
            return jsonify({"error": "Query parameter 'q' is required"}), 400

        # Construct the URL with the separate query parameters
        api_url = f"http://192.168.36.100/search.php?format={format_type}&q={requests.utils.quote(query)}&limit={limit}"

        current_app.logger.info(f"Constructed API URL: {api_url}")

        try:
            # Make the request to the external API
            response = requests.get(api_url)
            response.raise_for_status()  # Raise an error for bad status codes
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Request to external API failed: {e}")
            return jsonify({"error": "External API request failed"}), 500

        # Return the JSON response from the external API
        return jsonify(response.json())
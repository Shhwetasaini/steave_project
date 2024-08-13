import hashlib
import os
import uuid
import logging
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, messaging
from bson import ObjectId
from flask import current_app, request, url_for
from werkzeug.utils import secure_filename  
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To
from datetime import timezone
from geopy.geocoders import GoogleV3

logger = logging.getLogger(__name__)


def create_property(property_data):
    try: 
        google_location_api_key = current_app.config['GOOGLE_LOCATION_API_KEY']
        geocoder = GoogleV3(api_key=google_location_api_key)  
        location = geocoder.geocode(property_data['address'])
        if location:
            property_data['latitude'] = location.latitude
            property_data['longitude'] = location.longitude
            
        result = current_app.db.properties.insert_one(property_data)
        property_id = result.inserted_id
        logger.info("Property created successfully.")
        return str(property_id)
    except Exception as e:
        logger.error(f"Error creating property: {str(e)}")
        return False


def send_email(subject, message, recipient):
    try:
        # Replace 'YOUR_SENDGRID_API_KEY' with your actual SendGrid API key
        sg = sendgrid.SendGridAPIClient(current_app.config['SENDGRID_API_KEY'])

        # Set up the sender and recipient
        from_email = Email(current_app.config['MAIL_USERNAME'])  # Change to your verified sender
        to_email = To(recipient)  # Change to your recipient

        # Create a Mail object
        mail = Mail(from_email, to_email)

        # Set the email subject
        mail.subject = subject

        # Set the email content (plain text or HTML)
        mail.content = sendgrid.helpers.mail.Content("text/plain", message)  # Changed 'contents' to 'content'

        # Send an HTTP POST request to /mail/send
        response = sg.send(mail)
        
        # Return status code and headers
        return response.status_code, response.headers
    except Exception as e:
        return 400 , {"error": str(e)}


def get_client_ip():
    """
    Get the client's IP address from the request object in Flask.
    """
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.remote_addr
    return ip


def generate_unique_name(folder_path, base_name):
    full_path = os.path.join(folder_path, base_name)

    if not os.path.exists(full_path):
        return base_name

    filename, file_extension = os.path.splitext(base_name)
    index = 1

    while os.path.exists(os.path.join(folder_path, f"{filename}_{index}{file_extension}")):
        index += 1

    return f"{filename}_{index}{file_extension}"


def format_phone_number(phone):
    # Check if phone is not None
    if phone is not None:
        # Remove non-numeric characters except the plus sign
        formatted_number = ''.join(filter(str.isdigit, phone))
        if not formatted_number.startswith('+'):
            formatted_number = '+' + formatted_number
        return formatted_number
    else:
        return None


def is_valid(coupon):
    """
    Check if the coupon is currently valid.
    """
    return coupon['expiration_date'] >= timezone.now().date()


def validate_address(address):

    # Use Google Maps Geocoding API to validate the entered address
    google_location_api_key = current_app.config['GOOGLE_LOCATION_API_KEY']
    
    geocoder = GoogleV3(api_key=google_location_api_key)
    try:
        location = geocoder.geocode(address)
        if location:
            address_components = location.raw['address_components']
            # Check if the address contains necessary components (e.g., country, state, postal code)
            has_country = any('country' in component['types'] for component in address_components)
            has_state = any('administrative_area_level_1' in component['types'] for component in address_components)
            has_postal_code = any('postal_code' in component['types'] for component in address_components)
            if has_country and has_state and has_postal_code:
                return True
    except Exception as e:
        pass
    return False

def save_panoramic_image(panoramic_image, user, property_id):
    try:
        org_filename = secure_filename(panoramic_image.filename)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}_{org_filename}"
        user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_properties', str(user['uuid']), str(property_id), 'panoramic_image')
        os.makedirs(user_media_dir, exist_ok=True)

        if os.path.exists(os.path.join(user_media_dir, filename)):
            return {'error': 'File with the same name already exists in the folder'}
        
        image_path = os.path.join(user_media_dir, filename)
        panoramic_image.save(image_path)
        image_url = url_for('serve_media', filename=os.path.join('user_properties', str(user['uuid']), str(property_id), 'panoramic_image', org_filename))

        return {'image_url':image_url, 'filename': filename}
    except Exception as e:
        return  {'error': str(e)}

def get_receivers(user_role_key, user_uuid, query=None):
    pipeline = [
        {
            '$match': {
                user_role_key: user_uuid
            }
        },
        {
            '$project': {
                '_id': 0,
                'property_id': 1,
                'other_user_id': f"${'buyer_id' if user_role_key == 'seller_id' else 'seller_id'}",
                'last_message': {'$arrayElemAt': ['$message_content', -1]}
            }
        }
    ]
    receivers = list(current_app.db.buyer_seller_messaging.aggregate(pipeline))
    if query:
        filtered_receivers = []
        query_lower = query.lower()
        for receiver in receivers:
            other_user = current_app.db.users.find_one({'uuid': receiver['other_user_id']}, {'email': 1, 'first_name': 1, 'last_name': 1, 'profile_pic': 1, '_id': 0})
            if other_user:
                if query_lower in (other_user.get('first_name') or '').lower() or \
                   query_lower in (other_user.get('last_name') or '').lower() or \
                   query_lower in (other_user.get('email') or '').lower():
                    receiver['email'] = other_user.get('email')
                    receiver['first_name'] = other_user.get('first_name')
                    receiver['last_name'] = other_user.get('last_name')
                    receiver['profile_pic'] = other_user.get('profile_pic')
                    receiver['user_id'] = receiver.pop('other_user_id')
                    filtered_receivers.append(receiver)
        return filtered_receivers
    
    for receiver in receivers:
        other_user = current_app.db.users.find_one({'uuid': receiver['other_user_id']}, {'email': 1, 'first_name': 1, 'last_name': 1, 'profile_pic': 1, '_id': 0})
        property_details = current_app.db.properties.find_one({'_id': ObjectId(receiver['property_id'])}, {'address': 1, 'images': 1,  '_id': 0})
        receiver['property_address'] = property_details['address'] if property_details else None
        receiver['property_images'] = property_details['images'] if property_details else None
        receiver['email'] = other_user.get('email') if other_user else None
        receiver['first_name'] = other_user.get('first_name') if other_user else None
        receiver['last_name'] = other_user.get('last_name') if other_user else None
        receiver['profile_pic'] = other_user.get('profile_pic') if other_user else None
        receiver['user_id'] = receiver.pop('other_user_id')
        receiver['time'] = datetime.now().strftime("%Y%m%d%H%M%S")
    return receivers


def search_messages(user_uuid, query):
    pipeline = [
        {
            '$match': {
                '$or': [
                    {'buyer_id': user_uuid},
                    {'seller_id': user_uuid}
                ]
            }
        },
        {
            '$unwind': '$message_content'
        },
        {
            '$match': {
                '$or': [
                    {'message_content.message': {'$regex': query, '$options': 'i'}},
                    {'message_content.media': {'$regex': query, '$options': 'i'}}
                ]
            }
        },
        {
            '$project': {
                '_id': 0,
                'property_id': 1,
                'message': '$message_content.message',
                'media': '$message_content.media',
                'timestamp': '$message_content.timestamp',
                'user_id': {
                    '$cond': {
                        'if': {'$eq': ['$buyer_id', user_uuid]},
                        'then': '$seller_id',
                        'else': '$buyer_id'
                    }
                }
            }
        },
        {
            '$lookup': {
                'from': 'users',
                'localField': 'user_id',
                'foreignField': 'uuid',
                'as': 'user_details'
            }
        },
        {
            '$unwind': '$user_details'
        },
        {
            '$project': {
                'property_id': 1,
                'message': 1,
                'media': 1,
                'timestamp': 1,
                'user_details.email': 1,
                'user_details.first_name': 1,
                'user_details.last_name': 1,
                'user_details.profile_pic': 1
            }
        }
    ]
    messages = list(current_app.db.buyer_seller_messaging.aggregate(pipeline))
    return messages


def search_customer_property_mesage(query, user_uuid):
    # Search criteria
    search_criteria = {
        "$and": [
            {"user_id": user_uuid},
            {
                "$or": [
                    {"property_address": {"$regex": query, "$options": "i"}},
                    {"message_content.message": {"$regex": query, "$options": "i"}},
                    {"message_content.media": {"$regex": query, "$options": "i"}}
                ]
            }
        ]
    }


    results = current_app.db.users_customer_service_property_chat.find(search_criteria)
    response = []
    user_list = []
    user_results = current_app.db.users_customer_service_property_chat.find()
    name = "Customer-Service"
    for user_result in user_results:
        if query.lower() in name.lower():
            user_dict =  {
                "email": "",
                "first_name": "Customer",
                "last_message": {},
                "last_name": "Service",
                "profile_pic": "",
                "property_id": user_result.get('property_id'),
                "user_id": ""
            }
            user_list.append(user_dict)
    for result in results:
        matched_columns = []
        if query.lower() in result.get('property_address', '').lower():
            matched_columns.append({
                "matched_column": "property_address",
                "matched_value": result.get('property_address')
            })

        for message in result.get('message_content', []):
            if 'message' in message and query.lower() in message['message'].lower():
                matched_columns.append({
                    "matched_column": "message",
                    "matched_value": message['message']
                })
            elif 'media' in message and query.lower() in message['media'].lower():
                matched_columns.append({
                    "matched_column": "media",
                    "matched_value": message['media']
                })

            if matched_columns:
                for matched in matched_columns:
                    response.append({
                        "property_id": result.get('property_id'),
                        "timestamp": message.get('timestamp'),
                        matched["matched_column"]: matched["matched_value"],
                        "user_details": {
                            "email": "",
                            "first_name": "Customer",
                            "last_name": "Service",
                            "profile_pic": ""
                        }
                    })
                matched_columns = []

    return (response, user_list)


def search_customer_service_mesage(query, user_uuid):
    # Search criteria
    
    search_criteria = {
        "$and": [
            {"user_id": user_uuid},
            {
                "$or": [
                    {"messages.message": {"$regex": query, "$options": "i"}},
                    {"messages.media": {"$regex": query, "$options": "i"}}
                ]
            }
        ]
    }

    results = current_app.db.messages.find(search_criteria)
    response = []
    for result in results:
        matched_columns = []
        for message in result.get('messages', []):
            if 'message' in message and query.lower() in message['message'].lower():
                matched_columns.append({
                    "matched_column": "message",
                    "matched_value": message['message']
                })
            elif 'media' in message and query.lower() in message['media'].lower():
                matched_columns.append({
                    "matched_column": "media",
                    "matched_value": message['media']
                })

            if matched_columns:
                for matched in matched_columns:
                    response.append({
                        "timestamp": message.get('timestamp'),
                        matched["matched_column"]: matched["matched_value"],
                        "user_details": {
                            "email": "",
                            "first_name": "Customer",
                            "last_name": "Support",
                            "profile_pic": ""
                        }
                    })
                matched_columns = []

    return response

def validate_property_type(property_type):
    valid_types = ['Single_Family', 'Multifamily', 'Condo', 'Townhouse']
    return property_type in valid_types


def validate_property_status(property_status):
    valid_statuses = ['For Sale', 'Pending', 'Sold']
    return property_status in valid_statuses

from firebase_admin import exceptions  # Import exceptions module

def send_notification(device_token):
    try:
        # Check if Firebase is already initialized
        if not firebase_admin._apps:
            cred = credentials.Certificate('/home/local/API/airebroker-firebase-adminsdk-er6ol-27eb6bb50a.json')
            firebase_admin.initialize_app(cred)

        message_body = "New message received"

        message = messaging.Message(
            notification=messaging.Notification(
                title='Notification',
                body=message_body,
            ),
            token=device_token,
        )

        response = messaging.send(message)
        return {"success": "Notification sent", "response": response}
    except exceptions.FirebaseError as e:
        # Handle specific Firebase errors
        return {"error": str(e), "detail": "Check if the device token is valid and associated with the correct Firebase project."}
    except Exception as e:
        # Handle any other exceptions
        return {"error": str(e)}
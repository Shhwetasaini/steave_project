import hashlib
import os
import uuid
import logging
from datetime import datetime

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
        result = current_app.db.properties.insert_one(property_data)
        property_id = result.inserted_id
        logger.info("Property created successfully.")
        return str(property_id)
    except Exception as e:
        logger.error(f"Error creating property: {str(e)}")
        return False


def send_email(subject, message, recipient):
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
    geocoder = GoogleV3(api_key='AIzaSyCPFDGMxu0OwtR6skUVt2e_pIY6TOFF42E')
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

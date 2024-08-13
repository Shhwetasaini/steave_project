# In myapp/views.py
import base64
import phonenumbers
import logging
import os
import re
import stripe
import fitz
from datetime import datetime
from geopy.geocoders import GoogleV3
from email_validator  import validate_email, EmailNotValidError
from bson import ObjectId
from werkzeug.utils import secure_filename

from flask import session, current_app, request, jsonify, url_for
from flask_jwt_extended import get_jwt_identity
from app.services.authentication import custom_jwt_required, log_action
from app.services.admin import log_request
from flask.views import MethodView


from app.services.properties import (
    create_property,
    generate_unique_name,
    get_client_ip,
    send_email,
    is_valid,
    validate_address,
    validate_property_type,
    validate_property_status
)


logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = 'sk_test_51ObRVYDBozxLjRB4vlgKvA7OOJAp6WYTlOqjQJ2e1AmngXP5aiQBvVZzehDAntHcVJsj6tUi2k4kuQRWwIHcDFCd003B5WogrF'
stripe.api_key = STRIPE_SECRET_KEY



class PropertyTypeSelectionView(MethodView):
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
            return jsonify({'error': 'Unauthorized access'}), 401
        
        data = request.json
        property_address = data.get('seller_address',None)
        property_type = data.get('property_type',None)
        property_status = data.get('status', None)


        if not property_address or not property_type:
            return jsonify({"error":"seller_address and property_type field is required"}), 400

        if property_address.isdigit():
          return jsonify({'error': 'seller_address and property_type field is required'}), 400
        
        # Check if the address contains "US" or "United States" or "États-Unis"
        if not re.search(r'\b(US|United States|USA|États-Unis|U\.S\.?)\b', property_address, flags=re.IGNORECASE):
            return jsonify({'error': 'Please enter a valid address in the United States.'}), 400
        
        # Check if seller_property_address is present in e_sign_data and contains mn, minnesota, fl, or florida
        if not any(keyword in  property_address.lower() for keyword in ['mn', 'minnesota', 'fl', 'florida']):
            return jsonify({'error': "The address must be located in Minnesota (MN) or Florida (FL)."}), 400
        
        valid_address = validate_address(property_address)
        if not valid_address:
            return jsonify({'error': "Invalid Address. missing country, state or postal_code"}), 400
           
        # Validate property_type
        valid_property_type = validate_property_type(property_type)
        if not valid_property_type:
            return jsonify({'error': f"Invalid property_type. applicable types are: [Condo, Townhouse, Single_Family, Multifamily]"}), 400
        
        # Validate property_status
        if property_status is not None and property_status != '':
            valid_status = validate_property_status(property_status)
            if not valid_status:
                return jsonify({'error': f"Invalid status. applicable status are: [For Sale, Pending, Sold, Cancelled]"}), 400
            
        property_data = {
            'type': property_type,
            'address': property_address,
            'images': [],
            'panoramic_images': [],
            "name": data.get('name', None),
            "status": property_status,
            "construction": data.get('construction', None),
            "state": data.get('state', None),
            "city": data.get('city', None),
            "latitude": float(data.get('latitude', 0.0) or 0.0),
            "longitude": float(data.get('longitude', 0.0) or 0.0),
            "beds": int(data.get('beds', 0) or 0),
            "baths": int(data.get('baths', 0) or 0),
            "full_bathrooms": int(data.get('full_bathrooms', 0) or 0),
            "half_bathrooms": int(data.get('half_bathrooms', 0) or 0),
            "kitchen": int(data.get('kitchen', 0) or 0),
            "description": data.get('description', None),
            "price": float(data.get('price', 0.0) or 0.0),
            "size": float(data.get('size', 0.0) or 0.0),
            "built_in": data.get('built_in', None),
            "attached_garage": int(data.get('attached_garage', 0) or 0),
            "garage_size": float(data.get('garage_size', 0.0) or 0.0),
            "appliances": data.get('appliances', []),
            "kitchen_features": data.get('kitchen_features', []),
            "features": data.get('features', []),
            "type_and_styles": data.get('type_and_styles', []),
            "materials": data.get('materials', []),
            "listed_date": data.get('listed_date', None),
            "last_updated_date": data.get('last_updated_date', None),
            "available_viewing_times": data.get('available_viewing_times', []),
            "open_house_times": data.get('open_house_times', [])
        }       

        property_id = create_property(property_data)
        if not property_id:
            return jsonify({'error': 'Failed to create property.'}), 400
        logger.info('Property created successfully')
        property_data['property_id'] = property_id
        
        user_info = {
            'first_name': user['first_name'],
            'last_name': user['last_name'],
            'email': user['email'],
            'phone': user['phone'],
            'user_id': user['uuid']
        }
        property_data.pop('_id', None)
        transaction_result = current_app.db.transaction.insert_one({
            'property_data': property_data,
            'user_info': user_info,
            'amount': None,
            'signed_property_contract': None
        })

        if transaction_result.inserted_id:
            transaction_id = str(transaction_result.inserted_id)
            logger.info('Transaction created successfully')
        else:
            return jsonify({'error': 'Failed to create transaction.'}), 400
        data['property_id'] = property_id
        data['transaction_id'] = transaction_id
        log_action(user['uuid'], user['role'], "selected-property_address and property_type", data)
        return jsonify({'message':'data saved successfully.', 'transaction_id': transaction_id}), 201


class PropertyTourView(MethodView):
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
            return jsonify({'error': 'Unauthorized access'}), 401

        data = request.json
        property_id = data.get('property_id')
        tour_request_data = data.get('request_tour')

        try:
            requester_name = tour_request_data.get('requester_name')
            requester_id = tour_request_data.get('requester_id')
            requested_datetime = datetime.fromisoformat(tour_request_data.get('requested_datetime'))

            property_details = current_app.db.properties.find_one({'_id': ObjectId(property_id)})
            if not property_details:
                return jsonify({'error': 'Property not found'}), 404

            # Fetch owner information from the transaction collection using property_id
            transaction_info = current_app.db.transaction.find_one({'property_data.property_id': property_id})
            if not transaction_info:
                return jsonify({'error': 'Transaction information not found'}), 404

            owner_info = transaction_info['user_info']
            open_house_times = property_details.get('open_house_times', [])
            if requested_datetime in open_house_times:
                return jsonify({'error': 'Requested time overlaps with an open house event'}), 400

            owner_email = owner_info['email']

            subject = 'Property Tour Request'
            message = (f"Request for tour on {requested_datetime} from {requester_name} ({requester_id}).")
            status_code, response = send_email(subject, message, owner_email)

            if status_code == 400:
                return jsonify({'error': response['error']}), 400

            return jsonify({'message': 'Tour request sent successfully'}), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 400

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

        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 401

        data = request.json
        property_id = data.get('property_id')
        available_times = data.get('available_viewing_times', [])
        open_house_times = data.get('open_house_times', [])

        try:
            available_times = [datetime.fromisoformat(time) for time in available_times]
            open_house_times = [datetime.fromisoformat(time) for time in open_house_times]
        except ValueError:
            return jsonify({'error': 'Invalid datetime format in available_viewing_times or open_house_times'}), 400

        property_details = current_app.db.properties.find_one({'_id': ObjectId(property_id)})

        if not property_details:
            return jsonify({'error': 'Property not found'}), 404

        current_app.db.properties.update_one(
            {'_id': ObjectId(property_id)},
            {'$set': {
                'available_viewing_times': available_times,
                'open_house_times': open_house_times
            }}
        )

        return jsonify({'message': 'Available viewing times and open house times updated successfully'}), 200
        

class PropertyUploadImageView(MethodView):
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

        data = request.form
        transaction_id = data.get('transaction_id')
        labels = request.form.getlist('labels')
        images = request.files.getlist("images")
        

        if not transaction_id or not labels:
            return jsonify({'error':'Missing transacion_id or label'}), 400
        
        if len(labels) != len(images):
            return jsonify({'error': "label and images should be same length"}), 400
        
        transaction_data = current_app.db.transaction.find_one({"_id": ObjectId(transaction_id)})
        if not transaction_data:
            return jsonify({'error':'Invalid Transaction'}), 400
        
        #Check for incorrect or used transaction
        existing_transaction = current_app.db.property_seller_transaction.find_one(
            {
             'transaction_id': transaction_id, 
             'property_id': transaction_data['property_data']['property_id']
            }
        )
        if existing_transaction:
            return jsonify({'error':'Invalid transaction, transaction already exist for this property'}), 400
        
        uploaded_images = 0
        image_urls = []
        if images:
            try:
                for label,image in zip(labels,images):
                    # Save image and get URL
                    org_filename = secure_filename(image.filename)
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    filename = f"{timestamp}_{org_filename}"
                    user_media_dir = os.path.join(
                        current_app.config['UPLOAD_FOLDER'], 
                        'user_properties', transaction_data['user_info']['user_id'], 
                        transaction_data['property_data']['property_id']
                    )
                    os.makedirs(user_media_dir, exist_ok=True)
                    image_path = os.path.join(user_media_dir, filename)
                    image.save(image_path)
                    # Generate URL for accessing the saved image
                    image_url = url_for(
                        'serve_media', 
                        filename=os.path.join(
                            'user_properties', 
                            transaction_data['user_info']['user_id'], 
                            transaction_data['property_data']['property_id'], 
                            filename
                        )
                    )
                    image_urls.append({'label': label, 'name': filename, 'image_url': image_url})
                
                current_app.db.properties.update_one(
                    {"_id": ObjectId(transaction_data['property_data']['property_id'])},
                    {"$set": {"images": image_urls}}
                )
                current_app.db.transaction.update_one(
                    {"_id": ObjectId(transaction_id)},
                    {"$set": {"property_data.images": image_urls}}
                )
                uploaded_images = len(image_urls)
                
            except Exception as e:
                logger.error(f"Error Uploading property images: {str(e)}")
                return jsonify({'error':'Failed to upload image'}), 400
            
        payload = {
            "transaction_id":transaction_id, 
            "property_id": transaction_data['property_data']['property_id'], 
            "images": image_urls
        }
        log_action(user['uuid'],user['role'], "added-property-images", payload)
        return jsonify({'message':'data saved successfully.', 'uploaded_images':uploaded_images}), 200


class SavePdfView(MethodView):
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

        data = request.json
        transaction_id = data.get('transaction_id')
        signature_data = data.get('signature_data')
        logger.info(signature_data)
        if not transaction_id or not signature_data:
            return jsonify({'error':'Missing transacion_id or signature_data'}), 400
        
        transaction = current_app.db.transaction.find_one({'_id': ObjectId(transaction_id)})
        if not transaction:
            return jsonify({'error':'Invalid Transaction'}), 400
        
         
        #Check for incorrect or used transaction
        existing_transaction = current_app.db.property_seller_transaction.find_one({"transaction_id": transaction_id, 'property_id': transaction['property_data']['property_id']})
        if existing_transaction:
            return jsonify({'error':'Invalid transaction, transaction already exist for this property'}), 400
        
        template_pdf = None
        signature_pdf = None
        signature_file_path = None
        data = request.json

        try:
            _, encoded_data = signature_data.split(',', 1)
            binary_data = base64.b64decode(encoded_data)
            property_address = transaction.get('property_data')['address'].lower()
            if 'mn' in property_address or 'minnesota' in property_address:
                template_path = '/home/local/API/seller.pdf'
            elif 'fl' in property_address or 'florida' in property_address:
                template_path = '/home/local/API/florida.pdf'
            else:
                return jsonify({'error': 'Invalid property_address.'}), 400
            
            signer_name = f"{transaction.get('user_info')['first_name']}_{transaction.get('user_info')['last_name']}"
            folder_path = os.path.join(current_app.root_path, 'media', 'Home', 'sign')
            os.makedirs(folder_path, exist_ok=True)
            signature_file_name = f"{signer_name}_signature.png"
            signature_file_path = os.path.join(folder_path, signature_file_name)
            with open(signature_file_path, 'wb') as file:
                file.write(binary_data)
            template_pdf = fitz.open(template_path)
            signature_pdf = fitz.open(signature_file_path)
            # Debugging: Print the page count
            print("Number of pages in the template PDF:", template_pdf.page_count)
            first_page = template_pdf[0]
            first_page.insert_text((20, 20), f"User IP: {get_client_ip()}")
            if template_pdf.page_count >= 4:
                fifth_page = template_pdf[3]  # Adjusted page number to exist within the document's range
                rect = fitz.Rect(430, 0, 625, 850)
                fifth_page.insert_image(rect, pixmap=signature_pdf[0].get_pixmap(), keep_proportion=True)
            else:
                return jsonify({"error":"PDF does not have enough pages to insert the signature."}), 400
            
            unique_filename = generate_unique_name(folder_path, f"{signer_name}_signed_document.pdf")
            file_path = os.path.join(folder_path, unique_filename)
            template_pdf.save(file_path)
            
            doc_url = url_for('serve_media', filename=os.path.join('Home','sign', unique_filename))

            document_data = {
                'user_name':user.get('first_name') +" "+ user.get('last_name'),
                'property_name':transaction.get('property_data').get('name'),
                'property_address':transaction.get('property_data').get('address'),
                'name': unique_filename,
                'url': doc_url,
                'type': 'signed_property_contract',
                'uploaded_at': datetime.now()
            }

            # Update the uploaded_documents collection
            current_app.db.users_uploaded_docs.update_one(
                {'uuid': transaction.get('user_info')['user_id']},
                {'$push': {'uploaded_documents': document_data}},
                upsert=True
            )
            
            current_app.db.transaction.update_one({"_id": ObjectId(transaction_id)}, {"$set": {"signed_property_contract": doc_url}})

            document_data['transaction_id'] = transaction_id
            document_data['property_id'] =  transaction['property_data']['property_id']
            document_data.pop('_id', None)
            log_action(user['uuid'], user['role'], "signed-property_contract", document_data) 
            return jsonify({'message':'data saved successfully.'}), 200
        except Exception as e:
            print("Error during PDF generation:", str(e))
            return jsonify({'error': str(e)}), 500
        finally:
            if template_pdf:
                template_pdf.close()
            if signature_pdf:
                signature_pdf.close()
            if signature_file_path:
                os.remove(signature_file_path)
        

class CheckoutView(MethodView):
    decorators = [custom_jwt_required()]
    def post(self):
        logger.info("Checkout process initiated.")
        current_user = get_jwt_identity()
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404

        data = request.json
        transaction_id = data.get('transaction_id')
        token = data.get('token')
        code = data.get('code')
        payment_amount = int(data.get('payment_amount', 997)  or 0)

        if payment_amount != 497 and payment_amount != 997:
            return jsonify({'error':'Invalid payment amount'}), 400
        
        if not transaction_id or not token:
            return jsonify({'error':'Missing transacion_id or card token'}), 400
        
        transaction = current_app.db.transaction.find_one({'_id': ObjectId(transaction_id)})
        if not transaction:
            return jsonify({'error':'Invalid Transaction'}), 400
        
        #Check for incorrect or used transaction
        existing_transaction = current_app.db.property_seller_transaction.find_one({"transaction_id": transaction_id, 'property_id': transaction['property_data']['property_id']})
        if existing_transaction:
            return jsonify({'error':'Invalid transaction, transaction already exist for this property'}), 400
        
        coupon = current_app.db.coupon.find_one({'code': code})
        if coupon:
            if is_valid(coupon):
                amount = int(coupon['discount_amount'] * 100)
            else:
                amount = int(payment_amount) * 100  # Use the payment_amount from the request
        else:
            amount = int(payment_amount) * 100  # Use the payment_amount from the request

        logger.info(f"Token received: {token}, Amount: {amount}")

        try:
            if amount < 100 or amount > 1000000:
                return jsonify({'error':'Invalid amount'}), 400
            
            logger.info("Amount validated.")

            charge = stripe.Charge.create(
                amount=amount,
                currency='usd',
                source=token,
                description='Seller App',
            )
        
            if not (charge.paid and charge.status == 'succeeded'):
                return jsonify({'error': 'Payment failed.'}), 400
            
            logger.info("Charge created successfully.")
            current_app.db.transaction.update_one({'_id':ObjectId(transaction_id)}, {'$set': {'amount': amount}})
            
            lookup_data = {
                "transaction_id": transaction_id,
                "property_id": transaction['property_data']['property_id'], 
                "seller_id": transaction['user_info']['user_id'],
                "realtors": []  
            }
            # Insert lookup data into the lookup table
            current_app.db.property_seller_transaction.insert_one(lookup_data)
            
            subject = 'Welcome to Our Platform'
            message = 'Thank you for signing up. We appreciate your business.'
            recipient_email =  transaction['user_info']['email']
            
            # Replace `send_email` with your actual email sending function
            status_code, headers = send_email(subject, message, recipient_email)
            if status_code == 202:
                transaction.pop('_id', None)
                lookup_data.pop('_id', None)
                payload = {
                    'transaction':transaction,
                    'property_seller_transaction': lookup_data
                } 
                log_action(user['uuid'],user['role'], "purchassed-property", payload)
                logger.info("Email sent successfully.")
                return jsonify({'message': 'Property purchase succesfull.'}), 201  # Specify the success URL
            else:
                logger.error("Failed to send email.")
                return jsonify({'error': 'Failed to send email.'}), 400

        except stripe.error.CardError as e:
            logger.error(f"Stripe card error: {e}")
            return jsonify({'error': str(e)}), 400

        except ValueError as ve:
            logger.error(f"Invalid amount error: {ve}"), 400
            return jsonify({'error': str(ve)})
        
        except Exception as e:
            logger.error(f"Failed to checkout: {e}")
            return jsonify({'error': str(e)}), 400

from datetime import datetime
import werkzeug
import logging
import os
from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify, request, url_for
from flask_jwt_extended import get_jwt_identity

from flask import current_app
from app.services.admin import log_request
from app.services.authentication import custom_jwt_required, log_action
from app.services.media import extract_first_page_as_image, document_exists, resource_exists



class ReceiveMediaView(MethodView):
    decorators = [custom_jwt_required()]

    def post(self):
        log_request(request)
        current_user = get_jwt_identity()
        
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        # Handle both JSON and multipart/form-data for receiving files
        if request.content_type.startswith('multipart/form-data'):
            file = request.files.get('file')
            label = request.form.get('label', 'no_label')

            if ' ' in label:
                return jsonify({'error':'Spaces are not allowed in the label!'}), 200

            if not file:
                return jsonify({'error':'file is missing!'}), 200

            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'users_media', str(user['uuid']))
            os.makedirs(user_media_dir, exist_ok=True)

            if file and werkzeug.utils.secure_filename(file.filename):
                org_filename = werkzeug.utils.secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"{timestamp}_{label}_{org_filename}"
                user_media_path = os.path.join(user_media_dir, filename)
                file.save(user_media_path)
                media_url = url_for('serve_media', filename=os.path.join('users_media', str(user['uuid']), filename))
                
                uploaded_media = [{'file': media_url, 'label': label}]

                # Update the media collection
                current_app.db.media.update_one(
                    {'user_id': user['uuid']},
                    {'$push': {'user_media': {'$each': uploaded_media}}},
                    upsert=True
                )
        elif request.is_json:
            # Handle JSON content if needed. This block is placeholder for future expansion.
            pass
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200

        log_action(user['uuid'], user['role'], "uploaded-media", uploaded_media)
        return jsonify({"message": "File successfully received"}), 200


class SendMediaView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        all_media = current_app.db.media.find_one({'user_id': user['uuid']}, {'_id': 0})

        if not all_media:
            return jsonify([]), 200
        
        log_action(user['uuid'], user['role'], "viewed-media",None)      
        return jsonify(all_media.get('user_media')), 200


class DeleteMediaView(MethodView):
    decorators = [custom_jwt_required()]

    def delete(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        # Check if file URL is provided
        file_url = request.form.get('file_url')
        if not file_url:
            return jsonify({'error': 'File URL is missing!'}), 200

        # Extract the filename from the URL
        file_name = os.path.basename(file_url)
     
        # Delete the file from the server
        user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'users_media', str(user['uuid']))
        file_path = os.path.join(user_media_dir, file_name)
       
        if os.path.exists(file_path):
            os.remove(file_path)
        else:
            return jsonify({'error': 'File not found on the server!'}), 200

        # Update the media collection in the database
        current_app.db.media.update_one(
            {'user_id': user['uuid']},
            {'$pull': {'user_media': {'file': file_url}}},
            upsert=True
        )
        log_action(user['uuid'], user['role'], "deleted-media", {'file': file_url})
        return jsonify({'message': 'File deleted successfully'}), 200
    

class DownloadDocView(MethodView):
    decorators = [custom_jwt_required()]
    
    def post(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200
        
        name = data.get('filename')

        if not name:
            return jsonify({"error": "name is missing!"}), 200

        document = current_app.db.documents.find_one({'name':name})

        if not document:
            return jsonify({'error':"document does not exist!"}),  200

        document_data = {
            'name': document['name'],
            'url': document['url'],
            'type': document['type'],
            'downloaded_at': datetime.now()
        }

        # Check if the document already exists for the user in downloaded_documents
        query = {
            "uuid": user['uuid'],
            "downloaded_documents": {
                "$elemMatch": {
                    "name": document_data['name']
                }
            }
        }
        existing_document = current_app.db.users_downloaded_docs.find_one(query)
        
        if existing_document:
            current_app.db.users_downloaded_docs.update_one(
                query,
                {'$set': {'downloaded_documents.$.is_signed': document_data['is_signed']}}
            )
            log_action(user['uuid'], user['role'], "downloaded-document", document_data)
            return jsonify({"message": "Document already exists for the user. Updated."}), 200
        else:
            # Add the new document to the user's downloaded_documents field
            current_app.db.users_downloaded_docs.insert_one(
                {'uuid': user['uuid'], 'downloaded_documents':[document_data]}
            )
            log_action(user['uuid'], user['role'], "downloaded-document", document_data)
            return jsonify({"message": "Document successfully added to user's documents"}), 200

   
class UploadDocView(MethodView):
    decorators = [custom_jwt_required()]

    def put(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        file = request.files.get('file')
        if not file:
            return jsonify({'error': 'File is missing!'}), 400

        if file and werkzeug.utils.secure_filename(file.filename):
            org_filename = werkzeug.utils.secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"{timestamp}_{org_filename}"
            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
            os.makedirs(user_media_dir, exist_ok=True)
            user_doc_path = os.path.join(user_media_dir, filename)
            file.save(user_doc_path)
            doc_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))

            document_data = {
                'name': file.filename,
                'url': doc_url,
                'type': None,
                'uploaded_at': datetime.now()
            }

            # Update the uploaded_documents collection
            current_app.db.users_uploaded_docs.update_one(
                {'uuid': user['uuid']},
                {'$push': {'uploaded_documents': document_data}},
                upsert=True
            )
         
            log_action(user['uuid'], user['uuid'], "uploaded-document", document_data)
            return jsonify({"message": "File successfully uploaded!", "uploaded-document": document_data}), 200
        else:
            return jsonify({"error": "File is missing or invalid filename."}), 400


class AllDocsView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        flforms_docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms')
        mnforms_docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms')

        for forms_dir in [flforms_docs_dir, mnforms_docs_dir]:
            forms_type = "FL_Forms" if forms_dir == flforms_docs_dir else "MN_Forms"
            for folder in os.listdir(forms_dir):
                folder_path = os.path.join(forms_dir, folder)
                if os.path.isdir(folder_path):
                    for file in os.listdir(folder_path):
                        if file.endswith('.pdf'):
                            doc_name = file
                            doc_url = url_for('serve_media', filename=os.path.join('templates/' + forms_type, folder, file).replace('\\', '/'))
                            preview_page_url = doc_url[:-4] + '.jpg'

                            # Check if document already exists in MongoDB
                            if not document_exists(doc_name):
                                image_name = extract_first_page_as_image(os.path.join(folder_path, file))
                                if image_name:
                                    # Check if preview image already exists in MongoDB and fo   lder
                                    if not resource_exists(preview_page_url, doc_url):
                                        # Store data in MongoDB
                                        document_data = {
                                            'name': doc_name,
                                            'url': doc_url,
                                            'added_at': datetime.now(),
                                            'preview_image': preview_page_url,
                                            'description': "",
                                            'type': forms_type,
                                            'folder': folder
                                        }
                                        current_app.db.documents.insert_one(document_data)

        # Retrieve data from MongoDB and return as JSON response
        documents = list(current_app.db.documents.find({}, {"_id": 0}))
        log_action(user['uuid'], user['uuid'], "viwed-all-document", None)
        return jsonify(documents), 200


class UserDownloadedDocsView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request(request)
        current_user = get_jwt_identity()
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        if user:
            user_docs = current_app.db.users_downloaded_docs.find_one({'uuid': user['uuid']}, {'downloaded_documents': 1, '_id': 0})
            if not user_docs:
                return jsonify([]), 200
            log_action(user['uuid'], user['role'], "viewed-downloaded-docs", None)
            return jsonify(user_docs['downloaded_documents']), 200
        else:
            return jsonify({'error': 'User not found'}), 200


class UserUploadedDocsView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request(request)
        current_user = get_jwt_identity()
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        if user:
            user_docs = current_app.db.users_uploaded_docs.find_one({'uuid': user['uuid']}, {'uploaded_documents': 1, '_id': 0})
            if not user_docs:
                return jsonify([]), 200
            log_action(user['uuid'], user['role'], "viewed-downloaded-docs", None)
            return jsonify(user_docs['uploaded_documents']), 200
        else:
            return jsonify({'error': 'User not found'}), 200

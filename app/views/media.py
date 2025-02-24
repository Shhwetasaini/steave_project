from datetime import datetime, timedelta
import werkzeug
from bson import ObjectId
import requests
import os
import urllib
from email_validator import validate_email, EmailNotValidError
from pymongo.errors import OperationFailure
from flask.views import MethodView
from flask import jsonify, logging, request, url_for
from flask_jwt_extended import get_jwt_identity

from flask import current_app
from app.services.admin import log_request
from app.services.authentication import custom_jwt_required, log_action
from app.services.media import (
    extract_first_page_as_image, 
    document_exists, resource_exists,
    insert_answer_in_pdf,
    create_user_document,
    send_finalized_document
)
from app.services.properties import get_client_ip


class ReceiveMediaView(MethodView):
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
        # Handle both JSON and multipart/form-data for receiving files
        if not request.content_type.startswith('multipart/form-data'):
            return jsonify({"error": "Unsupported Content Type"}), 415  # Unsupported Media Type

        file = request.files.get('file')
        label = request.form.get('label', 'no_label')

        if ' ' in label:
           return jsonify({'error': 'Spaces are not allowed in the label!'}), 400  # Bad Request

        if not file:
            return jsonify({'error': 'File is missing!'}), 400  # Bad Request

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

            # Update the media collection atomically
            result = current_app.db.media.update_one(
                {'user_id': user['uuid']},
                {'$push': {'user_media': {'$each': uploaded_media}}},
                upsert=True
            )

            if result.modified_count == 0 and result.upserted_id is None:
                return jsonify({'error': 'Failed to update media collection'}), 500  # Internal Server Error
        
        log_action(user['uuid'], user['role'], "uploaded-media", uploaded_media)
        return jsonify({"message": "File successfully received"}), 200  # OK


class SendMediaView(MethodView):
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

        all_media = current_app.db.media.find_one({'user_id': user['uuid']}, {'_id': 0})

        if not all_media or not all_media.get('user_media'):
            return jsonify([]), 200
        
        log_action(user['uuid'], user['role'], "viewed-media", {})      
        return jsonify({'data': all_media.get('user_media')}), 200


class DeleteMediaView(MethodView):
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
            return jsonify({'error': 'User not found'}), 404
        # Check if file URL is provided
        file_url = request.form.get('file_url')
        if not file_url:
            return jsonify({'error': 'File URL is missing!'}), 400

        # Extract the filename from the URL
        file_name = os.path.basename(file_url)

        # Delete the file from the server
        user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'users_media', str(user['uuid']))
        file_path = os.path.join(user_media_dir, file_name)

        if os.path.exists(file_path):
            os.remove(file_path)
        else:
            return jsonify({'error': 'File not found on the server!'}), 404

        # Update the media collection in the database
        result = current_app.db.media.update_one(
            {'user_id': user['uuid']},
            {'$pull': {'user_media': {'file': file_url}}},
            upsert=True
        )

        if result.modified_count == 0 and result.upserted_id is None:
            return jsonify({'error': 'Failed to update media collection'}), 500

        log_action(user['uuid'], user['role'], "deleted-media", {'file': file_url})
        return jsonify({'message': 'File deleted successfully'}), 200


class DownloadDocView(MethodView):
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
        if not request.content_type.startswith('multipart/form-data'):
            return jsonify({"error": "Unsupported Content Type"}), 415
        
        data = request.form
        name = data.get('filename')

        if not name:
            return jsonify({"error": "name is missing!"}), 400  # Bad Request

        document = current_app.db.documents.find_one({'name': name})

        if not document:
            return jsonify({'error': "Document does not exist!"}), 404  # Not Found

        document_data = {
            'doc_id': str(ObjectId()),  # Generate a unique ID for the document
            'name': document['name'],
            'url': document['url'],
            'type': document['type'],
            'state' : document['state'],
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
                {'$set': {'downloaded_documents.$.downloaded_at': document_data['downloaded_at']}}
            )
            log_action(user['uuid'], user['role'], "downloaded-document", document_data)
            return jsonify({"message": "Document already exists for the user. Updated."}), 200
        else:
            current_app.db.users_downloaded_docs.update_one(
                {'uuid': user['uuid']}, 
                {'$push': {'downloaded_documents': document_data}},
                upsert=True
            )
            log_action(user['uuid'], user['role'], "downloaded-document", document_data)
            return jsonify({"message": "Document successfully added to user's documents"}), 200  # Created


class UploadDocView(MethodView):
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
        
        file = request.files.get('file')
        if not file:
            return jsonify({'error': 'File is missing!'}), 400  # Bad Request

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
                'doc_id': str(ObjectId()),  # Generate a unique ID for the document
                'name': file.filename,
                'url': doc_url,
                'type': "user-docs",
                'state': None,
                'uploaded_at': datetime.now()
            }

            # Update the uploaded_documents collection
            current_app.db.users_uploaded_docs.update_one(
                {'uuid': user['uuid']},
                {'$push': {'uploaded_documents': document_data}},
                upsert=True
            )
         
            log_action(user['uuid'], user['uuid'], "uploaded-document", document_data)
            return jsonify({"message": "File successfully uploaded!", "uploaded-document": document_data}), 200  # Created
        else:
            return jsonify({"error": "File is missing or invalid filename."}), 400  # Bad Request
            
            
    def delete(self, doc_id):
        log_request()
        current_user = get_jwt_identity()
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not user:
            return jsonify({'error': 'User not found'}), 404

        doc_id = str(doc_id)

        # Find the document before deleting it
        user_doc = current_app.db.users_uploaded_docs.find_one(
            {'uuid': user['uuid'], 'uploaded_documents.doc_id': doc_id},
            {'uploaded_documents.$': 1}
        )

        if not user_doc or 'uploaded_documents' not in user_doc:
            return jsonify({"error": "No document found with the given ID, or you are unauthorized to delete"}), 404

        # Get the document details
        document = user_doc['uploaded_documents'][0]
        doc_url = document['url']

        # Delete the document from the user's uploaded documents
        user_docs = current_app.db.users_uploaded_docs.update_one(
            {'uuid': user['uuid']},
            {'$pull': {'uploaded_documents': {'doc_id': doc_id}}}
        )

        if user_docs.modified_count > 0:
            # Document was found and deleted from the database
            file_name = os.path.basename(doc_url)
            user_docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
            file_path = os.path.join(user_docs_dir, file_name)
            
            if os.path.exists(file_path):
                os.remove(file_path)
                log_action(user['uuid'], user['role'], "deleted-user-document", {'file': doc_url})
                return jsonify({'message': 'Document deleted successfully'}), 200
            else:
                return jsonify({'error': 'File not found on the server!'}), 404
        else:
            return jsonify({"error": "Failed to delete the document"}), 500
        
    
    def put(self, doc_id):
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
            
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Ensure the doc_id is a valid ObjectId
        try:
            doc_id = str(doc_id)
        except Exception as e:
            return jsonify({'error': 'Invalid document ID'}), 400

        # Find the document to update
        user_doc = current_app.db.users_uploaded_docs.find_one(
            {'uuid': user['uuid'], 'uploaded_documents.doc_id': doc_id},
            {'uploaded_documents.$': 1}
        )

        if not user_doc or 'uploaded_documents' not in user_doc:
            return jsonify({"error": "Document not found or unauthorized"}), 404

        # Prepare updated document data
        updated_document = {}

        file = request.files.get('file')
        if file and werkzeug.utils.secure_filename(file.filename):
            org_filename = werkzeug.utils.secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"{timestamp}_{org_filename}"
            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
            os.makedirs(user_media_dir, exist_ok=True)
            user_doc_path = os.path.join(user_media_dir, filename)
            file.save(user_doc_path)

            # Update document data with the new file
            doc_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))
            updated_document['uploaded_documents.$.name'] = file.filename
            updated_document['uploaded_documents.$.url'] = doc_url

        # Update metadata fields if provided
        if 'type' in request.form:
            updated_document['uploaded_documents.$.type'] = request.form['type']
        if 'name' in request.form:
            updated_document['uploaded_documents.$.name'] = request.form['name']
        
        # Update the document's upload time
        updated_document['uploaded_documents.$.uploaded_at'] = datetime.now()

        # Update the document in the database
        result = current_app.db.users_uploaded_docs.update_one(
            {'uuid': user['uuid'], 'uploaded_documents.doc_id': doc_id},
            {'$set': updated_document}
        )

        if result.matched_count > 0 and result.modified_count > 0:
            # Retrieve the updated document to return it in the response
            updated_doc = current_app.db.users_uploaded_docs.find_one(
                {'uuid': user['uuid'], 'uploaded_documents.doc_id': doc_id},
                {'uploaded_documents.$': 1}
            )
            if updated_doc and 'uploaded_documents' in updated_doc:
                updated_document = updated_doc['uploaded_documents'][0]
                log_action(user['uuid'], user['role'], "updated-user-document", updated_document)
                return jsonify({"message": "Document updated successfully", "updated-document": updated_document}), 200
            else:
                return jsonify({"error": "Failed to retrieve updated document"}), 500
        else:
            return jsonify({"error": "Failed to update the document"}), 500
                    
class UserDownloadedDocsView(MethodView):
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
            user_docs = current_app.db.users_downloaded_docs.find_one(
                {'uuid': user['uuid']},
                {'downloaded_documents': 1, '_id': 0}
            )
            if not user_docs:
                return jsonify([]), 200
          
            log_action(user['uuid'], user['role'], "viewed-downloaded-docs", {})
            return jsonify({'data': user_docs['downloaded_documents']}), 200
        else:
            return jsonify({'error': 'User not found'}), 404  #Not found




class AllDocsView(MethodView):
    
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

        # Extract query parameters for filtering
        query_type = request.args.get('type')
        query_folder = request.args.get('folder')
        recently_used = request.args.get('recently_used')
        start_date = request.args.get('start_date')  # Optional start date filter
        end_date = request.args.get('end_date')  # Optional end date filter

        # Validate the recently_used parameter
        if recently_used not in [None, 'true', 'false']:
            return jsonify({'error': 'Invalid value for recently_used parameter. Expected "true" or "false".'}), 400
        recently_used = recently_used == 'true'

        # Prepare document directories
        flforms_docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms')
        mnforms_docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms')
        folders_set = set()
        types_set = set()

        for forms_dir in [flforms_docs_dir, mnforms_docs_dir]:
            forms_type = "FL_Forms" if forms_dir == flforms_docs_dir else "MN_Forms"
            state = "Florida" if forms_dir == flforms_docs_dir else "Minnesota"
            types_set.add(forms_type)

            for folder in os.listdir(forms_dir):
                folder_path = os.path.join(forms_dir, folder)
                if os.path.isdir(folder_path):
                    folders_set.add(folder)
                    for file in os.listdir(folder_path):
                        if file.endswith('.pdf'):
                            doc_name = file
                            doc_url = url_for('serve_media', filename=os.path.join('templates/' + forms_type, folder, file).replace('\\', '/'))
                            preview_page_url = doc_url[:-4] + '.jpg'
                            
                            # Check if document already exists in MongoDB
                            if not document_exists(doc_name):
                                image_name = extract_first_page_as_image(os.path.join(folder_path, file))
                                if image_name:
                                    # Check if preview image already exists in MongoDB and folder
                                    if not resource_exists(preview_page_url, doc_url):
                                        # Store data in MongoDB
                                        document_data = {
                                            'name': doc_name,
                                            'url': doc_url,
                                            'added_at': datetime.now(),
                                            'preview_image': preview_page_url,
                                            'description': "",
                                            'type': forms_type,
                                            "state": state,
                                            'folder': folder
                                        }
                                        current_app.db.documents.insert_one(document_data)

        # Build the MongoDB query with filters
        query_filter = {}
        if query_type:
            query_filter['type'] = query_type
        if query_folder:
            query_filter['folder'] = query_folder
        if recently_used:
            try:
                thirty_days_ago = datetime.utcnow() - timedelta(days=30)
                query_filter['added_at'] = {"$gte": thirty_days_ago}
            except Exception as e:
                return jsonify({'error': 'Error calculating date for recently used filter.'}), 400

        # Add date range filtering if start_date or end_date is provided
        if start_date or end_date:
            date_filter = {}
            if start_date:
                try:
                    date_filter['$gte'] = datetime.strptime(start_date, "%Y-%m-%d")
                except ValueError:
                    return jsonify({'error': 'Invalid start_date format. Expected YYYY-MM-DD.'}), 400
            if end_date:
                try:
                    date_filter['$lte'] = datetime.strptime(end_date, "%Y-%m-%d")
                except ValueError:
                    return jsonify({'error': 'Invalid end_date format. Expected YYYY-MM-DD.'}), 400
            query_filter['added_at'] = date_filter

        # Retrieve data from MongoDB with filters and return as JSON response
        documents = list(current_app.db.documents.find(query_filter))
        formatted_documents = []
        for doc in documents:
            doc['id'] = str(doc.pop('_id'))
            formatted_documents.append(doc)

        log_action(user['uuid'], user['role'], "viewed-all-documents", {})
        
        response = {
            'data': formatted_documents,
            'filters': {
                'folders': list(folders_set),
                'types': list(types_set)
            },
            "length": len(documents)
        }
        return jsonify(response), 200
    

class UserDocumentsView(MethodView):
    decorators = [custom_jwt_required()]
    
    def get(self):
        try:
            log_request()
            current_user = get_jwt_identity()
            try:
                validate_email(current_user)
                user = current_app.db.users.find_one({'email': current_user})
            except EmailNotValidError:
                user = current_app.db.users.find_one({'uuid': current_user})

            if not user:
                return jsonify({'error': 'User not found'}), 404

            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            # Convert strings to datetime objects if provided
            start_date = datetime.fromisoformat(start_date_str) if start_date_str else None
            end_date = datetime.fromisoformat(end_date_str) if end_date_str else None

            # Construct the conditions based on the provided dates
            date_conditions = []
            if start_date:
                date_conditions.append({"$gte": ["$$doc.uploaded_at", start_date]})
            if end_date:
                date_conditions.append({"$lte": ["$$doc.uploaded_at", end_date]})

            # If there are conditions, use them; otherwise, return true (no filtering)
            cond = {"$and": date_conditions} if date_conditions else True
            pipeline = [
                {
                    "$match": {
                        "uuid": user['uuid']
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        "uploaded_documents": {
                            "$filter": {
                                "input": "$uploaded_documents",
                                "as": "doc",
                                "cond": cond
                            }
                        }
                    }
                }
            ]

            documents = list(current_app.db.users_uploaded_docs.aggregate(pipeline))

            log_data = {
                'start_date': start_date_str,
                'end_date': end_date_str,
            }
            log_action(user['uuid'], user['role'], "viewed-uploaded-docs-in-daterange", log_data)

            if documents and documents[0].get('uploaded_documents'):
                filtered_documents = documents[0]['uploaded_documents']
                return jsonify({"data": filtered_documents, "filters": log_data, "length": len(filtered_documents)}), 200
            else:
                return jsonify({"data": [], "filters": log_data, "length": 0}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500


class DocumentFillRequestView(MethodView):
    decorators = [custom_jwt_required()]
    
    def get(self, document_id):
        try:
            log_request()
            current_user = get_jwt_identity()
            try:
                validate_email(current_user)
                user = current_app.db.users.find_one({'email': current_user})
            except EmailNotValidError:
                user = current_app.db.users.find_one({'uuid': current_user})

            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            document = current_app.db.documents.find_one({'_id': ObjectId(document_id)})
            if not document:
                return jsonify({'error': 'document not found'}), 404
            
            # Get URL of original PDF
            relative_path_encoded = document['url'].split('/media/')[-1]
            relative_path_decoded = urllib.parse.unquote(relative_path_encoded)
            original_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], relative_path_decoded)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            # Check if modified PDF already exists
            filename = f"{timestamp}_{user['first_name']}-{user['last_name']}_{werkzeug.utils.secure_filename(document['name'])}"
            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
            new_doc_path = os.path.join(user_media_dir, filename)

            user_document = create_user_document(original_file_path, new_doc_path, user_media_dir, filename, user)
            if user_document.get('error'):
                return jsonify(user_document), 500
            else:
                doc_url = user_document.get('doc_url')

            # Document data to be inserted or updated
            user_name = user.get('first_name') + " " + user['last_name']
            doc_type = f"fill_and_sign_{document['type']}"
        
            document_data = {
                'user_name': user_name,
                'name': filename,
                'url': doc_url,
                'type': doc_type,
                'state': document.get('state'),
                'is_signed': False,
                'uploaded_at': datetime.now()
            }
            
            # Push a new document
            current_app.db.users_uploaded_docs.update_one(
                {'uuid': user['uuid']},
                {'$push': {'uploaded_documents': document_data}},
                upsert=True
            )
            document['user_ip'] = get_client_ip()
            document['timestamp'] = datetime.now()
            document['original_document_id'] = document_id
            document['original_document_name'] = document['name']
            log_action(user['uuid'], user['role'], "document-fill-request/view", document_data)
            return jsonify(user_document), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500


class DocAnswerInsertionView(MethodView):
    decorators = [custom_jwt_required()]
    
    def get(self, document_id):
        try:
            log_request()
            current_user = get_jwt_identity()
            try:
                validate_email(current_user)
                user = current_app.db.users.find_one({'email': current_user})
            except EmailNotValidError:
                user = current_app.db.users.find_one({'uuid': current_user})

            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            document = current_app.db.documents.find_one({'_id': ObjectId(document_id)})
            if not document:
                return jsonify({'error': 'document not found'}), 404
            
            doc_questions = list(current_app.db.doc_questions_answers.find({'document_id': document_id}))
            questions = []
            for question in doc_questions:
                if len(question.get("answer_locations", [])) > 0:
                    question_info = {
                        "question_id": str(question.pop('_id')),
                        "text": question.get("text"),
                        "type" : question.get("type"),
                        "answer_input_type": question.get("answer_locations", [])[0].get("answerInputType"),
                        "answer_data_type": question.get("answer_locations", [])[0].get("answerOutputType")
                    }
                    if question.get("answer_locations", [])[0].get("answerInputType") in ('multiple-checkbox-single-choice-answer', 'multiple-checkbox-multiple-choice-answer'):
                        position_dict = {}
                        answer_locations = question.get("answer_locations", [])
                        for location in answer_locations:
                            position = location['position']
                            value = location['value']
                            if position not in position_dict:
                                position_dict[position] = []
                            position_dict[position].append(value)
                        question_info['values'] = position_dict
                    elif question.get("answer_locations", [])[0].get("answerInputType") == 'multiline':
                        position_dict = {}
                        answer_locations = question.get("answer_locations", [])
                        for location in answer_locations:
                            position = location['position']
                            max_width = location['endX'] - location['startX']
                            if position not in position_dict:
                                position_dict[position] = []
                            position_dict[position].append(max_width)
                        question_info['max_width'] = position_dict
                    elif question.get("answer_locations", [])[0].get("answerInputType") == 'single-line':
                        answer_locations = question.get("answer_locations", [])
                        answers_max_width = []
                        for location in answer_locations:
                            max_width = location['endX'] - location['startX']
                            answers_max_width.append(max_width)
                        question_info['max_width'] = answers_max_width
                        
                    questions.append(question_info)

            log_action(user['uuid'], user['role'], "viewed-document-questions", {'document_id':document_id})
            return jsonify(questions), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def post(self, document_id):
        try:
            log_request()
            current_user = get_jwt_identity()
            try:
                validate_email(current_user)
                user = current_app.db.users.find_one({'email': current_user})
            except EmailNotValidError:
                user = current_app.db.users.find_one({'uuid': current_user})

            if not user:
                return jsonify({'error': 'User not found'}), 404

            # Check if all required parameters are present in the request payload
            required_params = ['question_id', 'answer', 'doc_url']
            if not all(param in request.json for param in required_params):
                return jsonify({'error': 'Missing required parameters'}), 400

            question_id = request.json['question_id']
            answer = request.json['answer']
            doc_url = request.json['doc_url']
            values = request.json.get('values')  #for multiple-checkbox

            # Retrieve original PDF from MongoDB
            document = current_app.db.documents.find_one({'_id': ObjectId(document_id)})
            if not document:
                return jsonify({'error': 'Document not found'}), 404

            # Document data to be inserted or updated
            user_name = user.get('first_name') + " " + user['last_name']
            doc_type = f"fill_and_sign_{document['type']}"
            
            # Check if a document with the same URL, user_name, name, and type already exists for the user
            existing_document = current_app.db.users_uploaded_docs.find_one(
                {
                    'uuid': user['uuid'],
                    'uploaded_documents': {
                        '$elemMatch': {
                            'url': doc_url,
                            'user_name': user_name,
                            'type': doc_type
                        }
                    }
                },
                {'uploaded_documents.$': 1, '_id':0}
            )
            if not existing_document:
                return jsonify({'error': 'Please request for sign and fill of the document'}), 404
            
            user_document = existing_document.get('uploaded_documents')[0]

            # Retrieve answer locations from the database based on the question ID
            question = current_app.db.doc_questions_answers.find_one(
                {'document_id': document_id, '_id': ObjectId(question_id)},
                {'_id': 0}
            )

            if not question:
                return jsonify({'error': 'Question does not exist for this document'}), 404
            answer_locations = question.get('answer_locations')

            # Get URL of original PDF
            relative_path_encoded = doc_url.split('/media/')[-1]
            relative_path_decoded = urllib.parse.unquote(relative_path_encoded)
            doc_path = os.path.join(current_app.config['UPLOAD_FOLDER'], relative_path_decoded)
            
            inserted_answer = insert_answer_in_pdf(
                doc_path, answer_locations, answer, user, values, user_document.get('name')
            )

            if inserted_answer.get('error'):
                return jsonify(inserted_answer), 400
            elif inserted_answer.get('server-error'):
                return jsonify(inserted_answer), 500
            else:
                doc_url = inserted_answer.get('doc_url')
        
            # Update the doc_questions_answers collection with the answer
            current_app.db.doc_questions_answers.update_one(
                {'document_id': document_id, '_id': ObjectId(question_id)},
                {'$set': {'answer': answer}},
                upsert=True
            )

            if question.get('text') in ["Signature", "signature"]:
                current_app.db.users_uploaded_docs.update_one(
                    {
                        'uuid': user['uuid'],
                        'uploaded_documents.url': doc_url,
                        'uploaded_documents.user_name': user_name,
                        'uploaded_documents.name': user_document.get('name'),
                        'uploaded_documents.type': doc_type
                    },
                    {'$set': {
                                'uploaded_documents.$.uploaded_at': datetime.now(),
                                'uploaded_documents.$.is_signed': True,
                            }
                    }
                )
                send_doc = send_finalized_document(user, doc_path)
                if not send_doc.get('message'):
                    log_data =  {
                        'original_document_id': document_id,
                        'original_document_name': document['name'],
                        'question_id': question_id,
                        'question_text': question['text'], 
                        'inserted_text': answer,
                        'user_doc_id' : str(user_document.get('_id')),
                        'user_doc_name': user_document.get('name'),
                        'user_doc_url': doc_url,
                        'user_doc_signed': user_document.get('is_signed'),
                        'email_sent': True, 
                        'user_ip': get_client_ip(),
                        'timestamp': datetime.now()
                    }
                    log_action(user['uuid'], user['role'], "document-signed-and-email-sent", log_data)
                    return jsonify({'message':"Document signed successfully and send to the user email"}), 200
                else:
                    return jsonify({'error': send_doc.get('error')}), 500

            log_data =  {
                'original_document_id': document_id,
                'original_document_name': document['name'],
                'question_id': question_id,
                'question_text': question['text'], 
                'inserted_text': answer,
                'user_doc_id' : str(user_document.get('_id')),
                'user_doc_name': user_document.get('name'),
                'user_doc_url': doc_url,
                'user_doc_signed': user_document.get('is_signed'),
                'user_ip': get_client_ip(),
                'timestamp': datetime.now()
            }

            log_action(user['uuid'], user['role'], "inserted-answer-for-question", log_data)
            # Return the URL of the saved PDF
            return jsonify({'doc_url': doc_url})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


class DocumentPrefillAnswerView(MethodView):
    decorators = [custom_jwt_required()]
    
    def post(self):
        try:
            log_request()
            current_user = get_jwt_identity()
            try:
                validate_email(current_user)
                user = current_app.db.users.find_one({'email': current_user})
            except EmailNotValidError:
                user = current_app.db.users.find_one({'uuid': current_user})

            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            # Check if all required parameters are present in the request payload
            required_params = ['street_number', 'street_name', 'city', 'state', 'required_fields']
            if not all(param in request.json for param in required_params):
                return jsonify({'error': 'Missing required parameters'}), 400
            payload = {
                'street_number': request.json['street_number'],
                'street_name': request.json['street_name'],
                'city': request.json['city'],
                'state': request.json['state']
            }
            api_url = "http://24.152.187.23:50002/api/v1/search"
            response = requests.post(api_url, json=payload)

            if response.status_code == 200:
                prefill_data = response.json()
                return jsonify(prefill_data)
            else:
                return jsonify({'error': "Something went wrong, unable to get prefill data"}), 500
        
        except Exception as e:
            return jsonify({'error': str(e)}), 500

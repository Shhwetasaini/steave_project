from datetime import datetime
import werkzeug
from bson import ObjectId
import os
import urllib
from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify, request, url_for
from flask_jwt_extended import get_jwt_identity

from flask import current_app
from app.services.admin import log_request
from app.services.authentication import custom_jwt_required, log_action
from app.services.media import (
    extract_first_page_as_image, 
    document_exists, resource_exists,
    insert_answer_in_pdf
)


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
        log_request()
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
        log_request()
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
        log_request()
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
                {'$set': {'downloaded_documents.$.downloaded_at': document_data['downloaded_at']}}
            )
            log_action(user['uuid'], user['role'], "downloaded-document", document_data)
            return jsonify({"message": "Document already exists for the user. Updated."}), 200
        else:
            
            current_app.db.users_downloaded_docs.update_one(
                {'uuid': user['uuid']}, 
                {'$push': { 'downloaded_documents':document_data}},
               upsert=True
            )
            log_action(user['uuid'], user['role'], "downloaded-document", document_data)
            return jsonify({"message": "Document successfully added to user's documents"}), 200

   
class UploadDocView(MethodView):
    decorators = [custom_jwt_required()]

    def put(self):
        log_request()
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
        log_request()
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
        documents = list(current_app.db.documents.find({}))
        formatted_documents = []
        for doc in documents:
            doc['id'] = str(doc.pop('_id'))
            formatted_documents.append(doc)

        log_action(user['uuid'], user['role'], "viewed-all-documents", None)
        return jsonify(formatted_documents), 200


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
          
            log_action(user['uuid'], user['role'], "viewed-downloaded-docs", None)
            return jsonify(user_docs['downloaded_documents']), 200
        else:
            return jsonify({'error': 'User not found'}), 200


class UserUploadedDocsView(MethodView):
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
            user_docs = current_app.db.users_uploaded_docs.find_one({'uuid': user['uuid']}, {'uploaded_documents': 1, '_id': 0})
            if not user_docs:
                return jsonify([]), 200
            log_action(user['uuid'], user['role'], "viewed-uploaded-docs", None)
            return jsonify(user_docs['uploaded_documents']), 200
        else:
            return jsonify({'error': 'User not found'}), 200


class DocsDateRangeView(MethodView):
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
                return jsonify({'error': 'User not found'})

            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            doc_type = request.args.get('doc_type')

            if not start_date or not end_date or not doc_type:
                return jsonify({"error": "Please provide start_date, end_date and doc_type in params"})
            if doc_type not in ['user-docs', 'all-docs']:
                return jsonify({"error": "Invalid value provided in params for doc_type"})

            start_date = datetime.fromisoformat(start_date)
            end_date = datetime.fromisoformat(end_date)

            if doc_type == 'all-docs':
                documents = list(current_app.db.documents.find(
                    {
                        "added_at": {
                            "$gt": start_date,
                            "$lt": end_date
                        }
                    },
                    {
                        '_id': 0
                    }
                ))
                
                log_data = {
                    'start_date': start_date,
                    'end_date': end_date,
                    'doc_type': doc_type
                }
                log_action(user['uuid'], user['role'], "viewed-uploaded-docs-in-daterange", log_data)
                return jsonify(documents)
            elif doc_type == 'user-docs':
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
                                    "cond": {
                                        "$and": [
                                            {"$gt": ["$$doc.uploaded_at", start_date]},
                                            {"$lt": ["$$doc.uploaded_at", end_date]}
                                        ]
                                    }
                                }
                            }
                        }
                    }
                ]               

                documents = list(current_app.db.users_uploaded_docs.aggregate(pipeline))

                log_data = {
                    'start_date': start_date,
                    'end_date': end_date,
                    'doc_type': doc_type
                }
                log_action(user['uuid'], user['role'], "viewed-uploaded-docs-in-daterange", log_data)
                
                if documents:
                    return jsonify(documents[0].get('uploaded_documents'))
                else:
                    return jsonify([]) 
        except Exception as e:
            return jsonify({"error": str(e)})


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
                return jsonify({'error': 'User not found'})
            
            document = current_app.db.documents.find_one({'_id': ObjectId(document_id)})
            if not document:
                return jsonify({'error': 'document not found'})
            
            doc_questions = list(current_app.db.doc_questions_answers.find({'document_id': document_id}))
            questions = []
            for question in doc_questions:
                if len(question.get("answer_locations", [])) > 0:
                    question_info = {
                        "question_id": str(question.pop('_id')),
                        "text": question.get("text"),
                        "answer_input_type": question.get("answer_locations", [])[0].get("answerInputType")
                    }
                    questions.append(question_info)

            log_action(user['uuid'], user['role'], "viewed-document-questions", {'document_id':document_id})
            return jsonify(questions), 200
        except Exception as e:
            return jsonify({"error": str(e)})

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
                return jsonify({'error': 'User not found'})

            # Check if all required parameters are present in the request payload
            required_params = ['question_id', 'answer']
            if not all(param in request.json for param in required_params):
                return jsonify({'error': 'Missing required parameters'})

            question_id = request.json['question_id']
            answer = request.json['answer']
            value = request.json['value']  #for multiple-checkbox

            # Retrieve original PDF from MongoDB
            document = current_app.db.documents.find_one({'_id': ObjectId(document_id)})
            if not document:
                return jsonify({'error': 'Document not found'})

            # Retrieve answer locations from the database based on the question ID
            answer_locations = current_app.db.doc_questions_answers.find_one(
                {'document_id': document_id, '_id': ObjectId(question_id)},
                {'answer_locations': 1, '_id': 0}
            )

            if not answer_locations:
                return jsonify({'error': 'Question does not exist for this document'})

            # Get URL of original PDF
            relative_path_encoded = document['url'].split('/media/')[-1]
            relative_path_decoded = urllib.parse.unquote(relative_path_encoded)
            original_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], relative_path_decoded)
            
            # Check if modified PDF already exists
            filename = f"{user['first_name']}-{user['last_name']}_{werkzeug.utils.secure_filename(document['name'])}"
            user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
            new_doc_path = os.path.join(user_media_dir, filename)

            
            inserted_answer = insert_answer_in_pdf(
                new_doc_path, original_file_path, answer_locations, answer, user_media_dir, user, filename
            )

            if inserted_answer.get('error'):
                return jsonify(inserted_answer)
            else:
                doc_url = inserted_answer.get('doc_url')

            # Update the document data in the database with the file URL
            document_data = {
                'user_name': user.get('first_name') + " " + user['last_name'],
                'name': filename,
                'url': doc_url,
                'type': f"filled_{document['type']}",
                'uploaded_at': datetime.now()
            }

            # Update the uploaded_documents collection in the database
            current_app.db.users_uploaded_docs.update_one(
                {'uuid': user['uuid']},
                {'$push': {'uploaded_documents': document_data}},
                upsert=True
            )

            # Update the doc_questions_answers collection with the answer
            current_app.db.doc_questions_answers.update_one(
                {'document_id': document_id, '_id': ObjectId(question_id)},
                {'$set': {'answer': answer}},
                upsert=True
            )

            log_data =  {
                'document_id':document_id,
                'question_id': question_id,
                'answer': answer,
                'doc_url': doc_url
            }

            log_action(user['uuid'], user['role'], "inserted-answer-for-question", log_data)
            # Return the URL of the saved PDF
            return jsonify({'success': True, 'pdf_url': doc_url})
        except Exception as e:
            return jsonify({'error': str(e)})

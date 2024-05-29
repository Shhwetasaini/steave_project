import os
import hashlib
from datetime import datetime 
import json

from flask.views import MethodView
from flask import jsonify, request, url_for
from flask import current_app
from werkzeug.utils import secure_filename
from flask_jwt_extended import get_jwt_identity

from app.services.authentication import custom_jwt_required, log_action
from app.services.admin import (
    log_request, 
    get_folders_and_files, 
    file_exists_in_folder, 
    rename_filename,
    update_files_in_documents_db
)


class AllDocumentsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        
        documents = list(current_app.db.documents.find({},{'_id':False}))
        log_action(user['uuid'], user['role'], "viewed-all-documents", None)
        return jsonify(documents), 200
         

class EditDocumentsView(MethodView):
    decorators =  [custom_jwt_required()]
    def put(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
      
        update_doc = {}
        
        data = request.json
        docname = data.get('docname')
        description =  data.get('description')
        rename = data.get('rename')
        folder = data.get('folder')
        
        if description:
            update_doc['description'] = description
        if rename:
            document = current_app.db.documents.find_one({'name' : rename + '.pdf'})
            if not document:
                new_url = rename_filename(docname, rename, folder)
                updated_path = os.path.splitext(new_url)[0]
                pdf_path = updated_path + '.pdf'
                updated_pdf_path = pdf_path.rsplit('templates/')
                doc_url = url_for('serve_media', filename=os.path.join('templates/'+ updated_pdf_path[1]).replace('\\', '/'))
                preview_page_url = doc_url[:-4] + '.jpg'
                update_doc['name'] = rename + '.pdf'
                update_doc['url'] = doc_url
                update_doc['preview_image'] = preview_page_url
            else:
                return jsonify({'error': 'File with this name already exist!'}), 400 
            
        update_doc['updated_at'] = datetime.now()
        updated_document = current_app.db.documents.find_one_and_update(
            {"name": docname},
            {"$set": update_doc},
            return_document=True 
        )
    
        if updated_document:
            log_action(user['uuid'], user['role'], "updated-document", update_doc)
            return jsonify({'message': 'Document Updated Successfully!'})       



class FlFormsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        
        root_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms')
        folders_and_files = get_folders_and_files(root_dir)
        log_action(user['uuid'], user['role'], "viewed-FL-forms", None)
        return jsonify(folders_and_files), 200
       


class MnFormsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        root_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms')
        folders_and_files = get_folders_and_files(root_dir)
        log_action(user['uuid'], user['role'], "viewed-ML-forms", None)
        return jsonify(folders_and_files), 200


class SingleFlFormsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self, filename, folder):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        # Specify the folder path
        folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', folder)
        # Check if the file exists in the folder
        if file_exists_in_folder(folder_path, filename):
            # Query MongoDB collection for the document object
            document = current_app.db.documents.find_one({'name': filename},  {'_id': 0})
            if document:
                filepath = os.path.join(folder_path, filename)
                log_action(user['uuid'], user['role'], "viewed-single-FL-forms", {'filename':f"{filepath}/{filename}"})
                return jsonify(document), 200
            else:
                return jsonify({'error': 'Document not found in the database'}), 404
        else:
            return jsonify({'error': 'File not found in the folder'}), 404


class SingleMnFormsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self, filename, folder):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        # Specify the folder path
        folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', folder)

        # Check if the file exists in the folder
        if file_exists_in_folder(folder_path, filename):
            # Query MongoDB collection for the document object
            document = current_app.db.documents.find_one({'name': filename},  {'_id': 0})
            if document:
                log_action(user['uuid'], user['role'], "viewed-single-ML-forms", {'filename':f"{folder_path}/{filename}"})
                return jsonify(document), 200
            else:
                return jsonify({'error': 'Document not found in the database'}), 404
        else:
            return jsonify({'error': 'File not found in the folder'}), 404


class UploadDocumentView(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})

        data = request.form
        folder_type = data.get('folder_type')
        folder = data.get('folder') 
        new_folder = data.get('new_folder')
        file = request.files.get('file')
        if folder:
            file_folder = folder
        else:
            file_folder = new_folder
        filename = file.filename
        document  = current_app.db.documents.find_one({'name': filename})
        if document:
            return jsonify({'error': 'File with this name already exist!'}), 400 
        file_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', folder_type, file_folder)
        os.makedirs(file_dir, exist_ok=True)
        file_path = os.path.join(file_dir, filename)
        file.save(file_path)
        document_data = update_files_in_documents_db()
        document_data.pop('_id')
        log_data = {
            "folder_type": folder_type,
            "existing_folder": folder,
            "new_folder": new_folder,
            "file" : file_path,
            "document_data": document_data
        }
        log_action(user['uuid'], user['role'], "uploaded-document", log_data)
        return jsonify({'message': 'File uploaded succesfully'}), 200
        


class MoveFlFormsFileView(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        try:
            
            # Get data from the frontend
            filename_with_extension = request.json.get('filename')
            source_folder = request.json.get('source_folder')
            dest_folder = request.json.get('dest_folder')

            # Extract filename and extension
            filename, extension = os.path.splitext(filename_with_extension)

            # Determine source and destination paths for both file extensions
            source_pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', source_folder, filename_with_extension)
            source_jpg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', source_folder, filename + '.jpg')
            dest_pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', dest_folder, filename_with_extension)
            dest_jpg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', dest_folder, filename + '.jpg')

            # Create destination folder if it doesn't exist
            dest_folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', dest_folder)
            os.makedirs(dest_folder_path, exist_ok=True)

            # Move both files
            os.rename(source_pdf_path, dest_pdf_path)
            os.rename(source_jpg_path, dest_jpg_path)

             # Update MongoDB documents with the new URLs
            doc_name = filename_with_extension
            doc_url = url_for('serve_media', filename=os.path.join('templates', 'FL_Forms', dest_folder, filename_with_extension))
            preview_page_url = url_for('serve_media', filename=os.path.join('templates', 'FL_Forms', dest_folder, filename + '.jpg'))
            
            # Find the existing document in MongoDB
            existing_document = current_app.db.documents.find_one({'name': doc_name})
            
            # Update the existing document if found
            if not existing_document:
                return jsonify({'error': 'File does not exist!'}), 404

            current_app.db.documents.update_one(
                {'name': doc_name},
                {'$set': {
                    'url': doc_url,
                    'added_at': datetime.now(),
                    'preview_image': preview_page_url,
                    'type': 'FL_Forms'
                }}
            )
            data = {
                'source_folder':source_folder,
                'dest_folder':dest_folder,
                'doc_name': doc_name,
                'file':doc_url,
                'preview_image':preview_page_url,
                'type': 'FL_Forms'
            }

            log_action(user['uuid'], user['role'], "moved-FL-forms", data)
            return jsonify({'message': 'Files moved successfully'}), 200
        except Exception as e:
            print(str(e))
            return jsonify({'error': str(e)}), 500


class MoveMnFormsFileView(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        try:
            # Get data from the frontend
            filename_with_extension = request.json.get('filename')
            source_folder = request.json.get('source_folder')
            dest_folder = request.json.get('dest_folder')

            # Extract filename and extension
            filename, extension = os.path.splitext(filename_with_extension)

            # Determine source and destination paths for both file extensions
            source_pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', source_folder, filename_with_extension)
            source_jpg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', source_folder, filename + '.jpg')
            dest_pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', dest_folder, filename_with_extension)
            dest_jpg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', dest_folder, filename + '.jpg')

            # Create destination folder if it doesn't exist
            dest_folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', dest_folder)
            os.makedirs(dest_folder_path, exist_ok=True)

            # Move both files
            os.rename(source_pdf_path, dest_pdf_path)
            os.rename(source_jpg_path, dest_jpg_path)

             # Update MongoDB documents with the new URLs
            doc_name = filename_with_extension
            doc_url = url_for('serve_media', filename=os.path.join('templates', 'MN_Forms', dest_folder, filename_with_extension))
            preview_page_url = url_for('serve_media', filename=os.path.join('templates', 'MN_Forms', dest_folder, filename + '.jpg'))
            
            # Find the existing document in MongoDB
            existing_document = current_app.db.documents.find_one({'name': doc_name})
            
            # Update the existing document if found
            if not existing_document:
                return jsonify({'error': 'File does not exist!'}), 404

            current_app.db.documents.update_one(
                {'name': doc_name},
                {'$set': {
                    'url': doc_url,
                    'added_at': datetime.now(),
                    'preview_image': preview_page_url,
                    'type': 'MN_Forms'
                }}
            )
            data = {
                'source_folder':source_folder,
                'dest_folder':dest_folder,
                'docname': doc_name,
                'file':doc_url,
                'preview_image':preview_page_url,
                'type': 'MN_Forms'
            }

            log_action(user['uuid'], user['role'], "moved-ML-forms", data)
            return jsonify({'message': 'Files moved successfully'}), 200
        except Exception as e:
            print(str(e))
            return jsonify({'error': str(e)}), 500


class DownloadedDocsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self, uuid):
        log_request()
        current_user = get_jwt_identity()
        logged_in_user = current_app.db.users.find_one({'email': current_user})
       
        user = current_app.db.users.find_one({'uuid': uuid}, {'_id': 0})
        if user:
            log_action(logged_in_user['uuid'], logged_in_user['role'], "viewed-downloaded-docs", None)
            return jsonify(user), 200
        else:
            return jsonify({"error":"User does not exist!"}), 404



class UploadedDocsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self, uuid):
        log_request()
        current_user = get_jwt_identity()
        logged_in_user = current_app.db.users.find_one({'email': current_user})
        user = current_app.db.users.find_one({'uuid': uuid}, {'_id': 0})
        if user:
            log_action(logged_in_user['uuid'], logged_in_user['role'], "viewed-downloaded-docs", None)
            return jsonify(user), 200
        else:
            return jsonify({"error":"User does not exist!"}), 404


class SingleFormQuestionView(MethodView):
    decorators =  [custom_jwt_required()]
    
    def post(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})

        data = request.json
        folder_type = data.get('type')
        folder = data.get('folder') 
        filename = data.get('name')
        url = data.get('url')
        page = data.get('page')
        questions = data.get('question')

        try:
            document  = current_app.db.documents.find_one({'name': filename, 'type': folder_type, 'folder': folder, 'url': url})
            if not document:
                return jsonify({'error': 'document not found'}), 404
            
            # Handle case where 'questions' array is not yet initialized
            existing_questions = document.get('questions', [])
            num = len(existing_questions)
            
            # Prepare list to hold new questions
            new_questions = []
            # Assign sequential numbers to the new questions and add to new list
            for i, question in enumerate(questions, start=num + 1):
                question_data = {'question_id': i, 'question': question, 'page': page}
                new_questions.append(question_data)
            
            # Update the document with the combined questions array
            current_app.db.documents.update_one(
                {'name': filename, 'type': folder_type, 'folder': folder, 'url': url},
                {
                    '$set': {'updated_at': datetime.now()},
                    '$addToSet': {'questions': {'$each': new_questions}}
                }
            )

            return jsonify({'message': 'Questions added successfully'}), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500

        
    def put(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})

        data = request.json
        folder_type = data.get('type')
        folder = data.get('folder') 
        filename = data.get('name')
        url = data.get('url')
        question_id = int(data.get('edit_question_id'))
        new_question = data.get('editquestion')
        answer_location = data.get('answer_location')

        try:
            document = current_app.db.documents.find_one({'name': filename, 'type': folder_type, 'folder': folder, 'url': url})
            if not document:
                return jsonify({'error': 'document not found'}), 404

            # Find the index of the question to be updated
            index_to_update = next((i for i, q in enumerate(document['questions']) if q['question_id'] == question_id), None)
            if index_to_update is not None:
                # Update the question if new_question is provided
                if new_question:
                    document['questions'][index_to_update]['question'] = new_question

                if answer_location:
                    # Update or insert answer_location
                    if 'answer_location' in document['questions'][index_to_update]:
                        document['questions'][index_to_update]['answer_location'].update(answer_location)
                    else:
                        document['questions'][index_to_update]['answer_location'] = answer_location

                # Update the document in the database
                current_app.db.documents.update_one(
                    {'_id': document['_id']},
                    {'$set': {'questions': document['questions'], 'updated_at': datetime.now()}}
                )

                log_data = {
                    "folder_type": folder_type,
                    "folder": folder,
                    "filename": filename,
                    "url": url,
                    "new_question": new_question,
                    "answer_location": answer_location
                }
                log_action(user['uuid'], user['role'], "updated-question-on-document", log_data)

                return jsonify({'message': 'Question updated successfully'}), 200
            else:
                return jsonify({'error': 'question not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def delete(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        
        data = request.json
        folder_type = data.get('type')
        folder = data.get('folder') 
        filename = data.get('name')
        url = data.get('url')
        question_id_to_delete = int(data.get('delete_question_id'))
        
        try:
            document = current_app.db.documents.find_one({'name': filename, 'type': folder_type, 'folder': folder, 'url': url})
            if not document:
                return jsonify({'error': 'document not found'}), 200
            
            # Find the index of the question to be deleted
            index_to_delete = next((i for i, q in enumerate(document['questions']) if q['question_id'] == question_id_to_delete), None)
            if index_to_delete is not None:
                # Delete the question from the questions array
                del document['questions'][index_to_delete]
                
                # Update the document in the database
                current_app.db.documents.update_one(
                    {'name': filename, 'type': folder_type, 'folder': folder, 'url': url},
                    {'$set': {'questions': document['questions'], 'updated_at': datetime.now()}}
                )
                
                log_data = {
                    "folder_type": folder_type,
                    "folder": folder,
                    "filename": filename,
                    "url": url,
                    "deleted_question_id": question_id_to_delete
                }
                log_action(user['uuid'], user['role'], "deleted-question-on-document", log_data)
                
                return jsonify({'message': 'Question deleted successfully'}), 200
            else:
                return jsonify({'error': 'question not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

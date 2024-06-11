import os
import hashlib
from datetime import datetime 
from bson import ObjectId

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
            document = current_app.db.documents.find_one({'name': filename})
            document['id'] = str(document['_id'])
            all_questions = list(current_app.db.doc_questions_answers.find({'document_id': document['id']}))
            questions = [{'question_id': str(doc.pop('_id')), **doc} for doc in all_questions]
            document['questions'] = questions
            document.pop('_id')
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
            document = current_app.db.documents.find_one({'name': filename})
            document['id'] = str(document['_id'])
            all_questions = list(current_app.db.doc_questions_answers.find({'document_id': document['id']}))
            questions = [{'question_id': str(doc.pop('_id')), **doc} for doc in all_questions]
            document['questions'] = questions
            document.pop('_id')
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
        doc_id = data.get('document_id')
        questions = data.get('question')

        if not doc_id or not questions:
            return jsonify({'error': 'document_id and questions are required'}), 400

        try:
            document = current_app.db.documents.find_one({'_id': ObjectId(doc_id)})
            if not document:
                return jsonify({'error': 'document not found'}), 404

            db_questions = []
            for question in questions:
                question_data = {
                    'document_id': doc_id,
                    'text': question,
                    'answer_locations':[]
                }
                db_questions.append(question_data)
            
            current_app.db.doc_questions_answers.insert_many(db_questions)

            log_data = {
                "document_id": doc_id,
                "questions": questions,
            }

            log_action(user['uuid'], user['role'], "added-question-on-document", log_data)

            return jsonify({'message': 'questions added successfully'})

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        
    def put(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})

        data = request.json
        question_id = data.get('edit_question_id')
        doc_id = data.get('document_id')
        new_question = data.get('editquestion')
        currentRect = data.get('currentRect')

        if not doc_id or not question_id:
            return jsonify({'error': 'document_id and question_id are required'}), 400
        
        try:
            document = current_app.db.documents.find_one({'_id': ObjectId(doc_id)})
            if not document:
                return jsonify({'error': 'document not found'}), 404
            
            if new_question:
                # Update the question in the database
                current_app.db.doc_questions_answers.update_one(
                    {'_id': ObjectId(question_id), 'document_id':doc_id},
                    {'$set': {'text': new_question}}
                )
                log_data = {
                    "question_id": question_id,
                    "new_question": new_question,
                    "document_id": doc_id,
                    "answer_locations": currentRect
                }
                log_action(user['uuid'], user['role'], "updated-question-on-document", log_data)
                return jsonify({'message': 'Question updated successfully'}), 200
            elif currentRect:
                question = current_app.db.doc_questions_answers.find_one({'_id': ObjectId(question_id), 'document_id':doc_id})
                if question:
                    answer_locations = question.get('answer_locations', [])
                    current_app.db.doc_questions_answers.update_one(
                        {'_id': ObjectId(question_id), 'document_id': doc_id},
                        {'$push': {'answer_locations': {'$each': answer_locations + currentRect}}}
                    )

                    log_data = {
                        "question_id": question_id,
                        "new_question": new_question,
                        "document_id": doc_id,
                        "answer_locations": currentRect
                    }

                    log_action(user['uuid'], user['role'], "updated-question-on-document", log_data)
                    return jsonify({'message': 'Question updated successfully'}), 200
                else:
                    return jsonify({'error':"Question not found for this documnet"}),400
            else:
                return jsonify({'error':"Required payload is missing"}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def delete(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        data = request.json
        doc_id = data.get('document_id')
        question_id = data.get('delete_question_id')

        if not doc_id or not question_id:
            return jsonify({'error': 'document_id and question_id are required'}), 400
        try:
            document = current_app.db.documents.find_one({'_id': ObjectId(doc_id)})
            if not document:
                return jsonify({'error': 'document not found'}), 404
            
            question = current_app.db.doc_questions_answers.find_one({'_id': ObjectId(question_id),  'document_id': doc_id})
            if not question:
                return jsonify({'error': 'Question not found'}), 404

            current_app.db.doc_questions_answers.delete_one({'_id': ObjectId(question_id)})

            log_data = {"document_id": doc_id, "deleted_question_id": question_id}
            
            log_action(user['uuid'], user['role'], "deleted-question-on-document", log_data)

            return jsonify({'message': 'Question deleted successfully'})

        except Exception as e:
            return jsonify({'error': str(e)}), 500

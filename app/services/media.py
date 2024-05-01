import os

from flask import current_app
from pdf2image import convert_from_path


def extract_first_page_as_image(pdf_file_path):
    images = convert_from_path(pdf_file_path)
    if images:
        image_name = os.path.splitext(os.path.basename(pdf_file_path))[0]
        image_path = os.path.join(os.path.dirname(pdf_file_path), image_name + '.jpg')
        images[0].save(image_path, 'JPEG')
        return image_name + '.jpg'
    else:
        return None


# Function to check if document exists in MongoDB
def document_exists(name):
    return current_app.db.documents.find_one({'name': name}) is not None

  
# Function to check if preview image or URL exists in MongoDB and folder
def resource_exists(preview_page_url, doc_url):
    return (current_app.db.documents.find_one({'$or': [{'preview_image': preview_page_url}, {'url': doc_url}]}) is not None) and \
           (os.path.isfile(preview_page_url) or os.path.isfile(doc_url))
        
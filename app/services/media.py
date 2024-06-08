import os
import io
import werkzeug
from PyPDF2 import PdfReader, PdfWriter

from flask import current_app, url_for
from pdf2image import convert_from_path 
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter


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


def insert_answer_in_pdf(new_doc_path, original_file_path, answer_locations, answer, user_media_dir, user, value, filename):
    if os.path.exists(new_doc_path):
        reader = PdfReader(new_doc_path)
    else:
        reader = PdfReader(original_file_path)

    writer = PdfWriter()

    # Iterate over each page of the original PDF
    for page_num in range(len(reader.pages)):
        # Get the page object
        page = reader.pages[page_num]

        # Check if there are answer locations for this page
        page_answer_locations = [loc for loc in answer_locations.get('answer_locations', []) if loc.get('pageNum') == page_num + 1]
        if page_answer_locations:
            # Create a new PDF with ReportLab
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=letter)
            can.setFillColorRGB(0, 0, 1)

            # Add all answer locations to the overlay
            for location in page_answer_locations:
                if location['answerInputType'] == 'single-checkbox':
                    if answer != True:
                        return {'error': 'answer value must be true for single-checkbox questions'}
                    
                    x = location['startX']
                    y = letter[1] - location['endY'] + 6
                    can.drawString(x, y, '✔')
                elif location['answerInputType'] == 'multiple-checkbox':
                    if answer != True or not value:
                        return {'error': 'answer value must be true and option value is required for multiple-checkbox questions'}
                    if location['value'] == value:
                        x = location['startX']
                        y = letter[1] - location['endY'] + 6
                        can.drawString(x, y, '✔')
                else:                   
                    x = location['startX']
                    y = letter[1] - location['endY'] + 2
                    can.drawString(x, y, answer)

            can.save()

            # Move to the beginning of the StringIO buffer
            packet.seek(0)
            new_pdf = PdfReader(packet)

            # Merge the newly created overlay with the existing page
            page.merge_page(new_pdf.pages[0])

        # Add the (possibly modified) original page to the PDF writer
        writer.add_page(page)

    # Create the directory if it doesn't exist
    os.makedirs(user_media_dir, exist_ok=True)

    # Write the modified PDF content to a file in the media folder
    with open(new_doc_path, 'wb') as fp:
        writer.write(fp)

    # Construct the URL for accessing the saved PDF
    doc_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))

    return {'doc_url': doc_url}

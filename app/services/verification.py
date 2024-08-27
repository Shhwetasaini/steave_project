import os
from datetime import datetime
from werkzeug.utils import secure_filename

def save_file(file, directory, file_type=None):
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filepath = os.path.join(directory, f"{timestamp}_{filename}")
    file.save(filepath)
    return filepath

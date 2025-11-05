from flask import Flask, render_template, request, send_file, redirect, url_for
from werkzeug.utils import secure_filename
import io
import os
import zipfile
import csv
import re
from PyPDF2 import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas
from reportlab.lib import colors
import tempfile

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max folder size
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_pdf():
    try:
        # Check if files are present
        if 'files' not in request.files:
            return redirect_with_error('No files provided')
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return redirect_with_error('No files selected')
        
        # Filter only PDF files
        pdf_files = []
        for file in files:
            if file.filename and allowed_file(file.filename):
                pdf_files.append(file)
        
        if len(pdf_files) == 0:
            return redirect_with_error('No PDF files found in the selected folder')
        
        # Get form data
        text_input = request.form.get('text', '').strip()
        font_size = int(request.form.get('font_size', 12))
        font_family = request.form.get('font_family', 'Helvetica')
        text_color = request.form.get('text_color', '#000000')
        bg_color = request.form.get('bg_color', '#FAFAFA')
        
        # Parse CSV file if provided
        csv_mapping = {}
        csv_file = request.files.get('csv_file')
        if csv_file and csv_file.filename:
            try:
                csv_data = csv_file.read().decode('utf-8')
                csv_reader = csv.DictReader(io.StringIO(csv_data))
                
                # Handle both 'file_name' and 'filename' as column names
                for row in csv_reader:
                    filename = None
                    text = None
                    
                    # Try different possible column names
                    for key in row.keys():
                        key_lower = key.lower().strip()
                        if key_lower in ['file_name', 'filename', 'file']:
                            filename = row[key].strip() if row[key] else None
                        elif key_lower == 'text':
                            text = row[key].strip() if row[key] else None
                    
                    if filename and text:
                        # Normalize filename (remove path if present, keep just the name)
                        filename = os.path.basename(filename.strip())
                        # Store both with and without .pdf extension for flexible matching
                        csv_mapping[filename] = text
                        if filename.lower().endswith('.pdf'):
                            csv_mapping[filename[:-4]] = text
                        
            except Exception as e:
                return redirect_with_error(f'Error parsing CSV file: {str(e)}')
        
        # Process all PDFs and create zip file
        zip_buffer = io.BytesIO()
        processed_count = 0
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file in pdf_files:
                try:
                    # Read PDF file (need to reset file pointer if already read)
                    file.seek(0)
                    pdf_bytes = file.read()
                    
                    # Determine text to use for this file
                    # Extract just the basename for matching (before secure_filename modifies it)
                    filename_basename = os.path.basename(file.filename)
                    original_filename = secure_filename(file.filename)
                    
                    # Try to find matching text in CSV (try exact match, then without extension)
                    file_text = csv_mapping.get(filename_basename, None)
                    if file_text is None and filename_basename.lower().endswith('.pdf'):
                        file_text = csv_mapping.get(filename_basename[:-4], None)
                    if file_text is None:
                        file_text = text_input  # Fallback to manual text input
                    
                    # Process PDF
                    output_pdf = process_pdf_file(pdf_bytes, file_text, font_size, font_family, text_color, bg_color)
                    
                    # Get original filename and create new filename with _p suffix
                    if filename_basename.endswith('.pdf'):
                        output_filename = filename_basename[:-4] + '_p.pdf'
                    else:
                        output_filename = filename_basename + '_p.pdf'
                    
                    # Add processed PDF to zip
                    zip_file.writestr(output_filename, output_pdf)
                    processed_count += 1
                    
                except Exception as e:
                    # Log error but continue processing other files
                    import traceback
                    print(f"Error processing {file.filename}: {str(e)}")
                    print(traceback.format_exc())
                    continue
        
        if processed_count == 0:
            return redirect_with_error('No PDFs were successfully processed. Check that the PDFs are valid and CSV mappings are correct.')
        
        zip_buffer.seek(0)
        
        # Return zip file as download
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name='processed_pdfs.zip'
        )
    
    except Exception as e:
        return redirect_with_error(str(e))

def redirect_with_error(error_message):
    """Redirect to index with error message"""
    from flask import redirect, url_for
    return redirect(url_for('index', error=error_message))

def process_pdf_file(pdf_bytes, text_input, font_size, font_family, text_color, bg_color):
    """
    Process PDF: Add text box to top 12.5%, shrink content to bottom 87.5%
    Uses the same approach as test.py - scaling the page content and adding overlay
    """
    # Read the source PDF
    pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
    
    if len(pdf_reader.pages) == 0:
        raise ValueError('PDF has no pages')
    
    # Get first page dimensions
    first_page = pdf_reader.pages[0]
    page_width = float(first_page.mediabox.width)
    page_height = float(first_page.mediabox.height)
    
    # Create a PDF writer
    pdf_writer = PdfWriter()
    
    # Clone the first page to avoid modifying the original
    # Create a temporary PDF to clone the page properly
    temp_writer = PdfWriter()
    temp_writer.add_page(first_page)
    temp_buffer = io.BytesIO()
    temp_writer.write(temp_buffer)
    temp_buffer.seek(0)
    
    temp_reader = PdfReader(temp_buffer)
    modified_first_page = temp_reader.pages[0]
    
    # Create text overlay PDF
    overlay_pdf = io.BytesIO()
    overlay_canvas = canvas.Canvas(overlay_pdf, pagesize=(page_width, page_height))
    
    # Draw background rectangle and text if provided
    if text_input:
        # Convert hex colors to RGB
        bg_rgb = hex_to_rgb(bg_color)
        text_rgb = hex_to_rgb(text_color)
        
        # Calculate text box area (top 12.5%)
        text_box_height = page_height * 0.125
        
        # Draw background rectangle
        overlay_canvas.setFillColor(colors.Color(bg_rgb[0]/255, bg_rgb[1]/255, bg_rgb[2]/255))
        overlay_canvas.rect(0, page_height - text_box_height, page_width, text_box_height, 
                           fill=1, stroke=0)
        
        # Draw border
        overlay_canvas.setStrokeColor(colors.Color(0.8, 0.8, 0.8))
        overlay_canvas.setLineWidth(1)
        overlay_canvas.rect(0, page_height - text_box_height, page_width, text_box_height, 
                           fill=0, stroke=1)
        
        # Set font and color for text
        font_name = get_font_name(font_family)
        overlay_canvas.setFont(font_name, font_size)
        overlay_canvas.setFillColor(colors.Color(text_rgb[0]/255, text_rgb[1]/255, text_rgb[2]/255))
        
        # Draw text using textobject (like test.py)
        textobject = overlay_canvas.beginText()
        
        # Position text in the top 12.5% area
        # Start from top, leaving some margin
        text_x = 72  # 1 inch from left (like test.py)
        text_y = page_height - (font_size * 1.5)  # Position near top of text box area
        
        textobject.setTextOrigin(text_x, text_y)
        textobject.setFont(font_name, font_size)
        textobject.setFillColor(colors.Color(text_rgb[0]/255, text_rgb[1]/255, text_rgb[2]/255))
        
        # Add an empty line first
        textobject.textLine('')
        
        # Parse and format text - split by "Key: Value" pattern
        # Handle both newline-separated and space-separated key-value pairs
        lines_to_display = []
        
        # First, check if text contains newlines (already formatted)
        if '\n' in text_input:
            lines_to_display = [line.strip() for line in text_input.split('\n') if line.strip()]
        else:
            # Parse space-separated "Key: Value" pairs
            # Split by pattern like "Key: Value" where Value may contain spaces until next "Key:"
            # Pattern to match "Key: Value" pairs, including empty values
            # Matches: word(s) followed by colon, then optional value until next word(s) followed by colon or end
            pattern = r'([^:]+):\s*([^:]*?)(?=\s+[^:]+:\s*|$)'
            matches = re.findall(pattern, text_input)
            
            if matches:
                # Format each match as "Key: Value" (even if value is empty)
                lines_to_display = []
                for key, value in matches:
                    key = key.strip()
                    value = value.strip()
                    if value:
                        lines_to_display.append(f"{key}: {value}")
                    else:
                        # Display field name even if value is empty
                        lines_to_display.append(f"{key}:")
            else:
                # Fallback: split by spaces and try to find colons
                parts = text_input.split()
                current_line = ""
                for part in parts:
                    if ':' in part and current_line:
                        # This part starts a new key-value pair
                        lines_to_display.append(current_line.strip())
                        current_line = part
                    else:
                        if current_line:
                            current_line += " " + part
                        else:
                            current_line = part
                if current_line:
                    lines_to_display.append(current_line.strip())
        
        # Add each line of text
        for line in lines_to_display:
            if line.strip():
                textobject.textLine(line.strip())
        
        overlay_canvas.drawText(textobject)
    
    overlay_canvas.save()
    overlay_pdf.seek(0)
    
    # Transform the original page content - scale to 87.5% height
    # This creates a 12.5% top margin
    scale_factor_y = 0.875  # Scale to 87.5% of original height
    transformation = Transformation().scale(sx=1.0, sy=scale_factor_y).translate(tx=0, ty=0)
    modified_first_page.add_transformation(transformation)
    
    # Read overlay PDF and merge if it has content
    overlay_reader = PdfReader(overlay_pdf)
    if len(overlay_reader.pages) > 0:
        overlay_page = overlay_reader.pages[0]
        # Merge the text overlay ON TOP of the transformed page
        modified_first_page.merge_page(overlay_page)
    
    # Add the modified first page to the writer
    pdf_writer.add_page(modified_first_page)
    
    # Copy remaining pages
    for i in range(1, len(pdf_reader.pages)):
        pdf_writer.add_page(pdf_reader.pages[i])
    
    # Write to bytes
    output = io.BytesIO()
    pdf_writer.write(output)
    output.seek(0)
    
    return output.read()

def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        # Default to black if invalid
        hex_color = '000000'
    try:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (0, 0, 0)  # Default to black

def get_font_name(font_family):
    """Get ReportLab font name from font family selection"""
    font_map = {
        'Helvetica': 'Helvetica',
        'Times-Roman': 'Times-Roman',
        'Courier': 'Courier'
    }
    return font_map.get(font_family, 'Helvetica')

if __name__ == '__main__':
    import sys
    import os
    # Check if we're in a virtual environment
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        # Get port from environment variable (for Cloud Run/App Engine) or default to 8080
        port = int(os.environ.get('PORT', 8080))
        app.run(debug=True, port=port, host='0.0.0.0')
    else:
        print("Please activate the virtual environment first:")
        print("source venv/bin/activate")
        print("Then run: python app.py")
        sys.exit(1)


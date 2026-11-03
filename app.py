from flask import Flask, render_template, request, send_file, redirect, url_for, Response, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
import hmac
import io
import os
import secrets
import zipfile
import csv
import re
import logging
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas
from reportlab.lib import colors

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('pdf-tools')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max folder size

# App Engine / Cloud Run sit behind one Google proxy that sets X-Forwarded-For / X-Forwarded-Proto.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# --- Authentication (HTTP Basic) -------------------------------------------------
# Credentials come only from the environment: env.yaml for App Engine (see
# env.yaml.example), --set-env-vars or Secret Manager for Cloud Run, or exported
# shell variables for local runs. They are deliberately not stored in the code.
AUTH_USERNAME = os.environ.get('APP_USERNAME')
AUTH_PASSWORD = os.environ.get('APP_PASSWORD')
if not AUTH_USERNAME or not AUTH_PASSWORD:
    raise RuntimeError('APP_USERNAME and APP_PASSWORD environment variables must be set (see env.yaml.example)')

def credentials_ok(auth):
    if not auth or auth.type != 'basic' or auth.username is None or auth.password is None:
        return False
    user_ok = hmac.compare_digest(auth.username.encode(), AUTH_USERNAME.encode())
    pass_ok = hmac.compare_digest(auth.password.encode(), AUTH_PASSWORD.encode())
    return user_ok and pass_ok

# --- Rate limiting ----------------------------------------------------------------
# In-memory store: limits apply per instance, which is sufficient as a brute-force
# and abuse brake for a small internal tool.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=['120 per minute'],
    storage_uri='memory://',
)

# --- CSRF (double-submit cookie, no server-side state) ------------------------------
CSRF_COOKIE = 'csrf_token'

def is_https():
    return request.scheme == 'https'

@app.before_request
def require_auth():
    if request.path.startswith('/static/'):
        return None
    if not credentials_ok(request.authorization):
        log.warning('Rejected unauthenticated request from %s', get_remote_address())
        return Response(
            'Authentication required', 401,
            {'WWW-Authenticate': 'Basic realm="PDF Tools", charset="UTF-8"'},
        )
    return None

@app.after_request
def security_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    if is_https():
        resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return resp

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    resp = Response(render_template('index.html', csrf_token=token))
    resp.set_cookie(CSRF_COOKIE, token, httponly=True, samesite='Strict', secure=is_https())
    return resp

def csrf_ok():
    cookie = request.cookies.get(CSRF_COOKIE, '')
    form = request.form.get('csrf_token', '')
    return bool(cookie) and hmac.compare_digest(cookie, form)

@app.route('/process', methods=['POST'])
@limiter.limit('20 per minute')
def process_pdf():
    if not csrf_ok():
        abort(403)
    try:
        if 'files' not in request.files:
            return redirect_with_error('No files provided')

        files = request.files.getlist('files')
        if not files:
            return redirect_with_error('No files selected')

        pdf_files = [f for f in files if f.filename and allowed_file(f.filename)]
        if not pdf_files:
            return redirect_with_error('No PDF files found in the selected folder')

        text_input = request.form.get('text', '').strip()
        try:
            font_size = int(request.form.get('font_size', 10))
        except ValueError:
            return redirect_with_error('Font size must be a whole number')
        font_size = max(8, min(72, font_size))
        font_family = request.form.get('font_family', 'Helvetica')
        text_color = request.form.get('text_color', '#000000')
        bg_color = request.form.get('bg_color', '#FAFAFA')

        # Parse CSV file if provided
        csv_mapping = {}
        csv_file = request.files.get('csv_file')
        if csv_file and csv_file.filename:
            try:
                csv_data = csv_file.read().decode('utf-8-sig')
                csv_reader = csv.DictReader(io.StringIO(csv_data))
                for row in csv_reader:
                    filename = None
                    text = None
                    for key in row.keys():
                        if key is None:
                            continue
                        key_lower = key.lower().strip()
                        if key_lower in ['file_name', 'filename', 'file']:
                            filename = row[key].strip() if row[key] else None
                        elif key_lower == 'text':
                            text = row[key].strip() if row[key] else None
                    if filename and text:
                        filename = os.path.basename(filename.strip())
                        csv_mapping[filename] = text
                        if filename.lower().endswith('.pdf'):
                            csv_mapping[filename[:-4]] = text
            except Exception:
                log.warning('CSV parse failure', exc_info=True)
                return redirect_with_error('The CSV file could not be read. Check that it is UTF-8 text with file_name and text columns.')

        zip_buffer = io.BytesIO()
        processed_count = 0
        failed_count = 0

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for index, file in enumerate(pdf_files):
                try:
                    file.seek(0)
                    pdf_bytes = file.read()

                    filename_basename = os.path.basename(file.filename)

                    file_text = csv_mapping.get(filename_basename)
                    if file_text is None and filename_basename.lower().endswith('.pdf'):
                        file_text = csv_mapping.get(filename_basename[:-4])
                    if file_text is None:
                        file_text = text_input

                    output_pdf = process_pdf_file(pdf_bytes, file_text, font_size, font_family, text_color, bg_color)

                    if filename_basename.lower().endswith('.pdf'):
                        output_filename = filename_basename[:-4] + '_p.pdf'
                    else:
                        output_filename = filename_basename + '_p.pdf'

                    zip_file.writestr(output_filename, output_pdf)
                    processed_count += 1
                except Exception as e:
                    # Deliberately do not log the filename or document contents.
                    failed_count += 1
                    log.warning('Failed to process file #%d of %d: %s', index + 1, len(pdf_files), type(e).__name__)
                    continue

        log.info('Processed %d file(s), %d failed', processed_count, failed_count)

        if processed_count == 0:
            return redirect_with_error('No PDFs were successfully processed. Check that the PDFs are valid and CSV mappings are correct.')

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name='processed_pdfs.zip',
        )

    except Exception:
        log.error('Unhandled error in /process', exc_info=True)
        return redirect_with_error('An unexpected error occurred while processing. Please try again.')

def redirect_with_error(error_message):
    """Redirect to index with a user-facing error message"""
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
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        port = int(os.environ.get('PORT', 8080))
        # Debug mode is never enabled here: the Werkzeug debugger allows remote code
        # execution. Bind to localhost unless HOST is set explicitly (containers use gunicorn).
        host = os.environ.get('HOST', '127.0.0.1')
        app.run(debug=False, port=port, host=host)
    else:
        print("Please activate the virtual environment first:")
        print("source venv/bin/activate")
        print("Then run: python app.py")
        sys.exit(1)

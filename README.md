# PDF Tools - Python Flask Version

A web application for manipulating PDF files by adding text boxes to the first page.

## Features

- Upload a PDF file
- Add a text box to the top 25% of the first page
- Automatically shrink the original first page content to fit in the remaining 75%
- Customize text formatting (font size, font family, text color, background color)
- Download the processed PDF

## Setup

### Prerequisites

- Python 3.7 or higher
- pip (Python package manager)

### Installation

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:
   ```bash
   APP_USERNAME=youruser APP_PASSWORD=yourpassword python app.py
   ```

3. Open your browser and navigate to:
   ```
   http://localhost:8080
   ```

## Security

- **Login:** the app requires a username and password (HTTP Basic Auth), read from the
  `APP_USERNAME` and `APP_PASSWORD` environment variables. They are never stored in the repo:
  copy `env.yaml.example` to `env.yaml` (git-ignored) for App Engine, or pass them with
  `--set-env-vars` on Cloud Run. The app refuses to start without them.
- **No storage:** uploaded PDFs and CSVs are processed in memory and never written to disk
  or sent to third parties. Filenames and document contents are not logged.
- **Local runs** bind to `127.0.0.1` only and never enable debug mode. Set `HOST=0.0.0.0`
  to listen on all interfaces.
- Requests are rate limited and the upload form is CSRF protected.
- Dependencies are pinned; run `pip-audit -r requirements.txt` periodically.

## Usage

1. Click the upload area or choose a PDF file
2. Enter your text in the text box
3. Adjust formatting options (font size, font family, colors)
4. Click "Process PDF" to generate the modified PDF
5. The PDF will automatically download

## Technologies Used

- **Flask**: Web framework for Python
- **pypdf**: For PDF manipulation and page scaling
- **ReportLab**: For creating PDF overlays with text and graphics
- HTML, CSS, and JavaScript for the frontend

## Project Structure

```
pdf-tools/
├── app.py              # Flask application
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html     # Frontend HTML
├── static/
│   └── style.css      # CSS styling
└── README.md          # This file
```

## Browser Support

Works best in modern browsers (Chrome, Firefox, Safari, Edge).

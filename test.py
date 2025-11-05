# main.py
import io
from PyPDF2 import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

def add_top_margin_and_text(input_pdf_path, output_pdf_path, text_to_add):
    """
    Adds a 25% margin to the top of the first page by scaling and shifting
    the original content down. Then, it adds a text box in that new space.

    Args:
        input_pdf_path (str): The path to the input PDF file.
        output_pdf_path (str): The path to save the modified PDF file.
        text_to_add (str): The text content to add in the text box. Use '\n' for new lines.
    """
    try:
        # Open the existing PDF
        existing_pdf = PdfReader(open(input_pdf_path, "rb"))
        output_writer = PdfWriter()

        # Get the first page and its dimensions
        first_page = existing_pdf.pages[0]
        page_width = first_page.mediabox.width
        page_height = first_page.mediabox.height

        # --- Create the text overlay first ---
        # This overlay will be placed in the new top margin.
        packet = io.BytesIO()
        # Use the actual page dimensions for the canvas
        can = canvas.Canvas(packet, pagesize=(page_width, page_height))
        textobject = can.beginText()
        
        # Position the text in the top 25% of the page.
        # The top margin starts at 75% of the page height. We'll place the text
        # a bit below the top edge to look nice.
        text_y_position = float(page_height * 0.95)
        textobject.setTextOrigin(72, text_y_position) # Start 1 inch from the left
        textobject.setFont("Helvetica-Bold", 16)
        textobject.setFillColor(colors.red)
        for line in text_to_add.split('\n'):
            textobject.textLine(line)
        can.drawText(textobject)
        can.save()
        packet.seek(0)
        text_overlay_pdf = PdfReader(packet)
        text_overlay_page = text_overlay_pdf.pages[0]

        # --- Transform the original page content ---
        # Create a transformation to scale content to 75% height and align to bottom.
        # This effectively creates a 25% top margin.
        transformation = Transformation().scale(sx=1, sy=0.95).translate(tx=0, ty=0)
        first_page.add_transformation(transformation)

        # Now merge the text overlay ON TOP of the transformed page
        first_page.merge_page(text_overlay_page)

        # Add the modified first page to the writer
        output_writer.add_page(first_page)

        # Add the rest of the pages from the original PDF
        for i in range(1, len(existing_pdf.pages)):
            output_writer.add_page(existing_pdf.pages[i])

        # Write the final result to the output file
        with open(output_pdf_path, "wb") as outputStream:
            output_writer.write(outputStream)

        print(f"Successfully added a top margin and text to '{input_pdf_path}' and saved as '{output_pdf_path}'")

    except FileNotFoundError:
        print(f"Error: The file '{input_pdf_path}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

# --- Main execution block ---
if __name__ == "__main__":
    # Define the input PDF, the output PDF, and the text to add
    input_file = "cab_back.pdf"  # The original PDF
    output_file = "output.pdf" # The new PDF with the text box
    # Use \n to create a new line in the text
    text = "This text is in the new \n 25% top margin."

    # Create a dummy input PDF if it doesn't exist, for demonstration purposes
    try:
        with open(input_file, "rb"):
            pass
    except FileNotFoundError:
        print(f"Creating a dummy '{input_file}' for demonstration.")
        c = canvas.Canvas(input_file, pagesize=letter)
        c.drawString(100, 750, "This is original content near the top.")
        c.drawString(100, 400, "This is original content in the middle.")
        c.drawString(100, 50, "This is original content at the bottom.")
        c.save()

    # Call the function to add the text and the blank page
    add_top_margin_and_text(input_file, output_file, text)

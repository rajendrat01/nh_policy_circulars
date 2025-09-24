import fitz  # PyMuPDF
from PIL import Image
import io
import sys

# Usage: python save_pdf_page_image.py <pdf_path> <page_num> <output_image_path>
# Example: python save_pdf_page_image.py ../output/pdfs/7_1_88.pdf 0 ../output/page1.png

def save_pdf_page_as_image(pdf_path, page_num, output_image_path):
    doc = fitz.open(pdf_path)
    if page_num < 0 or page_num >= doc.page_count:
        print(f"Page number {page_num} out of range. PDF has {doc.page_count} pages.")
        return
    page = doc[page_num]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x scaling for better OCR
    img_data = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_data))
    image.save(output_image_path)
    print(f"Saved page {page_num+1} of {pdf_path} as {output_image_path}")
    doc.close()

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python save_pdf_page_image.py <pdf_path> <page_num> <output_image_path>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    page_num = int(sys.argv[2])
    output_image_path = sys.argv[3]
    save_pdf_page_as_image(pdf_path, page_num, output_image_path)

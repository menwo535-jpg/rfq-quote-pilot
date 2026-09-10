"""Development-only synthetic fixture generator (requires reportlab)."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

root = Path(__file__).parent
target = root / 'samples' / 'rfq.pdf'
c = canvas.Canvas(str(target), pagesize=(792, 612))
c.setTitle('Synthetic RFQ sample - DEMO-001')
c.setFillColor(HexColor('#193c56'))
c.setFont('Helvetica-Bold', 24)
c.drawString(48, 554, 'Electrical parts request')
c.setFont('Helvetica', 11)
c.setFillColor(HexColor('#506579'))
c.drawString(48, 529, 'Synthetic fixture / DEMO-001 / agreed pilot text layout')
c.setFont('Courier', 11)
c.setFillColor(HexColor('#183047'))
y = 472
for line in (root / 'samples' / 'rfq.txt').read_text().splitlines():
    c.drawString(48, y, line)
    y -= 24
c.setFont('Helvetica', 10)
c.drawString(48, 90, 'Sample contains known items, an unknown code, a unit mismatch, zero quantity and duplicate catalogue prices.')
c.save()
print(target)

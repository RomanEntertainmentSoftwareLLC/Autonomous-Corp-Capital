# ACC Owner's Manual V4 - QA Report

## Build outputs

- PDF: ACC_Owners_Manual_V4.pdf
- DOCX: ACC_Owners_Manual_V4.docx
- Markdown source: ACC_Owners_Manual_V4.md
- HTML preview/source: ACC_Owners_Manual_V4.html

## PDF verification

- `pdfinfo` completed successfully.
- Page count: 148 pages.
- Page size: Letter, 612 x 792 pt.
- PDF text extraction completed successfully with `pdftotext`.
- Extracted text line count: 8,754 lines.
- Sample PDF pages rendered successfully with `pdftoppm`:
  - page 1: cover
  - page 2: table of contents
  - page 50: interior manual page
  - page 100: appendix/tool reference area
  - page 148: final maintenance checklist

## DOCX verification

- DOCX was generated as a minimal raw OOXML Word document with cover, static TOC, styles, and full manual content.
- The sandbox LibreOffice/DOCX render path was unstable during this run, so the PDF is the visually verified primary deliverable.
- The DOCX is included as an editable companion source, but the PDF should be treated as the presentation-ready version.

## Known production notes

- The PDF was generated directly from the manual source using a custom ReportLab canvas renderer to avoid the prior table-compression failure and avoid Markdown-to-DOCX/PDF hangs.
- Long tables are rendered as readable record blocks instead of cramped table sludge.
- The manual deliberately separates implemented ACC/V2 features from future Dreambot/V3 plans.

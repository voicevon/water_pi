
import os
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 注册中文字体 (使用微软雅黑)
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
pdfmetrics.registerFont(TTFont('YaHei', FONT_PATH))
pdfmetrics.registerFont(TTFont('YaHei-Bold', FONT_PATH, subfontIndex=1))

def create_pdf(md_path, pdf_path):
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    styles = getSampleStyleSheet()
    
    # 定义中文字体样式
    title_style = ParagraphStyle(
        'TitleCN', parent=styles['Heading1'], fontName='YaHei-Bold', fontSize=24, 
        alignment=1, spaceAfter=20, textColor=colors.HexColor("#2E5077")
    )
    h2_style = ParagraphStyle(
        'H2CN', parent=styles['Heading2'], fontName='YaHei-Bold', fontSize=18, 
        spaceBefore=15, spaceAfter=10, textColor=colors.HexColor("#4DA1A9"),
        borderPadding=(0, 0, 5, 0), borderStyle=None
    )
    h3_style = ParagraphStyle(
        'H3CN', parent=styles['Heading3'], fontName='YaHei-Bold', fontSize=14, 
        spaceBefore=12, spaceAfter=8, textColor=colors.HexColor("#79D7BE")
    )
    body_style = ParagraphStyle(
        'BodyCN', parent=styles['Normal'], fontName='YaHei', fontSize=10.5, 
        leading=16, spaceAfter=8, alignment=0
    )
    quote_style = ParagraphStyle(
        'QuoteCN', parent=body_style, leftIndent=20, fontName='YaHei', 
        fontSize=9, textColor=colors.gray, italic=True
    )

    content = []

    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    table_data = []
    in_table = False

    for line in lines:
        line = line.strip()
        
        # 处理表格
        if line.startswith('|') and '|' in line:
            if not in_table:
                in_table = True
                table_data = []
            
            # 排除分隔线 | --- |
            if re.match(r'^\|[\s:-|]*\|$', line):
                continue
                
            cells = [c.strip() for c in line.split('|') if c.strip() != '']
            # 处理加粗
            cells = [Paragraph(re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', c), body_style) for c in cells]
            table_data.append(cells)
            continue
        elif in_table:
            # 表格结束，渲染表格
            if table_data:
                t = Table(table_data, colWidths=[120, 100, 260])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F6F4F0")),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, -1), 'YaHei'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ]))
                content.append(t)
                content.append(Spacer(1, 12))
            in_table = False
            if not line: continue

        # 处理标题
        if line.startswith('# '):
            content.append(Paragraph(line[2:], title_style))
        elif line.startswith('## '):
            content.append(Paragraph(line[3:], h2_style))
        elif line.startswith('### '):
            content.append(Paragraph(line[4:], h3_style))
        
        # 处理水平分割线
        elif line == '---':
            content.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey, spaceBefore=5, spaceAfter=10))
            
        # 处理图片
        elif re.match(r'^!\[(.*?)\]\((.*?)\)$', line):
            img_match = re.match(r'^!\[(.*?)\]\((.*?)\)$', line)
            caption = img_match.group(1)
            img_path = img_match.group(2)
            if os.path.exists(img_path):
                img = Image(img_path)
                # 针对移动端长截图，限制高度或宽度。A4 宽约 480。
                orig_w, orig_h = img.imageWidth, img.imageHeight
                max_w = 240  # 缩小宽度以适应长图
                aspect = orig_h / float(orig_w)
                img.drawWidth = max_w
                img.drawHeight = max_w * aspect
                img.hAlign = 'CENTER'
                content.append(img)
                if caption:
                    content.append(Paragraph(caption, ParagraphStyle('Caption', parent=body_style, alignment=1, fontSize=9, textColor=colors.grey)))
                content.append(Spacer(1, 15))

        # 处理列表
        elif line.startswith('- '):
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line[2:])
            text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
            content.append(Paragraph(f"&bull; {text}", body_style))
        elif line.startswith('    - '):
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line[6:])
            text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
            content.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;&bull; {text}", body_style))
            
        # 处理引用
        elif line.startswith('> '):
            text = line[2:].replace('`', '<code>').replace('`', '</code>')
            content.append(Paragraph(text, quote_style))
            
        # 结尾斜体文字
        elif line.startswith('*') and line.endswith('*'):
            text = line[1:-1]
            content.append(Paragraph(f"<i>{text}</i>", body_style))

        # 普通正文
        elif line:
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
            content.append(Paragraph(text, body_style))

    doc.build(content)
    print(f"成功生成 PDF: {pdf_path}")

if __name__ == "__main__":
    create_pdf("pi_water_user_manual.md", "pi_water_user_manual.pdf")

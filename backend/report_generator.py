"""
FundIQ IC Report Generator
Generates professional PDF reports for Investment Committee review
"""
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates IC (Investment Committee) PDF reports"""
    
    def __init__(self, output_dir="reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1f2937'),
            spaceAfter=12,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        # Subtitle style
        self.styles.add(ParagraphStyle(
            name='Subtitle',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#6b7280'),
            spaceAfter=20,
            alignment=TA_CENTER,
            fontName='Helvetica-Oblique'
        ))
        
        # Section header
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#374151'),
            spaceAfter=10,
            spaceBefore=15,
            fontName='Helvetica-Bold'
        ))
        
        # Risk text (red)
        self.styles.add(ParagraphStyle(
            name='RiskText',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#ef4444'),
            fontName='Helvetica'
        ))
    
    def generate_report(
        self,
        document_id: str,
        document_name: str,
        insights: dict,
        anomalies: list,
        notes: list,
        rows_sample: list = None
    ) -> str:
        """Generate complete IC report"""
        try:
            filename = f"{document_id}_IC_Report.pdf"
            filepath = os.path.join(self.output_dir, filename)
            
            # Create PDF document
            doc = SimpleDocTemplate(
                filepath,
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=72
            )
            
            story = []
            
            # Add header
            story.extend(self._create_header(document_name))
            
            # Add executive summary
            story.extend(self._create_executive_summary(insights, anomalies))
            
            # Add key insights
            story.extend(self._create_insights_section(insights))
            
            # Add anomalies section
            story.extend(self._create_anomalies_section(anomalies))
            
            # Add notes section
            if notes:
                story.extend(self._create_notes_section(notes))
            
            # Add data sample if provided
            if rows_sample:
                story.extend(self._create_data_sample(rows_sample))
            
            # Add footer
            story.extend(self._create_footer())
            
            # Build PDF
            doc.build(story, onFirstPage=self._add_page_number, onLaterPages=self._add_page_number)
            
            logger.info(f"Report generated successfully: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Error generating report: {e}")
            raise
    
    def _create_header(self, document_name: str):
        """Create report header"""
        elements = []
        
        # Title
        elements.append(Paragraph(
            "FundIQ Investment Committee Report",
            self.styles['CustomTitle']
        ))
        
        # Subtitle
        elements.append(Paragraph(
            f'Document: <b>{document_name}</b>',
            self.styles['Subtitle']
        ))
        
        # Generation date
        elements.append(Paragraph(
            f"Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            self.styles['Subtitle']
        ))
        
        elements.append(Spacer(1, 0.3 * inch))
        
        return elements
    
    def _create_executive_summary(self, insights: dict, anomalies: list):
        """Create executive summary section"""
        elements = []
        
        elements.append(Paragraph(
            "Executive Summary",
            self.styles['SectionHeader']
        ))
        
        # Overall risk assessment
        total_anomalies = len(anomalies)
        high_severity = len([a for a in anomalies if a.get('severity') == 'high'])
        
        risk_level = "LOW"
        risk_color = colors.green
        if high_severity > 0:
            risk_level = "HIGH"
            risk_color = colors.red
        elif total_anomalies > 5:
            risk_level = "MEDIUM"
            risk_color = colors.orange
        
        summary_text = f"""
        <b>Risk Assessment:</b> <font color="{risk_color.hexval()}">{risk_level}</font><br/>
        <b>Total Anomalies Detected:</b> {total_anomalies}<br/>
        <b>High Severity Issues:</b> {high_severity}<br/>
        <b>Overall Severity:</b> {insights.get('overall_severity', 'N/A').upper()}<br/>
        <b>Risk Score:</b> {insights.get('risk_score', 0)}/100
        """
        
        elements.append(Paragraph(summary_text, self.styles['Normal']))
        elements.append(Spacer(1, 0.2 * inch))
        
        # Key findings
        if insights.get('summary'):
            elements.append(Paragraph(
                f"<b>Key Finding:</b> {insights['summary']}",
                self.styles['Normal']
            ))
        
        elements.append(Spacer(1, 0.3 * inch))
        
        return elements
    
    def _create_insights_section(self, insights: dict):
        """Create insights breakdown section"""
        elements = []
        
        elements.append(Paragraph(
            "Insights Breakdown",
            self.styles['SectionHeader']
        ))
        
        # Create insights table
        if insights.get('insights'):
            for insight in insights['insights']:
                category = insight.get('category', 'Unknown')
                count = insight.get('count', 0)
                severity = insight.get('severity', 'green')
                summary = insight.get('summary', '')
                
                # Color code by severity
                color_map = {
                    'red': colors.HexColor('#ef4444'),
                    'yellow': colors.HexColor('#f59e0b'),
                    'green': colors.HexColor('#10b981')
                }
                severity_color = color_map.get(severity, colors.black)
                
                text = f"""
                <b>{category}</b> ({count} issues)<br/>
                <font color="{severity_color.hexval()}">● {severity.upper()}</font><br/>
                {summary}
                """
                
                elements.append(Paragraph(text, self.styles['Normal']))
                elements.append(Spacer(1, 0.15 * inch))
        
        elements.append(Spacer(1, 0.2 * inch))
        
        return elements
    
    def _create_anomalies_section(self, anomalies: list):
        """Create detailed anomalies section"""
        elements = []
        
        elements.append(Paragraph(
            "Top Anomalies (Detailed View)",
            self.styles['SectionHeader']
        ))
        
        if not anomalies:
            elements.append(Paragraph(
                "✓ No anomalies detected. Data appears clean.",
                self.styles['Normal']
            ))
            elements.append(Spacer(1, 0.2 * inch))
            return elements
        
        # Show top 10 anomalies
        top_anomalies = sorted(
            anomalies,
            key=lambda x: {'high': 3, 'medium': 2, 'low': 1}.get(x.get('severity', 'low'), 0),
            reverse=True
        )[:10]
        
        # Create table data
        table_data = [
            ['Severity', 'Type', 'Description', 'Row']
        ]
        
        for anomaly in top_anomalies:
            severity = anomaly.get('severity', 'N/A').upper()
            anomaly_type = anomaly.get('anomaly_type', 'Unknown').replace('_', ' ').title()
            description = anomaly.get('description', 'No description')[:60] + '...'
            row_index = anomaly.get('row_index', -1)
            row_text = f"Row {row_index + 1}" if row_index >= 0 else 'N/A'
            
            table_data.append([severity, anomaly_type, description, row_text])
        
        # Create table
        table = Table(table_data, colWidths=[0.8*inch, 1.5*inch, 3.5*inch, 0.8*inch])
        
        # Style table
        table.setStyle(TableStyle([
            # Header styling
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            
            # Body styling
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Severity column
            ('ALIGN', (3, 1), (3, -1), 'CENTER'),  # Row column
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')])
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 0.3 * inch))
        
        return elements
    
    def _create_notes_section(self, notes: list):
        """Create notes section"""
        elements = []
        
        elements.append(Paragraph(
            "Team Notes & Comments",
            self.styles['SectionHeader']
        ))
        
        if not notes:
            elements.append(Paragraph(
                "No notes available.",
                self.styles['Normal']
            ))
        else:
            for idx, note in enumerate(notes[:10], 1):  # Limit to 10 notes
                content = note.get('content', 'No content')
                author = note.get('author', 'Unknown')
                created_at = note.get('created_at', '')
                
                note_text = f"""
                <b>Note {idx}</b> (by {author})<br/>
                {content}
                """
                
                elements.append(Paragraph(note_text, self.styles['Normal']))
                elements.append(Spacer(1, 0.1 * inch))
        
        elements.append(Spacer(1, 0.2 * inch))
        
        return elements
    
    def _create_data_sample(self, rows_sample: list):
        """Create sample data preview"""
        elements = []
        
        elements.append(PageBreak())
        elements.append(Paragraph(
            "Data Sample (First 5 Rows)",
            self.styles['SectionHeader']
        ))
        
        if not rows_sample:
            return elements
        
        # Limit to first 5 rows
        sample = rows_sample[:5]
        
        # Get column names from first row
        if not sample:
            return elements
        
        columns = list(sample[0].get('raw_json', {}).keys())[:6]  # Limit columns
        
        # Create table data
        table_data = [columns]
        
        for row in sample:
            raw_json = row.get('raw_json', {})
            row_data = [str(raw_json.get(col, ''))[:20] for col in columns]
            table_data.append(row_data)
        
        # Create table
        col_width = 6.5 * inch / len(columns)
        table = Table(table_data, colWidths=[col_width] * len(columns))
        
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')])
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 0.2 * inch))
        
        return elements
    
    def _create_footer(self):
        """Create report footer"""
        elements = []
        
        elements.append(Spacer(1, 0.5 * inch))
        
        # Tagline
        elements.append(Paragraph(
            '<i>"The devil is in the details — FundIQ finds the devil."</i>',
            self.styles['Subtitle']
        ))
        
        # Disclaimer
        disclaimer = """
        <font size=8 color="#6b7280">
        This report was automatically generated by FundIQ. The anomalies and insights 
        identified should be verified by qualified personnel. FundIQ provides detection 
        tools but does not replace professional judgment.
        </font>
        """
        elements.append(Paragraph(disclaimer, self.styles['Normal']))
        
        return elements
    
    def _add_page_number(self, canvas, doc):
        """Add page numbers to each page"""
        page_num = canvas.getPageNumber()
        text = f"Page {page_num}"
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(colors.grey)
        canvas.drawRightString(
            doc.pagesize[0] - 72,
            30,
            text
        )
        canvas.restoreState()


# Convenience function for direct use
def generate_report(document_id, document_name, insights, anomalies, notes, rows_sample=None):
    """Generate IC report (convenience function)"""
    generator = ReportGenerator()
    return generator.generate_report(
        document_id,
        document_name,
        insights,
        anomalies,
        notes,
        rows_sample
    )


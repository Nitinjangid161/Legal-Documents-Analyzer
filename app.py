import gradio as gr
import os
import json
import re
from datetime import datetime
import logging
from typing import Dict, List, Any, Tuple
import tempfile
from pathlib import Path
import time
import hashlib

# Document processing libraries
import PyPDF2
from docx import Document
from PIL import Image
import pandas as pd
from openpyxl import load_workbook

# New library for handling scanned PDFs
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    print("Warning: pdf2image library not found. Scanned PDF analysis will be disabled. Run 'pip install pdf2image'")


# AI/ML libraries
try:
    import google.generativeai as genai
    GOOGLE_AI_AVAILABLE = True
except ImportError:
    GOOGLE_AI_AVAILABLE = False
    print("Google AI not available. Using fallback analysis.")

# OCR library for image analysis
try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("Pytesseract not found. Image analysis will be disabled.")


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AdvancedLegalAnalyzer:
    def __init__(self):
        # Risk keywords and document patterns remain the same
        self.risk_keywords = {
            'critical_risk': {
                'terms': [
                    'irrevocable', 'unlimited liability', 'perpetual obligation',
                    'waive all rights', 'complete indemnification', 'liquidated damages',
                    'penalty clause', 'criminal liability', 'personal guarantee',
                    'joint and several liability', 'unlimited damages', 'unilateral termination'
                ],
                'weight': 15, 'description': 'Critical terms that could expose you to significant legal or financial risk'
            },
            'high_risk': {
                'terms': [
                    'indemnify', 'hold harmless', 'at will termination', 'sole discretion',
                    'no warranty', 'force majeure', 'assignment of rights',
                    'non-compete', 'confidentiality breach', 'automatic renewal', 'binding arbitration'
                ],
                'weight': 10, 'description': 'High-risk terms that significantly limit your rights or increase obligations'
            },
            'medium_risk': {
                'terms': [
                    'termination', 'breach', 'default', 'damages', 'liability',
                    'jurisdiction', 'governing law', 'modification', 'amendment', 'notice period'
                ],
                'weight': 6, 'description': 'Medium-risk terms that require careful consideration'
            },
            'favorable_terms': {
                'terms': [
                    'mutual agreement', 'reasonable notice', 'good faith negotiation',
                    'proportional liability', 'cap on damages', 'right to cure',
                    'mutual termination', 'equitable relief', 'cost sharing'
                ],
                'weight': -3, 'description': 'Generally favorable terms that protect your interests'
            }
        }
        self.document_patterns = {
            'government_form': ['आय', 'घोषणा पत्र', 'सरकार', 'प्रमाण पत्र', 'form', 'affidavit', 'declaration'],
            'employment_contract': ['employee', 'employer', 'salary', 'benefits', 'job description', 'termination', 'non-compete', 'confidentiality'],
            'rental_agreement': ['landlord', 'tenant', 'lease', 'rent', 'security deposit', 'premises', 'utilities', 'maintenance', 'eviction'],
            'service_agreement': ['service provider', 'client', 'deliverables', 'scope of work', 'payment terms', 'intellectual property'],
        }

        # Initialize Google AI model
        self.ai_model = None
        self._setup_ai()

    def _setup_ai(self):
        """Setup Google AI model with your API key."""
        if not GOOGLE_AI_AVAILABLE:
            logger.error("Google Generative AI library is not installed.")
            return
            
        try:
            # --- PASTE YOUR API KEY HERE ---
            # For security, it's better to use an environment variable in a real application
            # e.g., api_key = os.environ.get("GEMINI_API_KEY")
            api_key = "AIzaSyCC5uG15v13Wu00F2gpewE_iB6qYSaCQ54"

            if not api_key:
                logger.warning("API key is missing. Please add your Gemini API key.")
                return

            genai.configure(api_key=api_key)
            self.ai_model = genai.GenerativeModel(
                'gemini-1.5-flash', # Using the fast and capable Flash model
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2, top_p=0.9, max_output_tokens=4096
                )
            )
            logger.info("Google AI (Gemini) model initialized successfully.")

        except Exception as e:
            logger.error(f"Failed to initialize Google AI model: {e}")

    def extract_text_from_file(self, file_path: str) -> Tuple[str, Dict]:
        file_path_obj = Path(file_path)
        metadata = {
            'file_name': file_path_obj.name, 'file_size': file_path_obj.stat().st_size,
            'file_type': file_path_obj.suffix.lower()
        }
        text = ""
        file_ext = file_path_obj.suffix.lower()

        if file_ext == '.pdf':
            text, pdf_meta = self._extract_from_pdf_hybrid(file_path)
            metadata.update(pdf_meta)
        elif file_ext == '.docx':
            doc = Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            if not OCR_AVAILABLE:
                raise ValueError("OCR is not available. Please install pytesseract.")
            text, img_meta = self._extract_from_image(file_path_obj)
            metadata.update(img_meta)
        else:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()

        text = self._advanced_text_cleaning(text)
        metadata['word_count'] = len(text.split())
        return text, metadata

    def _extract_from_pdf_hybrid(self, file_path: str) -> Tuple[str, Dict]:
        text = ""
        metadata = {'pages': 0, 'ocr_pages': []}
        try:
            pdf_reader = PyPDF2.PdfReader(file_path)
            metadata['pages'] = len(pdf_reader.pages)
            for page_num, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                if not page_text or len(page_text.strip()) < 50:
                    if PDF2IMAGE_AVAILABLE and OCR_AVAILABLE:
                        logger.info(f"Page {page_num + 1} has low text, attempting OCR...")
                        try:
                            images = convert_from_path(file_path, first_page=page_num + 1, last_page=page_num + 1)
                            if images:
                                page_text = pytesseract.image_to_string(images[0], lang='eng+hin')
                                metadata['ocr_pages'].append(page_num + 1)
                        except Exception as ocr_err:
                            logger.error(f"OCR failed for page {page_num + 1}: {ocr_err}")
                            page_text = ""
                text += f"\n--- Page {page_num + 1} ---\n{page_text or ''}\n"
        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
            raise
        return text, metadata

    def _extract_from_image(self, file_path: Path) -> Tuple[str, Dict]:
        try:
            with Image.open(file_path) as img:
                text = pytesseract.image_to_string(img, lang='eng+hin')
                return text, {'image_resolution': f"{img.width}x{img.height}"}
        except Exception as e:
            logger.error(f"OCR extraction error: {e}")
            raise
        return "", {}

    def _advanced_text_cleaning(self, text: str) -> str:
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'--- Page \d+ ---', '', text)
        return text.strip()

    def identify_document_type(self, text: str) -> Tuple[str, float]:
        scores = {}
        if not text: return "Unknown", 0.0
        for doc_type, keywords in self.document_patterns.items():
            scores[doc_type] = sum(text.lower().count(keyword) for keyword in keywords)
        
        total_score = sum(scores.values())
        if total_score == 0: return "General Document", 0.5
        
        best_type = max(scores, key=scores.get)
        confidence = scores[best_type] / total_score
        return best_type.replace('_', ' ').title(), confidence

    def analyze_document_comprehensive(self, text: str, metadata: Dict) -> Dict[str, Any]:
        doc_type, confidence = self.identify_document_type(text)
        ai_analysis = self._enhanced_ai_analysis(text, doc_type) if self.ai_model else {}
        risk_assessment = self._enhanced_risk_assessment(text)
        analysis_result = {
            **risk_assessment, **ai_analysis,
            'document_type': doc_type, 'type_confidence': confidence,
            'key_terms': self._extract_key_terms(text),
            'compliance': self._enhanced_compliance_check(text),
            'metadata': metadata,
        }
        analysis_result['overall_score'] = self._calculate_overall_score(analysis_result)
        return analysis_result

    def _enhanced_ai_analysis(self, text: str, doc_type: str) -> Dict[str, Any]:
        try:
            prompt = f"""
            As an expert analyst reviewing a '{doc_type}', provide a detailed JSON response.
            Analyze the document text. Be concise.

            Respond with this exact JSON structure:
            {{
                "document_title": "A concise, likely title for this document.",
                "parties_involved": "A brief description of parties. If a contract, name Party A/B roles. If a form, name Applicant/Authority.",
                "executive_summary": "A 3-4 sentence summary for a busy executive, highlighting the purpose and key outcomes.",
                "eli5_summary": "Explain Like I'm 5: A one-sentence, super-simple explanation.",
                "key_financial_terms": ["List key monetary values found, e.g., 'Total Income: ₹2,00,000'"],
                "important_dates": ["List key dates found, e.g., 'Date of Issue: 18/08/25'"],
                "potential_issues": [
                    {{"issue": "Describe a potential problem", "severity": "High|Medium|Low", "recommendation": "Suggest an action"}}
                ],
                "action_items": ["List immediate, actionable steps for the user."]
            }}

            Document text: "{text[:20000]}"
            """
            response = self.ai_model.generate_content(prompt)
            # A more robust way to find and parse JSON from the response
            response_text = response.text.strip()
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if not json_match:
                json_match = re.search(r"(\{.*?\})", response_text, re.DOTALL)

            if json_match:
                json_text = json_match.group(1)
                return json.loads(json_text)
            else:
                raise ValueError("No valid JSON object found in the AI response.")

        except Exception as e:
            logger.error(f"Enhanced AI analysis failed: {e}")
            return {"executive_summary": f"AI analysis failed: {e}"}

    def _enhanced_risk_assessment(self, text: str) -> Dict[str, Any]:
        risk_findings = {}
        total_risk_score = 0
        text_lower = text.lower()
        for risk_level, data in self.risk_keywords.items():
            found_terms = [{'term': term, 'count': text_lower.count(term)} for term in data['terms'] if term in text_lower]
            if found_terms:
                risk_findings[risk_level] = {'terms_found': found_terms, 'description': data['description']}
                total_risk_score += sum(t['count'] * data['weight'] for t in found_terms)
        
        if total_risk_score >= 100: overall_risk = "Critical"
        elif total_risk_score >= 50: overall_risk = "High"
        elif total_risk_score >= 20: overall_risk = "Medium"
        elif total_risk_score > -10: overall_risk = "Low"
        else: overall_risk = "Favorable"
        return {'overall_risk_level': overall_risk, 'risk_score': total_risk_score, 'risk_findings': risk_findings}

    def _extract_key_terms(self, text: str) -> List[Dict]:
        legal_terms_db = {
            'indemnification': 'One party agrees to cover the losses of another.',
            'limitation of liability': 'Caps the amount of damages a party can be responsible for.',
            'confidentiality': 'Obligation to keep certain information secret.',
            'termination': 'Conditions under which the agreement can be ended.',
            'governing law': 'Specifies which laws will be used to interpret the agreement.',
            'arbitration': 'A private method of resolving disputes outside of court.'
        }
        text_lower = text.lower()
        return [{'term': term.title(), 'definition': definition} for term, definition in legal_terms_db.items() if term in text_lower]

    def _enhanced_compliance_check(self, text: str) -> Dict[str, Any]:
        clauses = {"Termination": ['terminate', 'termination'], "Governing Law": ['governed by'], "Dispute Resolution": ['arbitration', 'mediation'], "Confidentiality": ['confidential'], "Liability": ['liability', 'indemnify']}
        text_lower = text.lower()
        results = {clause: any(kw in text_lower for kw in kws) for clause, kws in clauses.items()}
        score = (sum(results.values()) / len(clauses)) * 100
        return {'score': round(score), 'checklist': results}

    def _calculate_overall_score(self, analysis: Dict) -> Dict[str, Any]:
        risk_score = analysis.get('risk_score', 0)
        compliance_score = analysis.get('compliance', {}).get('score', 0)
        normalized_risk_score = max(0, 100 - (risk_score * 0.66))
        final_score = int((normalized_risk_score * 0.6) + (compliance_score * 0.4))
        grade = "F"
        if final_score >= 90: grade = "A+"
        elif final_score >= 80: grade = "A"
        elif final_score >= 70: grade = "B"
        elif final_score >= 60: grade = "C"
        elif final_score >= 50: grade = "D"
        return {'score': final_score, 'grade': grade}

# --- UI Formatting and Chatbot Functions ---

def format_dashboard(analysis: Dict) -> str:
    if not analysis or 'error' in analysis: return "<h3>Analysis Failed</h3>"
    scorecard = analysis.get('overall_score', {})
    risk_level = analysis.get('overall_risk_level', 'N/A')
    risk_colors = {"Critical": "#e53e3e", "High": "#dd6b20", "Medium": "#d69e2e", "Low": "#38a169", "Favorable": "#3182ce"}
    risk_color = risk_colors.get(risk_level, "#718096")
    
    financial_html = "".join(f'<li>{item}</li>' for item in analysis.get('key_financial_terms', []))
    dates_html = "".join(f'<li>{item}</li>' for item in analysis.get('important_dates', []))

    return f"""
    <div style="padding: 20px; border-radius: 10px; background-color: #f7fafc;">
        <h2 style="margin-top:0;">{analysis.get('document_title', 'Document Analysis')}</h2>
        <p><em>{analysis.get('eli5_summary', '')}</em></p>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; text-align: center; margin: 25px 0;">
            <div><h3 style="margin:0;color:#4a5568;">Grade</h3><p style="font-size:2.5em;margin:5px 0;color:{risk_color};font-weight:bold;">{scorecard.get('grade', 'N/A')}</p></div>
            <div><h3 style="margin:0;color:#4a5568;">Risk Level</h3><p style="font-size:2.5em;margin:5px 0;color:{risk_color};font-weight:bold;">{risk_level}</p></div>
            <div><h3 style="margin:0;color:#4a5568;">Compliance</h3><p style="font-size:2.5em;margin:5px 0;color:#4a5568;font-weight:bold;">{analysis.get('compliance', {}).get('score', 0)}%</p></div>
        </div>
        <h3>Executive Summary</h3><p>{analysis.get('executive_summary', 'Not available.')}</p>
        <h3>Parties Involved</h3><p>{analysis.get('parties_involved', 'Not identified.')}</p>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            <div><h3>💰 Key Financial Terms</h3><ul>{financial_html or '<li>None identified</li>'}</ul></div>
            <div><h3>🗓️ Important Dates</h3><ul>{dates_html or '<li>None identified</li>'}</ul></div>
        </div>
        <h3>Action Items</h3><ul>{''.join(f'<li>{item}</li>' for item in analysis.get('action_items', []))}</ul>
    </div>
    """

def format_risk_analysis(analysis: Dict) -> Tuple[str, str]:
    if not analysis or 'risk_findings' not in analysis: return "<p>No risk data.</p>", "<p>No risk data.</p>"
    risk_findings = analysis.get('risk_findings', {})
    risk_data = {"Critical": len(risk_findings.get('critical_risk', {}).get('terms_found', [])), "High": len(risk_findings.get('high_risk', {}).get('terms_found', [])), "Medium": len(risk_findings.get('medium_risk', {}).get('terms_found', []))}
    risk_colors = {"Critical": "#e53e3e", "High": "#dd6b20", "Medium": "#d69e2e"}
    max_val = max(risk_data.values()) if any(risk_data.values()) else 1
    chart_html = '<div style="padding:10px;">' + "".join([f'<div style="margin-bottom:8px;"><strong style="display:inline-block;width:80px;">{L}</strong><div style="display:inline-block;width:calc(100% - 110px);background:#e2e8f0;"><div style="width:{(c/max_val*100)}%;background:{risk_colors[L]};color:white;text-align:right;padding:4px;">{c}</div></div></div>' for L, c in risk_data.items()]) + '</div>'
    details_md = "## Risk Details\n" + "\n".join([f"### {L.replace('_',' ').title()}\n*{D['description']}*\n" + "".join([f"- **{t['term']}** (found {t['count']} time(s))\n" for t in D['terms_found']]) for L, D in risk_findings.items()])
    return chart_html, details_md

def format_compliance_analysis(analysis: Dict) -> str:
    if not analysis or 'compliance' not in analysis: return "No data."
    checklist = analysis.get('compliance', {}).get('checklist', {})
    return "## Standard Clause Checklist\n" + "\n".join([f"- {'✅' if P else '❌'} **{C}:** {'Present' if P else 'Missing'}" for C, P in checklist.items()])

def format_key_terms(analysis: Dict) -> str:
    if not analysis or not analysis.get('key_terms'): return "No key terms identified."
    return "## Important Legal Terms\n" + "\n".join([f"### {t['term']}\n> {t['definition']}\n" for t in analysis.get('key_terms')])

def ask_enhanced_question(doc_text: str, question: str, chat_history: List, language: str, analysis_data: Dict):
    chat_history = chat_history or []
    
    if not doc_text or not question:
        chat_history.append({"role": "user", "content": question})
        chat_history.append({"role": "assistant", "content": "Please upload and analyze a document first."})
        return chat_history
    try:
        analyzer = AdvancedLegalAnalyzer()
        if not analyzer.ai_model:
            chat_history.append({"role": "user", "content": question})
            chat_history.append({"role": "assistant", "content": "AI model is not available for Q&A."})
            return chat_history

        lang_instruction = "Provide a helpful, conversational answer in simple English."
        if language == "Hinglish":
            lang_instruction = "Provide a helpful, conversational answer in Hinglish (mixing Hindi and English using Roman script)."

        prompt = f"""
        You are a helpful assistant explaining a document.
        CONTEXT FROM INITIAL ANALYSIS:
        - Document Type: {analysis_data.get('document_type', 'N/A')}
        - Overall Risk: {analysis_data.get('overall_risk_level', 'N/A')}
        - Summary: {analysis_data.get('executive_summary', 'N/A')}

        FULL DOCUMENT TEXT (for reference):
        ---
        {doc_text[:15000]}
        ---

        USER QUESTION: "{question}"

        INSTRUCTIONS:
        - Answer the user's question based on the document text.
        - {lang_instruction}
        - If you can't find the answer, say so clearly. Do not make up information.
        """
        response = analyzer.ai_model.generate_content(prompt)
        answer = response.text.strip()
    except Exception as e:
        logger.error(f"Q&A Error: {e}")
        answer = f"Sorry, I encountered an error: {e}"
    
    chat_history.append({"role": "user", "content": question})
    chat_history.append({"role": "assistant", "content": answer})
    return chat_history

# --- Main Gradio App ---
def create_enhanced_interface():
    with gr.Blocks(theme=gr.themes.Soft(), css="footer {display: none !important}") as interface:
        gr.HTML("""<div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:30px;text-align:center;color:white;">
                   <h1 style="margin:0;font-size:2.5em;">⚖️ Advanced AI Legal Analyzer</h1>
                   <p style="font-size:1.2em;">Instant, intelligent insights into your legal documents.</p></div>""")

        with gr.Row():
            with gr.Column(scale=1, min_width=350):
                file_input = gr.File(label="Upload Document", file_types=[".pdf", ".docx", ".txt", ".png", ".jpg"])
                analyze_btn = gr.Button("🚀 Analyze Document", variant="primary")
                with gr.Accordion("Document Metadata", open=False):
                    metadata_output = gr.JSON(label="File Info")

            with gr.Column(scale=3):
                with gr.Tabs() as result_tabs:
                    with gr.TabItem("📊 Dashboard", id=0):
                        dashboard_output = gr.HTML("### Upload a document to see the analysis dashboard.")
                    with gr.TabItem("⚠️ Risk Analysis", id=1):
                        risk_chart_output = gr.HTML()
                        ai_issues_output = gr.JSON(label="AI Identified Issues")
                        risk_details_output = gr.Markdown()
                    with gr.TabItem("✅ Compliance", id=2):
                        compliance_output = gr.Markdown()
                    with gr.TabItem("📚 Key Terms", id=3):
                        key_terms_output = gr.Markdown()
                    with gr.TabItem("💬 Ask a Question", id=4):
                        chatbot = gr.Chatbot(label="Chat about this Document", height=400, type="messages")
                        with gr.Row():
                            lang_select = gr.Radio(["English", "Hinglish"], label="Response Language", value="English", scale=1)
                            question_input = gr.Textbox(
                                label="Your Question", 
                                placeholder="e.g., What is the total income mentioned?",
                                scale=3,
                                container=False
                            )
                        ask_btn = gr.Button("Submit Question")

        analysis_state = gr.State({})
        doc_text_state = gr.State("")

        def run_analysis(file, progress=gr.Progress(track_tqdm=True)):
            if file is None:
                raise gr.Error("Please upload a file first.")
            progress(0.1, desc="Initializing...")
            analyzer = AdvancedLegalAnalyzer()
            progress(0.3, desc="Reading and processing document...")
            text, metadata = analyzer.extract_text_from_file(file.name)
            if not text or len(text.strip()) < 50:
                raise gr.Error("Failed to extract sufficient text. The document might be empty, corrupted, or fully image-based without OCR tools installed.")
            progress(0.6, desc="Running AI Analysis...")
            analysis = analyzer.analyze_document_comprehensive(text, metadata)
            progress(0.9, desc="Formatting Results...")
            dashboard = format_dashboard(analysis)
            chart, risk_details = format_risk_analysis(analysis)
            compliance = format_compliance_analysis(analysis)
            key_terms = format_key_terms(analysis)
            ai_issues = analysis.get('potential_issues', [])
            return dashboard, chart, risk_details, ai_issues, compliance, key_terms, metadata, analysis, text, gr.Tabs(selected=0)

        analyze_btn.click(
            fn=run_analysis, inputs=[file_input],
            outputs=[dashboard_output, risk_chart_output, risk_details_output, ai_issues_output, compliance_output,
                     key_terms_output, metadata_output, analysis_state, doc_text_state, result_tabs]
        )
        
        def submit_question_and_clear(doc_text, question, chat_history, lang, analysis_data):
            new_history = ask_enhanced_question(doc_text, question, chat_history, lang, analysis_data)
            return new_history, ""

        ask_btn.click(
            fn=submit_question_and_clear,
            inputs=[doc_text_state, question_input, chatbot, lang_select, analysis_state],
            outputs=[chatbot, question_input]
        )
        question_input.submit(
            fn=submit_question_and_clear,
            inputs=[doc_text_state, question_input, chatbot, lang_select, analysis_state],
            outputs=[chatbot, question_input]
        )

    return interface

if __name__ == "__main__":
    print("🚀 Starting Advanced AI Legal Document Analyzer...")
    if not PDF2IMAGE_AVAILABLE or not OCR_AVAILABLE:
        print("⚠️ WARNING: Full capabilities (scanned PDFs, images) are disabled.")
    app = create_enhanced_interface()
    # For deployment, server_name must be 0.0.0.0
    app.queue().launch(server_name="0.0.0.0", show_error=True)
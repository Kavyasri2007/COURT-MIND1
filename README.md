# COURT MIND – Legal Document Summarizer

Eudia is an AI-powered web application that helps legal professionals quickly understand complex legal documents. Users can securely upload legal PDFs and receive structured summaries, case status insights, timelines, and actionable recommendations.

# Features
Secure login using Firebase Authentication

Upload and summarize multiple legal PDFs

AI-powered legal summarization using Google Gemini
 
Automatic extraction of:

Case details & parties

Sections of law invoked

Past & upcoming hearing dates

Case timeline

Case status detection (Ongoing / Closed)

Smart recommendations for ongoing case

Summaries stored securely in Firestore

# Tech Stack

Frontend: Streamlit

Backend: FastAPI

AI Model: Google Gemini

Database: Firebase Firestore

Auth: Firebase Authentication

PDF Processing: PyMuPDF

# Setup (Quick)

pip install -r requirements.txt

uvicorn main:app --reload --port 8000

streamlit run app.py

#
Add your Firebase credentials, Gemini API key, and .env variables before running.

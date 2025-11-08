import streamlit as st
import requests
import pyrebase
import os
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = "http://localhost:8000/upload/"

st.set_page_config(page_title="Eudia – Legal Summarizer", page_icon="⚖️")

# === Firebase Authentication Setup ===
firebase_config = {
    "apiKey": "AIzaSyB_6ZBOkX3osY1-j5DZQe-9HC-P0b2v1pw",
    "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
    "projectId": os.getenv("FIREBASE_PROJECT_ID"),
    "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET"),
    "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
    "appId": os.getenv("FIREBASE_APP_ID"),
    "databaseURL": ""
}

try:
    firebase = pyrebase.initialize_app(firebase_config)
    auth = firebase.auth()
except Exception as e:
    st.error(f"Firebase initialization failed. Please check your .env file. Error: {e}")
    st.stop()

# === Session State Initialization ===
if 'user' not in st.session_state:
    st.session_state.user = None

# === Login/Signup Page ===
if not st.session_state.user:
    st.title("⚖️ Welcome to Eudia")
    choice = st.selectbox("Login or Signup", ["Login", "Sign Up"])

    email = st.text_input("Email Address")
    password = st.text_input("Password", type="password")

    if choice == "Sign Up":
        if st.button("Create My Account"):
            try:
                user = auth.create_user_with_email_and_password(email, password)
                st.session_state.user = user
                st.success("Account created successfully! You are now logged in.")
                st.rerun()
            except Exception as e:
                st.error(f"Signup failed: {e}")

    if choice == "Login":
        if st.button("Login"):
            try:
                user = auth.sign_in_with_email_and_password(email, password)
                st.session_state.user = user
                st.success("Logged in successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

# === Main Application Page (if logged in) ===
else:
    st.sidebar.title(f"Welcome!")
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

    st.title("⚖️ Eudia – Legal Document Summarizer")
    st.write("Upload legal documents to get an AI-powered summary.")

    client_name = st.text_input("👤 Client Name", placeholder="e.g., John Doe")
    file_type = st.selectbox(
        "📄 File Type",
        ["Court Order", "Pleading", "Contract", "Affidavit", "Discovery Document", "Other"]
    )

    uploaded_files = st.file_uploader(
        "📂 Upload Documents (PDF or Text)",
        type=["pdf", "txt"],
        accept_multiple_files=True
    )

    if uploaded_files and client_name and file_type:
        # Get the user's ID token
        id_token = st.session_state.user['idToken']

        st.info(f"📤 Sending {len(uploaded_files)} file(s) to backend...")

        # Prepare files for multipart upload
        files_to_upload = [("files", (file.name, file, file.type)) for file in uploaded_files]
        data = {
            "client_name": client_name,
            "file_type": file_type
        }
        headers = {"Authorization": f"Bearer {id_token}"}

        try:
            response = requests.post(BACKEND_URL, files=files_to_upload, data=data, headers=headers)
            response.raise_for_status()  # Raise an exception for bad status codes
            response_data = response.json()

            st.success("✅ Summaries Generated Successfully!")

            for item in response_data.get("summaries", []):
                with st.expander(f"🧾 Summary for: {item.get('filename')}"):
                    # === Display Case Status and Recommendations First ===
                    case_status = item.get("case_status", "Unknown")
                    status_color = "blue" if case_status == "Ongoing" else "green"
                    st.subheader(f"Case Status: :{status_color}[{case_status}]")

                    recommendations = item.get("recommendations", [])
                    if recommendations:
                        st.info("💡 Recommendations & Next Steps")
                        for tip in recommendations:
                            st.write(f"- {tip}")
                        st.divider()

                    # === Display Summary ===
                    st.markdown(item.get("summary_markdown", "No summary found."))

                    # === Extract Metadata ===
                    metadata = item.get("metadata", {})
                    dates_info = metadata.get("dates", {})
                    upcoming_dates_count = dates_info.get("upcoming", {}).get("count", 0)
                    past_dates_count = dates_info.get("past", {}).get("count", 0)
                    sections_count = metadata.get("sections", {}).get("count", 0)

                    # === Display Metrics ===
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("📅 Upcoming Dates", upcoming_dates_count)
                    with col2:
                        st.metric("✅ Completed Dates", past_dates_count)
                    with col3:
                        st.metric("⚖️ Sections Found", sections_count)
                    
                    # === Show Timeline ===
                    timeline = metadata.get("timeline")
                    if timeline:
                        st.subheader("⏳ Case Timeline")
                        # Create a markdown table from the list of events
                        table = "| Date | Event Context | Status |\n|---|---|---|\n"
                        for event in timeline:
                            table += f"| {event['date']} | {event['event_context'][:100]}... | {event['status']} |\n"
                        st.markdown(table)
                    
                    # Display the structured summary
                    structured = item.get("summary_markdown", {})
                    if structured and "error" not in structured:
                        st.subheader("🧩 Structured Case Summary")
                        with st.expander("View Full Structured Data (JSON)"):
                            st.json(structured)

        except requests.exceptions.HTTPError as err:
            error_detail = err.response.json().get("detail", err.response.text) if err.response else str(err)
            st.error(f"Backend Error: {err.response.status_code} - {error_detail}")
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")
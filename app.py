import streamlit as st
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import random

# --- CONFIGURATION ---
st.set_page_config(page_title="Japanese Study App", page_icon="🇯🇵")

# Configure Gemini API
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash')

# Establish Google Sheets Connection
conn = st.connection("gsheets", type=GSheetsConnection)

import random # Add this to the very top of your app.py with the other imports

# --- LOAD VOCABULARY FROM FILE ---
# Read the file. We use sep='\t' assuming it's tab-separated. 
# (If you saved it as a comma-separated CSV, change it to sep=',')
df = pd.read_csv("vocab.tsv", sep="\t", names=["Kanji", "Meaning_and_Pronunciation"])

# Convert it into a dictionary. 
# This maps the Italian meaning (front of card) to the Kanji (back of card)
vocab = dict(zip(df["Meaning_and_Pronunciation"], df["Kanji"]))

# NOTE: If you want the Kanji on the FRONT of the card instead, use this line:
# vocab = dict(zip(df["Kanji"], df["Meaning_and_Pronunciation"]))

allowed_words_list = ", ".join(vocab.values())

# --- STATE MANAGEMENT ---
if "flipped" not in st.session_state:
    st.session_state.flipped = False

# --- HELPER FUNCTIONS ---
def log_progress(task_type, result):
    """Fetches the Google Sheet, appends a new row, and updates it."""
    # 1. Read existing data
    existing_data = conn.read(spreadsheet=st.secrets["SPREADSHEET_URL"], usecols=[0, 1, 2])
    
    # 2. Create new row
    new_row = pd.DataFrame([{
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Task": task_type,
        "Result": result
    }])
    
    # 3. Combine and update
    updated_data = pd.concat([existing_data, new_row], ignore_index=True)
    conn.update(spreadsheet=st.secrets["SPREADSHEET_URL"], data=updated_data)

def check_translation_with_ai(italian_sentence, user_japanese):
    """Uses Gemini to grade the translation and enforce the vocab list."""
    prompt = f"""
    The user is learning Japanese. 
    They were asked to translate the Italian sentence: "{italian_sentence}" into Japanese.
    Their answer was: "{user_japanese}".
    
    Rules for grading:
    1. Check if the grammar and meaning are correct.
    2. STRICT VOCABULARY CHECK: The user is ONLY allowed to use Japanese words that correspond to this vocabulary list: {allowed_words_list}. 
       If they used an advanced word or kanji outside this list, mark it incorrect and tell them which word is forbidden.
    
    Reply in this exact format:
    [CORRECT] or [INCORRECT]
    Explanation: (Write a 1-2 sentence explanation of any errors or forbidden words).
    """
    response = model.generate_content(prompt)
    return response.text

# --- UI LAYOUT ---
st.title("🇯🇵 Japanese Practice")

# Create two tabs for the two features
tab1, tab2 = st.tabs(["Flashcards", "Sentence Translation"])

with tab1:
    st.header("Vocab Flashcard")
    current_word = "gatto" # In a real app, you'd pick randomly from vocab.keys()
    
    if not st.session_state.flipped:
        st.subheader(f"🇮🇹 {current_word}")
        if st.button("Flip Card"):
            st.session_state.flipped = True
            st.rerun()
    else:
        st.subheader(f"🇯🇵 {vocab[current_word]}")
        st.write("Did your friend get it right?")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Yes, I knew it"):
                log_progress(f"Flashcard: {current_word}", "Correct")
                st.success("Progress logged!")
                st.session_state.flipped = False
                # Here you could trigger a new random word
        with col2:
            if st.button("❌ No, I missed it"):
                log_progress(f"Flashcard: {current_word}", "Incorrect")
                st.error("Progress logged! Try again next time.")
                st.session_state.flipped = False

with tab2:
    st.header("Sentence Translation")
    st.write("Translate this sentence using ONLY the approved vocabulary:")
    
    target_sentence = "Io mangio la mela."
    st.info(f"🇮🇹 **{target_sentence}**")
    
    user_translation = st.text_input("Type your Japanese translation here:")
    
    if st.button("Check Translation"):
        if user_translation:
            with st.spinner("Checking grammar and vocabulary..."):
                # Call Gemini API
                feedback = check_translation_with_ai(target_sentence, user_translation)
                
                # Display Results
                if "[CORRECT]" in feedback.upper():
                    st.success(feedback)
                    log_progress(f"Translation: {target_sentence}", "Correct")
                else:
                    st.error(feedback)
                    log_progress(f"Translation: {target_sentence}", "Incorrect")
        else:
            st.warning("Please enter a translation first.")

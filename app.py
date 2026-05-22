import streamlit as st
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import random

# --- VOCABULARY SELECTION UI ---
# This creates a nice panel on the left side of the screen
st.sidebar.header("⚙️ Settings")

# Define your files here. Make sure the filenames perfectly match the files in your folder!
AVAILABLE_VOCABS = {
    "Terzo Anno": "Kanji terzo anno - v3 ripulito.txt",
    "Secondo Anno": "Kanji secondo anno.tsv",
    "Primo Anno": "Kanji primo anno.tsv" # Replace with your actual 3rd file's name!
}

# Let the user pick multiple options. By default, "Terzo Anno" is selected.
selected_lists = st.sidebar.multiselect(
    "Select vocabularies to practice:",
    options=list(AVAILABLE_VOCABS.keys()),
    default=["Terzo Anno"] 
)

# If the user unchecks all boxes, stop the app and show a warning
if not selected_lists:
    st.warning("👈 Please select at least one vocabulary list from the sidebar to start!")
    st.stop()

# --- LOAD AND COMBINE VOCABULARY ---
vocab = {}

for list_name in selected_lists:
    file_path = AVAILABLE_VOCABS[list_name]
    try:
        df = pd.read_csv(file_path, sep="\t", names=["Kanji", "Meaning_and_Pronunciation"])
        
        # Smart check: if the file has a header row like "Giapponese \t Italiano", skip it!
        #if df.iloc[0]["Kanji"] == "Giapponese":
            #df = df.iloc[1:]
            
        # Merge the new words into our main dictionary
        vocab.update(dict(zip(df["Meaning_and_Pronunciation"], df["Kanji"])))
    except FileNotFoundError:
        st.sidebar.error(f"⚠️ Could not find file: {file_path}")

allowed_words_list = ", ".join(vocab.values())

# --- STATE MANAGEMENT ---
if "flipped" not in st.session_state:
    st.session_state.flipped = False

# CRITICAL FIX: If you uncheck a vocabulary list, the app might be holding onto a 'current_word' 
# that no longer exists in the loaded lists. This resets the word safely if that happens.
if "current_word" not in st.session_state or st.session_state.current_word not in vocab:
    st.session_state.current_word = random.choice(list(vocab.keys()))

# --- HELPER FUNCTIONS ---
# (Keep your log_progress and check_translation_with_ai functions exactly as they are below here)
def log_progress(task_type, result):
    """Fetches the Google Sheet, appends a new row, and updates it."""
    # 1. Read existing data (ttl=0 forces a fresh read, ignoring the cache!)
    existing_data = conn.read(spreadsheet=st.secrets["SPREADSHEET_URL"], usecols=[0, 1, 2], ttl=0)
    
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
    
    # 1. Callback function to reset the card if the user changes direction mid-guess
    def reset_card():
        st.session_state.flipped = False

    # 2. Add the radio button for direction selection
    direction = st.radio(
        "Guessing direction:", 
        ["Italian ➔ Japanese", "Japanese ➔ Italian"], 
        horizontal=True,
        on_change=reset_card
    )
    
    # Initialize a random word in the session state if one doesn't exist
    if "current_word" not in st.session_state:
        st.session_state.current_word = random.choice(list(vocab.keys()))
        
    current_word = st.session_state.current_word
    
    # 3. Determine what goes on the front and back based on the radio button
    if direction == "Italian ➔ Japanese":
        front_text = current_word
        back_text = vocab[current_word]
    else:
        front_text = vocab[current_word]
        back_text = current_word
    
    # 4. Display the card using our dynamic front/back variables
    if not st.session_state.flipped:
        st.subheader(front_text)
        if st.button("Flip Card"):
            st.session_state.flipped = True
            st.rerun()
    else:
        st.subheader(back_text)
        st.write("Did your friend get it right?")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Yes, I knew it"):
                # Bonus: We log the direction in the Google Sheet so you know how they practiced!
                log_progress(f"Flashcard ({direction}): {current_word}", "Correct")
                st.success("Progress logged!")
                st.session_state.flipped = False
                # Pick a new random word for the next card!
                st.session_state.current_word = random.choice(list(vocab.keys())) 
                st.rerun()
        with col2:
            if st.button("❌ No, I missed it"):
                log_progress(f"Flashcard ({direction}): {current_word}", "Incorrect")
                st.error("Progress logged! Try again next time.")
                st.session_state.flipped = False
                st.session_state.current_word = random.choice(list(vocab.keys()))
                st.rerun()

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

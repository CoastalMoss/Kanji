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

# --- VOCABULARY SELECTION UI ---
# This creates a nice panel on the left side of the screen
st.sidebar.header("⚙️ Settings")

master_vocab = pd.read_csv("Kanji anni 1, 2 e 3.tsv", sep="\t")
# Ensure the ID column is strictly treated as integers (failsafe)
master_vocab["ID"] = pd.to_numeric(master_vocab["ID"], errors="coerce").fillna(0).astype(int)

available_years = sorted(master_vocab["Anno"].dropna().unique().astype(int).tolist())
selected_years = st.sidebar.multiselect(
    "Select Year(s) to practice:",
    options=available_years,
    default=available_years
)

if not selected_years:
    st.sidebar.warning("👈 Please select at least one year!")
    st.stop()

# Let the user pick multiple options. By default, "Terzo Anno" is selected.
#selected_lists = st.sidebar.multiselect(
#    "Select vocabularies to practice:",
#    options=list(AVAILABLE_VOCABS.keys()),
#    default=["Terzo Anno"] 
#)

# If the user unchecks all boxes, stop the app and show a warning
#if not selected_lists:
#    st.warning("👈 Please select at least one vocabulary list from the sidebar to start!")
#    st.stop()

# --- LOAD AND COMBINE VOCABULARY ---
# vocab = {}

# for list_name in selected_lists:
#     file_path = AVAILABLE_VOCABS[list_name]
#     try:
#         df = pd.read_csv(file_path, sep="\t", names=["Kanji", "Meaning_and_Pronunciation"])
        
#         # Smart check: if the file has a header row like "Giapponese \t Italiano", skip it!
#         #if df.iloc[0]["Kanji"] == "Giapponese" or df.iloc[0]["Kanji"] == "Kanji":
#          #   df = df.iloc[1:]
            
#         # Merge the new words into our main dictionary
#         vocab.update(dict(zip(df["Meaning_and_Pronunciation"], df["Kanji"])))
#     except FileNotFoundError:
#         st.sidebar.error(f"⚠️ Could not find file: {file_path}")

# allowed_words_list = ", ".join(vocab.values())

study_mode = st.sidebar.radio(
    "Study Mode:",
    ["All Vocabulary", "Needs Practice (Weak)", "Unseen Only"]
)
# --- 3. CALCULATE PROGRESS ON THE FLY ---
# Load Event Log (ttl=0 ensures fresh data!)
log_df = conn.read(spreadsheet=st.secrets["SPREADSHEET_URL"], usecols=[0, 1, 2, 3], ttl=0)

# Clean up log headers and ensure correct data types
if len(log_df.columns) == 4:
    log_df.columns = ["Date", "Direction", "VocabID", "Result"]
    # Force VocabID to be an integer so it perfectly matches the master document
    log_df["VocabID"] = pd.to_numeric(log_df["VocabID"], errors="coerce")
    log_df = log_df.dropna(subset=["VocabID"])
    log_df["VocabID"] = log_df["VocabID"].astype(int)
else:
    log_df = pd.DataFrame(columns=["Date", "Direction", "VocabID", "Result"])

if not log_df.empty:
    # Pivot the log to count Correct/Incorrect per Direction per ID
    stats_df = pd.pivot_table(
        log_df, 
        index="VocabID", 
        columns=["Direction", "Result"], 
        aggfunc="size", 
        fill_value=0
    )
    # Flatten multi-level columns (e.g. becomes "Italian ➔ Japanese_Correct")
    stats_df.columns = [f"{direction}_{result}" for direction, result in stats_df.columns]
    
    # Merge stats into master vocabulary based on the IDs
    master_df = pd.merge(master_vocab, stats_df, left_on="ID", right_index=True, how="left").fillna(0)
else:
    # If the log is empty, just use the master and create 0s
    master_df = master_vocab.copy()

# Failsafe: Ensure all 4 stat columns exist (in case someone hasn't gotten an "Incorrect" yet)
expected_cols = [
    "Italian ➔ Japanese_Correct", "Italian ➔ Japanese_Incorrect", 
    "Japanese ➔ Italian_Correct", "Japanese ➔ Italian_Incorrect"
]
for col in expected_cols:
    if col not in master_df.columns:
        master_df[col] = 0

# --- 4. APPLY FILTERS TO CREATE THE "DECK" ---
# Filter by Year
deck_df = master_df[master_df["Anno"].isin(selected_years)]

# Filter by Study Mode
if study_mode == "Unseen Only":
    deck_df = deck_df[
        (deck_df["Italian ➔ Japanese_Correct"] == 0) & 
        (deck_df["Italian ➔ Japanese_Incorrect"] == 0) & 
        (deck_df["Japanese ➔ Italian_Correct"] == 0) & 
        (deck_df["Japanese ➔ Italian_Incorrect"] == 0)
    ]
elif study_mode == "Needs Practice (Weak)":
    # Show cards where total Incorrect > total Correct
    total_incorrect = deck_df["Italian ➔ Japanese_Incorrect"] + deck_df["Japanese ➔ Italian_Incorrect"]
    total_correct = deck_df["Italian ➔ Japanese_Correct"] + deck_df["Japanese ➔ Italian_Correct"]
    deck_df = deck_df[total_incorrect > total_correct]

if deck_df.empty:
    st.success("🎉 No kanji match these filters! You've mastered them or need to change settings.")
    st.stop()
    
# --- STATE MANAGEMENT ---
if "flipped" not in st.session_state:
    st.session_state.flipped = False
    
if "current_id" not in st.session_state or st.session_state.current_id not in deck_df["ID"].values:
    st.session_state.current_id = random.choice(deck_df["ID"].tolist())
    st.session_state.flipped = False

# CRITICAL FIX: If you uncheck a vocabulary list, the app might be holding onto a 'current_word' 
# that no longer exists in the loaded lists. This resets the word safely if that happens.
# if "current_word" not in st.session_state or st.session_state.current_word not in vocab:
#     st.session_state.current_word = random.choice(list(vocab.keys()))

# --- HELPER FUNCTIONS ---
# (Keep your log_progress and check_translation_with_ai functions exactly as they are below here)
def log_progress(vocab_id, direction, result):
    """Appends a new attempt to the 4-column Google Sheet."""
    existing_data = conn.read(spreadsheet=st.secrets["SPREADSHEET_URL"], usecols=[0, 1, 2, 3], ttl=0)
    if len(existing_data.columns) != 4:
        existing_data = pd.DataFrame(columns=["Date", "Direction", "VocabID", "Result"])
    else:
        existing_data.columns = ["Date", "Direction", "VocabID", "Result"]
        
    new_row = pd.DataFrame([{
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Direction": direction,
        "VocabID": int(vocab_id), # Save strictly as integer
        "Result": result
    }])
    
    updated_data = pd.concat([existing_data, new_row], ignore_index=True)
    conn.update(spreadsheet=st.secrets["SPREADSHEET_URL"], data=updated_data)

def check_translation_with_ai(italian_sentence, user_japanese):
    """Uses Gemini to grade the translation and enforce the vocab list."""
    prompt = f"""
    The user is learning Japanese. 
    They were asked to translate the Italian sentence: '{italian_sentence}' into Japanese.
    Their answer was: '{user_japanese}'.
    
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
    # if "current_word" not in st.session_state:
    #     st.session_state.current_word = random.choice(list(vocab.keys()))
        
    # current_word = st.session_state.current_word
    
    # 3. Determine what goes on the front and back based on the radio button
    # Fetch the specific row data for the current flashcard
    current_row = deck_df[deck_df["ID"] == st.session_state.current_id].iloc[0]

    if direction == "Italian ➔ Japanese":
        front_text = current_row["Italiano"]
        back_text = current_row["Kanji"]
    else:
        front_text = current_row["Kanji"]
        back_text = current_row["Italiano"]
    
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
                log_progress(current_row["ID"], direction, "Correct")
                st.success("Progress logged!")
                st.session_state.flipped = False
                st.session_state.current_id = random.choice(deck_df["ID"].tolist())
                st.rerun()
        with col2:
            if st.button("❌ No, I missed it"):
                log_progress(current_row["ID"], direction, "Incorrect")
                st.error("Progress logged! Try again next time.")
                st.session_state.flipped = False
                st.session_state.current_id = random.choice(deck_df["ID"].tolist())
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
